from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.ai.client import AIClient, AIRefusal, BudgetExceeded, estimate_cost
from app.core import crypto
from app.core.logging import redact, register_secret
from app.storage.schemas import TokenUsage


class Answer(BaseModel):
    domain: str
    confidence: float


class _FakeMessages:
    """Stands in for client.beta.messages in unit tests only (the real code path always calls the API)."""

    def __init__(self, stop_reason: str = "end_turn") -> None:
        self.calls = 0
        self.stop_reason = stop_reason
        self.last_kwargs: dict = {}

    def parse(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        return SimpleNamespace(
            model=kwargs["model"],
            stop_reason=self.stop_reason,
            stop_details=None,
            usage=SimpleNamespace(
                input_tokens=1000,
                output_tokens=200,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=500,
            ),
            parsed_output=Answer(domain="healthcare", confidence=0.9),
        )


def _client(tmp_path, fake, **kw) -> AIClient:
    ai = AIClient(cache_dir=tmp_path / "cache", **kw)
    ai._client = SimpleNamespace(beta=SimpleNamespace(messages=fake))  # type: ignore[assignment]
    return ai


def test_structured_call_shape_usage_and_cache(tmp_path):
    fake = _FakeMessages()
    seen: list[TokenUsage] = []
    ai = _client(tmp_path, fake, on_usage=seen.append)
    out = ai.structured(system="sys", content="pages...", schema=Answer, purpose="classify")
    assert out.domain == "healthcare"
    kw = fake.last_kwargs
    assert kw["model"] == "claude-sonnet-5-5"
    assert kw["thinking"] == {"type": "adaptive"}
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert "tool_choice" not in kw  # forced tool choice is rejected by current models
    assert ai.usage.input_tokens == 1000 and ai.usage.cache_write_tokens == 500
    assert ai.usage.cost_usd == pytest.approx(estimate_cost("claude-sonnet-5-5", 1000, 200, 0, 500))
    # identical request -> answered from the local cache, no second API call
    again = ai.structured(system="sys", content="pages...", schema=Answer, purpose="classify")
    assert again == out and fake.calls == 1 and ai.usage.cached_responses == 1
    assert len(seen) == 2


def test_budget_is_enforced_before_sending(tmp_path):
    fake = _FakeMessages()
    ai = _client(tmp_path, fake, budget_tokens=1500)
    ai.structured(system="s", content="one", schema=Answer, use_cache=False)
    with pytest.raises(BudgetExceeded):
        ai.structured(system="s", content="two", schema=Answer, use_cache=False)
    assert fake.calls == 1


def test_refusal_raises(tmp_path):
    ai = _client(tmp_path, _FakeMessages(stop_reason="refusal"))
    with pytest.raises(AIRefusal):
        ai.structured(system="s", content="x", schema=Answer, use_cache=False)


def test_unavailable_without_key():
    assert AIClient.available() is False


def test_redaction_of_registered_secrets():
    register_secret("Sup3r-Secret!")
    assert redact("login with Sup3r-Secret! please") == "login with *** please"


def test_usernames_are_not_treated_as_secrets():
    token = crypto.encrypt_json({"role:admin": {"username": "Admin", "password": "admin-pass-77"}})
    crypto.decrypt_json(token)
    assert redact("Admin menu") == "Admin menu"
    assert redact("pw admin-pass-77") == "pw ***"


def test_workspace_header_only_when_configured(monkeypatch):
    from app.ai.client import workspace_headers

    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "")
    assert workspace_headers() == {}
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "wrkspc_abc")
    assert workspace_headers() == {"anthropic-workspace-id": "wrkspc_abc"}
    assert workspace_headers("") == {}
