"""Shared Pydantic v2 schemas used across all microservices.

Import pattern (from any service):
    from shared.models.schemas import CustomerCreate, Requirement, ...
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field


# ── Enumerations ──────────────────────────────────────────────────────────────

class StatusEnum(str, Enum):
    active = "active"
    inactive = "inactive"
    pending = "pending"
    completed = "completed"
    failed = "failed"


class PriorityEnum(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class EmailStatusEnum(str, Enum):
    pending = "pending"
    sent = "sent"
    failed = "failed"
    bounced = "bounced"
    opened = "opened"
    replied = "replied"


class NotificationChannelEnum(str, Enum):
    email = "email"
    whatsapp = "whatsapp"
    teams = "teams"


# ── Customer ──────────────────────────────────────────────────────────────────

class CustomerBase(BaseModel):
    name: str
    email: EmailStr
    company: Optional[str] = None
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    notes: Optional[str] = None
    tags: List[str] = []
    status: StatusEnum = StatusEnum.active
    priority: PriorityEnum = PriorityEnum.medium
    metadata: Dict[str, Any] = {}


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    status: Optional[StatusEnum] = None
    priority: Optional[PriorityEnum] = None
    metadata: Optional[Dict[str, Any]] = None


class Customer(CustomerBase):
    id: str = Field(alias="_id")
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}


# ── Requirement ───────────────────────────────────────────────────────────────

class RequirementBase(BaseModel):
    customer_id: str
    title: str
    description: Optional[str] = None
    skills: List[str] = []
    domain: Optional[str] = None
    budget: Optional[float] = None
    duration_days: Optional[int] = None
    num_participants: Optional[int] = None
    location: Optional[str] = None
    delivery_mode: Optional[str] = None
    status: StatusEnum = StatusEnum.pending
    priority: PriorityEnum = PriorityEnum.medium
    metadata: Dict[str, Any] = {}


class RequirementCreate(RequirementBase):
    pass


class RequirementUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    skills: Optional[List[str]] = None
    domain: Optional[str] = None
    budget: Optional[float] = None
    duration_days: Optional[int] = None
    num_participants: Optional[int] = None
    location: Optional[str] = None
    delivery_mode: Optional[str] = None
    status: Optional[StatusEnum] = None
    priority: Optional[PriorityEnum] = None
    metadata: Optional[Dict[str, Any]] = None


class Requirement(RequirementBase):
    id: str = Field(alias="_id")
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}


# ── Journey ───────────────────────────────────────────────────────────────────

class JourneyStep(BaseModel):
    step: str
    status: str = "pending"
    timestamp: Optional[datetime] = None
    notes: Optional[str] = None
    metadata: Dict[str, Any] = {}


class JourneyBase(BaseModel):
    customer_id: str
    requirement_id: Optional[str] = None
    current_stage: str = "initial_contact"
    steps: List[JourneyStep] = []
    status: StatusEnum = StatusEnum.active
    metadata: Dict[str, Any] = {}


class JourneyCreate(JourneyBase):
    pass


class JourneyUpdate(BaseModel):
    current_stage: Optional[str] = None
    steps: Optional[List[JourneyStep]] = None
    status: Optional[StatusEnum] = None
    metadata: Optional[Dict[str, Any]] = None


class Journey(JourneyBase):
    id: str = Field(alias="_id")
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}


# ── EmailLog ──────────────────────────────────────────────────────────────────

class EmailLogBase(BaseModel):
    customer_id: Optional[str] = None
    requirement_id: Optional[str] = None
    gmail_message_id: Optional[str] = None
    gmail_thread_id: Optional[str] = None
    subject: Optional[str] = None
    sender: Optional[str] = None
    recipient: Optional[str] = None
    body_snippet: Optional[str] = None
    direction: str = "inbound"
    status: EmailStatusEnum = EmailStatusEnum.pending
    processed: bool = False
    ai_analysis: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = {}


class EmailLogCreate(EmailLogBase):
    pass


class EmailLog(EmailLogBase):
    id: str = Field(alias="_id")
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}


# ── Automation ────────────────────────────────────────────────────────────────

class AutomationTrigger(BaseModel):
    type: str
    event: Optional[str] = None
    cron: Optional[str] = None
    conditions: Dict[str, Any] = {}


class AutomationAction(BaseModel):
    type: str
    config: Dict[str, Any] = {}


class AutomationBase(BaseModel):
    name: str
    description: Optional[str] = None
    trigger: AutomationTrigger
    actions: List[AutomationAction] = []
    is_active: bool = True
    metadata: Dict[str, Any] = {}


class AutomationCreate(AutomationBase):
    pass


class AutomationUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    trigger: Optional[AutomationTrigger] = None
    actions: Optional[List[AutomationAction]] = None
    is_active: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None


class Automation(AutomationBase):
    id: str = Field(alias="_id")
    created_at: datetime
    updated_at: datetime
    last_run: Optional[datetime] = None
    run_count: int = 0

    model_config = {"populate_by_name": True}


# ── Trainer ───────────────────────────────────────────────────────────────────

class TrainerBase(BaseModel):
    name: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    skills: List[str] = []
    domains: List[str] = []
    experience_years: Optional[int] = None
    location: Optional[str] = None
    daily_rate: Optional[float] = None
    availability: Optional[str] = None
    rating: Optional[float] = None
    bio: Optional[str] = None
    metadata: Dict[str, Any] = {}


class TrainerCreate(TrainerBase):
    pass


class TrainerUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    skills: Optional[List[str]] = None
    domains: Optional[List[str]] = None
    experience_years: Optional[int] = None
    location: Optional[str] = None
    daily_rate: Optional[float] = None
    availability: Optional[str] = None
    rating: Optional[float] = None
    bio: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class Trainer(TrainerBase):
    id: str = Field(alias="_id")
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}


# ── Slot ──────────────────────────────────────────────────────────────────────

class SlotBase(BaseModel):
    trainer_id: Optional[str] = None
    customer_id: Optional[str] = None
    requirement_id: Optional[str] = None
    slot_type: str = "trainer"          # trainer / client
    start_time: datetime
    end_time: datetime
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    meeting_link: Optional[str] = None
    status: str = "available"           # available / booked / cancelled
    metadata: Dict[str, Any] = {}


class SlotCreate(SlotBase):
    pass


class SlotUpdate(BaseModel):
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    meeting_link: Optional[str] = None
    status: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class Slot(SlotBase):
    id: str = Field(alias="_id")
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}


# ── Generic responses ─────────────────────────────────────────────────────────

class PaginatedResponse(BaseModel):
    items: List[Any]
    total: int
    page: int
    page_size: int
    pages: int


class MessageResponse(BaseModel):
    message: str
    data: Optional[Any] = None
