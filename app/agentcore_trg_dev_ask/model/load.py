import os

from strands.models.bedrock import BedrockModel

# Inference-profile id, not a bare model id: every Anthropic model here is
# INFERENCE_PROFILE-only. The CLI scaffolds a `global.` Sonnet 4.5 id, which
# this account cannot invoke (AccessDeniedException). See pre-research/bedrock/.
#
# `us.` rather than `jp.`: the whole project sits in us-east-1 because the
# Web Search Tool connector is offered there and nowhere else
# (pre-research/websearch/). `jp.` is an ap-northeast-only profile and fails
# from us-east-1 with "The provided model identifier is invalid".
DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-6"

# Answers are read aloud while riding, so cap the output length. This also caps
# the per-request output cost (docs/01_architecture.md section 9).
#
# ⚠️ Too tight a cap does not shorten the answer - it truncates mid-sentence and
# the whole call fails with MaxTokensReachedException, leaving a broken partial
# message in the history. 300 was hit in practice once the system prompt grew.
#
# This budget is not just the spoken answer: with web search, the tool calls and
# search queries the model emits count against it too, so a question that
# searches twice can hit a cap that a direct answer never would.
#
# Keeping answers short is the system prompt's job, not this cap's - the cap is
# only a backstop against a runaway response.
DEFAULT_MAX_TOKENS = 800


def load_model() -> BedrockModel:
    """Get Bedrock model client using IAM credentials."""
    return BedrockModel(
        model_id=os.environ.get("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID),
        region_name=os.environ.get("BEDROCK_REGION", "us-east-1"),
        max_tokens=int(os.environ.get("BEDROCK_MAX_TOKENS", DEFAULT_MAX_TOKENS)),
    )
