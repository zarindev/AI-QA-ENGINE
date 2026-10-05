"""Claude API client used by every AI stage.

* Structured JSON: `structured()` asks for a Pydantic model and returns a validated instance
  (`beta.messages.parse` with `output_format`, so the response is guaranteed to match the schema).
* Retries: the SDK retries 408/409/429/5xx/connection errors; `max_retries` comes from settings.
* Refusals: `fallbacks: "default"` re-runs a declined request on Anthropic's recommended fallback model;
  a final `stop_reason == "refusal"` raises `AIRefusal`.
* Caching: the stable system prompt carries `cache_control` (prompt caching on the API side), and identical
  requests are answered from a local disk cache in workspace/.cache/ai (configurable).
* Budget: every call adds to a shared `TokenUsage`; once the run's token budget is spent, `BudgetExceeded`
  is raised *before* the next request is sent.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel

from app.core.config import get_settings, load_env
from app.core.logging import get_logger, register_secret
from app.core.paths import workspace_root
from app.storage.schemas import TokenUsage

log = get_logger("ai")
T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"

# USD per million tokens: (input, output, cache_read, cache_write_5m)
PRICING: dict[str, tuple[float, float, float, float]] = {
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-opus-5": (5.00, 25.00, 0.50, 6.25),
    "claude-opus-4-8": (5.00, 25.00, 0.50, 6.25),
    "claude-sonnet-5": (2.00, 10.00, 0.20, 2.50),
    "claude-haiku-4-5": (1.00, 5.00, 0.10, 1.25),
    "claude-fable-5-1": (10.00, 50.00, 0.25, 12.50),
}
DEFAULT_PRICE = PRICING["claude-sonnet-5-5"]


class AIUnavailable(RuntimeError):
    """No API key configured."""


class BudgetExceeded(RuntimeError):
    pass


class AIRefusal(RuntimeError):
    pass


class AIResponseError(RuntimeError):
    pass


WORKSPACE_HINT = (
    "This key belongs to your user account rather than a workspace, so Anthropic needs to know which workspace "
    "to bill. Enter the workspace ID (Console → Settings → Workspaces, it starts with “wrkspc_”), "
    "or create a key inside a workspace instead."
)


def workspace_headers(workspace_id: str | None = None) -> dict[str, str]:
    """User-level keys (not scoped to a workspace) must name the workspace on every request."""
    load_env()
    ws = (workspace_id if workspace_id is not None else os.environ.get("ANTHROPIC_WORKSPACE_ID", "")).strip()
    return {"anthropic-workspace-id": ws} if ws else {}


def estimate_cost(
    model: str, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0
) -> float:
    price = PRICING.get(model, DEFAULT_PRICE)
    return (
        input_tokens * price[0] + output_tokens * price[1] + cache_read * price[2] + cache_write * price[3]
    ) / 1e6


def image_block(path: Path, media_type: str = "image/png") -> dict[str, Any]:
    data = base64.standard_b64encode(Path(path).read_bytes()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


class AIClient:
    def __init__(
        self,
        usage: TokenUsage | None = None,
        budget_tokens: int | None = None,
        on_usage: Callable[[TokenUsage], None] | None = None,
        cache_dir: Path | None = None,
        settings: dict[str, Any] | None = None,
    ) -> None:
        load_env()
        self.settings = (settings or get_settings())["ai"]
        self.model: str = self.settings["model"]
        self.usage = usage if usage is not None else TokenUsage()
        self.budget = (
            budget_tokens if budget_tokens is not None else int(self.settings.get("run_token_budget", 0))
        )
        self.on_usage = on_usage
        self.cost_budget = float(self.settings.get("run_cost_budget_usd", 0) or 0)
        self.cache_dir = cache_dir or workspace_root() / ".cache" / "ai"
        self.use_fallbacks = bool(self.settings.get("use_server_fallbacks", True))
        self._lock = threading.Lock()
        self._client: anthropic.Anthropic | None = None

    # ------------------------------------------------------------------ setup

    @staticmethod
    def available() -> bool:
        load_env()
        return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
            if not key:
                raise AIUnavailable("ANTHROPIC_API_KEY is not set. Add it to .env or paste it in Settings.")
            register_secret(key)
            self._client = anthropic.Anthropic(
                api_key=key,
                timeout=float(self.settings.get("request_timeout_s", 180)),
                max_retries=int(self.settings.get("max_retries", 3)),
                default_headers=workspace_headers(),
            )
        return self._client

    @staticmethod
    def validate_key(key: str, workspace_id: str | None = None) -> tuple[bool, str]:
        """Cheap key check used by the onboarding screen: list models (no tokens spent)."""
        try:
            anthropic.Anthropic(
                api_key=key, max_retries=1, timeout=20.0, default_headers=workspace_headers(workspace_id)
            ).models.list(limit=1)
            return True, "API key is valid."
        except anthropic.BadRequestError as exc:
            if "workspace" in str(exc).lower():
                return False, WORKSPACE_HINT
            return False, f"Anthropic rejected the request: {exc.message}"
        except anthropic.AuthenticationError:
            return False, "Anthropic rejected this API key."
        except anthropic.PermissionDeniedError:
            return False, "This key does not have permission to use the API."
        except anthropic.APIConnectionError:
            return False, "Could not reach api.anthropic.com — check your internet connection."
        except anthropic.APIStatusError as exc:
            return False, f"Unexpected API error ({exc.status_code})."

    # ------------------------------------------------------------------ accounting

    def _check_budget(self) -> None:
        """Budgets count uncached tokens (cache reads cost a tenth and would exhaust a token budget early) and
        dollars. Raised before the next request, so a run never overshoots by more than one request."""
        u = self.usage
        uncached = u.input_tokens + u.output_tokens + u.cache_write_tokens
        if self.budget and uncached >= self.budget:
            raise BudgetExceeded(
                f"Token budget of {self.budget:,} uncached tokens for this run is used up "
                "(Settings → Claude → token budget)."
            )
        if self.cost_budget and u.cost_usd >= self.cost_budget:
            raise BudgetExceeded(
                f"Cost budget of ${self.cost_budget:.2f} for this run is used up "
                "(Settings → Claude → cost budget)."
            )

    def _record(self, model: str, usage: Any, cached: bool = False) -> None:
        with self._lock:
            if cached:
                self.usage.cached_responses += 1
            else:
                i = int(getattr(usage, "input_tokens", 0) or 0)
                o = int(getattr(usage, "output_tokens", 0) or 0)
                cr = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
                cw = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
                self.usage.input_tokens += i
                self.usage.output_tokens += o
                self.usage.cache_read_tokens += cr
                self.usage.cache_write_tokens += cw
                self.usage.requests += 1
                self.usage.cost_usd = round(self.usage.cost_usd + estimate_cost(model, i, o, cr, cw), 6)
            snapshot = self.usage.model_copy()
        if self.on_usage:
            self.on_usage(snapshot)

    # ------------------------------------------------------------------ disk cache

    def _cache_key(self, payload: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> Any | None:
        if not self.settings.get("response_cache", True):
            return None
        path = self.cache_dir / key[:2] / f"{key}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
        return None

    def _cache_put(self, key: str, value: Any) -> None:
        if not self.settings.get("response_cache", True):
            return
        path = self.cache_dir / key[:2] / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    # ------------------------------------------------------------------ requests

    def _common_kwargs(self, system: str, effort: str | None, max_tokens: int | None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": int(max_tokens or self.settings.get("max_tokens", 16000)),
            # Stable instructions first, cached; volatile content goes in the user turn.
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": effort or self.settings.get("effort", "medium")},
        }
        if self.use_fallbacks:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        return kwargs

    def _send(self, fn: Callable[..., Any], kwargs: dict[str, Any]) -> Any:
        self._check_budget()
        try:
            response = fn(**kwargs)
        except anthropic.BadRequestError as exc:
            if "credit balance" in str(exc).lower():
                raise AIUnavailable(
                    "Your Anthropic account has no API credits left. Add credits in the Console under "
                    "Settings → Billing, then resume the run."
                ) from exc
            if "fallback" in str(exc).lower() and kwargs.get("fallbacks"):
                log.warning(
                    "Server-side fallbacks were rejected for this account/model; retrying without them."
                )
                self.use_fallbacks = False
                kwargs = {k: v for k, v in kwargs.items() if k not in ("fallbacks", "betas")}
                response = fn(**kwargs)
            else:
                raise
        self._record(getattr(response, "model", self.model), response.usage)
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise AIRefusal(f"Claude declined this request (category: {category or 'unspecified'}).")
        if response.stop_reason == "max_tokens":
            raise AIResponseError(
                "The response hit max_tokens before finishing; raise ai.max_tokens in settings."
            )
        return response

    def structured(
        self,
        *,
        system: str,
        content: str | list[dict[str, Any]],
        schema: type[T],
        purpose: str = "",
        effort: str | None = None,
        max_tokens: int | None = None,
        use_cache: bool = True,
    ) -> T:
        """One request -> one validated Pydantic object."""
        user_content = [{"type": "text", "text": content}] if isinstance(content, str) else content
        kwargs = self._common_kwargs(system, effort, max_tokens)
        kwargs["messages"] = [{"role": "user", "content": user_content}]
        kwargs["output_format"] = schema

        key = self._cache_key(
            {
                "model": self.model,
                "system": system,
                "content": user_content,
                "schema": schema.model_json_schema(),
                "effort": kwargs["output_config"]["effort"],
            }
        )
        if use_cache:
            hit = self._cache_get(key)
            if hit is not None:
                self._record(self.model, None, cached=True)
                log.info("AI %s: answered from local cache", purpose or schema.__name__)
                return schema.model_validate(hit)

        log.info("AI %s: calling %s", purpose or schema.__name__, self.model)
        # The SDK refuses non-streaming requests that could take over 10 minutes (~21k max_tokens);
        # large outputs (requirements, test suites) stream and are parsed from the final message.
        call = self._stream_parse if kwargs["max_tokens"] > 16000 else self.client.beta.messages.parse
        response = self._send(call, kwargs)
        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            raise AIResponseError(
                f"Claude returned no parseable {schema.__name__} for {purpose or 'request'}."
            )
        self._cache_put(key, parsed.model_dump(mode="json"))
        return parsed

    def _stream_parse(self, **kwargs: Any) -> Any:
        with self.client.beta.messages.stream(**kwargs) as stream:
            return stream.get_final_message()

    def messages(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        effort: str | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        """Raw multi-turn call for agent loops (stage ⑥). Returns the SDK message object."""
        kwargs = self._common_kwargs(system, effort, max_tokens)
        kwargs["messages"] = messages
        if tools:
            kwargs["tools"] = tools
            # Forced tool choice is not available on current models: "auto" + the prompt asks for one tool call,
            # and parallel calls are disabled so each turn is exactly one browser action.
            kwargs["tool_choice"] = {"type": "auto", "disable_parallel_tool_use": True}
        return self._send(self.client.beta.messages.create, kwargs)
