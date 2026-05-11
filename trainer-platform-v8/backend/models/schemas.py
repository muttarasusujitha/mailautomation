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

class Trainer(BaseModel):
    trainer_id: str
    name: str
    technologies: str = ""
    skills: List[str] = []
    experience_years: float = 0
    experience_raw: str = ""
    certifications: str = ""
    phone: str = ""
    email: str = ""
    location: str = ""
    linkedin: str = ""
    resume: str = ""
    source_sheet: str = ""
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
