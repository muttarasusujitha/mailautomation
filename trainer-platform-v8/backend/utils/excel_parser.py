import pandas as pd
import re
from typing import List, Dict, Any
from io import BytesIO


def parse_experience(raw: str) -> float:
    """Extract numeric years from strings like '8+ years', '12+', '10+ yrs'"""
    if not raw:
        return 0.0
    match = re.search(r'(\d+(?:\.\d+)?)', str(raw))
    return float(match.group(1)) if match else 0.0


def clean_phone(raw: str) -> str:
    return re.sub(r'[^\d+\-\s]', '', str(raw or '')).strip()


def parse_skills(raw: str) -> List[str]:
    if not raw or str(raw).strip() in ['-', 'nan', '']:
        return []
    return [s.strip() for s in re.split(r'[,;|•\n]', str(raw)) if s.strip()]


def normalize_row(row: Dict, sheet_name: str, idx: int) -> Dict[str, Any]:
    """Normalize a single Excel row to standard trainer schema"""
    name = str(
        row.get('Trainers Name') or row.get('name') or row.get('Full Name') or ''
    ).strip()
    if not name or name.lower() in ['nan', 'trainers name']:
        return None

    technologies = str(row.get('Technologies') or row.get('technologies') or '').strip()
    skills_raw = str(row.get('Skills') or row.get('skills') or '').strip()
    experience_raw = str(row.get('Experience') or row.get('experience') or '0').strip()
    certifications = str(row.get('Certifications') or row.get('certifications') or '').strip()
    phone = clean_phone(str(row.get('Contact No') or row.get('phone') or ''))
    email = str(row.get('Email') or row.get('email') or '').strip()
    location = str(row.get('Location') or row.get('location') or '').strip()
    linkedin = str(row.get('Linkedin Profile') or row.get('LinkedIn Profile') or row.get('linkedin') or '').strip()
    resume = str(row.get('Resumes') or row.get('resume') or '').strip()

    combined_text = f"{technologies} {skills_raw} {certifications}".lower()

    return {
        "trainer_id": f"trainer_{sheet_name[:3].lower()}_{idx}_{hash(name) % 10000}",
        "name": name,
        "technologies": technologies,
        "skills": parse_skills(skills_raw),
        "combined_text": combined_text,
        "experience_years": parse_experience(experience_raw),
        "experience_raw": experience_raw,
        "certifications": certifications,
        "phone": phone,
        "email": email if '@' in email else '',
        "location": location if location.lower() != 'nan' else '',
        "linkedin": linkedin if linkedin.lower() not in ['nan', '-', ''] else '',
        "resume": resume if resume.lower() not in ['nan', '-', ''] else '',
        "source_sheet": sheet_name,
        "status": "new",
        "match_score": None,
        "rank": None,
    }


def parse_excel_file(file_bytes: bytes) -> List[Dict[str, Any]]:
    """Parse all sheets from the trainer Excel file"""
    all_trainers = []
    seen_keys = set()

    try:
        xl = pd.ExcelFile(BytesIO(file_bytes))
        sheet_names = xl.sheet_names

        for sheet in sheet_names:
            try:
                df = pd.read_excel(BytesIO(file_bytes), sheet_name=sheet, header=0)
                df = df.where(pd.notna(df), '')

                for idx, row in df.iterrows():
                    trainer = normalize_row(row.to_dict(), sheet, idx)
                    if trainer is None:
                        continue
                    # Deduplicate by name+email
                    dedup_key = f"{trainer['name'].lower()}|{trainer['email'].lower()}"
                    if dedup_key not in seen_keys:
                        seen_keys.add(dedup_key)
                        all_trainers.append(trainer)
            except Exception as e:
                print(f"⚠️ Error parsing sheet '{sheet}': {e}")
                continue

    except Exception as e:
        raise ValueError(f"Failed to parse Excel file: {e}")

    return all_trainers
