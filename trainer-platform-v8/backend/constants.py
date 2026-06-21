"""
MAINT-005: Centralised constants to replace magic strings and numbers scattered
across the codebase. Import from here instead of repeating inline literals.
"""

# ── Trainer / Requirement statuses ───────────────────────────────────────────
class TrainerStatus:
    PENDING_REVIEW = "pending_review"
    INTERESTED = "interested"
    CONTACTED = "contacted"
    CONFIRMED = "confirmed"
    DECLINED = "declined"
    COMMERCIAL_NEGOTIATION_REQUESTED = "commercial_negotiation_requested"


class RequirementStatus:
    OPEN = "open"
    SELECTED = "selected"
    TRAINER_SELECTED_AUTO_SENT = "trainer_selected_auto_sent"
    TOC_REQUESTED = "toc_requested"
    TRAINING_CONFIRMED = "training_confirmed"
    CLOSED = "closed"
    FULFILLED = "fulfilled"

    # Statuses that lock a requirement from further slot mailings
    LOCKED_STATUSES = frozenset({
        SELECTED,
        TRAINER_SELECTED_AUTO_SENT,
        TOC_REQUESTED,
        TRAINING_CONFIRMED,
        CLOSED,
        FULFILLED,
    })


# ── Email / reminder statuses ─────────────────────────────────────────────────
class EmailStatus:
    SENT = "sent"
    FAILED = "failed"
    PENDING = "pending"
    CANCELLED = "cancelled"
    SENDING = "sending"
    SKIPPED_REQUIREMENT_SELECTED = "skipped_requirement_selected"


class ReminderStatus:
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SENDING = "sending"
    MISSING = "missing"
    SKIPPED_REQUIREMENT_SELECTED = "skipped_requirement_selected"


# ── Mail types ────────────────────────────────────────────────────────────────
class MailType:
    INTERVIEW_REMINDER = "interview_reminder"
    CLIENT_SLOT_OPTIONS = "client_slot_options"
    TRAINER_COMMERCIAL_NEGOTIATION = "trainer_commercial_negotiation"
    MAIL1 = "mail1"
    MAIL2 = "mail2"
    MAIL2_FOLLOWUP = "mail2_followup"
    MAIL3 = "mail3"
    MAIL3_SLOT_FOLLOWUP = "mail3_slot_followup"
    MAIL4 = "mail4"
    MAIL5_OK = "mail5_ok"
    MAIL5_REJECT = "mail5_reject"
    TRAINER_DATES_CLARIFICATION = "trainer_dates_clarification"
    TRAINER_COMMERCIAL_NEGOTIATION_TYPE = "trainer_commercial_negotiation"
    AI_EXTRA_QUESTION_REPLY = "ai_extra_question_reply"


# ── Client inbox / request statuses ──────────────────────────────────────────
class ClientRequestStatus:
    PENDING_APPROVAL = "pending_approval"
    AUTO_SENT = "auto_sent"
    APPROVED = "approved"
    REJECTED = "rejected"
    SPAM = "spam"


# ── WhatsApp statuses ─────────────────────────────────────────────────────────
class WhatsAppStatus:
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    RECEIVED = "received"
    FAILED = "failed"
    UNDELIVERED = "undelivered"
    SKIPPED = "skipped"

    SUCCESS_STATUSES = frozenset({QUEUED, SENT, DELIVERED, READ, RECEIVED})
    FAILURE_STATUSES = frozenset({FAILED, UNDELIVERED, SKIPPED})


# ── Commercial ────────────────────────────────────────────────────────────────
CLAHAN_COMMERCIAL_MARKUP_INR = 5000  # INR markup added on top of trainer commercial

# ── Pagination defaults ───────────────────────────────────────────────────────
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

# ── DB collection names ───────────────────────────────────────────────────────
class Collection:
    TRAINERS = "trainers"
    REQUIREMENTS = "requirements"
    SHORTLISTS = "shortlists"
    EMAIL_LOGS = "email_logs"
    CONVERSATIONS = "conversations"
    CLIENT_EMAILS = "client_emails"
    CLIENT_SLOT_EMAILS = "client_slot_emails"
    INTERVIEW_REMINDERS = "interview_reminders"
    ADMIN_SETTINGS = "admin_settings"
    TRAINER_PROFILE_LEADS = "trainer_profile_leads"
    GMAIL_SYNC = "gmail_sync"
