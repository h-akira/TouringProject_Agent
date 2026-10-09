"""AgentCore agent for the touring app — answers a rider's spoken questions.

The conversation carries across invocations that share a runtimeSessionId
(US-1.02); the agent looks things up on the web rather than telling a rider who
cannot touch their phone to check an app (US-1.04); and it finds places around
the rider with distances and sides worked out in code (tools/places.py).
Voice (Transcribe / Polly), API-key auth and the facts in the prompt (date,
address, heading) are handled by the Backend before the question reaches this
agent - see docs-parent/03_units_contracts.md UC-5.

Deliberately trimmed from the CLI scaffold:
  - the scaffolded MCP client (mcp_client/, pointed at mcp.exa.ai) and skills/
    are deleted; nothing imported them. Web search goes through the project's
    own gateway instead — see tools/web_search.py.
  - the add_numbers demo tool is dropped as noise.
  - SlidingWindowConversationManager replaces NullConversationManager, which
    keeps no history at all and so cannot answer a follow-up question.

Note the history is per process, so it survives only while the session's
microVM is alive — see the caveat on `_SESSION_AGENTS` below.
"""

import os
from collections import OrderedDict
from typing import Optional

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager

from model.load import load_model
from tools.places import LOCATION_KEY, search_nearby_places, search_places_by_name
from tools.web_search import load_web_search

app = BedrockAgentCoreApp()
log = app.logger

SYSTEM_PROMPT = """\
あなたはバイクでツーリング中のライダーを支援するAIです。
回答は音声で読み上げられ、ライダーは走行中で画面を見られません。

回答のルール:
- 2〜3文程度で簡潔に答える。前置きや復唱はしない。
- Markdown記法（**、#、箇条書き記号など）は一切使わない。読み上げると不自然になる。
- 方角や左右は、ユーザーから与えられた情報をそのまま使う。自分で計算し直さない。
- 確実でないことは「たぶん」「〜と思われます」と正直に伝える。
- 今日の日付と現在時刻は、質問に添えられた【現在日時】を正とする。
  自分の知識から日付を推測しない（検索結果の日付の新旧もこれを基準に判断する）。
- 直前までの会話を踏まえ、「それ」「その山」のような指示語も文脈から解釈する。
- 質問は音声認識の文字起こしなので、別の漢字への誤変換（例:「公園」が「講演」）や、
  音の似た別の語への聞き間違い（例:「温泉」が「音声」）が混じることがある。
  文脈に合わない語があれば、読みが同じか似ていて意味の通る語として解釈して答える。

位置と進行方向の扱い:
- 質問ごとに現在地と進行方向が変わる。「いま右手に見える」なら最新の位置を、
  「さっきの山」なら**その話題が出たときの位置**を使う。
- 進行方向が示されないことがある（停車中・方向転換直後）。
  そのときは方角や左右に触れず、位置だけで答える。推測も流用もしない。

調べ方のルール:
- ライダーは走行中で、スマホを操作できない。
  「アプリで確認してください」「検索してみてください」とは絶対に答えない。
  代わりに web 検索ツールで自分で調べて答える。
- 天気・気温・道路状況・営業時間・イベントなど、その日その時の情報は必ず検索する。
- 逆に、山や地域の由来のように変わらない知識は、検索せずそのまま答える。
- web 検索するときは地名を具体的に書く。「近くの」「この先の」では検索が効かないので、
  与えられた現在地の住所から都道府県名と市町村名を補って検索する。
  例:「箱根 天気」ではなく「神奈川県箱根町 天気」。
- 検索しても分からなければ、分からないと正直に答える。作り話はしない。

周辺の場所の調べ方:
- 「右手に見える公園」「一番近いマクドナルド」のように、現在地の周辺の具体的な場所を
  聞かれたら、web 検索ではなく search_nearby_places（種類で探す）か
  search_places_by_name（名前で探す）を使う。現在地は自動で渡されるので座標は書かない。
- 山・湖・駅・都市など特定の場所の方角や距離を聞かれたら、富士山のように有名な場所でも
  知識で答えず、必ず search_places_by_name で調べる（遠い場所でもよい）。
  方角に関係ない知識（「富士山の高さ」など）は調べずに答える。
- ツールが返す距離・方角・左右は計算済みの事実なので、そのまま使う。
  進行方向が無いときにツールが返す方角（北東など）は使ってよいが、左右は言わない。
- 地図のデータは位置がずれていることがある。候補が複数あれば一番近いものを答え、
  「たぶん」を付けて断定しすぎない。
"""

# How many turns to keep. Every turn is re-sent to Bedrock on the next call, so
# this is the direct lever on input-token cost; 20 is ~10 question/answer pairs.
MAX_TURNS = int(os.environ.get("AGENT_MAX_TURNS", "20"))

# Cap on concurrently cached sessions, so one long-lived process can neither
# leak history between sessions nor grow without bound.
MAX_CACHED_SESSIONS = 128

# session_id -> Agent. In-process only: AgentCore gives each session its own
# microVM, so this survives exactly as long as that microVM. A cold start (or
# an idle timeout) empties it and the conversation silently restarts. Durable
# history would need AgentCore Memory, which this project does not use - see
# docs/01_architecture.md section 3.
_SESSION_AGENTS: "OrderedDict[str, Agent]" = OrderedDict()

# Built once per process and shared by every session: the gateway connection is
# stateless as far as we use it, and reconnecting per session would add a round
# trip to each new conversation. None when no gateway is configured, in which
# case the agent still answers, just from the model's own knowledge.
_WEB_SEARCH = load_web_search()
if _WEB_SEARCH is None:
    log.warning("no gateway url in env - answering without web search")


def _get_or_create_agent(session_id: str) -> Agent:
    """Return the Agent for this session, creating it on first contact."""
    if session_id in _SESSION_AGENTS:
        _SESSION_AGENTS.move_to_end(session_id)
        return _SESSION_AGENTS[session_id]

    if len(_SESSION_AGENTS) >= MAX_CACHED_SESSIONS:
        evicted, _ = _SESSION_AGENTS.popitem(last=False)
        log.info("evicted session from cache: %s", evicted)

    log.info("creating agent for session: %s", session_id)
    # Passing the MCPClient itself (rather than a list of tools) lets Strands
    # own the connection lifecycle, so there is no context manager to hold open
    # across the async entrypoint below.
    _SESSION_AGENTS[session_id] = Agent(
        model=load_model(),
        system_prompt=SYSTEM_PROMPT,
        tools=[search_nearby_places, search_places_by_name]
        + ([_WEB_SEARCH] if _WEB_SEARCH else []),
        conversation_manager=SlidingWindowConversationManager(
            window_size=MAX_TURNS
        ),
    )
    return _SESSION_AGENTS[session_id]


def _extract_location(payload: dict) -> Optional[dict]:
    """The rider's position and heading as data, if the Backend sent them.

    Handed to the place tools through invocation_state, so they never depend on
    the model copying coordinates out of the prompt
    (docs-parent/03_units_contracts.md UC-5). Validated again in tools/places.py.
    """
    location = payload.get("location")
    return location if isinstance(location, dict) else None


def _extract_prompt(payload: dict) -> str:
    """Pull the question out of the request body.

    `prompt` is what the AgentCore CLI and console send, so accept that as well
    as this app's own `question` field.
    """
    for key in ("question", "prompt"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


@app.entrypoint
async def invoke(payload: dict, context):
    # AgentCore derives session_id from the runtimeSessionId on the request.
    # Same id -> same agent -> the earlier turns are still in context.
    session_id = getattr(context, "session_id", None) or "default-session"
    question = _extract_prompt(payload)

    if not question:
        yield {"error": "`question` (or `prompt`) is required and must be non-empty."}
        return

    agent = _get_or_create_agent(session_id)
    turns_before = len(agent.messages)
    # Log the rider's words, not the context block the Lambda prepends (date,
    # coordinates, address): the head of `question` is that block, so a plain
    # prefix would show the date and never the question.
    asked = question.rsplit("質問: ", 1)[-1]
    log.info("session=%s turns_before=%d q=%r", session_id, turns_before, asked[:80])

    # Per question, not per session: the rider moves between questions.
    invocation_state = {LOCATION_KEY: _extract_location(payload)}
    async for event in agent.stream_async(question, invocation_state=invocation_state):
        # Pass through only the model stream events; the SDK also emits
        # bookkeeping dicts that the client has no use for.
        if isinstance(event, dict) and "event" in event:
            yield event


if __name__ == "__main__":
    app.run()
