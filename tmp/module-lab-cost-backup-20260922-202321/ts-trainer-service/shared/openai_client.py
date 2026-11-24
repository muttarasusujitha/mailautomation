"""OpenAI client wrapper with support for custom API base (e.g. AWS Bedrock Mantle).

Usage:
    from microservices.shared.openai_client import get_openai_client
    client = get_openai_client()  # reads OPENAI_API_KEY and OPENAI_API_BASE from env

This wrapper tries to instantiate the modern OpenAI client (OpenAI class) and
falls back to the classic `openai` module global configuration so existing code
that does `import openai` still works.

Environment variables supported:
- OPENAI_API_KEY: API key (can be an OpenAI key or a Bedrock Mantle key)
- OPENAI_API_BASE: Optional base URL to send requests to, e.g.
  https://bedrock-mantle.ap-south-1.api.aws/v1

The wrapper is intentionally lightweight — it returns either a client instance
or the imported openai module so callers can continue using their existing
patterns. Prefer migrating to a single call site that uses the returned client.
"""
from __future__ import annotations

import os
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)

try:
    # Newer OpenAI SDK exposes an OpenAI client class
    from openai import OpenAI as _OpenAIClient  # type: ignore
    _HAS_OPENAI_CLASS = True
except Exception:  # pragma: no cover - runtime import fallback
    _OpenAIClient = None
    _HAS_OPENAI_CLASS = False

try:
    import openai as _openai_module  # classic module-based client
except Exception:  # pragma: no cover
    _openai_module = None


def _env(var: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(var)
    if v is None:
        return default
    return v.strip()


def get_openai_client(api_key: Optional[str] = None, api_base: Optional[str] = None) -> Any:
    """Return an OpenAI-compatible client configured with API key and base.

    - If the modern `OpenAI` class is available (openai.OpenAI), returns an
      instance of it configured with api_key/api_base.
    - Otherwise configures the classic `openai` module (openai.api_key,
      openai.api_base) and returns the module object.

    This function never raises if the openai package is missing; instead it
    logs and returns None so callers can handle absence of the dependency.
    """
    api_key = api_key or _env("OPENAI_API_KEY")
    api_base = api_base or _env("OPENAI_API_BASE")

    if _HAS_OPENAI_CLASS and _OpenAIClient is not None:
        try:
            kwargs = {}
            if api_key:
                kwargs["api_key"] = api_key
            if api_base:
                # Many OpenAI-compatible endpoints accept `api_base`.
                kwargs["api_base"] = api_base
            client = _OpenAIClient(**kwargs)
            logger.debug("Created OpenAI client with api_base=%s", api_base)
            return client
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to create OpenAI client instance: %s", exc)

    if _openai_module is not None:
        try:
            if api_key:
                try:
                    # new-style attribute
                    setattr(_openai_module, "api_key", api_key)
                except Exception:
                    _openai_module.api_key = api_key
            if api_base:
                try:
                    setattr(_openai_module, "api_base", api_base)
                except Exception:
                    _openai_module.api_base = api_base
            logger.debug("Configured openai module with api_base=%s", api_base)
            return _openai_module
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to configure openai module: %s", exc)

    logger.warning("openai package not installed; get_openai_client() returns None")
    return None


# Small convenience function used by callers that prefer a minimal API.
def chat_completion_create(client: Any, **kwargs: Any) -> Any:
    """Call a chat completion method on the provided client.

    This supports both the modern client (.chat.completions.create) and the
    classic module (openai.ChatCompletion.create). Callers should prefer
    to use the returned client directly, but this helper eases migration.
    """
    if client is None:
        raise RuntimeError("OpenAI client is not available — install openai package or set env vars")

    # Modern client: client.chat.completions.create
    try:
        chat = getattr(client, "chat")
        completions = getattr(chat, "completions")
        create = getattr(completions, "create")
        return create(**kwargs)
    except Exception:
        pass

    # Classic module: openai.ChatCompletion.create
    try:
        return client.ChatCompletion.create(**kwargs)
    except Exception as exc:  # pragma: no cover - fallback
        raise
