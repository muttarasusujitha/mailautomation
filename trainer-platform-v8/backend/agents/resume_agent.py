import io
import json
import os
import re
import uuid
import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

import fitz
from docx import Document
from config import get_settings

try:
    import google.generativeai as genai
except ImportError:
    genai = None


TECHNOLOGY_CATEGORIES = [
    "DevOps",
    "Data Engineering",
    "Agentic AI",
    "Gen AI",
    "Full Stack",
    "MLOps",
    "LLMOps",
    "AIOps",
    "SRE",
    "Cloud",
    "Cybersecurity",
    "Multi-Skillset",
]

DEFAULT_GEMINI_MODEL = "gemini-1.5-flash"
GEMINI_FALLBACK_MODELS = [
    "gemini-flash-latest",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
]

RESUME_JSON_FIELDS = {
    "name": "",
    "email": "",
    "phone": "",
    "location": "",
    "experience_years": 0,
    "role_designation": "",
    "linkedin": "",
    "education": "",
    "skills": [],
    "certifications": [],
    "past_clients": [],
    "training_count": None,
    "day_rate": None,
    "hourly_rate": None,
    "technology_category": "Multi-Skillset",
    "secondary_categories": [],
    "summary": "",
}

COMMON_SKILLS = [
    "Python",
    "Java",
    "JavaScript",
    "TypeScript",
    "React",
    "Angular",
    "Node.js",
    "Django",
    "Flask",
    "FastAPI",
    "Spring Boot",
    "AWS",
    "Azure",
    "GCP",
    "Docker",
    "Kubernetes",
    "Terraform",
    "Jenkins",
    "GitLab",
    "GitHub Actions",
    "DevOps",
    "MLOps",
    "Machine Learning",
    "Deep Learning",
    "Generative AI",
    "LangChain",
    "LLM",
    "OpenAI",
    "Data Engineering",
    "Spark",
    "Databricks",
    "Kafka",
    "Airflow",
    "SQL",
    "MongoDB",
    "PostgreSQL",
    "Cybersecurity",
    "SRE",
]


class ResumeProcessingError(Exception):
    pass


def _gemini_api_key() -> str:
    settings = get_settings()
    return (os.getenv("GEMINI_API_KEY", "") or getattr(settings, "gemini_api_key", "")).strip()


def _gemini_model_names() -> List[str]:
    settings = get_settings()
    configured = (
        os.getenv("GEMINI_MODEL", "")
        or getattr(settings, "gemini_model", "")
        or DEFAULT_GEMINI_MODEL
    ).strip()

    names: List[str] = []
    for name in [configured, DEFAULT_GEMINI_MODEL, *GEMINI_FALLBACK_MODELS]:
        if name and name not in names:
            names.append(name)
    return names


def _gemini_model(model_name: str, max_output_tokens: int = 1600):
    if genai is None:
        raise ResumeProcessingError(
            "google-generativeai is not installed. Run: pip install google-generativeai"
        )

    api_key = _gemini_api_key()
    if not api_key:
        raise ResumeProcessingError("GEMINI_API_KEY is not set in backend .env")

    genai.configure(api_key=api_key)
    return genai.GenerativeModel(
        model_name=model_name,
        generation_config={
            "temperature": 0,
            "max_output_tokens": max_output_tokens,
            "response_mime_type": "application/json",
        },
    )


def _json_prompt(resume_text: str, strict: bool = False) -> str:
    strict_prefix = (
        "Your previous response was invalid. Return ONLY one JSON object. "
        "No markdown backticks, no comments, no explanation, no leading or trailing text.\n\n"
        if strict
        else "Return ONLY valid JSON with no extra text no markdown backticks no explanation.\n\n"
    )
    return f"""{strict_prefix}You are a resume parser. Extract information ONLY from the actual resume text provided.

STRICT RULES:
- Do NOT guess or assume any field.
- Do NOT infer skills from job title, projects, tools, or domain.
- If a field is not explicitly found in the resume text, return an empty string for scalar fields, [] for list fields, and null for numeric fields.
- Extract skills ONLY from a section explicitly titled Skills, Technical Skills, Core Skills, Key Skills, Technical Proficiencies, Tools & Technologies, or Technologies.
- Extract domain/specialization ONLY from job title, headline, profile summary, or professional summary.
- Extract experience ONLY from explicitly mentioned years.
- Extract certifications ONLY if clearly listed in a Certifications section.
- Extract location, email, phone, LinkedIn, day_rate, and hourly_rate ONLY if explicitly present.
- Do not assign a domain based on keywords found only in projects or tools sections.

Return this JSON shape exactly:
{{
  "name": "",
  "domain": "",
  "experience_years": null,
  "skills": [],
  "certifications": [],
  "email": "",
  "phone": "",
  "location": "",
  "linkedin": "",
  "day_rate": null,
  "hourly_rate": null,
  "role_designation": "",
  "technology_category": "",
  "secondary_categories": [],
  "summary": ""
}}

Resume text:
---
{resume_text[:60000]}
---"""


def _specialty_prompt(profile: Dict[str, Any]) -> str:
    profile_json = json.dumps(
        {
        "name": profile.get("name"),
        "skills": profile.get("skills", []),
        "experience_years": profile.get("experience_years"),
        "role_designation": profile.get("role_designation", ""),
        "education": profile.get("education", ""),
        "technology_category": profile.get("technology_category"),
        "secondary_categories": profile.get("secondary_categories", []),
        "certifications": profile.get("certifications", []),
            "summary": profile.get("summary", ""),
        },
        ensure_ascii=False,
    )
    return f"""Generate exactly 3 concise trainer specialty keyword tags based on this trainer profile.
Examples: Kubernetes Expert, LangChain Specialist, Production MLOps.
Return ONLY a valid JSON array of 3 strings. No markdown. No explanation.

Profile:
{profile_json}"""


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


def _extract_json_array(text: str) -> List[str]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", cleaned, flags=re.DOTALL)
        if not match:
            raise
        data = json.loads(match.group(0))
    return [str(item).strip() for item in data if str(item).strip()][:3]


SECTION_ALIASES = {
    "skills": [
        "skills",
        "technical skills",
        "core skills",
        "key skills",
        "technical proficiencies",
        "tools & technologies",
        "tools and technologies",
        "technologies",
    ],
    "certifications": ["certifications", "certification", "certificates", "licenses"],
    "summary": ["summary", "profile", "profile summary", "professional summary", "career summary", "objective"],
}

SECTION_BOUNDARIES = {
    "experience", "professional experience", "work experience", "employment history",
    "projects", "project experience", "education", "academic", "certifications",
    "certification", "skills", "technical skills", "core skills", "key skills",
    "tools & technologies", "tools and technologies", "technologies", "summary",
    "profile", "professional summary", "career summary", "objective", "achievements",
    "awards", "publications", "personal details", "contact", "languages",
}


def _clean_section_heading(line: str) -> str:
    cleaned = re.sub(r"^[\s#>*\-•]+|[:\s#>*\-•]+$", "", line or "").strip().lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _is_section_heading(line: str) -> bool:
    cleaned = _clean_section_heading(line)
    if not cleaned or len(cleaned) > 48:
        return False
    first_part = cleaned.split(":", 1)[0].strip()
    return (
        cleaned in SECTION_BOUNDARIES
        or first_part in SECTION_BOUNDARIES
        or bool(re.fullmatch(r"[A-Z][A-Z /&+-]{2,}:?", line.strip()))
    )


def _section_text(resume_text: str, aliases: List[str], max_lines: int = 30) -> str:
    lines = resume_text.splitlines()
    alias_set = {alias.lower() for alias in aliases}
    chunks: List[str] = []
    for index, line in enumerate(lines):
        heading = _clean_section_heading(line)
        if heading not in alias_set:
            continue
        section_lines: List[str] = []
        for next_line in lines[index + 1:index + 1 + max_lines]:
            if _is_section_heading(next_line):
                break
            if next_line.strip():
                section_lines.append(next_line.strip())
        chunks.append("\n".join(section_lines))
    return "\n".join(chunk for chunk in chunks if chunk).strip()


def _split_section_items(section: str) -> List[str]:
    raw_items = re.split(r"[,;|•\n]+", section or "")
    cleaned: List[str] = []
    seen = set()
    for item in raw_items:
        text = re.sub(r"^[\-\u2022*]+\s*", "", item).strip()
        text = re.sub(r"\s+", " ", text)
        if not text or len(text) > 80:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        cleaned.append(text)
    return cleaned


def _explicit_skills(resume_text: str) -> List[str]:
    section = _section_text(resume_text, SECTION_ALIASES["skills"], max_lines=35)
    if not section:
        return []
    items = _split_section_items(section)
    if items:
        return items[:40]
    lower_section = section.lower()
    return [skill for skill in COMMON_SKILLS if skill.lower() in lower_section]


def _explicit_certifications(resume_text: str) -> List[str]:
    section = _section_text(resume_text, SECTION_ALIASES["certifications"], max_lines=25)
    return _split_section_items(section)[:12] if section else []


def _summary_or_headline_text(resume_text: str) -> str:
    summary = _section_text(resume_text, SECTION_ALIASES["summary"], max_lines=12)
    header = "\n".join(line.strip() for line in resume_text.splitlines()[:14] if line.strip())
    return "\n".join([summary, header]).strip()


def _pdf_bytes_for_open(file_bytes: bytes) -> bytes:
    header_at = file_bytes[:2048].find(b"%PDF")
    if header_at > 0:
        return file_bytes[header_at:]
    return file_bytes


def _pdf_open_error_message(exc: Exception, file_bytes: bytes) -> str:
    if b"%PDF" not in file_bytes[:2048]:
        return (
            "This file has a .pdf extension, but it is not a valid PDF file. "
            "Open it once on your computer and export/download it again as PDF, or upload a DOCX resume."
        )
    return (
        "This PDF appears to be damaged or incomplete, so it cannot be opened for text extraction. "
        "Please open the resume and save/export it again as a new PDF, or upload the DOCX version."
    )


def _extract_pdf_text(file_bytes: bytes) -> str:
    text_parts: List[str] = []
    try:
        with fitz.open(stream=_pdf_bytes_for_open(file_bytes), filetype="pdf") as doc:
            if doc.needs_pass:
                raise ResumeProcessingError(
                    "This PDF is password-protected. Please remove the password and upload it again."
                )
            for page in doc:
                text_parts.append(page.get_text("text"))
    except ResumeProcessingError:
        raise
    except Exception as exc:
        raise ResumeProcessingError(_pdf_open_error_message(exc, file_bytes)) from exc
    return "\n".join(text_parts).strip()


def _extract_docx_text(file_bytes: bytes) -> str:
    doc = Document(io.BytesIO(file_bytes))
    parts = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells if cell.text and cell.text.strip())
    return "\n".join(parts).strip()


def extract_text(file_bytes: bytes, filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        text = _extract_pdf_text(file_bytes)
        if len(text.strip()) < 50:
            raise ResumeProcessingError(
                "This PDF opens, but it does not contain enough selectable text. It is likely scanned/image-only. "
                "Upload a digital/text PDF or DOCX version of the resume."
            )
        return text
    if lower.endswith(".docx"):
        text = _extract_docx_text(file_bytes)
        if len(text.strip()) < 50:
            raise ResumeProcessingError("Could not extract enough text from this DOCX resume.")
        return text
    raise ResumeProcessingError("Only PDF and DOCX resume files are accepted.")


def _as_string(value: Any) -> str:
    return str(value or "").strip()


def _name_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _as_string(value).lower())


def _is_same_person(existing: Dict[str, Any], profile: Dict[str, Any]) -> bool:
    existing_name = _name_key(existing.get("name"))
    profile_name = _name_key(profile.get("name"))
    if existing_name and profile_name:
        return existing_name == profile_name
    return True


def _as_number(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value in (None, ""):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group(0)) if match else default


def _as_int_or_none(value: Any) -> Optional[int]:
    num = _as_number(value)
    return int(num) if num is not None else None


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


def _normalize_category(value: Any) -> str:
    raw = _as_string(value).lower()
    for category in TECHNOLOGY_CATEGORIES:
        if category.lower() == raw:
            return category
    aliases = {
        "generative ai": "Gen AI",
        "genai": "Gen AI",
        "agent ai": "Agentic AI",
        "agentic": "Agentic AI",
        "data engineer": "Data Engineering",
        "fullstack": "Full Stack",
        "full-stack": "Full Stack",
        "llm ops": "LLMOps",
        "ml ops": "MLOps",
        "site reliability": "SRE",
        "security": "Cybersecurity",
    }
    return aliases.get(raw, "Multi-Skillset")


def _normalize_profile(data: Dict[str, Any]) -> Dict[str, Any]:
    profile = {**RESUME_JSON_FIELDS, **(data or {})}
    primary = _normalize_category(profile.get("technology_category") or profile.get("domain"))
    secondary = [
        _normalize_category(item)
        for item in _as_list(profile.get("secondary_categories"), limit=2)
    ]
    secondary = [item for item in secondary if item != primary][:2]

    normalized = {
        "name": _as_string(profile.get("name")),
        "email": _as_string(profile.get("email")).lower(),
        "phone": _as_string(profile.get("phone")),
        "location": _as_string(profile.get("location")),
        "experience_years": _as_number(profile.get("experience_years"), 0) or 0,
        "role_designation": _as_string(
            profile.get("role_designation")
            or profile.get("designation")
            or profile.get("role")
            or profile.get("job_title")
            or profile.get("domain")
        ),
        "linkedin": _as_string(profile.get("linkedin") or profile.get("linkedin_url")),
        "education": _as_string(profile.get("education")),
        "skills": _as_list(profile.get("skills")),
        "certifications": _as_list(profile.get("certifications")),
        "past_clients": _as_list(profile.get("past_clients")),
        "training_count": _as_int_or_none(profile.get("training_count")),
        "day_rate": _as_number(profile.get("day_rate")),
        "hourly_rate": _as_number(profile.get("hourly_rate")),
        "technology_category": primary,
        "secondary_categories": secondary,
        "summary": _as_string(profile.get("summary")),
    }
    normalized["category"] = normalized["technology_category"]
    normalized["technologies"] = ", ".join(normalized["skills"][:12])
    normalized["experience_raw"] = (
        f"{normalized['experience_years']:g} years"
        if normalized["experience_years"]
        else ""
    )
    return normalized


def _name_from_filename(filename: str) -> str:
    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    stem = re.sub(r"[_\-]+", " ", stem)
    stem = re.sub(r"\b(resume|cv|profile|trainer)\b", "", stem, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", stem).strip().title()


def _first_plausible_name(resume_text: str, filename: str) -> str:
    for line in resume_text.splitlines()[:12]:
        clean = re.sub(r"[^A-Za-z .'-]", " ", line).strip()
        clean = re.sub(r"\s+", " ", clean)
        words = clean.split()
        if 2 <= len(words) <= 5 and not any(word.lower() in {"resume", "curriculum", "vitae", "email", "phone"} for word in words):
            return clean.title()
    return _name_from_filename(filename)


def _fallback_category(skills: List[str], resume_text: str) -> str:
    text = f"{resume_text} {' '.join(skills)}".lower()
    skill_text = " ".join(skills).lower()
    role_text = " ".join(resume_text.splitlines()[:30]).lower()
    scores = {category: 0 for category in TECHNOLOGY_CATEGORIES}

    def add(category: str, amount: int, keywords: List[str], source: str = text):
        scores[category] += amount * sum(1 for keyword in keywords if keyword in source)

    add("Agentic AI", 5, ["agentic", "multi agent", "autogen", "crewai"], text)
    add("Gen AI", 4, ["generative ai", "genai", "llm", "langchain", "openai", "rag", "prompt engineering"], text)
    add("MLOps", 4, ["mlops", "model deployment", "model monitoring"], text)
    add("Data Engineering", 4, ["data engineering", "spark", "databricks", "airflow", "kafka", "etl", "hadoop"], text)
    add("SRE", 4, ["sre", "site reliability", "observability", "prometheus", "grafana"], text)

    add("Full Stack", 3, ["react", "angular", "vue", "node.js", "node ", "typescript", "javascript", "frontend", "backend", "full stack"], skill_text)
    add("Full Stack", 2, ["django", "flask", "fastapi", "spring boot", "html", "css"], skill_text)
    add("Full Stack", 1, ["sql", "postgresql", "mongodb", "mysql"], skill_text)
    if re.search(r"\b(frontend|backend|full\s*stack)\s+(engineer|developer|architect|trainer)\b", role_text):
        scores["Full Stack"] += 6

    add("DevOps", 4, ["devops", "kubernetes", "terraform", "jenkins", "ci/cd", "cicd", "gitlab", "github actions", "ansible", "helm"], skill_text)
    add("DevOps", 1, ["docker"], skill_text)
    if re.search(r"\bdevops\b", role_text):
        scores["DevOps"] += 6

    add("Cloud", 3, ["aws", "azure", "gcp"], skill_text)
    add("Cloud", 4, ["cloud"], role_text)
    cloud_provider_count = sum(1 for keyword in ["aws", "azure", "gcp"] if keyword in skill_text)
    if cloud_provider_count >= 2:
        scores["Cloud"] += 4

    add("Cybersecurity", 5, ["cybersecurity", "ethical hacking", "appsec", "soc", "iam", "vapt", "penetration testing"], text)
    if re.search(r"\b(cyber|security|soc|appsec)\s+(engineer|analyst|consultant|trainer)\b", role_text):
        scores["Cybersecurity"] += 6

    if "machine learning" in text or "deep learning" in text:
        scores["MLOps"] += 1 if scores["MLOps"] else 0

    # Generic support tools should not overpower the actual development domain.
    if scores["Full Stack"] >= 6:
        scores["Cloud"] = max(0, scores["Cloud"] - 3)
        scores["DevOps"] = max(0, scores["DevOps"] - 2)
    if scores["Data Engineering"] >= 6:
        scores["DevOps"] = max(0, scores["DevOps"] - 2)

    best_category, best_score = max(scores.items(), key=lambda item: item[1])
    if best_score >= 4:
        return best_category
    return "Multi-Skillset"


def _fallback_role_designation(resume_text: str) -> str:
    resume_text = _summary_or_headline_text(resume_text)
    role_patterns = [
        r"\b(senior\s+)?(software|data|devops|cloud|ml|ai|full\s*stack|backend|frontend)\s+(engineer|developer|architect|consultant|trainer)\b",
        r"\b(corporate|technical|freelance)\s+trainer\b",
        r"\b(project|program|delivery|training)\s+manager\b",
    ]
    for pattern in role_patterns:
        match = re.search(pattern, resume_text, flags=re.IGNORECASE)
        if match:
            return re.sub(r"\s+", " ", match.group(0)).strip().title()
    return ""


def _fallback_education(resume_text: str) -> str:
    education_lines = []
    for line in resume_text.splitlines():
        clean = re.sub(r"\s+", " ", line).strip()
        if re.search(
            r"\b(b\.?tech|bachelor|master|m\.?tech|mba|bca|mca|ph\.?d|degree|university|college)\b",
            clean,
            flags=re.IGNORECASE,
        ):
            education_lines.append(clean)
        if len(education_lines) >= 3:
            break
    return "; ".join(education_lines)


def _fallback_extract_profile(resume_text: str, filename: str, ai_error: Exception) -> Dict[str, Any]:
    email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", resume_text)
    phone_match = re.search(r"(?:\+?\d[\d ().-]{8,}\d)", resume_text)
    linkedin_match = re.search(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[^\s,;)>]+", resume_text, flags=re.IGNORECASE)
    rate_match = re.search(r"(?:day\s*rate|daily\s*rate|per\s*day)[:\s-]*(?:inr|rs\.?|₹)?\s*([0-9][0-9,]*(?:\.\d+)?)", resume_text, flags=re.IGNORECASE)
    exp_matches = [
        float(match.group(1))
        for match in re.finditer(r"(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)", resume_text, flags=re.IGNORECASE)
    ]
    skills = _explicit_skills(resume_text)
    cert_lines = _explicit_certifications(resume_text)
    domain_text = _summary_or_headline_text(resume_text)

    category = _fallback_category(skills, domain_text)
    profile = _normalize_profile({
        "name": _first_plausible_name(resume_text, filename),
        "email": email_match.group(0) if email_match else "",
        "phone": phone_match.group(0).strip() if phone_match else "",
        "experience_years": max(exp_matches) if exp_matches else 0,
        "role_designation": _fallback_role_designation(domain_text),
        "education": _fallback_education(resume_text),
        "linkedin": linkedin_match.group(0) if linkedin_match else "",
        "day_rate": _as_number(rate_match.group(1)) if rate_match else None,
        "skills": skills,
        "certifications": cert_lines,
        "technology_category": category,
        "summary": (
            domain_text[:300] if domain_text else ""
        ),
    })
    profile["extraction_source"] = "local_fallback"
    profile["needs_review"] = True
    profile["warning"] = f"AI extraction failed, so a local fallback was used: {ai_error}"
    return profile


def calculate_confidence(profile: Dict[str, Any]) -> float:
    checks = [
        bool(profile.get("name")),
        bool(profile.get("email")),
        bool(profile.get("phone")),
        bool(profile.get("location")),
        bool(profile.get("experience_years")),
        bool(profile.get("skills")),
        bool(profile.get("certifications")),
        bool(profile.get("past_clients")),
        profile.get("technology_category") in TECHNOLOGY_CATEGORIES,
        bool(profile.get("summary")),
    ]
    return round(sum(checks) / len(checks), 2)


def _gemini_response_text(response: Any) -> str:
    try:
        text = getattr(response, "text", "")
        if text:
            return text
    except Exception:
        pass

    parts: List[str] = []
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            text = getattr(part, "text", "")
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


async def _call_gemini_text(prompt: str, max_output_tokens: int = 1600) -> str:
    last_error: Optional[Exception] = None
    for model_name in _gemini_model_names():
        try:
            model = _gemini_model(model_name, max_output_tokens=max_output_tokens)
            response = await asyncio.to_thread(model.generate_content, prompt)
            raw = _gemini_response_text(response)
            if not raw:
                raise ResumeProcessingError(f"Gemini model {model_name} returned an empty response")
            return raw
        except Exception as exc:
            last_error = exc
    raise ResumeProcessingError(f"Gemini request failed: {last_error}")


async def _call_gemini_json(resume_text: str) -> Dict[str, Any]:
    last_error: Optional[Exception] = None
    for strict in (False, True):
        try:
            raw = await _call_gemini_text(_json_prompt(resume_text, strict=strict), max_output_tokens=1600)
            return _extract_json_object(raw)
        except Exception as exc:
            last_error = exc
    raise ResumeProcessingError(f"Gemini returned invalid JSON: {last_error}")


async def generate_specialty_tags(profile: Dict[str, Any]) -> List[str]:
    try:
        raw = await _call_gemini_text(_specialty_prompt(profile), max_output_tokens=120)
        tags = _extract_json_array(raw)
        if len(tags) == 3:
            return tags
    except Exception:
        pass

    skills = profile.get("skills", [])[:3] or [profile.get("technology_category", "Training")]
    fallback = [f"{skill} Specialist" for skill in skills]
    return (fallback + ["Corporate Trainer", "Technical Mentor", "Workshop Expert"])[:3]


async def process_resume(file_bytes: bytes, filename: str, db) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "filename": filename,
        "success": False,
        "error": None,
        "confidence_score": 0,
    }

    try:
        raw_text = extract_text(file_bytes, filename)
        try:
            extracted = await _call_gemini_json(raw_text)
            profile = _normalize_profile(extracted)
            profile["extraction_source"] = "gemini"
        except Exception as exc:
            profile = _fallback_extract_profile(raw_text, filename, exc)
        profile["trainer_id"] = f"TR-{uuid.uuid4().hex[:8].upper()}"
        profile["confidence_score"] = calculate_confidence(profile)

        duplicate = None
        if profile.get("email"):
            duplicate = await db["trainers"].find_one(
                {"email": {"$regex": f"^{re.escape(profile['email'])}$", "$options": "i"}},
                {"_id": 0, "trainer_id": 1, "email": 1, "name": 1},
            )
            if duplicate and _is_same_person(duplicate, profile):
                profile["trainer_id"] = duplicate["trainer_id"]
            elif duplicate:
                duplicate = None

        result.update(
            {
                **profile,
                "success": True,
                "duplicate": bool(duplicate),
                "existing_trainer_id": duplicate.get("trainer_id") if duplicate else None,
                "raw_text": raw_text,
            }
        )
    except Exception as exc:
        result["error"] = str(exc)

    return result


def trainer_document_from_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    skills = _as_list(profile.get("skills"))
    certifications = _as_list(profile.get("certifications"))
    raw_text = profile.get("raw_text", "")
    combined_parts = [
        profile.get("name", ""),
        profile.get("technology_category", ""),
        " ".join(profile.get("secondary_categories", [])),
        " ".join(skills),
        " ".join(certifications),
        " ".join(profile.get("specialty_tags", [])),
        profile.get("summary", ""),
        raw_text[:50000],
    ]
    return {
        "trainer_id": profile.get("trainer_id") or f"TR-{uuid.uuid4().hex[:8].upper()}",
        "name": profile.get("name", ""),
        "email": profile.get("email", ""),
        "phone": profile.get("phone", ""),
        "location": profile.get("location", ""),
        "linkedin": profile.get("linkedin", ""),
        "experience_years": profile.get("experience_years", 0),
        "experience_raw": profile.get("experience_raw", ""),
        "role_designation": profile.get("role_designation", ""),
        "education": profile.get("education", ""),
        "skills": skills,
        "technologies": profile.get("technologies") or ", ".join(skills),
        "certifications": certifications,
        "past_clients": _as_list(profile.get("past_clients")),
        "training_count": profile.get("training_count"),
        "day_rate": profile.get("day_rate"),
        "hourly_rate": profile.get("hourly_rate"),
        "technology_category": profile.get("technology_category", "Multi-Skillset"),
        "secondary_categories": _as_list(profile.get("secondary_categories"), limit=2),
        "category": profile.get("technology_category", "Multi-Skillset"),
        "summary": profile.get("summary", ""),
        "specialty_tags": _as_list(profile.get("specialty_tags"), limit=3),
        "confidence_score": profile.get("confidence_score", 0),
        "resume": raw_text[:50000],
        "combined_text": " ".join(combined_parts).lower(),
        "source": "resume_upload",
        "source_sheet": "resume_upload",
        "status": "new",
        "updated_at": datetime.utcnow(),
    }


async def save_trainer_from_resume(profile: Dict[str, Any], db) -> Dict[str, Any]:
    if not profile.get("success"):
        return {"saved": False, "error": profile.get("error") or "Resume processing failed"}

    specialty_tags = await generate_specialty_tags(profile)
    profile = {**profile, "specialty_tags": specialty_tags}
    trainer_doc = trainer_document_from_profile(profile)

    existing = None
    if trainer_doc.get("email"):
        existing = await db["trainers"].find_one(
            {"email": {"$regex": f"^{re.escape(trainer_doc['email'])}$", "$options": "i"}},
            {"_id": 0, "trainer_id": 1, "created_at": 1, "name": 1},
        )
        if existing and not _is_same_person(existing, trainer_doc):
            existing = None

    if existing:
        trainer_doc["trainer_id"] = existing["trainer_id"]
        trainer_doc["created_at"] = existing.get("created_at")
        await db["trainers"].update_one(
            {"trainer_id": existing["trainer_id"]},
            {"$set": {k: v for k, v in trainer_doc.items() if k != "created_at"}},
        )
        action = "updated"
    else:
        trainer_doc["created_at"] = datetime.utcnow()
        await db["trainers"].insert_one(trainer_doc)
        action = "inserted"

    await db["resume_uploads"].insert_one(
        {
            "upload_id": f"RES-{uuid.uuid4().hex[:12].upper()}",
            "trainer_id": trainer_doc["trainer_id"],
            "filename": profile.get("filename"),
            "file_size": len(profile.get("raw_text", "")),
            "processing_status": "completed",
            "extracted_data": {k: v for k, v in trainer_doc.items() if k not in {"resume", "combined_text"}},
            "confidence_score": profile.get("confidence_score", 0),
            "created_at": datetime.utcnow(),
            "processed_at": datetime.utcnow(),
        }
    )

    return {
        "saved": True,
        "action": action,
        "trainer_id": trainer_doc["trainer_id"],
        "specialty_tags": specialty_tags,
    }


def public_resume_result(result: Dict[str, Any]) -> Dict[str, Any]:
    hidden = {"raw_text"}
    return {key: value for key, value in result.items() if key not in hidden}
