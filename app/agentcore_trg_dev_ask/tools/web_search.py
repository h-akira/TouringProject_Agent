"""Web search, via the AgentCore Gateway's managed web-search connector.

The rider is moving, so answers like "check a weather app" are useless: the
model has to look things up itself (US-1.04). The connector is an AWS-operated
index reached over MCP, which keeps the search inside AWS and means there is no
third-party API key to store.

Availability is the reason this whole project deploys to us-east-1 — the
connector is offered there and nowhere else. See pre-research/websearch/.
"""

import os
from typing import Optional

from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
from strands.tools.mcp import MCPClient

# The gateway authorizes with AWS_IAM, so requests are SigV4-signed with the
# runtime's execution role. That role needs bedrock-agentcore:InvokeGateway;
# without it the calls come back as AccessDenied.
_AWS_SERVICE = "bedrock-agentcore"


# The CLI injects AGENTCORE_GATEWAY_<NAME>_URL for each gateway in the project.
# Matching on the prefix rather than one hard-coded name means renaming the
# gateway does not silently turn search off. GATEWAY_URL overrides it, which is
# what local runs use.
_INJECTED_URL_PREFIX = "AGENTCORE_GATEWAY_"
_INJECTED_URL_SUFFIX = "_URL"


def _find_gateway_url() -> Optional[str]:
    """Return the gateway endpoint from the environment, if there is one."""
    override = os.environ.get("GATEWAY_URL")
    if override:
        return override

    # Sorted so the choice is deterministic if a future project adds a second
    # gateway; at that point this should take the name explicitly instead.
    for name in sorted(os.environ):
        if name.startswith(_INJECTED_URL_PREFIX) and name.endswith(_INJECTED_URL_SUFFIX):
            return os.environ[name]
    return None


def load_web_search() -> Optional[MCPClient]:
    """Return an MCP client for the gateway, or None when it is unconfigured.

    Returning None keeps the agent usable without a gateway: it simply answers
    from the model's own knowledge, which is how the earlier conversation
    -continuity work ran. That also keeps local development possible without
    deploying a gateway first.
    """
    endpoint = _find_gateway_url()
    if not endpoint:
        return None

    # Region is taken from the endpoint's own region rather than the runtime's,
    # since the two need not match.
    region = os.environ.get("GATEWAY_REGION", "us-east-1")

    return MCPClient(
        lambda: aws_iam_streamablehttp_client(
            endpoint=endpoint,
            aws_region=region,
            aws_service=_AWS_SERVICE,
        )
    )
