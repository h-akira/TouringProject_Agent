# AGENTS.md — Agent

ツーリング AI 会話アプリのエージェント（Bedrock AgentCore Runtime ＋ Strands）。会話の保持・回答の生成・Web 検索を担う。
親リポジトリ `TouringProject` の submodule。共通の規約は親の `AGENTS.md`（親の中で作業しているときは既に読まれている）。
このファイルは `agentcore` CLI が生成したものを置き換えたもの。

## どこに何があるか

| 場所 | 中身 |
|---|---|
| `docs/` | Agent の設計（現在の姿だけ） |
| `docs-parent/` | 親の `docs/` の写し（要件・技術方針・契約）。⚠️ 編集しない。更新は親の `docs/sync.sh` |
| `agentcore/agentcore.json` | プロジェクトの定義（Runtime・Gateway）。正本 |
| `agentcore/.llm-context/` | `agentcore.json` の型定義と検証の制約（CLI の生成物） |
| `agentcore/cdk/` | CDK（CLI の生成物） |
| `app/agentcore_trg_dev_ask/` | エージェントのコード（`main.py`・`model/load.py`・`tools/`） |
| `buildspec.yml` | CodeBuild の手順書 |

Agent に固有の ADR は無い（必要になったら `adr/` を作る。書き方は親の `AGENTS.md`）。
コードのコメントから参照してよいのは、`docs/`・`docs-parent/` と research の絶対 URL だけ（learning・親の adr は参照しない）。

## 前提

- ⚠️ リージョンは `us-east-1`（Web 検索のコネクタがそこにしか無い）。Backend は東京。混同すると動かない。
- モデル ID は `us.anthropic.claude-sonnet-4-6`。⚠️ `jp.` は ap-northeast 専用で、us-east-1 からは "model identifier is invalid" になる。Claude 5 系はこのアカウントでは使えない。
- ソースは S3 に zip で置く方式（CodeZip）。Docker は要らない。
- Backend との約束（Runtime ARN の受け渡し・呼び出しの形）は契約（`docs-parent/03_units_contracts.md` UC-3・UC-5）。片方だけ変えない。
- Bedrock・Strands の実装を書くときは `claude-api` スキルを参照する（モデル ID や SDK の仕様を記憶に頼らない）。

## agentcore の定義を変えるとき（CLI の生成物にあった不変条件）

- ⚠️ `.json` が正本。エージェントの振る舞いを `cdk/` の生成コードを直接いじって変えない。
- 例外は、`agentcore.json` に書けない Runtime の実行ロールの権限だけ（`cdk/lib/cdk-stack.ts` の「Project addition」のブロック。いまは `geo-places`）。⚠️ `cdk/` を作り直すときはこのブロックを移す。
- ⚠️ リソースの `name` は CloudFormation の論理 ID になる。名前を変えるとリソースは作り直される（Runtime の ARN が変わり、Backend の再デプロイが要る）。他のフィールドの変更はその場で更新される。
- 変える前に `agentcore/.llm-context/*.ts` の型と制約（`@regex`・`@min`・`@max`）を読み、列挙値は文字列そのままで書く。名前は CloudFormation で使える形（英数字・先頭は英字。AgentCore はハイフン不可）。
- 変えたら `agentcore validate` で確かめる。リソースを消すときは `agentcore remove` を使う。
- ⚠️ `agentcore/aws-targets.json` はアカウント ID を含むので追跡しない（雛形は `aws-targets-sample.json`）。`agentcore/.cli/`・`.env.local` も追跡しない。

## 作業の規則

- ⚠️ デプロイと実機での確認はユーザーが行う。AI は `agentcore deploy` を実行しない。
- 手元で `agentcore deploy` した後は、Runtime の ARN を東京の SSM（`/trg/<env>/agent-runtime-arn`）に書く。ARN が変わったら Backend も再デプロイする。
- エージェントのテストは `app/agentcore_trg_dev_ask/tests/`（`uv run pytest`）。
- 手元での通しの確認は `scripts/ask_local.py`（本物の LLM とツールを呼ぶ。座標は公共のランドマークだけを使う）。

## 落とし穴

- ⚠️ AgentCore はアイドル中も課金される（文脈を保つため microVM が生きている）。
- 初回の応答は10秒前後（コールドスタート）。アプリ側では縮められない。
- ⚠️ `max_tokens` が厳しすぎると、回答が短くなるのではなく失敗し、壊れた部分応答が会話の履歴に残る。Web 検索のツール呼び出しも同じ枠を消費するので、読み上げる文章より余裕が要る。
- AgentCore Memory は使わない（会話の継続は「一問一答＋α」まで。15分以上あけた続きは想定しない）。走行ログのような記録が要るなら、会話の記憶ではなく DB 連携として別に設計する。
- メモ機能（US-X.01）は今は作らないが、`@tool` を足すだけで入れられる構造を保つ。
- ログには質問の本文だけを出す（座標・住所のブロックは出さない）。
