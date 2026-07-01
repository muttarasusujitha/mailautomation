"""AI assistant chat — conversational interface backed by Anthropic/Gemini."""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db
from app.config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    context: Optional[Dict[str, Any]] = None
    system_prompt: Optional[str] = None
    max_tokens: int = 1000
    temperature: float = 0.7



def _clean_messages(messages: List[ChatMessage]) -> List[Dict[str, str]]:
    cleaned = []
    for m in messages:
        role = m.role
        content = m.content.strip()
        if role not in {"user", "assistant"} or not content:
            continue
        if not cleaned and role != "user":
            continue
        if cleaned and cleaned[-1]["role"] == role:
            cleaned[-1]["content"] += f"\n\n{content}"
        else:
            cleaned.append({"role": role, "content": content})
    return cleaned[-12:]


async def _call_anthropic(messages: List[Dict], system: str, settings, max_tokens: int, temperature: float) -> str:
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY.strip())
    resp = await client.messages.create(
        model="claude-haiku-4-20250514",
        max_tokens=max_tokens,
        temperature=temperature,
        system=system or "You are TrainerSync AI — a helpful training coordination assistant.",
        messages=messages,
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()


async def _call_gemini(messages: List[Dict], system: str, settings, max_tokens: int, temperature: float) -> str:
    import google.generativeai as genai
    genai.configure(api_key=settings.GEMINI_API_KEY.strip())
    model = genai.GenerativeModel(
        settings.GEMINI_MODEL,
        generation_config={"temperature": temperature, "max_output_tokens": max_tokens},
        system_instruction=system or "You are TrainerSync AI — a helpful training coordination assistant.",
    )
    import asyncio
    history = [{"role": m["role"], "parts": [m["content"]]} for m in messages[:-1]]
    last = messages[-1]["content"]
    chat = model.start_chat(history=history)
    resp = await asyncio.get_event_loop().run_in_executor(None, lambda: chat.send_message(last))
    return resp.text.strip()


@router.post("/chat")
async def assistant_chat(payload: ChatRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    settings = get_settings()
    messages = _clean_messages(payload.messages)
    if not messages:
        raise HTTPException(400, "At least one user message is required")

    ctx = payload.context or {}
    ctx_lines = "\n".join(f"- {k}: {v}" for k, v in ctx.items() if v)
    system = payload.system_prompt or (
        "You are TrainerSync AI, an expert training coordination assistant.\n"
        "Help with trainer matching, requirement analysis, email drafting, and pipeline decisions.\n"
        + (f"\nContext:\n{ctx_lines}" if ctx_lines else "")
    )

    reply = ""
    error = ""
    if settings.ANTHROPIC_API_KEY.strip():
        try:
            reply = await _call_anthropic(messages, system, settings, payload.max_tokens, payload.temperature)
        except Exception as exc:
            logger.warning("Anthropic failed, trying Gemini: %s", exc)
            error = str(exc)

    if not reply and settings.GEMINI_API_KEY.strip():
        try:
            reply = await _call_gemini(messages, system, settings, payload.max_tokens, payload.temperature)
            error = ""
        except Exception as exc:
            logger.error("Gemini also failed: %s", exc)
            error = str(exc)

    if not reply:
        reply = (
            "I'm sorry, I couldn't process your request right now. "
            "Please check that ANTHROPIC_API_KEY or GEMINI_API_KEY is configured."
        )

    return {
        "success": True,
        "reply": reply,
        "error": error or None,
        "messages": messages + [{"role": "assistant", "content": reply}],
    }
