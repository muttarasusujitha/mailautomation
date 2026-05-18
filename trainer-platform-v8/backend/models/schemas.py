from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

class TrainerStatus(str, Enum):
    NEW = "new"
    CONTACTED = "contacted"
    INTERESTED = "interested"
    DECLINED = "declined"
    CONFIRMED = "confirmed"
    PENDING_REVIEW = "pending_review"

class EmailStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    REPLIED = "replied"

class ResumeProcessingStatus(str, Enum):
    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    REVIEW_PENDING = "review_pending"
    COMPLETED = "completed"
    FAILED = "failed"

class Trainer(BaseModel):
    trainer_id: str
    name: str
    technologies: str = ""
    skills: List[str] = []
    experience_years: float = 0
    experience_raw: str = ""
    certifications: List[str] = []
    phone: str = ""
    email: str = ""
    location: str = ""
    linkedin: str = ""
    resume: str = ""
    source_sheet: str = ""
    primary_category: str = ""
    technology_category: str = "Multi-Skillset"
    secondary_categories: List[str] = []
    domain: str = ""
    category: str = "Multi-Skillset"
    summary: str = ""
    past_clients: List[str] = []
    training_count: Optional[int] = None
    day_rate: Optional[float] = None
    hourly_rate: Optional[float] = None
    specialisation_tags: List[str] = []
    specialty_tags: List[str] = []
    industry_focus: List[str] = []
    skill_level_map: Dict[str, str] = {}
    language_of_delivery: List[str] = []
    confidence_score: float = 0
    confidence: float = 0
    needs_review: bool = False
    reasoning: str = ""
    status: TrainerStatus = TrainerStatus.NEW
    match_score: Optional[float] = None
    rank: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class RequirementCreate(BaseModel):
    technology_needed: str
    min_experience_years: int = 2
    required_skills: List[str] = []
    preferred_skills: List[str] = []
    required_certifications: List[str] = []
    preferred_location: str = ""
    must_have_linkedin: bool = False
    must_have_resume: bool = False
    top_n: int = 5
    job_title: str = ""
    job_description: str = ""
    send_emails: bool = False

class Requirement(RequirementCreate):
    requirement_id: str
    status: str = "active"
    total_matched: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ShortlistedTrainer(BaseModel):
    trainer_id: str
    name: str
    email: str
    phone: str
    technologies: str
    experience_raw: str
    match_score: float
    rank: int
    score_breakdown: Dict[str, Any] = {}
    linkedin: str = ""
    resume: str = ""
    location: str = ""
    source_sheet: str = ""
    primary_category: str = ""
    technology_category: str = "Multi-Skillset"
    secondary_categories: List[str] = []
    domain: str = ""
    specialisation_tags: List[str] = []
    specialty_tags: List[str] = []
    industry_focus: List[str] = []
    skill_level_map: Dict[str, str] = {}
    language_of_delivery: List[str] = []
    summary: str = ""
    status: TrainerStatus = TrainerStatus.NEW

class Shortlist(BaseModel):
    shortlist_id: str
    requirement_id: str
    technology_needed: str
    top_trainers: List[ShortlistedTrainer]
    total_matched: int
    created_at: datetime = Field(default_factory=datetime.utcnow)

class EmailLog(BaseModel):
    email_id: str
    trainer_id: str
    trainer_name: str
    requirement_id: str
    to_email: str
    subject: str
    body: str
    status: EmailStatus = EmailStatus.PENDING
    sent_at: Optional[datetime] = None
    reply_received: bool = False
    reply_text: str = ""
    reply_sentiment: str = ""
    retry_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)

class DashboardStats(BaseModel):
    total_trainers: int = 0
    total_requirements: int = 0
    total_emails_sent: int = 0
    total_replies: int = 0
    interested_count: int = 0
    declined_count: int = 0
    pending_review: int = 0
    reply_rate: float = 0.0
    interest_rate: float = 0.0


# ─── Resume Upload Schemas ───────────────────────────────────────────────────

class ResumeUpload(BaseModel):
    upload_id: str
    trainer_id: str
    filename: str
    file_size: int  # in bytes
    upload_source: str  # "direct" or "gmail"
    processing_status: ResumeProcessingStatus = ResumeProcessingStatus.UPLOADED
    extracted_text: str = ""
    extracted_data: Dict[str, Any] = {}
    extraction_error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    processed_at: Optional[datetime] = None


class ResumeExtractionResponse(BaseModel):
    upload_id: str
    trainer_id: str
    status: ResumeProcessingStatus
    filename: str
    extracted_data: Dict[str, Any]
    extraction_error: Optional[str] = None
    created_at: datetime
    processed_at: Optional[datetime] = None
