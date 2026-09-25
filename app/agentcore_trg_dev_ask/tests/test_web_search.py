"""Tests for gateway discovery in tools.web_search.

The agent has to stay useful when no gateway is configured, and it has to find
the URL the CLI injects without that URL being hard-coded anywhere. Both are
easy to break silently — a wrong variable name just turns search off — so they
are pinned here.
"""

import pytest

from tools.web_search import _find_gateway_url, load_web_search

INJECTED = "AGENTCORE_GATEWAY_GWTRGDEVMAIN_URL"
ENDPOINT = "https://example.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"


@pytest.fixture(autouse=True)
def clear_gateway_env(monkeypatch):
    """Start each test from an environment with no gateway variables."""
    for name in ("GATEWAY_URL", "GATEWAY_REGION", INJECTED):
        monkeypatch.delenv(name, raising=False)


def test_returns_none_when_no_gateway_configured():
    # The agent must still answer, just without search.
    assert _find_gateway_url() is None
    assert load_web_search() is None


def test_finds_the_url_the_cli_injects(monkeypatch):
    monkeypatch.setenv(INJECTED, ENDPOINT)
    assert _find_gateway_url() == ENDPOINT


def test_finds_injected_url_under_any_gateway_name(monkeypatch):
    # Renaming the gateway changes this variable's name, which must not
    # silently disable search.
    monkeypatch.setenv("AGENTCORE_GATEWAY_SOMETHINGELSE_URL", ENDPOINT)
    assert _find_gateway_url() == ENDPOINT


def test_explicit_override_wins_over_injected(monkeypatch):
    # Local runs point at their own endpoint while the injected one is present.
    monkeypatch.setenv(INJECTED, ENDPOINT)
    monkeypatch.setenv("GATEWAY_URL", "https://local.example/mcp")
    assert _find_gateway_url() == "https://local.example/mcp"


def test_ignores_unrelated_agentcore_variables(monkeypatch):
    # The CLI injects an auth-type variable alongside the URL; only the URL is
    # a valid endpoint.
    monkeypatch.setenv("AGENTCORE_GATEWAY_GWTRGDEVMAIN_AUTH_TYPE", "AWS_IAM")
    assert _find_gateway_url() is None


def test_builds_a_client_when_configured(monkeypatch):
    monkeypatch.setenv(INJECTED, ENDPOINT)
    assert load_web_search() is not None
