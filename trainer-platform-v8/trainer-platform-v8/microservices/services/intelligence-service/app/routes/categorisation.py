"""Trainer AI categorisation endpoint — wraps a local Ollama Sonnet call."""
import asyncio
import json
import logging
import os
import re
import shutil
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db
from app.config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()

SOFTWARE_TECH_DOMAINS = [
    "Software Development", "Frontend Development", "Backend Development",
    "Full Stack", "Cloud", "DevOps", "SRE", "Data Engineering", "Data Analytics",
    "Data Science", "Business Intelligence", "AI", "Gen AI", "Agentic AI",
    "Machine Learning", "MLOps", "LLMOps", "AIOps", "Cybersecurity", "Blockchain",
    "Database", "QA and Testing", "Automation Testing", "Enterprise Software",
    "ERP Software", "CRM Software", "Salesforce", "ServiceNow", "SAP Technical",
    "Mobile Development", "Game Development", "AR and VR", "IoT",
    "Embedded Systems", "Robotics", "Quantum Computing", "Programming Languages",
]


def _ollama_available() -> bool:
    binary = shutil.which(settings.OLLAMA_BINARY)
    return bool(binary)


async def _run_local_ollama(prompt: str) -> str:
    if not _ollama_available():
        raise HTTPException(503, "Local Ollama CLI not found. Install Ollama or set OLLAMA_BINARY correctly.")

    env = {**os.environ, "TERM": "dumb"}
    process = await asyncio.create_subprocess_exec(
        settings.OLLAMA_BINARY,
        "run",
        settings.OLLAMA_SONNET_MODEL,
        prompt,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        text=True,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        message = stderr.strip() or stdout.strip() or f"Ollama exited with code {process.returncode}"
        raise HTTPException(503, f"Ollama Sonnet execution failed: {message}")
    return stdout


def _extract_json(text: str) -> Dict[str, Any]:
    clean = re.sub(r"^```(?:json)?", "", text.strip(), flags=re.IGNORECASE).strip()
    clean = re.sub(r"```$", "", clean).strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", clean, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


class CategoriseRequest(BaseModel):
    trainer_id: Optional[str] = None
    trainer: Optional[Dict[str, Any]] = None
    save: bool = True


class BulkCategoriseRequest(BaseModel):
    limit: int = 20
    dry_run: bool = False


@router.post("/categorise")
async def categorise_trainer(payload: CategoriseRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    trainer = payload.trainer
    if not trainer and payload.trainer_id:
        trainer = await db.trainers.find_one({"trainer_id": payload.trainer_id}, {"_id": 0}) or {}
    if not trainer:
        raise HTTPException(400, "Provide trainer data or a valid trainer_id")

    if not _ollama_available():
        raise HTTPException(503, "Ollama CLI unavailable — install Ollama or configure OLLAMA_BINARY.")

    profile = {k: trainer.get(k) for k in [
        "trainer_id", "name", "technologies", "skills", "certifications",
        "experience_years", "summary", "past_clients", "training_count",
        "location", "category", "secondary_categories", "specialty_tags",
    ]}
    prompt = (
        f"Classify this software trainer. Return ONLY valid JSON.\n\n"
        f"Allowed domains: {json.dumps(SOFTWARE_TECH_DOMAINS)}\n\n"
        f"Return exactly: {{\"primary_category\": str, \"secondary_categories\": list, \"domain\": str, "
        f"\"specialisation_tags\": list, \"industry_focus\": list, \"skill_level_map\": dict, "
        f"\"language_of_delivery\": list, \"confidence\": float, \"needs_review\": bool, \"reasoning\": str}}\n\n"
        f"Trainer:\n{json.dumps(profile, default=str)}"
    )

    raw = await _run_local_ollama(prompt)
    result = _extract_json(raw)
    result["categorisation_model"] = settings.OLLAMA_SONNET_MODEL

    if payload.save and payload.trainer_id:
        from datetime import datetime
        await db.trainers.update_one(
            {"trainer_id": payload.trainer_id},
            {"$set": {**result, "technology_category": result.get("primary_category"), "updated_at": datetime.utcnow()}},
        )

    return {"success": True, "trainer_id": payload.trainer_id, "categorisation": result}


@router.post("/categorise/bulk")
async def bulk_categorise(payload: BulkCategoriseRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    query = {"$or": [
        {"primary_category": {"$exists": False}},
        {"primary_category": None},
        {"primary_category": ""},
    ]}
    cursor = db.trainers.find(query, {"_id": 0}).limit(payload.limit)
    trainers = [d async for d in cursor]
    processed = succeeded = failed = 0
    for t in trainers:
        processed += 1
        try:
            req = CategoriseRequest(trainer_id=t.get("trainer_id"), trainer=t, save=not payload.dry_run)
            await categorise_trainer(req, db)
            succeeded += 1
        except Exception as e:
            failed += 1
            logger.warning("Categorisation failed for %s: %s", t.get("trainer_id"), e)
        await asyncio.sleep(0.1)
    return {"processed": processed, "succeeded": succeeded, "failed": failed, "dry_run": payload.dry_run}
