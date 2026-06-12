import asyncio
import json
import os
import re
from datetime import datetime
from utils.time_utils import utc_now
from typing import Any, Dict, List, Optional

import anthropic
from config import get_settings


CATEGORISATION_MODEL = "claude-sonnet-4-20250514"

SOFTWARE_TECH_DOMAINS = [
    "Software Development",
    "Frontend Development",
    "Backend Development",
    "Full Stack",
    "Programming Languages",
    "Cloud",
    "DevOps",
    "SRE",
    "Data Engineering",
    "Data Analytics",
    "Data Science",
    "Business Intelligence",
    "AI",
    "Gen AI",
    "Agentic AI",
    "Machine Learning",
    "MLOps",
    "LLMOps",
    "AIOps",
    "Cybersecurity",
    "Blockchain",
    "Database",
    "QA and Testing",
    "Automation Testing",
    "Enterprise Software",
    "ERP Software",
    "CRM Software",
    "Salesforce",
    "ServiceNow",
    "SAP Technical",
    "Mobile Development",
    "Game Development",
    "AR and VR",
    "IoT",
    "Embedded Systems",
    "Robotics",
    "Quantum Computing",
]

NON_SOFTWARE_DOMAIN = "Non-Software Training"
NON_SOFTWARE_DOMAINS = {
    "business",
    "finance",
    "financial",
    "creative",
    "healthcare",
    "manufacturing",
    "language",
    "languages",
    "human language",
    "soft skills",
    "legal",
    "hr",
}
NON_SOFTWARE_CATEGORY_TERMS = [
    "language training",
    "ielts",
    "spoken english",
    "arabic",
    "hindi",
    "tamil",
    "telugu",
    "kannada",
    "malayalam",
    "bengali",
    "leadership",
    "communication",
    "negotiation",
    "sales training",
    "six sigma",
    "pmp",
    "accounting",
    "tax",
    "gst",
    "banking",
    "legal",
    "medical",
    "clinical",
    "nursing",
    "manufacturing",
    "supply chain",
    "logistics",
    "autocad",
    "solidworks",
    "graphic design",
    "video editing",
    "motion graphics",
]


def _anthropic_client() -> anthropic.AsyncAnthropic:
    settings = get_settings()
    api_key = (os.getenv("ANTHROPIC_API_KEY", "") or getattr(settings, "anthropic_api_key", "")).strip()
    return anthropic.AsyncAnthropic(api_key=api_key) if api_key else anthropic.AsyncAnthropic()


def _as_string(value: Any) -> str:
    return str(value or "").strip()


def _as_list(value: Any, limit: Optional[int] = None) -> List[str]:
    if value is None:
        items: List[Any] = []
    elif isinstance(value, list):
        items = value
    elif isinstance(value, str):
        items = re.split(r",|;|\n", value)
    else:
        items = [value]

    cleaned = []
    seen = set()
    for item in items:
        text = str(item).strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        cleaned.append(text)
    return cleaned[:limit] if limit else cleaned


def _extract_json_object(text: str) -> Dict[str, Any]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _trainer_profile_for_prompt(trainer: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "trainer_id": trainer.get("trainer_id"),
        "name": trainer.get("name"),
        "technologies": trainer.get("technologies"),
        "skills": trainer.get("skills", []),
        "certifications": trainer.get("certifications", []),
        "experience_years": trainer.get("experience_years", 0),
        "experience_raw": trainer.get("experience_raw", ""),
        "summary": trainer.get("summary", ""),
        "past_clients": trainer.get("past_clients", []),
        "training_count": trainer.get("training_count"),
        "location": trainer.get("location", ""),
        "legacy_category": trainer.get("technology_category") or trainer.get("category", ""),
        "legacy_secondary_categories": trainer.get("secondary_categories", []),
        "legacy_specialty_tags": trainer.get("specialty_tags", []),
        "resume_excerpt": _as_string(trainer.get("resume"))[:12000],
        "combined_profile_text": _as_string(trainer.get("combined_text"))[:12000],
    }


def _categorisation_prompt(trainer: Dict[str, Any]) -> str:
    profile_json = json.dumps(_trainer_profile_for_prompt(trainer), ensure_ascii=False, default=str)
    domains_json = json.dumps(SOFTWARE_TECH_DOMAINS, ensure_ascii=False)
    return f"""You are a world-class software technology training industry expert.
This TrainerSync instance recruits SOFTWARE TECHNOLOGY trainers only.
Classify this trainer accurately even if their software skill is niche, regional, emerging, or brand new.
Never say unknown. Always find the best matching software technology category or create a clear descriptive software category.

Think about what software technology domain this trainer serves. Use all skills, certifications,
experience summary, past client context, training count, and resume/profile text.
Choose the PRIMARY SPECIALIST from the resume headline, role/designation, profile summary,
training focus, and repeated core skills. Do not classify from one isolated tool or keyword.
Example: DevSecOps, IAM, SAST, DAST, Trivy, Aqua Security, or OWASP inside a DevOps/SRE
resume should remain DevOps/SRE unless the headline/summary clearly says Cybersecurity,
SOC, AppSec, Ethical Hacking, VAPT, or Penetration Testing.

Allowed software technology domains:
{domains_json}

Important software examples and rules:
- Python, Java, JavaScript, TypeScript, Go, Rust, C++, Swift, Kotlin, Dart, R, Scala, PHP, Ruby, and Solidity can be primary trainer categories when that is the main expertise.
- React, Angular, Vue, Node.js, Django, Spring Boot, .NET, MERN, MEAN, and similar stacks are software development categories.
- AWS, Azure, GCP, Kubernetes, Docker, Terraform, CI/CD, Jenkins, GitLab, SRE, and observability belong to Cloud, DevOps, or SRE.
- Data Engineering, Data Science, Data Analytics, Power BI, Tableau, SQL, Spark, Hadoop, and Big Data are software/data technology categories.
- Cybersecurity, Ethical Hacking, SOC, AppSec, VAPT, Penetration Testing, and clearly stated cloud security are Cybersecurity.
- Solidity is usually Blockchain.
- SAP ABAP, SAP Basis, SAP Fiori, SAP HANA, SAP FICO, Oracle ERP, Salesforce, ServiceNow, Microsoft Dynamics, Workday, HubSpot, and Zoho are Enterprise Software, ERP Software, or CRM Software.
- Unity, Unreal Engine, AR, VR, IoT, Embedded Systems, Robotics, and Quantum Computing are software technology categories when training is about the platform, programming, or engineering.
- Salesforce, ServiceNow, Workday, Oracle ERP, HubSpot, and Zoho are Enterprise or CRM platforms.
- Do not use broad non-software domains such as Business, Finance, Creative, Healthcare, Manufacturing, or Language.
- If the profile is mainly non-software training, set primary_category to "Non-Software Training", domain to "{NON_SOFTWARE_DOMAIN}", confidence below 0.7, and needs_review to true.
- Do not force a fixed category list. If a precise software category is better than a broad one, create it.
- If confidence is below 0.7, set needs_review to true.

Return ONLY valid JSON. No markdown, no backticks, no explanation outside the JSON object.
The JSON must use exactly these keys:
{{
  "primary_category": "single best category as a string",
  "secondary_categories": ["up to 3 additional categories"],
  "domain": "one software technology domain from the allowed list, or Non-Software Training only when the trainer is not a software technology trainer",
  "specialisation_tags": ["5 precise software keyword tags such as Kubernetes Expert, Power BI Specialist, Solidity Trainer"],
  "industry_focus": ["industries this software trainer has delivered in, such as Banking, IT, Pharma, Education"],
  "skill_level_map": {{"main skill": "Beginner|Intermediate|Expert"}},
  "language_of_delivery": ["human languages the trainer can deliver software training in, such as English, Hindi, Tamil"],
  "confidence": 0.0,
  "needs_review": false,
  "reasoning": "one sentence explaining why this category was chosen"
}}

Trainer profile:
{profile_json}"""


def _normalise_skill_level(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw.startswith("expert") or raw in {"advanced", "senior"}:
        return "Expert"
    if raw.startswith("beginner") or raw in {"basic", "foundation", "foundational"}:
        return "Beginner"
    return "Intermediate"


def _normalise_software_domain(primary: str, domain: Any) -> str:
    raw_domain = _as_string(domain)
    for allowed in SOFTWARE_TECH_DOMAINS:
        if allowed.lower() == raw_domain.lower():
            return allowed
    for allowed in SOFTWARE_TECH_DOMAINS:
        if allowed.lower() == _as_string(primary).lower():
            return allowed

    text = f"{primary} {raw_domain}".lower()
    if (
        any(term in text for term in ["devops", "ci/cd", "cicd", "jenkins", "kubernetes", "terraform", "sre", "site reliability"])
        and not any(term in text for term in ["cybersecurity", "ethical hacking", "penetration testing", "vapt", "soc analyst", "appsec"])
    ):
        if "sre" in text or "site reliability" in text:
            return "SRE"
        return "DevOps"
    keyword_map = [
        ("Full Stack", ["full stack", "mern", "mean"]),
        ("Frontend Development", ["frontend", "react", "angular", "vue", "html", "css"]),
        ("Backend Development", ["backend", "spring", "django", "fastapi", "node", ".net", "api"]),
        ("DevOps", ["devops", "kubernetes", "terraform", "jenkins", "ci/cd", "cicd"]),
        ("Cloud", ["cloud architect", "cloud engineer", "aws", "azure", "gcp", "cloud"]),
        ("SRE", ["sre", "site reliability", "observability", "prometheus", "grafana"]),
        ("Cybersecurity", ["cybersecurity", "ethical hacking", "penetration testing", "vapt", "appsec", "soc"]),
        ("Data Engineering", ["data engineering", "spark", "hadoop", "etl", "pipeline"]),
        ("Data Science", ["data science", "machine learning", "ml ", "statistics"]),
        ("Data Analytics", ["data analytics", "analytics", "excel analytics"]),
        ("Business Intelligence", ["power bi", "tableau", "looker", "business intelligence", "bi "]),
        ("Gen AI", ["gen ai", "generative ai", "llm", "prompt", "rag"]),
        ("Agentic AI", ["agentic", "agents", "autonomous agent"]),
        ("MLOps", ["mlops", "model deployment", "model monitoring"]),
        ("LLMOps", ["llmops"]),
        ("AIOps", ["aiops"]),
        ("Blockchain", ["blockchain", "solidity", "web3", "ethereum", "smart contract"]),
        ("Database", ["sql", "mongodb", "postgres", "mysql", "database", "oracle database"]),
        ("QA and Testing", ["testing", "qa", "selenium", "cypress", "playwright"]),
        ("Automation Testing", ["automation testing", "test automation"]),
        ("Programming Languages", ["python", "java", "javascript", "typescript", "go", "rust", "c++", "swift", "kotlin", "dart", "scala", "php", "ruby"]),
        ("Mobile Development", ["android", "ios", "flutter", "react native", "mobile"]),
        ("Game Development", ["unity", "unreal", "game development"]),
        ("AR and VR", ["ar ", "vr ", "augmented reality", "virtual reality"]),
        ("IoT", ["iot", "internet of things"]),
        ("Embedded Systems", ["embedded", "firmware", "rtos"]),
        ("Robotics", ["robotics", "ros"]),
        ("Quantum Computing", ["quantum"]),
        ("ERP Software", ["sap", "oracle erp", "erp", "fico", "abap", "hana", "fiori"]),
        ("CRM Software", ["salesforce", "crm", "hubspot", "zoho"]),
        ("ServiceNow", ["servicenow"]),
        ("Enterprise Software", ["workday", "microsoft dynamics", "enterprise software"]),
    ]

    for mapped_domain, keywords in keyword_map:
        if any(keyword in text for keyword in keywords):
            return mapped_domain

    non_software_terms = [
        "language", "ielts", "arabic", "hindi", "tamil", "soft skills", "leadership",
        "finance", "accounting", "tax", "gst", "healthcare", "nursing", "manufacturing",
        "autocad", "solidworks", "graphic design", "video editing", "six sigma", "pmp",
    ]
    if raw_domain.lower() == NON_SOFTWARE_DOMAIN.lower() or any(term in text for term in non_software_terms):
        return NON_SOFTWARE_DOMAIN

    return "Software Development"


def is_software_domain(domain: Any) -> bool:
    text = _as_string(domain).lower()
    if not text or text == NON_SOFTWARE_DOMAIN.lower() or text in NON_SOFTWARE_DOMAINS:
        return False
    return any(item.lower() == text for item in SOFTWARE_TECH_DOMAINS)


def is_software_category(category: Any, domain: Any = "") -> bool:
    category_text = _as_string(category).lower()
    domain_text = _as_string(domain).lower()
    if not category_text:
        return False
    if domain_text == NON_SOFTWARE_DOMAIN.lower() or domain_text in NON_SOFTWARE_DOMAINS:
        return False
    if is_software_domain(domain):
        return True
    return not any(term in category_text for term in NON_SOFTWARE_CATEGORY_TERMS)


def _normalise_categorisation(data: Dict[str, Any]) -> Dict[str, Any]:
    primary = _as_string(data.get("primary_category")) or _as_string(data.get("category")) or "General Training"
    domain = _normalise_software_domain(primary, data.get("domain"))
    confidence = data.get("confidence", 0.0)
    try:
        confidence = max(0.0, min(float(confidence), 1.0))
    except (TypeError, ValueError):
        confidence = 0.0

    raw_skill_map = data.get("skill_level_map") if isinstance(data.get("skill_level_map"), dict) else {}
    skill_level_map = {
        _as_string(skill): _normalise_skill_level(level)
        for skill, level in raw_skill_map.items()
        if _as_string(skill)
    }

    return {
        "primary_category": primary,
        "secondary_categories": [
            item for item in _as_list(data.get("secondary_categories"), limit=3)
            if item.lower() != primary.lower()
        ][:3],
        "domain": domain,
        "specialisation_tags": _as_list(data.get("specialisation_tags"), limit=5),
        "industry_focus": _as_list(data.get("industry_focus"), limit=8),
        "skill_level_map": skill_level_map,
        "language_of_delivery": _as_list(data.get("language_of_delivery"), limit=8),
        "confidence": confidence,
        "needs_review": bool(data.get("needs_review")) or confidence < 0.7 or domain == NON_SOFTWARE_DOMAIN,
        "reasoning": _as_string(data.get("reasoning"))[:500],
        "categorisation_model": CATEGORISATION_MODEL,
        "categorised_at": utc_now(),
    }


def category_update_fields(category_data: Dict[str, Any]) -> Dict[str, Any]:
    primary = category_data.get("primary_category", "General Training")
    tags = _as_list(category_data.get("specialisation_tags"), limit=5)
    update_fields = {
        **category_data,
        # Compatibility fields used by existing pages and matching code.
        "technology_category": primary,
        "category": primary,
        "specialty_tags": tags,
        "updated_at": utc_now(),
    }
    return update_fields


async def categorise_trainer(trainer: Dict[str, Any]) -> Dict[str, Any]:
    client = _anthropic_client()
    message = await client.messages.create(
        model=CATEGORISATION_MODEL,
        max_tokens=1800,
        temperature=0,
        messages=[{"role": "user", "content": _categorisation_prompt(trainer)}],
    )
    raw = "".join(
        block.text for block in message.content
        if getattr(block, "type", "") == "text"
    )
    return _normalise_categorisation(_extract_json_object(raw))


async def bulk_categorise_all(db) -> Dict[str, int]:
    processed = succeeded = failed = 0
    pending_query = {
        "$and": [
            {"$or": [
                {"primary_category": {"$exists": False}},
                {"primary_category": None},
                {"primary_category": ""},
            ]},
            {"categorisation_failed_at": {"$exists": False}},
        ]
    }

    while True:
        batch = await db["trainers"].find(pending_query).limit(10).to_list(10)
        if not batch:
            break

        for trainer in batch:
            processed += 1
            try:
                category_data = await categorise_trainer(trainer)
                await db["trainers"].update_one(
                    {"_id": trainer["_id"]},
                    {
                        "$set": category_update_fields(category_data),
                        "$unset": {"categorisation_error": "", "categorisation_failed_at": ""},
                    },
                )
                succeeded += 1
            except Exception as exc:
                failed += 1
                await db["trainers"].update_one(
                    {"_id": trainer["_id"]},
                    {"$set": {
                        "categorisation_error": str(exc),
                        "categorisation_failed_at": utc_now(),
                    }},
                )

            await asyncio.sleep(0)

    return {"processed": processed, "succeeded": succeeded, "failed": failed}


async def get_all_categories(db) -> List[str]:
    trainers = await db["trainers"].find(
        {"primary_category": {"$nin": [None, ""]}},
        {"_id": 0, "primary_category": 1, "domain": 1},
    ).to_list(10000)
    categories = {
        str(trainer.get("primary_category", "")).strip()
        for trainer in trainers
        if is_software_category(trainer.get("primary_category"), trainer.get("domain"))
    }
    return sorted({category for category in categories if category}, key=lambda item: item.lower())
