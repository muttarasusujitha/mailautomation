"""Example: call an OpenAI-compatible chat completion (AWS Bedrock Mantle) using the
get_openai_client() wrapper.

Configure env (example):
  set OPENAI_API_KEY=<your-bedrock-mantle-key>
  set OPENAI_API_BASE=https://bedrock-mantle.ap-south-1.api.aws/v1
  pip install openai
  python microservices\shared\bedrock_example.py

The script is intentionally conservative and prints useful debug hints if the
client is not available or the request fails.
"""
from __future__ import annotations

import os
import json
import logging
from microservices.shared.openai_client import get_openai_client, chat_completion_create

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_demo():
    client = get_openai_client()
    if client is None:
        logger.error("OpenAI client unavailable. Ensure 'openai' package is installed and OPENAI_API_KEY is set.")
        return

    # A minimal chat messages payload. Adjust `model` as required by your Bedrock setup.
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Say hello in one sentence."},
    ]

    # Try using the wrapper helper which supports both modern and classic clients.
    try:
        resp = chat_completion_create(client, model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), messages=messages, max_tokens=64)
        # The response shape differs between providers / SDK versions. Print raw output for inspection.
        print("Raw response:\n", json.dumps(resp, default=str, indent=2))
    except Exception as exc:
        logger.exception("Chat completion request failed: %s", exc)


if __name__ == "__main__":
    # Quick environment debug
    logger.info("OPENAI_API_KEY present: %s", bool(os.getenv("OPENAI_API_KEY")))
    logger.info("OPENAI_API_BASE: %s", os.getenv("OPENAI_API_BASE"))
    run_demo()
