"""Async adapter using the same Ollama /api/generate contract as intelligence-service."""
import json
from types import SimpleNamespace
from typing import Any

import httpx


class OllamaResponses:
    """Expose the existing plain-prompt Ollama API through the TOC planner interface."""

    def __init__(self, ollama_url: str, timeout: float = 300):
        endpoint = ollama_url.strip().rstrip("/")
        if endpoint.endswith("/api/chat"):
            endpoint = endpoint[:-len("/api/chat")] + "/api/generate"
        elif not endpoint.endswith("/api/generate"):
            endpoint += "/api/generate"
        self.url = endpoint
        self.timeout = timeout

    async def create(self, *, model: str, input: str, instructions: str = "",
                     text: dict | None = None, max_output_tokens: int = 4000,
                     native_schema: bool = False, think: bool | None = None,
                     **_options: Any):
        output_format = (text or {}).get("format") or {}
        system_prompt = instructions or "Follow the user's request and return the requested result."
        if output_format.get("type") == "json_schema":
            system_prompt += (
                "\nReturn only a JSON object matching the supplied schema. Do not include markdown fences, "
                "commentary, or text outside the JSON object."
            )
            system_prompt += '\n' + json.dumps(output_format["schema"], ensure_ascii=False)

        prompt = input if isinstance(input, str) else json.dumps(input, ensure_ascii=False, default=str)
        body = {
            "model": model,
            "system": system_prompt,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0 if native_schema else 0.7, "num_predict": max_output_tokens},
        }
        if native_schema and output_format.get("type") == "json_schema":
            body["format"] = output_format["schema"]
        if think is not None:
            body["think"] = think

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.url, json=body)
            response.raise_for_status()

        result = response.json()
        content = result.get("response")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Ollama returned an empty generate response "
                             f"(done_reason={result.get('done_reason')}, "
                             f"generated_tokens={result.get('eval_count')}, "
                             f"prompt_tokens={result.get('prompt_eval_count')})")
        content = content.strip()
        if output_format.get("type") == "json_schema":
            content = _extract_json_object(content)
        return SimpleNamespace(output_text=content.strip())


def _extract_json_object(content: str) -> str:
    """Strip incidental prose or markdown around a generated JSON object."""
    decoder = json.JSONDecoder()
    for index, character in enumerate(content):
        if character != "{":
            continue
        try:
            value, end = decoder.raw_decode(content[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
    raise ValueError("Ollama did not return a valid JSON object")


class OllamaClient:
    """Minimal client compatible with curriculum_reasoning.structured()."""

    def __init__(self, base_url: str, timeout: float = 300):
        self.responses = OllamaResponses(base_url, timeout=timeout)
