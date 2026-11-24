import asyncio
import json
from pathlib import Path

from app.config import get_settings
from app.curriculum_reasoning import generate_reasoned_toc, builtin_records
from app.routes.toc import TocRequest


async def main():
    settings = get_settings()
    print(json.dumps({"reference_units": sum(r["version"] == "reference-import-v1" for r in builtin_records()),
                      "ai_configured": bool(settings.OPENAI_API_KEY.strip())}), flush=True)
    if not settings.OPENAI_API_KEY.strip():
        return
    from openai import AsyncOpenAI
    request = TocRequest(domain="Python", duration_days=1, hours_per_day=4,
        audience_level="Analysts who already know Python basics", custom_topics="pandas; CSV validation",
        client_notes="One day workshop. Teach cleaning missing values and validating a sales CSV. No web frameworks. Include two timed modules, a practical deliverable and an assessment.")
    async with AsyncOpenAI(api_key=settings.OPENAI_API_KEY.strip(), timeout=60, max_retries=0) as client:
        try:
            toc = await asyncio.wait_for(generate_reasoned_toc(request, client, settings), 180)
            Path('/tmp/toc-live-check.json').write_text(json.dumps(toc, indent=2))
            print(json.dumps({"status": toc["quality"]["status"], "errors": toc["quality"]["validation_errors"],
                "warnings": toc["quality"]["review_warnings"], "matching": toc["retrieval"]["method"],
                "days": len(toc["days"]), "modules": sum(len(d["modules"]) for d in toc["days"])}), flush=True)
        except Exception as exc:
            print(json.dumps({"live_ai_error": type(exc).__name__, "detail": str(exc)[:700]}), flush=True)


asyncio.run(main())
