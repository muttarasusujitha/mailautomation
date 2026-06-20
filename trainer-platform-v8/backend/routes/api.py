from fastapi import APIRouter, UploadFile, File, HTTPException, Request, Response, BackgroundTasks
from typing import Optional, List
from datetime import datetime, timedelta, timezone
from utils.time_utils import utc_from_timestamp, utc_now
import uuid
import re as _re
import json as _json
import base64 as _base64
import io
import zipfile
import os
import logging
import html as _html
import smtplib
import asyncio
import hashlib
from urllib.parse import urljoin as _urljoin
from email.utils import parseaddr as _parseaddr
from email.header import decode_header as _decode_header, make_header as _make_header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import fitz
from docx import Document as _DocxDocument
from pymongo import ReturnDocument
from pymongo.errors import ExecutionTimeout

from database import get_db
from config import get_settings
from agents.pipeline import run_pipeline
from agents.document_agent import (
    build_purchase_order_doc,
    public_purchase_order,
    purchase_order_filename,
    purchase_order_pdf_bytes,
    render_purchase_order_html,
)
from agents.toc_domain_dataset import list_domains, get_domain
from agents.toc_generation_agent import generate_toc_from_dataset, validate_toc
from agents.resume_agent import (
    ContactVerificationTier,
    TIER_WEIGHT,
    find_matching_trainer_for_lead,
    get_contact_verification_summary,
    linkedin_lead_to_unverified_profile,
    merge_linkedin_with_resume_profile,
    process_resume,
    public_resume_result,
    save_trainer_from_resume,
    trainer_document_from_profile,
)
from agents.categorisation_agent import (
    SOFTWARE_TECH_DOMAINS,
    bulk_categorise_all,
    categorise_trainer,
    category_update_fields,
    get_all_categories,
    is_software_domain,
)
from agents.email_agent import (
    check_email_replies,
    send_email_async, compose_retry_email, compose_interview_email,
    compose_shortlist_first_email,
    get_gmail_password,
    send_gmail_oauth_message,
)
from agents.client_slot_agent import (
    CLAHAN_CLIENT_COMMERCIAL_MARKUP_INR,
    ClientSlotError,
    client_budget_for_trainer_commercial,
    extract_trainer_commercial_details,
    looks_like_trainer_slots,
    send_client_slot_options_email,
    send_client_slots_for_email_log,
    send_pending_client_slot_replies,
)
from agents.teams_agent import send_teams_stage_notification
from agents.excel_store_agent import sync_business_excel, workbook_path
from agents.teams_direct_agent import (
    exchange_microsoft_code,
    get_teams_direct_config,
    microsoft_oauth_url,
    send_trainer_teams_direct_message,
)
from agents.client_intelligence_agent import (
    check_if_duplicate,
    create_requirement_from_email,
    ensure_requirement_from_email,
    extract_client_slot_confirmation,
    fetch_gmail_email,
    generate_calhan_reply,
    generate_client_requirement_closed_reply,
    get_calendar_service,
    get_gmail_auth_status,
    get_gmail_oauth_url,
    get_gmail_service,
    get_history_message_ids,
    auto_send_pending_client_replies_smtp,
    client_reply_auto_send_eligible,
    find_existing_client_clarification_request,
    find_matching_trainer_outbound_thread,
    is_likely_training_email,
    is_client_clarification_reply,
    mark_client_requirement_closed,
    poll_imap_client_inbox,
    process_client_email,
    record_trainer_reply_from_client_inbox,
    renew_gmail_watch,
    save_gmail_oauth_token,
    sender_domain,
    send_gmail_reply,
    upload_file_to_drive,
)
from agents.scheduler import (
    get_config as get_scheduler_config,
    load_config_from_db as load_scheduler_config_from_db,
    save_config_to_db as save_scheduler_config_to_db,
)
from agents.interview_reminder_scheduler import (
    cancel_interview_reminder,
    schedule_interview_reminder,
)
from agents.whatsapp_agent import (
    get_twilio_config,
    interview_reminder_fields,
    send_interview_whatsapp,
    send_shortlist_whatsapp,
    send_vendor_reply_notification,
    send_whatsapp_message,
    update_whatsapp_status,
)
from models.schemas import RequirementCreate

router = APIRouter()
logger = logging.getLogger(__name__)
CATEGORISATION_JOBS = {}

SELECTION_LOCK_STATUSES = {
    "selected",
    "trainer_selected_auto_sent",
    "toc_requested",
    "training_confirmed",
    "closed",
    "fulfilled",
}

TRACKING_PIXEL = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
    b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01"
    b"\x00\x00\x02\x02D\x01\x00;"
)


def _id_text(value) -> str:
    return str(value or "").strip()


def _requirement_selection_lock(requirement: Optional[dict]) -> dict:
    requirement = requirement or {}
    selected_trainer_id = _id_text(requirement.get("selected_trainer_id"))
    selection_status = _id_text(requirement.get("selection_status") or requirement.get("status")).lower()
    return {
        "locked": bool(selected_trainer_id) or selection_status in SELECTION_LOCK_STATUSES,
        "selected_trainer_id": selected_trainer_id,
        "selected_trainer_name": _id_text(requirement.get("selected_trainer_name")),
        "selection_status": selection_status,
    }


async def _requirement_trainer_send_guard(db, requirement_id: str, trainer_id: str) -> tuple[bool, dict, dict]:
    if not requirement_id:
        return True, {}, {}

    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    lock = _requirement_selection_lock(requirement)
    selected_trainer_id = lock["selected_trainer_id"]
    if not lock["locked"] or (selected_trainer_id and _id_text(trainer_id) == selected_trainer_id):
        return True, {}, requirement

    selected_label = lock["selected_trainer_name"] or selected_trainer_id or "another trainer"
    return False, {
        "success": True,
        "skipped": True,
        "status": "requirement_already_selected",
        "reason": f"{selected_label} is already selected for this requirement. Further trainer mails are stopped.",
        "requirement_id": requirement_id,
        "selected_trainer_id": selected_trainer_id,
        "selected_trainer_name": lock["selected_trainer_name"],
    }, requirement


async def _mark_requirement_selected_and_stop_others(
    db,
    *,
    requirement_id: str,
    trainer_id: str,
    trainer_name: str,
    selected_at: datetime,
) -> None:
    if not requirement_id or not trainer_id:
        return

    stop_reason = f"{trainer_name or 'Selected trainer'} selected for this requirement"
    selected_fields = {
        "selected_trainer_id": trainer_id,
        "selected_trainer_name": trainer_name,
        "selection_status": "selected",
        "selected_at": selected_at,
        "remaining_trainers_stopped": True,
        "remaining_trainers_stopped_at": selected_at,
    }
    await db["requirements"].update_one(
        {"requirement_id": requirement_id},
        {"$set": selected_fields},
    )
    await db["shortlists"].update_one(
        {"requirement_id": requirement_id},
        {"$set": selected_fields},
    )

    try:
        await db["shortlists"].update_one(
            {"requirement_id": requirement_id},
            {"$set": {
                "top_trainers.$[selected].pipeline_status": "selected",
                "top_trainers.$[selected].status": "selected",
            }},
            array_filters=[{"selected.trainer_id": trainer_id}],
        )
        await db["shortlists"].update_one(
            {"requirement_id": requirement_id},
            {"$set": {
                "top_trainers.$[other].pipeline_status": "stopped_selected",
                "top_trainers.$[other].status": "stopped_selected",
                "top_trainers.$[other].stopped_reason": stop_reason,
                "top_trainers.$[other].stopped_at": selected_at,
            }},
            array_filters=[{"other.trainer_id": {"$ne": trainer_id}}],
        )
    except Exception:
        pass

def _norm_subject(value: str = "") -> str:
    try:
        value = str(_make_header(_decode_header(str(value or ""))))
    except Exception:
        value = str(value or "")
    value = value.lower()
    value = _re.sub(r"=\?[^?]+\?[bq]\?[^?]+\?=", " ", value)
    value = value.replace("re:", "").replace("fw:", "").replace("fwd:", "")
    value = value.replace("[reminder 1]", "").replace("[reminder 2]", "").replace("[reminder 3]", "")
    value = _re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def _question_without_commitment(text: str = "") -> bool:
    clean = str(text or "").lower().strip()
    if not clean:
        return False
    strong_commitment = [
        "i am available", "i'm available", "i confirm my availability",
        "i am interested", "i'm interested", "yes i am", "yes, i am",
        "happy to proceed", "ready to proceed", "please proceed",
    ]
    if any(item in clean for item in strong_commitment):
        return False
    question_markers = [
        "?", "can you", "could you", "please confirm", "kindly confirm",
        "what is", "when is", "where is", "how many", "how much",
        "duration", "timing", "schedule", "date", "mode", "client",
        "rate", "payment", "toc", "agenda", "syllabus", "interview link",
    ]
    return any(item in clean for item in question_markers)


def _reply_sentiment_and_action(body: str) -> dict:
    text = str(body or "").lower()
    negative = [
        "not interested", "not available", "not able", "unable", "cannot",
        "can't", "decline", "declining", "busy", "not convenient", "withdraw",
    ]
    positive = [
        "available", "interested", "confirm", "confirmed", "accept", "accepted",
        "happy to", "sure", "okay", " ok ", "yes", "schedule", "agree", "proceed",
    ]
    if any(item in text for item in negative):
        return {"sentiment": "negative", "action": "mark_declined"}
    if _question_without_commitment(text):
        return {"sentiment": "neutral", "action": "requires_review"}
    if any(item in text for item in positive):
        return {"sentiment": "positive", "action": "mark_interested"}
    return {"sentiment": "neutral", "action": "requires_review"}


def _email_key(value: str = "") -> str:
    _, addr = _parseaddr(str(value or ""))
    return (addr or value or "").strip().lower()


def _check_gmail_replies_fast(
    *,
    since_days: int = 14,
    max_messages: int = 50,
    from_emails: Optional[List[str]] = None,
) -> tuple[bool, List[dict], str]:
    try:
        service = get_gmail_service()
        target_emails = sorted({
            _email_key(item)
            for item in (from_emails or [])
            if _email_key(item) and "@" in _email_key(item)
        })
        queries = []
        if target_emails:
            chunk_size = 12
            for i in range(0, min(len(target_emails), 96), chunk_size):
                chunk = target_emails[i:i + chunk_size]
                from_terms = " ".join(f"from:{addr}" for addr in chunk)
                queries.append(f"in:inbox newer_than:{int(since_days)}d {{{from_terms}}} -from:me")
        else:
            queries.append(f"in:inbox newer_than:{int(since_days)}d -from:me")

        message_ids = []
        seen = set()
        per_query_limit = max(10, min(50, max_messages))
        for query in queries:
            response = service.users().messages().list(
                userId="me",
                q=query,
                maxResults=per_query_limit,
            ).execute()
            for item in response.get("messages", []) or []:
                message_id = item.get("id")
                if message_id and message_id not in seen:
                    seen.add(message_id)
                    message_ids.append(message_id)
                if len(message_ids) >= max_messages:
                    break
            if len(message_ids) >= max_messages:
                break

        replies: List[dict] = []
        target_set = set(target_emails)
        for message_id in message_ids:
            meta = fetch_gmail_email(message_id, service)
            from_email = _email_key(meta.get("from_email", ""))
            if target_set and from_email not in target_set:
                continue
            body = (meta.get("clean_body") or meta.get("raw_body") or "")[:2000]
            verdict = _reply_sentiment_and_action(body)
            headers = meta.get("headers") or {}
            received_at = meta.get("received_at") or utc_now()
            replies.append({
                "msg_id": message_id,
                "message_id_header": headers.get("message-id", "") or meta.get("message_id_header", ""),
                "in_reply_to": headers.get("in-reply-to", ""),
                "references": headers.get("references", ""),
                "from_email": from_email,
                "from_raw": meta.get("from_email", ""),
                "subject": meta.get("subject", ""),
                "body": body,
                "sentiment": verdict["sentiment"],
                "action": verdict["action"],
                "received_at": received_at.isoformat() if hasattr(received_at, "isoformat") else str(received_at),
            })
        return True, replies, ""
    except Exception as exc:
        return False, [], str(exc)


def build_tracking_url(request: Request, email_id: str) -> str:
    return str(request.url_for("track_email_open", email_id=email_id))


async def get_admin_email_config(db):
    settings_doc = await db["admin_settings"].find_one(
        {"settings_id": "default"},
        {"_id": 0, "emailCfg": 1},
    )
    email_cfg = (settings_doc or {}).get("emailCfg") or {}
    return {k: v for k, v in email_cfg.items() if v not in (None, "")}


def _request_base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _normalise_chat_messages(messages: list) -> list:
    cleaned = []
    for item in messages or []:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        if not cleaned and role != "user":
            continue
        if cleaned and cleaned[-1]["role"] == role:
            cleaned[-1]["content"] = f"{cleaned[-1]['content']}\n\n{content}"
        else:
            cleaned.append({"role": role, "content": content})
    return cleaned[-12:]


async def _trainer_phone(db, trainer_id: str, fallback: str = "") -> str:
    if trainer_id:
        trainer = await db["trainers"].find_one(
            {"trainer_id": trainer_id},
            {"_id": 0, "phone": 1},
        )
        if (trainer or {}).get("phone"):
            return trainer["phone"]
    return fallback or ""


async def _trainer_for_direct_teams(db, trainer_id: str, fallback: Optional[dict] = None) -> dict:
    fallback = fallback or {}
    trainer = {}
    if trainer_id:
        trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or {}
    merged = {**fallback, **trainer}
    if trainer_id and not merged.get("trainer_id"):
        merged["trainer_id"] = trainer_id
    return merged


def _strip_quoted_reply_text(text: str) -> str:
    value = str(text or "")
    value = _re.split(r"\nOn .+wrote:\s*", value, maxsplit=1, flags=_re.IGNORECASE)[0]
    value = _re.split(r"\n-{2,}\s*Original Message\s*-{2,}", value, maxsplit=1, flags=_re.IGNORECASE)[0]
    lines = [line for line in value.splitlines() if not line.strip().startswith(">")]
    return "\n".join(lines).strip()


async def _client_contact_for_requirement(db, requirement_id: str, payload: dict) -> tuple:
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}

    email = (payload.get("client_email") or requirement.get("client_email") or "").strip()
    name = (
        payload.get("client_name")
        or requirement.get("client_name")
        or requirement.get("client_company")
        or "Client"
    )

    if not email:
        inbox_docs = await db["client_emails"].find(
            {"requirement_id": requirement_id},
            {"_id": 0},
        ).sort("created_at", -1).limit(1).to_list(1)
        inbox_doc = inbox_docs[0] if inbox_docs else {}
        extracted = inbox_doc.get("extracted") or {}
        email = (inbox_doc.get("from_email") or extracted.get("client_email") or "").strip()
        name = inbox_doc.get("from_name") or extracted.get("client_name") or name

    return requirement, email, name


def _trainer_greeting(name: str = "") -> str:
    clean = str(name or "").strip()
    return f"Dear {clean or 'Trainer'},"


def _client_note_excerpt(text: str, max_chars: int = 900) -> str:
    clean = _strip_quoted_reply_text(text)
    clean = "\n".join(line.rstrip() for line in clean.splitlines()).strip()
    while "\n\n\n" in clean:
        clean = clean.replace("\n\n\n", "\n\n")
    if len(clean) <= max_chars:
        return clean
    return clean[:max_chars].rsplit(" ", 1)[0].strip() + "..."


def _detect_client_interview_decision(subject: str = "", body: str = "") -> dict:
    text = _re.sub(r"\s+", " ", f"{subject or ''} {body or ''}".lower()).strip()
    if not text:
        return {"decision": "", "confidence": 0, "reason": "empty"}
    subject_text = str(subject or "").lower().strip()
    if (
        _re.match(r"^(accepted|declined|tentatively accepted|updated invitation|canceled|cancelled):", subject_text)
        or "has accepted this invitation" in text
        or "has declined this invitation" in text
        or "has tentatively accepted this invitation" in text
    ):
        return {"decision": "", "confidence": 0, "reason": "calendar rsvp"}

    rejection_patterns = [
        r"\bnot\s+selected\b",
        r"\bnot\s+shortlisted\b",
        r"\bnot\s+select(?:ing|ed)?\b",
        r"\breject(?:ed|ing)?\b",
        r"\bdeclin(?:ed|ing)e?\b",
        r"\bnot\s+proceed(?:ing)?\b",
        r"\bwill\s+not\s+proceed\b",
        r"\bmove\s+to\s+next\s+trainer\b",
        r"\bgo\s+with\s+another\s+trainer\b",
        r"\bnot\s+fit\b",
        r"\bnot\s+suitable\b",
    ]
    selection_patterns = [
        r"\bselected\b",
        r"\bshortlisted\b",
        r"\bapproved\b",
        r"\bconfirm(?:ed)?\s+(?:the\s+)?trainer\b",
        r"\bproceed\s+with\b",
        r"\bgo\s+ahead\s+with\b",
        r"\btrainer\s+is\s+confirmed\b",
        r"\bhe\s+is\s+selected\b",
        r"\bshe\s+is\s+selected\b",
    ]
    slot_context = _re.search(
        r"\b(slot|meeting|meet|interview schedule|interview slot|availability|timing|time)\b",
        text,
    )
    has_clear_trainer_selection = _re.search(
        r"\b(trainer|profile|candidate|he|she)\s+(?:is\s+|has\s+been\s+)?(?:selected|approved|confirmed)\b"
        r"|\b(?:select|approve|confirm)\s+(?:this\s+|the\s+)?(?:trainer|profile|candidate)\b"
        r"|\b(?:proceed|go\s+ahead)\s+with\s+(?:this\s+|the\s+)?(?:trainer|profile|candidate|he|she)\b",
        text,
    )
    if slot_context and not has_clear_trainer_selection:
        return {"decision": "", "confidence": 0, "reason": "slot scheduling context"}

    for pattern in rejection_patterns:
        if _re.search(pattern, text):
            return {"decision": "rejected", "confidence": 0.9, "reason": pattern}
    for pattern in selection_patterns:
        if _re.search(pattern, text):
            return {"decision": "selected", "confidence": 0.86, "reason": pattern}
    return {"decision": "", "confidence": 0, "reason": "no decision phrase"}


def _decision_mail_templates(trainer: dict, requirement: dict, decision: str, client_note: str = "") -> list:
    trainer_name = trainer.get("name") or trainer.get("trainer_name") or ""
    technology = requirement.get("technology_needed") or requirement.get("job_title") or "the training requirement"
    greeting = _trainer_greeting(trainer_name)
    note_block = f"\n\nClient note:\n{client_note}" if client_note else ""

    if decision == "selected":
        return [
            {
                "mail_type": "mail5_ok",
                "subject": f"Congratulations! You have been Selected - {technology}",
                "body": (
                    f"{greeting}\n\n"
                    f"Congratulations! The client has selected you for the {technology} training requirement."
                    f"{note_block}\n\n"
                    "We will coordinate the next steps and documentation with you shortly.\n\n"
                    "Regards,\nTrainerSync Team"
                ),
            },
        ]

    return [
        {
            "mail_type": "mail5_no",
            "subject": f"Update on Training Requirement - {technology}",
            "body": (
                f"{greeting}\n\n"
                f"Thank you for your time and interest in the {technology} training requirement.\n\n"
                "After the client discussion, we regret to inform you that the client has decided not to proceed with your profile for this requirement."
                f"{note_block}\n\n"
                "We will keep your profile on record and reach out for suitable future opportunities.\n\n"
                "Thank you once again for your cooperation.\n\n"
                "Regards,\nTrainerSync Team"
            ),
        }
    ]


def _duration_days_for_toc(requirement: dict) -> int:
    for key in ("duration_days", "duration"):
        value = requirement.get(key)
        if value:
            match = _re.search(r"\d+", str(value))
            if match:
                return max(1, min(int(match.group(0)), 100))
    hours = requirement.get("duration_hours")
    if hours:
        try:
            return max(1, min(int((float(hours) + 7) // 8), 100))
        except Exception:
            pass
    text = " ".join(str(requirement.get(key) or "") for key in ("preferred_dates", "timeline_start", "timeline_end", "description"))
    match = _re.search(r"\b(\d{1,2})\s*(?:day|days)\b", text, flags=_re.IGNORECASE)
    if match:
        return max(1, min(int(match.group(1)), 100))
    return 3


def _toc_domain_plan(technology: str) -> dict:
    tech = str(technology or "Training").lower()
    if any(key in tech for key in ("devops", "dev ops", "ci/cd", "cicd", "kubernetes", "docker")):
        return {
            "tools": ["Git", "Linux", "Docker", "Kubernetes", "Jenkins", "GitHub Actions", "Terraform", "Ansible", "Prometheus", "Grafana"],
            "prerequisites": [
                "Basic Linux command-line knowledge",
                "Understanding of software build and deployment flow",
                "Laptop with Docker/Desktop or cloud lab access",
            ],
            "outcomes": [
                "Design CI/CD pipelines for build, test, security scan, and deployment",
                "Containerize applications using Docker and manage images safely",
                "Deploy and troubleshoot workloads on Kubernetes",
                "Provision infrastructure using Terraform and automate configuration with Ansible",
                "Set up monitoring, logging, rollback, and release governance practices",
            ],
            "themes": [
                ("Linux & DevOps Foundations", [
                    "Linux file system, permissions, users, groups, process management, and service logs",
                    "Bash scripting with variables, loops, conditions, cron jobs, and backup automation",
                    "DevOps principles, SDLC, Agile overview, networking basics, DNS, HTTP/HTTPS, ports",
                    "Lab: Linux administration tasks, backup shell script, and networking validation",
                    "Jira: create Scrum project, Epic Linux & Networking Foundations, stories, subtasks, story points",
                ]),
                ("Version Control & Git Workflows", [
                    "Git fundamentals: init, clone, add, commit, push, pull, status, log",
                    "Branching, merge, rebase, cherry-pick, stash, hooks, conflict resolution",
                    "GitHub workflows: pull requests, code review, branch protection, issue keys",
                    "Lab: team PR workflow and merge conflict resolution",
                    "Jira: Epic Version Control, Sprint 1 planning, smart commits, PR-linked issue transitions",
                ]),
                ("Docker & Containerization", [
                    "Containers vs virtual machines, Docker CLI, images, layers, registries",
                    "Dockerfile authoring, build cache, multi-stage builds, image tagging",
                    "Docker Compose services, networks, volumes, env vars, and troubleshooting",
                    "Lab: deploy a full-stack app with Docker Compose end to end",
                    "Jira: Epic Containerization, Docker labels, Definition of Done, impediment logging",
                ]),
                ("Jenkins & CI/CD Pipelines", [
                    "Jenkins installation, plugins, admin setup, credentials, and global configuration",
                    "Freestyle jobs, build triggers, SCM polling, post-build actions",
                    "Declarative Jenkinsfile pipelines, stages, agents, shared libraries, parallel stages",
                    "Lab: build, test, Docker image creation, and registry push pipeline",
                    "Jira: CI/CD epic, Jenkins build links, automation transition on PR merge, release notes",
                ]),
                ("GitHub Actions & Advanced CI/CD", [
                    "GitHub Actions workflows, triggers, jobs, steps, marketplace actions",
                    "Build, test, lint on pull request, matrix builds, caching, artifacts",
                    "Deployment workflows, environment secrets, approvals, OIDC, reusable workflows",
                    "Lab: full GitHub Actions CI/CD from test to Docker build to deploy",
                    "Jira: deployment tracking, release versions, CI failure notifications, velocity report",
                ]),
                ("Terraform & Infrastructure as Code", [
                    "IaC concepts, Terraform providers, resources, init, plan, apply, destroy",
                    "Variables, outputs, locals, data sources, tfvars, state, and locking",
                    "Modules, Terraform Registry, S3 backend, multi-environment workspaces",
                    "Lab: provision AWS VPC, EC2/RDS module, remote state, and reusable variables",
                    "Jira: IaC epic, components terraform/aws/networking, risk register, sprint health dashboard",
                ]),
                ("Kubernetes Fundamentals", [
                    "Kubernetes architecture, control plane, etcd, scheduler, kubelet, nodes, pods",
                    "Deployments, ReplicaSets, Services, Namespaces, ConfigMaps, Secrets",
                    "PV/PVC, StorageClass, Ingress, NetworkPolicy, CoreDNS, Helm charts",
                    "Lab: deploy microservices app with Helm, Ingress, and persistent storage",
                    "Jira: Kubernetes Kanban board, deployment checklist, fix versions, incident ticket",
                ]),
                ("Monitoring, Logging & Observability", [
                    "Prometheus setup, exporters, scrape configs, PromQL, Alertmanager",
                    "Grafana dashboards, variables, panels, alerts, SLI/SLO tracking",
                    "ELK stack logging with Elasticsearch, Logstash, Kibana, Filebeat, tracing overview",
                    "Lab: metrics, logs, traces, dashboards, alerts, and postmortem workflow",
                    "Jira: ITSM incident project, SLA fields, alert-to-incident automation, CFD review",
                ]),
                ("Cloud, AWS, Security & Networking", [
                    "AWS EC2, S3, RDS, IAM, VPC, EKS, Lambda, Route53, CloudFront, CloudWatch",
                    "Subnets, NACLs, Security Groups, VPN, VPC peering, Transit Gateway",
                    "DevSecOps with IAM policies, Secrets Manager, SAST/DAST, Trivy, Snyk, OPA",
                    "Lab: deploy secure 3-tier app on AWS using Terraform, EKS, RDS, and ALB",
                    "Jira: cloud security findings, compliance checklist, risk matrix, change workflow",
                ]),
                ("Capstone: End-to-End DevOps Project", [
                    "Requirements, architecture design, tool selection, and pipeline design",
                    "Terraform AWS infrastructure, Dockerize app, push to ECR/Docker Hub",
                    "GitHub Actions and Jenkins pipeline: build, test, scan, deploy",
                    "Lab: Helm deploy to EKS with Prometheus, Grafana, ELK, demo, and rollback",
                    "Jira: full project sprint with epics, stories, tasks, burndown, velocity, retro",
                ]),
            ],
            "certifications": [
                "AWS Certified DevOps Engineer - Professional",
                "Certified Kubernetes Administrator (CKA)",
                "Certified Kubernetes Application Developer (CKAD)",
                "HashiCorp Certified: Terraform Associate",
                "GitHub Actions Certification",
                "Jenkins Certified Engineer",
                "Docker Certified Associate",
                "Atlassian Certified in Jira Software Development",
            ],
        }
    if any(key in tech for key in ("python", "django", "flask", "fastapi")):
        return {
            "tools": ["Python 3", "VS Code", "pip/venv", "pytest", "FastAPI/Flask", "SQLAlchemy", "Git"],
            "prerequisites": ["Basic programming knowledge", "Laptop with Python 3 installed", "Familiarity with command-line usage"],
            "outcomes": ["Write clean Python programs", "Build APIs and database-backed apps", "Test and debug Python applications", "Package and deploy Python services", "Apply Python best practices in projects"],
            "themes": [
                ("Python Foundations", ["Syntax, data types, control flow, functions, modules", "Collections, comprehensions, error handling", "File handling and virtual environments", "Lab: build CLI utilities", "Lab: debug and refactor Python scripts"]),
                ("Object-Oriented and Practical Python", ["Classes, objects, inheritance, dataclasses", "Iterators, decorators, context managers", "Working with APIs, JSON, and external packages", "Lab: consume REST API and process data", "Lab: build reusable Python package"]),
                ("Web/API Development", ["Flask/FastAPI routing, validation, middleware", "Database integration and ORM basics", "Authentication, logging, and error handling", "Lab: build CRUD API", "Lab: test API endpoints"]),
                ("Testing, Deployment, and Capstone", ["pytest, mocking, coverage, linting", "Dockerizing Python apps and deployment basics", "Performance, security, and production checklist", "Capstone lab: complete API project", "Assessment and next steps"]),
            ],
        }
    if any(key in tech for key in ("react", "frontend", "front end", "javascript")):
        return {
            "tools": ["Node.js", "React", "Vite", "React Router", "Axios", "Tailwind/CSS", "Git"],
            "prerequisites": ["HTML/CSS basics", "JavaScript ES6 knowledge", "Node.js installed"],
            "outcomes": ["Build component-based React apps", "Manage state and forms", "Integrate APIs", "Implement routing and UI patterns", "Deploy production frontend builds"],
            "themes": [
                ("React and Modern JavaScript Foundations", ["JS ES6 refresh, modules, promises", "React components, props, state", "JSX, events, conditional rendering", "Lab: build component library", "Lab: stateful mini app"]),
                ("Hooks, Forms, and API Integration", ["useEffect, custom hooks, form state", "Axios/fetch, loading/error states", "Validation and reusable form components", "Lab: API-backed dashboard", "Lab: form workflow with validation"]),
                ("Routing, Performance, and Production", ["React Router, layouts, protected routes", "Memoization, code splitting, UX states", "Build, deployment, accessibility basics", "Capstone lab: complete React app", "Review and assessment"]),
            ],
        }
    if any(key in tech for key in ("data engineering", "big data", "etl", "spark", "databricks")):
        return {
            "tools": ["SQL", "Python", "Apache Spark", "Airflow", "Cloud Storage", "Data Warehouse", "Git"],
            "prerequisites": ["SQL basics", "Basic Python knowledge", "Understanding of databases and files"],
            "outcomes": ["Design ETL/ELT pipelines", "Process batch data using Spark", "Validate data quality", "Orchestrate workflows", "Build production-ready data pipeline patterns"],
            "themes": [
                ("Data Engineering Foundations", ["ETL vs ELT, lakehouse, warehouse concepts", "Data modeling, partitioning, file formats", "SQL transformation and quality checks", "Lab: design pipeline architecture", "Lab: create validation rules"]),
                ("Batch Processing and Spark", ["Spark architecture, DataFrames, transformations", "Joins, aggregations, optimization basics", "Handling schema drift and bad records", "Lab: build Spark transformation job", "Lab: tune and troubleshoot job"]),
                ("Orchestration and Production Pipelines", ["Airflow DAGs, scheduling, retries", "Monitoring, logging, lineage, alerts", "Deployment and CI/CD for data pipelines", "Capstone lab: end-to-end data pipeline", "Assessment and best practices"]),
            ],
        }
    return {
        "tools": [technology, "Browser", "Code editor / relevant platform tools", "Collaboration tools"],
        "prerequisites": ["Basic understanding of IT systems and business workflows", "Laptop with required software access", f"Interest or prior exposure to {technology}"],
        "outcomes": [f"Understand core {technology} concepts and terminology", "Configure and use key tools in practical scenarios", "Apply best practices for real-world implementation", "Troubleshoot common issues and validate outcomes", "Complete hands-on exercises aligned with business use cases"],
        "themes": [
            ("Foundations and Environment Setup", ["Program introduction and learning outcomes", f"{technology} fundamentals and architecture", "Environment setup and tool walkthrough", "Core concepts with guided examples", "Hands-on lab: build the first working exercise"]),
            ("Core Implementation and Practical Workflows", ["Key features and implementation patterns", "Common business use cases", "Configuration and troubleshooting practices", "Hands-on lab: implement a real-world workflow", "Review, Q&A, and improvement discussion"]),
            ("Advanced Topics and Capstone", ["Advanced concepts and optimization", "Security, governance, and best practices", "Case study and scenario-based exercises", "Capstone project implementation", "Assessment, feedback, and next-step guidance"]),
        ],
    }


def _fallback_toc_data(payload: dict, reason: str = "") -> dict:
    technology = payload.get("technology") or "Training"
    duration_days = max(1, min(int(payload.get("duration_days") or 3), 100))
    audience_level = payload.get("audience_level") or "intermediate"
    mode = payload.get("mode") or "Online"
    plan = _toc_domain_plan(technology)
    themes = plan["themes"]

    def day_tools(title: str) -> str:
        clean = title.lower()
        if "linux" in clean:
            return "Linux + Jira"
        if "git" in clean and "github actions" not in clean:
            return "Git + GitHub + Jira"
        if "docker" in clean:
            return "Docker + Docker Compose + Jira"
        if "jenkins" in clean:
            return "Jenkins + Maven + Jira"
        if "github actions" in clean:
            return "GitHub Actions + Jira"
        if "terraform" in clean:
            return "Terraform + AWS + Jira"
        if "kubernetes" in clean:
            return "Kubernetes + kubectl + Jira"
        if "observability" in clean or "monitoring" in clean:
            return "Prometheus + Grafana + ELK + Jira"
        if "aws" in clean or "cloud" in clean:
            return "AWS + Terraform + Jira"
        if "capstone" in clean:
            return "All DevOps Tools + Jira"
        return ", ".join(plan["tools"][:3])

    def jira_focus(title: str, topics: list) -> str:
        for topic in topics:
            if str(topic).startswith("Jira:"):
                return str(topic).replace("Jira:", "", 1).strip()
        return f"Create delivery board and track {title} tasks"

    days = []
    for index in range(duration_days):
        title, topics = themes[index % len(themes)]
        if duration_days > len(themes) and index >= len(themes):
            title = f"{title} - Extended Practice"
        jira = jira_focus(title, topics)
        tools = day_tools(title)
        days.append({
            "day": index + 1,
            "title": f"Day {index + 1}: {title}",
            "focus_area": title,
            "tools": tools,
            "jira_focus": jira,
            "morning_session": {
                "time": "9:00 AM - 1:00 PM",
                "title": f"{title} - Concepts",
                "topics": [
                    {"time": "9:00 - 10:30", "topic": topics[0], "type": "lecture"},
                    {"time": "10:30 - 10:45", "topic": "Break", "type": "break"},
                    {"time": "10:45 - 12:15", "topic": topics[1], "type": "demo"},
                    {"time": "12:15 - 1:00", "topic": "Lunch", "type": "break"},
                ],
            },
            "afternoon_session": {
                "time": "1:00 PM - 5:00 PM",
                "title": f"{title} - Hands-on",
                "topics": [
                    {"time": "1:00 - 2:30", "topic": topics[2], "type": "lecture"},
                    {"time": "2:30 - 2:45", "topic": "Break", "type": "break"},
                    {"time": "2:45 - 4:00", "topic": topics[3], "type": "lab"},
                    {"time": "4:00 - 5:00", "topic": topics[4], "type": "jira"},
                ],
            },
            "learning_objectives": [
                f"Understand and apply {title} concepts in real delivery scenarios",
                f"Use {tools} to complete guided hands-on activities",
                "Connect technical delivery work with Jira epics, stories, subtasks, and sprint tracking",
                "Identify troubleshooting steps, risks, and production-readiness checks",
            ],
            "jira_practice": [
                jira,
                "Create or update Epics, Stories, Tasks, Subtasks, acceptance criteria, and story points",
                "Move work across To Do, In Progress, Review, and Done with comments and time logs",
                "Review sprint progress using burndown, velocity, dashboard, or incident/project reports",
            ],
        })

    overview_table = [
        {
            "day": day["day"],
            "focus_area": day["focus_area"],
            "primary_tools": day["tools"],
            "jira_focus": day["jira_focus"],
        }
        for day in days
    ]

    note = "Generated with deterministic fallback because AI generation was temporarily unavailable."
    if reason:
        note += f" Reason: {reason[:180]}"
    return {
        "title": f"{technology} Mastery",
        "subtitle": f"{duration_days}-Day Intensive Training Program",
        "overview": (
            f"This {duration_days}-day {technology} intensive takes learners from foundations to production-ready execution. "
            "Each 8-hour day combines theory, hands-on labs, and real-world Jira project management to simulate professional delivery workflows."
        ),
        "overview_table": overview_table,
        "prerequisites": plan["prerequisites"],
        "learning_outcomes": plan["outcomes"],
        "days": days,
        "tools_software": plan["tools"],
        "tools_reference": [
            {"category": "CI/CD Tools", "items": ["Jenkins - build automation, Jenkinsfile pipelines, shared libraries", "GitHub Actions - workflow files, marketplace actions, OIDC, reusable workflows"]},
            {"category": "Containerisation & Orchestration", "items": ["Docker - Dockerfiles, multi-stage builds, Compose, networking, volumes", "Kubernetes - Pods, Deployments, Services, Ingress, Helm, EKS"]},
            {"category": "Infrastructure as Code", "items": ["Terraform - providers, modules, workspaces, remote state, S3 backend"]},
            {"category": "Cloud Platform", "items": ["AWS - EC2, S3, RDS, IAM, VPC, EKS, Lambda, ALB, Route53, CloudWatch"]},
            {"category": "Monitoring & Observability", "items": ["Prometheus and Grafana - metrics, dashboards, alerting", "ELK Stack - Elasticsearch, Logstash, Kibana, Filebeat"]},
            {"category": "Project Management", "items": ["Jira Software - Scrum/Kanban boards, epics, stories, sprints, automation, reports"]},
        ] if "devops" in str(technology).lower() else [],
        "certification_roadmap": plan.get("certifications") or [],
        "certification_guidance": f"After this program, learners can prepare for: {', '.join(plan.get('certifications') or [f'relevant {technology} certifications'])}.",
        "trainer_notes": note,
    }


def _is_placeholder_api_key(value: str = "") -> bool:
    clean = str(value or "").strip().lower()
    return (
        not clean
        or clean.startswith("your_")
        or clean in {"your_gemini_api_key", "your-api-key", "your_api_key", "changeme", "placeholder"}
    )


def _has_value(*values) -> bool:
    return any(str(value or "").strip() for value in values)


def _toc_missing_client_inputs(requirement: dict, payload: Optional[dict] = None) -> list[dict]:
    payload = payload or {}
    missing = []
    if not _has_value(payload.get("duration_days"), payload.get("duration_hours"), requirement.get("duration_days"), requirement.get("duration_hours"), requirement.get("duration"), requirement.get("training_duration")):
        missing.append({"key": "duration", "label": "Total duration / training hours"})
    if not _has_value(payload.get("training_dates"), payload.get("timing"), payload.get("schedule"), requirement.get("training_dates"), requirement.get("preferred_dates"), requirement.get("timeline_start"), requirement.get("timeline_end"), requirement.get("timing"), requirement.get("schedule")):
        missing.append({"key": "dates_timing", "label": "Training dates and daily timings"})
    if not _has_value(payload.get("audience_level"), requirement.get("audience_level"), requirement.get("level")):
        missing.append({"key": "audience_level", "label": "Audience level: Basic / Intermediate / Advanced / Mixed"})
    if not _has_value(payload.get("mode"), requirement.get("mode"), requirement.get("training_mode")):
        missing.append({"key": "mode", "label": "Training mode: Online / Classroom / Hybrid"})
    if not _has_value(payload.get("custom_topics"), payload.get("client_notes"), requirement.get("client_notes"), requirement.get("job_description"), requirement.get("description"), requirement.get("content_scope"), requirement.get("syllabus"), requirement.get("topics")):
        missing.append({"key": "content_scope", "label": "Content scope/topics to cover"})
    return missing


async def _send_toc_details_request_to_client(
    db,
    request: Optional[Request],
    *,
    requirement: dict,
    trainer: Optional[dict] = None,
    missing: list[dict],
    source: str,
) -> dict:
    client_email = str(requirement.get("client_email") or "").strip()
    if not client_email:
        return {"success": False, "error": "Client email is required to request TOC inputs"}
    client_name = requirement.get("client_name") or requirement.get("client_company") or "Client"
    technology = requirement.get("technology_needed") or requirement.get("job_title") or "Training"
    trainer_name = (trainer or {}).get("name") or (trainer or {}).get("trainer_name") or requirement.get("selected_trainer_name") or "selected trainer"
    missing_lines = "\n".join(f"* {item['label']}" for item in missing)
    subject = f"Required Training Details for TOC Preparation - {technology}"
    body = (
        f"Dear {client_name},\n\n"
        f"Thank you for the discussion regarding the {technology} training requirement.\n\n"
        "To prepare an accurate Table of Contents (TOC) for the trainer and avoid assumptions, kindly share the below details:\n\n"
        f"{missing_lines}\n\n"
        "Please confirm the following format if possible:\n\n"
        "* Duration: [Number of days] and [hours per day]\n"
        "* Dates & Timings: [DD/MM/YYYY] to [DD/MM/YYYY], [Start time - End time]\n"
        "* Audience Level: Basic / Intermediate / Advanced / Mixed\n"
        "* Mode: Online / Classroom / Hybrid\n"
        "* Content Scope: Required topics, tools, project/lab expectations, and any exclusions\n\n"
        f"Once we receive these details, we will prepare and share the TOC for {trainer_name}.\n\n"
        "Thank you & regards,\n"
        "TrainerSync Team"
    )
    email_id = f"CLIENT-TOC-DETAILS-{uuid.uuid4().hex[:8].upper()}"
    smtp_config = await get_admin_email_config(db)
    success, error = await send_email_async(
        client_email,
        subject,
        body,
        smtp_config,
        build_tracking_url(request, email_id) if request else "",
    )
    now = utc_now()
    log_doc = {
        "email_id": email_id,
        "trainer_id": (trainer or {}).get("trainer_id") or requirement.get("selected_trainer_id") or "",
        "trainer_name": trainer_name,
        "requirement_id": requirement.get("requirement_id") or "",
        "to_email": client_email,
        "client_name": client_name,
        "client_email": client_email,
        "subject": subject,
        "body": body,
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "sent_at": now if success else None,
        "reply_received": False,
        "opened": False,
        "open_count": 0,
        "tracking_url": build_tracking_url(request, email_id) if request else "",
        "retry_count": 0,
        "mail_type": "client_toc_details_request",
        "source": source,
        "missing_toc_inputs": missing,
        "created_at": now,
    }
    await db["email_logs"].insert_one(log_doc)
    await db["conversations"].insert_one({**log_doc, "direction": "client_sent", "error": error if not success else ""})
    await db["requirements"].update_one(
        {"requirement_id": requirement.get("requirement_id")},
        {"$set": {
            "toc_input_status": "requested" if success else "request_failed",
            "toc_input_requested_at": now,
            "toc_input_request_email_id": email_id,
            "toc_missing_inputs": missing,
        }},
    )
    return {"success": success, "error": error, "email_id": email_id, "to_email": client_email, "missing": missing}


async def _auto_generate_and_send_toc(
    db,
    request: Optional[Request],
    *,
    trainer: dict,
    requirement: dict,
    source: str = "automation",
) -> dict:
    trainer_id = trainer.get("trainer_id") or ""
    requirement_id = requirement.get("requirement_id") or ""
    trainer_email = trainer.get("email") or trainer.get("trainer_email") or ""
    trainer_name = trainer.get("name") or trainer.get("trainer_name") or "Trainer"
    technology = requirement.get("technology_needed") or requirement.get("job_title") or "Training"

    if not trainer_id or not requirement_id or not trainer_email:
        return {"success": False, "error": "Trainer email or requirement id missing", "mail_type": "mail6_toc"}

    missing_inputs = _toc_missing_client_inputs(requirement)
    if missing_inputs:
        request_result = await _send_toc_details_request_to_client(
            db,
            request,
            requirement=requirement,
            trainer=trainer,
            missing=missing_inputs,
            source=f"{source}_toc_input_guard",
        )
        return {
            "success": False,
            "status": "toc_inputs_requested",
            "error": "Missing client TOC inputs. Requested details from client.",
            "mail_type": "client_toc_details_request",
            "details_request": request_result,
            "missing_inputs": missing_inputs,
        }

    existing = await db["toc_documents"].find_one(
        {
            "trainer_id": trainer_id,
            "requirement_id": requirement_id,
            "status": {"$in": ["sent", "draft"]},
        },
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    if existing and existing.get("status") == "sent":
        return {
            "success": True,
            "skipped": True,
            "status": "already_sent",
            "mail_type": "mail6_toc",
            "toc_id": existing.get("toc_id"),
        }

    sent_log = await db["email_logs"].find_one(
        {
            "trainer_id": trainer_id,
            "requirement_id": requirement_id,
            "mail_type": "mail6_toc",
            "status": "sent",
        },
        {"_id": 0, "email_id": 1, "toc_id": 1},
        sort=[("sent_at", -1), ("created_at", -1)],
    )
    if sent_log:
        return {
            "success": True,
            "skipped": True,
            "status": "already_sent",
            "mail_type": "mail6_toc",
            "email_id": sent_log.get("email_id"),
            "toc_id": sent_log.get("toc_id"),
        }

    duration_days = _duration_days_for_toc(requirement)
    mode = requirement.get("mode") or requirement.get("training_mode") or "Online"
    audience_level = requirement.get("audience_level") or requirement.get("level") or "intermediate"
    payload = {
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "trainer_email": trainer_email,
        "technology": technology,
        "duration_days": duration_days,
        "audience_level": audience_level,
        "mode": mode,
        "toc_type": "standard",
        "custom_topics": "",
    }

    try:
        toc_data = existing.get("toc_data") if existing else None
        generation_error = existing.get("generation_error", "") if existing else ""
        if not toc_data:
            try:
                toc_data = await _generate_toc_from_best_knowledge(
                    db,
                    {
                        **payload,
                        "technology": technology,
                        "audience_level": audience_level,
                        "mode": mode,
                        "client_notes": requirement.get("client_notes") or requirement.get("job_description") or "",
                    },
                    duration_days,
                )
                generation_error = ""
            except Exception as dataset_exc:
                generation_error = f"Knowledge base fallback failed: {dataset_exc}"
                toc_data = _fallback_toc_data(payload, generation_error)
        toc_data = validate_toc(toc_data, duration_days)
        toc_id = existing.get("toc_id") if existing else f"TOC-{uuid.uuid4().hex[:8].upper()}"
        doc = {
            "toc_id": toc_id,
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
            "trainer_name": trainer_name,
            "trainer_email": trainer_email,
            "technology": technology,
            "duration_days": duration_days,
            "audience_level": audience_level,
            "mode": mode,
            "toc_type": "standard",
            "custom_topics": "",
            "toc_data": toc_data,
            "generation_error": generation_error,
            "ai_provider": "ollomo" if not generation_error else "dataset_fallback",
            "status": "draft",
            "source": source,
            "created_at": existing.get("created_at") if existing else utc_now(),
            "updated_at": utc_now(),
        }
        await db["toc_documents"].update_one(
            {"toc_id": toc_id},
            {"$set": doc},
            upsert=True,
        )

        subject = f"AI Generated ToC / Course Agenda - {technology}"
        body = (
            f"Dear {trainer_name},\n\n"
            f"Congratulations again on being selected for the {technology} training.\n\n"
            "Please find attached the AI-generated Training Table of Contents / Course Agenda for your review.\n"
            "Kindly check the curriculum and share any required changes or additions before we share it with the client.\n\n"
            "Regards,\nTrainerSync Team"
        )
        pdf_bytes = _toc_pdf_bytes({**doc, "toc_data": toc_data})
        filename = f"{_clean_filename(technology)}_{toc_id}.pdf"
        smtp_config = await get_admin_email_config(db)
        success, error = _send_toc_email_with_attachment(
            trainer_email,
            subject,
            body,
            filename,
            pdf_bytes,
            smtp_config,
        )
        client_toc_result = {"skipped": True, "reason": "client email missing"}
        client_email = str(requirement.get("client_email") or "").strip()
        if client_email and client_email.lower() != str(trainer_email or "").strip().lower():
            client_subject = f"Training TOC / Course Agenda - {technology} - {trainer_name}"
            client_body = (
                f"Dear {requirement.get('client_name') or 'Client'},\n\n"
                f"Please find attached the generated Training Table of Contents / Course Agenda for the {technology} training.\n\n"
                f"Trainer: {trainer_name}\n"
                f"Duration: {duration_days} days\n"
                f"Mode: {mode}\n"
                f"Audience Level: {audience_level}\n\n"
                "Kindly review and share any changes or approval to proceed.\n\n"
                "Regards,\nTrainerSync Team"
            )
            client_email_id = f"CLIENT-TOC-{uuid.uuid4().hex[:8].upper()}"
            client_success, client_error = _send_toc_email_with_attachment(
                client_email,
                client_subject,
                client_body,
                filename,
                pdf_bytes,
                smtp_config,
            )
            client_toc_result = {
                "success": client_success,
                "error": client_error,
                "email_id": client_email_id,
                "to_email": client_email,
            }
            await db["client_messages"].insert_one({
                "message_id": f"CLIENT-MSG-{uuid.uuid4().hex[:8].upper()}",
                "client_email": client_email,
                "client_name": requirement.get("client_name") or client_email,
                "requirement_id": requirement_id,
                "trainer_id": trainer_id,
                "trainer_name": trainer_name,
                "subject": client_subject,
                "body": client_body,
                "mail_type": "client_toc",
                "direction": "sent",
                "status": "sent" if client_success else "failed",
                "error": client_error if not client_success else "",
                "sent_at": utc_now(),
                "toc_id": toc_id,
                "source": source,
            })
            await db["email_logs"].insert_one({
                "email_id": client_email_id,
                "trainer_id": trainer_id,
                "trainer_name": trainer_name,
                "requirement_id": requirement_id,
                "to_email": client_email,
                "subject": client_subject,
                "body": client_body,
                "status": "sent" if client_success else "failed",
                "error_message": client_error if not client_success else "",
                "sent_at": utc_now() if client_success else None,
                "reply_received": False,
                "opened": False,
                "open_count": 0,
                "tracking_url": build_tracking_url(request, client_email_id) if request else "",
                "retry_count": 0,
                "mail_type": "client_toc",
                "toc_id": toc_id,
                "toc_title": toc_data.get("title", ""),
                "source": source,
                "created_at": utc_now(),
            })
        email_id = f"EMAIL-{uuid.uuid4().hex[:8].upper()}"
        trainer_phone = await _trainer_phone(db, trainer_id, trainer.get("phone") or "")
        trainer_for_teams = await _trainer_for_direct_teams(db, trainer_id, trainer)
        whatsapp_result, teams_direct_result = await asyncio.gather(
            send_shortlist_whatsapp(
                db,
                trainer_phone=trainer_phone,
                trainer_name=trainer_name,
                subject=subject,
                body=body,
                mail_type="mail6_toc",
                requirement_id=requirement_id,
                email_id=email_id,
                request_base_url=_request_base_url(request) if request else "",
            ),
            send_trainer_teams_direct_message(
                db,
                trainer=trainer_for_teams,
                subject=subject,
                body=body,
                requirement_id=requirement_id,
                mail_type="mail6_toc",
                email_id=email_id,
            ),
        )
        sent_at = utc_now()
        await db["toc_documents"].update_one(
            {"toc_id": toc_id},
            {"$set": {
                "status": "sent" if success else "send_failed",
                "sent_at": sent_at if success else None,
                "send_error": error,
                "email_subject": subject,
                "email_body": body,
                "pdf_generated_at": sent_at,
                "whatsapp_summary": whatsapp_result,
                "teams_direct_summary": teams_direct_result,
                "client_toc_summary": client_toc_result,
            }},
        )
        await db["conversations"].insert_one({
            "trainer_id": trainer_id,
            "trainer_name": trainer_name,
            "to_email": trainer_email,
            "requirement_id": requirement_id,
            "subject": subject,
            "body": body,
            "mail_type": "mail6_toc",
            "direction": "sent",
            "status": "sent" if success else "failed",
            "error": error if not success else "",
            "sent_at": sent_at,
            "toc_id": toc_id,
            "toc_title": toc_data.get("title", ""),
            "source": source,
        })
        await db["email_logs"].insert_one({
            "email_id": email_id,
            "trainer_id": trainer_id,
            "trainer_name": trainer_name,
            "requirement_id": requirement_id,
            "to_email": trainer_email,
            "subject": subject,
            "body": body,
            "status": "sent" if success else "failed",
            "error_message": error if not success else "",
            "sent_at": sent_at if success else None,
            "reply_received": False,
            "opened": False,
            "open_count": 0,
            "tracking_url": build_tracking_url(request, email_id) if request else "",
            "retry_count": 0,
            "mail_type": "mail6_toc",
            "toc_id": toc_id,
            "toc_title": toc_data.get("title", ""),
            "trainer_phone": trainer_phone,
            "whatsapp_summary": whatsapp_result,
            "teams_direct_summary": teams_direct_result,
            "client_toc_summary": client_toc_result,
            "source": source,
            "created_at": sent_at,
        })
        if success:
            await db["trainers"].update_one({"trainer_id": trainer_id}, {"$set": {"status": "toc_requested"}})
        return {
            "success": success,
            "error": error,
            "mail_type": "mail6_toc",
            "email_id": email_id,
            "toc_id": toc_id,
            "whatsapp": whatsapp_result,
            "teams_direct": teams_direct_result,
            "client_toc": client_toc_result,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "mail_type": "mail6_toc"}


def _training_date_for_confirmation(requirement: dict) -> str:
    for key in ("training_dates", "preferred_dates", "timeline_start", "start_date"):
        value = str(requirement.get(key) or "").strip()
        if value:
            end = str(requirement.get("timeline_end") or "").strip()
            if key == "timeline_start" and end and end != value:
                return f"{value} to {end}"
            return value
    return "As per the client-approved schedule coordinated by Clahan Technologies"


def _venue_for_confirmation(requirement: dict) -> str:
    mode = str(requirement.get("mode") or requirement.get("training_mode") or "Online").strip()
    location = str(requirement.get("location") or requirement.get("preferred_location") or "").strip()
    if location and mode and mode.lower() not in location.lower():
        return f"{mode} - {location}"
    return location or mode or "Online / Client-approved platform"


async def _send_auto_training_confirmation(
    db,
    request: Optional[Request],
    *,
    trainer: dict,
    requirement: dict,
    source: str = "automation",
) -> dict:
    smtp_config = await get_admin_email_config(db)
    settings_doc = await db["admin_settings"].find_one(
        {"settings_id": "default"},
        {"_id": 0, "clientInboxCfg": 1, "twilioCfg": 1},
    ) or {}
    client_inbox_cfg = settings_doc.get("clientInboxCfg") or {}
    twilio_cfg = settings_doc.get("twilioCfg") or {}
    contact_email = (
        smtp_config.get("fromEmail")
        or smtp_config.get("smtpUser")
        or getattr(get_settings(), "from_email", "")
        or getattr(get_settings(), "gmail_user", "")
        or "recruitment@clahantech.com"
    )
    contact_phone = (
        client_inbox_cfg.get("vendorWhatsAppNumber")
        or twilio_cfg.get("vendorWhatsAppNumber")
        or "Clahan Technologies coordination team"
    )
    if str(contact_phone).startswith("whatsapp:"):
        contact_phone = str(contact_phone).replace("whatsapp:", "", 1)

    trainer_name = trainer.get("name") or trainer.get("trainer_name") or "Trainer"
    technology = requirement.get("technology_needed") or requirement.get("job_title") or "Training"
    training_date = _training_date_for_confirmation(requirement)
    venue = _venue_for_confirmation(requirement)
    subject = f"Training Schedule Confirmed - {technology}"
    body = (
        f"Dear {trainer_name},\n\n"
        f"We are pleased to confirm your engagement for the {technology} training. Please find the final details below:\n\n"
        f"Training Date: {training_date}\n"
        f"Venue / Platform: {venue}\n\n"
        "Action Items Before Training:\n"
        "* Ensure all materials and slides are ready\n"
        "* Review the generated ToC / Course Agenda shared by Clahan Technologies\n"
        "* Share soft copies of training content with us 2 days prior\n"
        "* Confirm your availability 24 hours before the training\n\n"
        "For any questions or additional information, please contact:\n\n"
        "Contact Name: Clahan Technologies Team\n"
        f"Phone: {contact_phone}\n"
        f"Email: {contact_email}\n\n"
        "We look forward to a successful training session.\n\n"
        "Regards,\nTrainerSync Team"
    )
    return await _send_trainer_pipeline_email(
        db,
        request,
        trainer=trainer,
        requirement=requirement,
        subject=subject,
        body=body,
        mail_type="mail7_confirm",
        source=source,
    )


async def _send_trainer_pipeline_email(
    db,
    request: Optional[Request],
    *,
    trainer: dict,
    requirement: dict,
    subject: str,
    body: str,
    mail_type: str,
    source: str = "automation",
) -> dict:
    trainer_id = trainer.get("trainer_id") or ""
    requirement_id = requirement.get("requirement_id") or ""
    to_email = trainer.get("email") or trainer.get("trainer_email") or ""
    trainer_name = trainer.get("name") or trainer.get("trainer_name") or "Trainer"
    if not trainer_id or not requirement_id or not to_email:
        return {"success": False, "error": "Trainer email or requirement id missing", "mail_type": mail_type}

    allowed, blocked_response, latest_requirement = await _requirement_trainer_send_guard(
        db,
        requirement_id,
        trainer_id,
    )
    if not allowed:
        blocked_response["mail_type"] = mail_type
        return blocked_response
    requirement = latest_requirement or requirement

    existing = await db["email_logs"].find_one(
        {
            "trainer_id": trainer_id,
            "requirement_id": requirement_id,
            "mail_type": mail_type,
            "status": "sent",
        },
        {"_id": 0, "email_id": 1},
        sort=[("sent_at", -1), ("created_at", -1)],
    )
    if existing:
        return {
            "success": True,
            "skipped": True,
            "status": "already_sent",
            "mail_type": mail_type,
            "email_id": existing.get("email_id"),
        }

    email_id = f"EMAIL-{uuid.uuid4().hex[:8].upper()}"
    tracking_url = build_tracking_url(request, email_id) if request else ""
    smtp_config = await get_admin_email_config(db)
    trainer_phone = await _trainer_phone(db, trainer_id, trainer.get("phone") or "")
    trainer_for_teams = await _trainer_for_direct_teams(db, trainer_id, trainer)
    email_result, whatsapp_result, teams_direct_result = await asyncio.gather(
        send_email_async(to_email, subject, body, smtp_config, tracking_url),
        send_shortlist_whatsapp(
            db,
            trainer_phone=trainer_phone,
            trainer_name=trainer_name,
            subject=subject,
            body=body,
            mail_type=mail_type,
            requirement_id=requirement_id,
            email_id=email_id,
            request_base_url=_request_base_url(request) if request else "",
        ),
        send_trainer_teams_direct_message(
            db,
            trainer=trainer_for_teams,
            subject=subject,
            body=body,
            requirement_id=requirement_id,
            mail_type=mail_type,
            email_id=email_id,
        ),
    )
    success, error = email_result
    now = utc_now()
    await db["conversations"].insert_one({
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "to_email": to_email,
        "requirement_id": requirement_id,
        "subject": subject,
        "body": body,
        "mail_type": mail_type,
        "direction": "sent",
        "status": "sent" if success else "failed",
        "error": error if not success else "",
        "sent_at": now,
        "email_id": email_id,
        "source": source,
    })
    await db["email_logs"].insert_one({
        "email_id": email_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "requirement_id": requirement_id,
        "to_email": to_email,
        "subject": subject,
        "body": body,
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "sent_at": now if success else None,
        "reply_received": False,
        "opened": False,
        "open_count": 0,
        "tracking_url": tracking_url,
        "retry_count": 0,
        "mail_type": mail_type,
        "trainer_phone": trainer_phone,
        "whatsapp_summary": whatsapp_result,
        "teams_direct_summary": teams_direct_result,
        "source": source,
        "created_at": now,
    })

    if success:
        status_by_type = {
            "mail5_ok": "selected",
            "mail5_no": "rejected",
            "mail6_toc": "toc_requested",
            "mail7_confirm": "training_confirmed",
        }
        trainer_status = status_by_type.get(mail_type)
        if trainer_status:
            await db["trainers"].update_one(
                {"trainer_id": trainer_id},
                {"$set": {"status": trainer_status}},
            )
        if mail_type == "mail5_ok":
            await _mark_requirement_selected_and_stop_others(
                db,
                requirement_id=requirement_id,
                trainer_id=trainer_id,
                trainer_name=trainer_name,
                selected_at=now,
            )
            await send_teams_stage_notification(
                db,
                stage="trainer_selected",
                trainer_name=trainer_name,
                requirement=requirement,
                request_base_url=_request_base_url(request) if request else "",
                context={"source": source, "email_id": email_id, "trainer_id": trainer_id},
            )
    return {
        "success": success,
        "error": error,
        "email_id": email_id,
        "mail_type": mail_type,
        "whatsapp": whatsapp_result,
        "teams_direct": teams_direct_result,
    }


def _trainer_commercial_negotiation_body(trainer_name: str, technology: str, amount: float, unit: str) -> str:
    amount_text = f"{float(amount):,.0f}" if amount else "the available"
    unit_label = unit or "session"
    return (
        f"Dear {trainer_name or 'Trainer'},\n\n"
        f"Thank you for your interest in the {technology} training requirement.\n\n"
        f"For this requirement, the available commercial budget is INR {amount_text} per {unit_label}. "
        "Kindly confirm whether this commercial is workable from your side so we can proceed with your profile for the next steps.\n\n"
        "Best Regards,\n"
        "Recruitment Team\n"
        "Clahan Technologies"
    )


async def _mark_shortlist_trainer_status(db, requirement_id: str, trainer_id: str, status: str, reason: str = "") -> None:
    if not requirement_id or not trainer_id:
        return
    fields = {
        "top_trainers.$.status": status,
        "top_trainers.$.pipeline_status": status,
        "top_trainers.$.updated_at": utc_now(),
    }
    if reason:
        fields["top_trainers.$.status_reason"] = reason
    await db["shortlists"].update_one(
        {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
        {"$set": fields},
    )


async def _send_next_trainer_after_decline(
    db,
    request: Optional[Request],
    *,
    declined_log: dict,
    reply: dict,
) -> dict:
    requirement_id = declined_log.get("requirement_id") or ""
    declined_trainer_id = declined_log.get("trainer_id") or ""
    if not requirement_id or not declined_trainer_id:
        return {"skipped": True, "reason": "Missing requirement or trainer id"}

    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    shortlist = await db["shortlists"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    top_trainers = shortlist.get("top_trainers") or []
    if not top_trainers:
        return {"skipped": True, "reason": "No shortlist found"}

    await _mark_shortlist_trainer_status(
        db,
        requirement_id,
        declined_trainer_id,
        "declined",
        "Trainer declined or not interested",
    )

    commercial_amount = (
        requirement.get("trainer_visible_budget_per_session")
        or requirement.get("trainer_requested_budget_per_session")
        or (declined_log.get("commercials") or {}).get("requested_trainer_commercial")
    )
    commercial_context = declined_log.get("mail_type") == "trainer_commercial_negotiation" or bool(commercial_amount)
    technology = requirement.get("technology_needed") or "Training"
    declined_index = next(
        (index for index, item in enumerate(top_trainers) if str(item.get("trainer_id")) == str(declined_trainer_id)),
        -1,
    )
    ordered_candidates = top_trainers[declined_index + 1:] + top_trainers[:max(declined_index, 0)]
    blocked_statuses = {"declined", "rejected", "selected", "stopped_selected", "training_confirmed"}

    for item in ordered_candidates:
        trainer_id = item.get("trainer_id")
        if not trainer_id or str(trainer_id) == str(declined_trainer_id):
            continue
        item_status = str(item.get("pipeline_status") or item.get("status") or "").strip().lower()
        if item_status in blocked_statuses:
            continue
        existing = await db["email_logs"].find_one(
            {
                "requirement_id": requirement_id,
                "trainer_id": trainer_id,
                "mail_type": "trainer_commercial_negotiation" if commercial_context else "mail1",
                "status": "sent",
                "reply_received": {"$ne": True},
            },
            {"_id": 0, "email_id": 1},
        )
        if existing:
            continue

        trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or item
        trainer_name = trainer.get("name") or trainer.get("trainer_name") or item.get("name") or "Trainer"
        if commercial_context and commercial_amount:
            mail_type = "trainer_commercial_negotiation"
            subject = f"Commercial Revision Request - {technology} Training"
            body = _trainer_commercial_negotiation_body(trainer_name, technology, float(commercial_amount), "session")
        else:
            mail_type = "mail1"
            subject = f"Training Requirement - {technology}"
            body = compose_shortlist_first_email(
                trainer_name,
                technology,
                str(requirement.get("duration_days") or requirement.get("duration_hours") or ""),
                str(requirement.get("mode") or ""),
                str(requirement.get("participant_count") or ""),
            )

        result = await _send_trainer_pipeline_email(
            db,
            request,
            trainer=trainer,
            requirement=requirement,
            subject=subject,
            body=body,
            mail_type=mail_type,
            source="next_trainer_after_decline",
        )
        if result.get("success"):
            await _mark_shortlist_trainer_status(
                db,
                requirement_id,
                trainer_id,
                "commercial_negotiation_requested" if mail_type == "trainer_commercial_negotiation" else "contacted",
                "Follow-up sent after previous trainer declined",
            )
            await db["requirements"].update_one(
                {"requirement_id": requirement_id},
                {"$set": {
                    "last_declined_trainer_id": declined_trainer_id,
                    "last_declined_trainer_name": declined_log.get("trainer_name") or "",
                    "next_trainer_followup_id": trainer_id,
                    "next_trainer_followup_name": trainer_name,
                    "next_trainer_followup_mail_type": mail_type,
                    "next_trainer_followup_at": utc_now(),
                }},
            )
        return {
            **result,
            "next_trainer_id": trainer_id,
            "next_trainer_name": trainer_name,
            "declined_trainer_id": declined_trainer_id,
        }

    await db["requirements"].update_one(
        {"requirement_id": requirement_id},
        {"$set": {
            "next_trainer_followup_status": "no_available_trainer",
            "next_trainer_followup_checked_at": utc_now(),
        }},
    )
    return {"skipped": True, "reason": "No available next trainer"}


async def _match_client_decision_candidate(db, meta: dict, clean_body: str) -> tuple[Optional[dict], Optional[dict], dict]:
    from_email = (meta.get("from_email") or "").strip()
    text = _re.sub(r"\s+", " ", f"{meta.get('subject') or ''} {clean_body or meta.get('snippet') or ''}".lower())
    domain = sender_domain(from_email)

    requirement_query = {"$or": []}
    if from_email:
        requirement_query["$or"].append({"client_email": {"$regex": f"^{_re.escape(from_email)}$", "$options": "i"}})
    if domain:
        requirement_query["$or"].append({"client_email_domain": domain})
    requirements = []
    if requirement_query["$or"]:
        requirements = await db["requirements"].find(requirement_query, {"_id": 0}).sort("created_at", -1).limit(25).to_list(25)

    requirement_by_id = {req.get("requirement_id"): req for req in requirements if req.get("requirement_id")}
    requirement_ids = list(requirement_by_id.keys())
    if not requirement_ids and from_email:
        slot_docs = await db["client_slot_emails"].find(
            {"to_email": {"$regex": f"^{_re.escape(from_email)}$", "$options": "i"}},
            {"_id": 0, "requirement_id": 1},
        ).sort("sent_at", -1).limit(25).to_list(25)
        requirement_ids = sorted({item.get("requirement_id") for item in slot_docs if item.get("requirement_id")})
        if requirement_ids:
            requirements = await db["requirements"].find(
                {"requirement_id": {"$in": requirement_ids}},
                {"_id": 0},
            ).to_list(25)
            requirement_by_id = {req.get("requirement_id"): req for req in requirements if req.get("requirement_id")}

    if not requirement_ids:
        return None, None, {"reason": "no requirement matched client email"}

    logs = await db["email_logs"].find(
        {
            "requirement_id": {"$in": requirement_ids},
            "mail_type": "mail4",
            "status": "sent",
            "interview_scheduled": True,
        },
        {"_id": 0},
    ).sort("sent_at", -1).limit(50).to_list(50)

    if not logs:
        slot_logs = await db["client_slot_emails"].find(
            {
                "requirement_id": {"$in": requirement_ids},
                "to_email": {"$regex": f"^{_re.escape(from_email)}$", "$options": "i"} if from_email else {"$exists": True},
            },
            {"_id": 0},
        ).sort("sent_at", -1).limit(50).to_list(50)
        logs = [
            {
                **item,
                "mail_type": "client_slot_options",
                "status": item.get("status") or "sent",
                "sent_at": item.get("sent_at") or item.get("created_at"),
                "to_email": item.get("trainer_email") or "",
                "trainer_name": item.get("trainer_name"),
                "source": "client_slot_decision_fallback",
            }
            for item in slot_logs
            if item.get("trainer_id") and item.get("requirement_id")
        ]

    if not logs:
        selected_trainer_id = next(
            (req.get("selected_trainer_id") for req in requirements if req.get("selected_trainer_id")),
            "",
        )
        if selected_trainer_id:
            selected_req = next(
                (req for req in requirements if str(req.get("selected_trainer_id") or "") == str(selected_trainer_id)),
                requirements[0] if requirements else {},
            )
            selected_trainer = await db["trainers"].find_one({"trainer_id": selected_trainer_id}, {"_id": 0}) or {
                "trainer_id": selected_trainer_id,
                "name": selected_req.get("selected_trainer_name"),
            }
            return selected_trainer, selected_req, {
                "score": 120,
                "selected_requirement_fallback": True,
            }
        return None, None, {"reason": "no scheduled interview or client slot mail found", "requirement_ids": requirement_ids}

    trainer_ids = [log.get("trainer_id") for log in logs if log.get("trainer_id")]
    trainers = await db["trainers"].find(
        {"trainer_id": {"$in": trainer_ids}},
        {"_id": 0},
    ).to_list(len(trainer_ids) or 1)
    trainer_by_id = {trainer.get("trainer_id"): trainer for trainer in trainers}

    scored = []
    for log in logs:
        requirement = requirement_by_id.get(log.get("requirement_id")) or {}
        trainer = trainer_by_id.get(log.get("trainer_id")) or {
            "trainer_id": log.get("trainer_id"),
            "name": log.get("trainer_name"),
            "email": log.get("to_email"),
            "phone": log.get("trainer_phone", ""),
        }
        trainer_name = str(trainer.get("name") or log.get("trainer_name") or "").strip().lower()
        trainer_parts = [part for part in _re.split(r"\s+", trainer_name) if len(part) > 2]
        requirement_id = str(log.get("requirement_id") or "").lower()
        technology = str(requirement.get("technology_needed") or log.get("technology") or "").lower()
        score = 0
        if trainer_name and trainer_name in text:
            score += 260
        elif trainer_parts and any(part in text for part in trainer_parts):
            score += 90
        if requirement_id and requirement_id in text:
            score += 120
        if technology and technology in text:
            score += 45
        if _re.search(r"\b(trainer|candidate|profile|interview|discussion)\b", text):
            score += 30
        sent_at = log.get("sent_at")
        if _recent_enough(sent_at, meta.get("received_at") or utc_now(), days=30):
            score += 35
        scored.append((score, log, trainer, requirement))

    if not scored:
        return None, None, {"reason": "no scored candidates"}
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_log, best_trainer, best_requirement = scored[0]
    viable_pairs = {
        (item[1].get("trainer_id"), item[1].get("requirement_id"))
        for item in scored
        if item[0] >= 50 and item[1].get("trainer_id") and item[1].get("requirement_id")
    }
    if len(viable_pairs) == 1 and best_score >= 50:
        if not best_trainer.get("email"):
            best_trainer["email"] = best_log.get("to_email")
        if not best_trainer.get("phone"):
            best_trainer["phone"] = best_log.get("trainer_phone", "")
        return best_trainer, best_requirement, {
            "score": best_score,
            "matched_email_id": best_log.get("email_id"),
            "single_candidate_group": True,
        }
    if (
        best_score >= 50
        and _recent_enough(best_log.get("sent_at"), meta.get("received_at") or utc_now(), days=7)
        and _re.search(r"\b(candidate|he|she|trainer|profile)\s+(?:has\s+been\s+|is\s+)?selected\b|\bselected\s+for\s+the\s+training\b", text)
    ):
        if not best_trainer.get("email"):
            best_trainer["email"] = best_log.get("to_email")
        if not best_trainer.get("phone"):
            best_trainer["phone"] = best_log.get("trainer_phone", "")
        return best_trainer, best_requirement, {
            "score": best_score,
            "matched_email_id": best_log.get("email_id"),
            "latest_recent_candidate_fallback": True,
            "viable_candidate_count": len(viable_pairs),
        }
    if best_score < 100 and len(logs) != 1:
        return None, None, {"reason": "ambiguous trainer decision", "score": best_score}
    if best_score < 70 and len(logs) == 1:
        return None, None, {"reason": "low confidence trainer decision", "score": best_score}
    if not best_trainer.get("email"):
        best_trainer["email"] = best_log.get("to_email")
    if not best_trainer.get("phone"):
        best_trainer["phone"] = best_log.get("trainer_phone", "")
    return best_trainer, best_requirement, {"score": best_score, "matched_email_id": best_log.get("email_id")}


async def _process_client_interview_decision(db, meta: dict, request: Optional[Request] = None) -> Optional[dict]:
    message_id = meta.get("email_id") or meta.get("gmail_message_id")
    if not message_id:
        return None
    existing = await db["post_interview_decisions"].find_one({"gmail_message_id": message_id}, {"_id": 0})
    if existing and existing.get("status") not in {"needs_manual_review", "trainer_decision_email_failed"}:
        return {"status": "already_processed_client_decision", **existing}

    clean_body = _strip_quoted_reply_text(meta.get("clean_body") or meta.get("raw_body") or meta.get("snippet") or "")
    decision = _detect_client_interview_decision(meta.get("subject", ""), clean_body)
    if not decision.get("decision"):
        return None

    trainer, requirement, match = await _match_client_decision_candidate(db, meta, clean_body)
    now = utc_now()
    decision_id = existing.get("decision_id") if existing else f"DECISION-{uuid.uuid4().hex[:8].upper()}"
    if not trainer or not requirement:
        doc = {
            "decision_id": decision_id,
            "gmail_message_id": message_id,
            "status": "needs_manual_review",
            "decision": decision,
            "match": match,
            "client_email": meta.get("from_email"),
            "subject": meta.get("subject"),
            "reply_text": clean_body,
            "updated_at": now,
        }
        await db["post_interview_decisions"].update_one(
            {"gmail_message_id": message_id},
            {"$set": doc, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        return {k: v for k, v in doc.items() if k != "_id"}

    prior_decision = await db["post_interview_decisions"].find_one(
        {
            "requirement_id": requirement.get("requirement_id"),
            "trainer_id": trainer.get("trainer_id"),
            "decision.decision": decision["decision"],
            "status": {"$in": ["trainer_selected_auto_sent", "trainer_rejected_auto_sent"]},
            "gmail_message_id": {"$ne": message_id},
        },
        {"_id": 0},
        sort=[("updated_at", -1), ("created_at", -1)],
    )
    if prior_decision:
        doc = {
            "decision_id": decision_id,
            "gmail_message_id": message_id,
            "status": "already_processed_client_decision_for_trainer",
            "decision": decision,
            "match": {**(match or {}), "prior_decision_id": prior_decision.get("decision_id")},
            "requirement_id": requirement.get("requirement_id"),
            "trainer_id": trainer.get("trainer_id"),
            "trainer_name": trainer.get("name") or trainer.get("trainer_name"),
            "trainer_email": trainer.get("email") or trainer.get("trainer_email"),
            "client_email": meta.get("from_email"),
            "client_name": meta.get("from_name"),
            "subject": meta.get("subject"),
            "reply_text": clean_body,
            "sent_results": prior_decision.get("sent_results") or [],
            "updated_at": now,
        }
        await db["post_interview_decisions"].update_one(
            {"gmail_message_id": message_id},
            {"$set": doc, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        return {k: v for k, v in doc.items() if k != "_id"}

    client_note = _client_note_excerpt(clean_body)
    sent_results = []
    for template in _decision_mail_templates(trainer, requirement, decision["decision"], client_note):
        sent = await _send_trainer_pipeline_email(
            db,
            request,
            trainer=trainer,
            requirement=requirement,
            subject=template["subject"],
            body=template["body"],
            mail_type=template["mail_type"],
            source="client_post_interview_decision",
        )
        sent_results.append(sent)
        if decision["decision"] != "selected":
            break
    if decision["decision"] == "selected" and sent_results and sent_results[0].get("success"):
        toc_result = await _auto_generate_and_send_toc(
            db,
            request,
            trainer=trainer,
            requirement=requirement,
            source="client_post_interview_decision",
        )
        sent_results.append(toc_result)
        if toc_result.get("success") and request:
            try:
                po_request_result = await request_client_purchase_order(
                    requirement.get("requirement_id"),
                    {
                        "trainer_id": trainer.get("trainer_id"),
                        "trainer_name": trainer.get("name") or trainer.get("trainer_name"),
                        "client_email": requirement.get("client_email"),
                        "client_name": requirement.get("client_name") or requirement.get("client_company") or "",
                    },
                    request,
                )
                sent_results.append({
                    "success": True,
                    "mail_type": "client_po_request",
                    "email_id": po_request_result.get("email_id"),
                    "to_email": po_request_result.get("to_email"),
                })
            except HTTPException as exc:
                sent_results.append({"success": False, "mail_type": "client_po_request", "error": exc.detail})
            except Exception as exc:
                sent_results.append({"success": False, "mail_type": "client_po_request", "error": str(exc)})

    final_status = "trainer_selected_auto_sent" if decision["decision"] == "selected" else "trainer_rejected_auto_sent"
    if not all(item.get("success") for item in sent_results):
        final_status = "trainer_decision_email_failed"
    doc = {
        "decision_id": decision_id,
        "gmail_message_id": message_id,
        "status": final_status,
        "decision": decision,
        "match": match,
        "requirement_id": requirement.get("requirement_id"),
        "trainer_id": trainer.get("trainer_id"),
        "trainer_name": trainer.get("name") or trainer.get("trainer_name"),
        "trainer_email": trainer.get("email") or trainer.get("trainer_email"),
        "client_email": meta.get("from_email"),
        "client_name": meta.get("from_name"),
        "subject": meta.get("subject"),
        "reply_text": clean_body,
        "sent_results": sent_results,
        "updated_at": now,
    }
    await db["post_interview_decisions"].update_one(
        {"gmail_message_id": message_id},
        {"$set": doc, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return {k: v for k, v in doc.items() if k != "_id"}


@router.post("/assistant/chat")
async def assistant_chat(payload: dict):
    system_prompt = str(payload.get("system") or "").strip()
    messages = _normalise_chat_messages(payload.get("messages") or [])
    if not messages:
        raise HTTPException(400, "Send at least one user message")

    settings = get_settings()
    api_key = (os.getenv("GEMINI_API_KEY", "") or getattr(settings, "gemini_api_key", "")).strip()
    if not api_key:
        raise HTTPException(503, "GEMINI_API_KEY is not configured on the backend")
    model = (os.getenv("GEMINI_MODEL", "") or getattr(settings, "gemini_model", "") or "gemini-2.0-flash").strip()

    try:
        import httpx as _httpx
        full_prompt = (system_prompt + "\n\n") if system_prompt else ""
        for m in messages:
            role = "User" if m["role"] == "user" else "Assistant"
            full_prompt += f"{role}: {m['content']}\n"
        full_prompt += "Assistant:"
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        async with _httpx.AsyncClient(timeout=30) as http_client:
            res = await http_client.post(gemini_url, json={
                "contents": [{"parts": [{"text": full_prompt}]}],
                "generationConfig": {"temperature": 0.5, "maxOutputTokens": 1000},
            })
            res.raise_for_status()
            data = res.json()
        reply = (data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")).strip()
        try:
            db = get_db()
            rates = await _dashboard_cost_rates(db)
            input_tokens = max(1, int(len(full_prompt) / 4))
            output_tokens = max(1, int(len(reply) / 4))
            cost_inr = (
                (input_tokens / 1000) * rates["gemini_input_1k_tokens"]
                + (output_tokens / 1000) * rates["gemini_output_1k_tokens"]
            )
            await db["ai_usage_logs"].insert_one({
                "usage_id": f"AI-{uuid.uuid4().hex[:10].upper()}",
                "provider": "gemini",
                "model": model,
                "feature": payload.get("feature") or "assistant_chat",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_inr": _money(cost_inr),
                "metadata": payload.get("metadata") or {},
                "created_at": utc_now(),
            })
        except Exception as log_exc:
            logger.warning("AI usage log failed: %s", log_exc)
        return {"reply": reply or "I could not generate a response.", "provider": "gemini", "model": model}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Assistant request failed: {exc}") from exc


def _parse_domain_csv(value: str) -> List[str]:
    return [item.strip().lower() for item in (value or "").split(",") if item.strip()]


async def _client_inbox_settings(db) -> dict:
    settings_doc = await db["admin_settings"].find_one(
        {"settings_id": "default"},
        {"_id": 0, "clientInboxCfg": 1, "twilioCfg": 1},
    )
    cfg = (settings_doc or {}).get("clientInboxCfg") or {}
    twilio = (settings_doc or {}).get("twilioCfg") or {}
    return {
        "autoSendEnabled": bool(cfg.get("autoSendEnabled", True)),
        "autoSendThreshold": float(cfg.get("autoSendThreshold", 70)),
        "clientDomainsWhitelist": cfg.get("clientDomainsWhitelist", ""),
        "replySignature": cfg.get("replySignature") or "Best Regards,\nRecruitment Team\nClahan Technologies",
        "vendorWhatsAppNumber": cfg.get("vendorWhatsAppNumber") or twilio.get("vendorWhatsAppNumber", ""),
        "inboxProvider": str(cfg.get("inboxProvider") or "gmail_api").strip().lower(),
    }


async def _known_client_domain(db, email_address: str) -> bool:
    domain = sender_domain(email_address)
    if not domain:
        return False
    existing = await db["requirements"].find_one(
        {"client_email_domain": domain},
        {"_id": 1},
    )
    if existing:
        return True
    existing = await db["client_emails"].find_one(
        {"from_email": {"$regex": f"@{_re.escape(domain)}$", "$options": "i"}},
        {"_id": 1},
    )
    return bool(existing)


def _decode_pubsub_payload(payload: dict) -> dict:
    data = ((payload.get("message") or {}).get("data") or "").strip()
    if not data:
        return {}
    padded = data + "=" * (-len(data) % 4)
    decoded = _base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
    return _json.loads(decoded)


def _public_doc(doc: dict) -> dict:
    clean = {k: v for k, v in (doc or {}).items() if k != "_id"}
    return clean


def _tier_value(tier: str) -> str:
    return tier.value if isinstance(tier, ContactVerificationTier) else str(tier or ContactVerificationTier.UNKNOWN.value)


def _linkedin_contact_display_class(tier: str) -> str:
    mapping = {
        ContactVerificationTier.RESUME_VERIFIED.value: "bg-emerald-50 text-emerald-700 border-emerald-200",
        ContactVerificationTier.AI_EXTRACTED.value: "bg-blue-50 text-blue-700 border-blue-200",
        ContactVerificationTier.LOCAL_FALLBACK.value: "bg-violet-50 text-violet-700 border-violet-200",
        ContactVerificationTier.LINKEDIN_SIGNAL.value: "bg-amber-50 text-amber-700 border-amber-200",
        ContactVerificationTier.MANUAL_ENTRY.value: "bg-teal-50 text-teal-700 border-teal-200",
        ContactVerificationTier.UNKNOWN.value: "bg-slate-50 text-slate-500 border-slate-200",
    }
    return mapping.get(_tier_value(tier), mapping[ContactVerificationTier.UNKNOWN.value])


def _linkedin_tier_label(tier: str) -> str:
    labels = {
        ContactVerificationTier.RESUME_VERIFIED.value: "Resume verified",
        ContactVerificationTier.AI_EXTRACTED.value: "AI verified",
        ContactVerificationTier.LOCAL_FALLBACK.value: "Extracted",
        ContactVerificationTier.LINKEDIN_SIGNAL.value: "Unverified",
        ContactVerificationTier.MANUAL_ENTRY.value: "Manual entry",
        ContactVerificationTier.UNKNOWN.value: "Unknown",
    }
    return labels.get(_tier_value(tier), "Unknown")


def _stamp_linkedin_signal_on_enriched(update_fields: dict, email: str = "", phone: str = "", name: str = "", linkedin: str = "", location: str = "") -> dict:
    contact_trust = {}
    values = {
        "email": email,
        "phone": phone,
        "name": name,
        "linkedin": linkedin,
        "location": location,
    }
    for field, value in values.items():
        clean_value = str(value or "").strip()
        if not clean_value:
            continue
        contact_trust[field] = {
            "tier": ContactVerificationTier.LINKEDIN_SIGNAL.value,
            "weight": TIER_WEIGHT[ContactVerificationTier.LINKEDIN_SIGNAL.value],
            "value": clean_value,
        }
    if contact_trust:
        existing = dict(update_fields.get("contact_trust") or {})
        existing.update(contact_trust)
        update_fields["contact_trust"] = existing
    update_fields["verification_tier"] = ContactVerificationTier.LINKEDIN_SIGNAL.value
    update_fields.setdefault("email_source", "linkedin_public_web_scan")
    return update_fields


def _enrich_lead_response(lead: dict) -> dict:
    lead = _public_doc(lead)
    contact_trust = lead.get("contact_trust") or {}
    tier = _tier_value(lead.get("verification_tier") or ContactVerificationTier.UNKNOWN.value)
    email_tier = _tier_value((contact_trust.get("email") or {}).get("tier") or ContactVerificationTier.UNKNOWN.value)
    phone_tier = _tier_value((contact_trust.get("phone") or {}).get("tier") or ContactVerificationTier.UNKNOWN.value)
    verified_tiers = {
        ContactVerificationTier.RESUME_VERIFIED.value,
        ContactVerificationTier.AI_EXTRACTED.value,
        ContactVerificationTier.MANUAL_ENTRY.value,
    }
    lead["ui_trust"] = {
        "overall_class": _linkedin_contact_display_class(tier),
        "email_class": _linkedin_contact_display_class(email_tier),
        "phone_class": _linkedin_contact_display_class(phone_tier),
        "email_verified": email_tier in verified_tiers,
        "phone_verified": phone_tier in verified_tiers,
        "show_verify_badge": tier == ContactVerificationTier.LINKEDIN_SIGNAL.value,
        "show_resume_request": tier == ContactVerificationTier.LINKEDIN_SIGNAL.value and bool(lead.get("contact_email")),
        "tier_label": _linkedin_tier_label(tier),
    }
    return lead


async def _is_duplicate_linkedin_lead(db, source_url: str, contact_email: str = "", trainer_name: str = "") -> Optional[str]:
    if source_url:
        existing = await db["trainer_profile_leads"].find_one(
            {"source_url": source_url},
            {"_id": 0, "lead_id": 1},
        )
        if existing:
            return existing.get("lead_id")
    email = str(contact_email or "").strip().lower()
    if email and "@" in email:
        existing = await db["trainer_profile_leads"].find_one(
            {
                "contact_email": {"$regex": f"^{_re.escape(email)}$", "$options": "i"},
                "status": {"$nin": ["rejected"]},
            },
            {"_id": 0, "lead_id": 1},
        )
        if existing:
            return existing.get("lead_id")
    return None


async def _save_linkedin_lead_as_trainer(db, lead: dict) -> dict:
    existing = await find_matching_trainer_for_lead(db, lead)
    now = utc_now()
    if existing:
        trainer_id = existing["trainer_id"]
        merged = merge_linkedin_with_resume_profile(existing, lead)
        update_doc = {
            "linkedin": merged.get("linkedin") or existing.get("linkedin", ""),
            "contact_trust": merged.get("contact_trust") or existing.get("contact_trust") or {},
            "verification_tier": merged.get("verification_tier") or existing.get("verification_tier") or ContactVerificationTier.UNKNOWN.value,
            "lead_id": lead.get("lead_id") or existing.get("lead_id") or "",
            "linkedin_lead_verified": True,
            "linkedin_unverified": False,
            "confidence_score": merged.get("confidence_score", existing.get("confidence_score", 0)),
            "updated_at": now,
        }
        for field in ("email", "phone"):
            if not existing.get(field) and merged.get(field):
                update_doc[field] = merged[field]
        await db["trainers"].update_one({"trainer_id": trainer_id}, {"$set": update_doc})
        await db["trainer_profile_leads"].update_one(
            {"lead_id": lead.get("lead_id")},
            {"$set": {
                "verification_status": "linked_to_trainer",
                "verified_trainer_id": trainer_id,
                "linkedin_lead_verified": True,
                "updated_at": now,
            }},
        )
        return {"saved": True, "action": "merged", "trainer_id": trainer_id}

    profile = linkedin_lead_to_unverified_profile(lead)
    doc = trainer_document_from_profile(profile)
    doc["source"] = "linkedin_lead"
    doc["source_sheet"] = "linkedin_search"
    doc["created_at"] = now
    await db["trainers"].insert_one(doc)
    await db["trainer_profile_leads"].update_one(
        {"lead_id": lead.get("lead_id")},
        {"$set": {
            "verification_status": "placeholder_created",
            "verified_trainer_id": doc["trainer_id"],
            "updated_at": now,
        }},
    )
    return {"saved": True, "action": "inserted", "trainer_id": doc["trainer_id"]}


async def _auto_verify_lead_on_resume_upload(db, resume_profile: dict) -> Optional[dict]:
    email = str(resume_profile.get("email") or "").strip().lower()
    name_key = _re.sub(r"[^a-z0-9]+", "", str(resume_profile.get("name") or "").lower())
    lead = None
    if email and "@" in email:
        lead = await db["trainer_profile_leads"].find_one(
            {
                "contact_email": {"$regex": f"^{_re.escape(email)}$", "$options": "i"},
                "verification_status": {"$nin": ["rejected"]},
            },
            {"_id": 0},
            sort=[("created_at", -1)],
        )
    if not lead and name_key and len(name_key) >= 4:
        domain = str(resume_profile.get("technology_category") or resume_profile.get("domain") or "").strip()
        query = {"verification_status": {"$nin": ["rejected"]}}
        if domain:
            pattern = {"$regex": _re.escape(domain), "$options": "i"}
            query["$or"] = [{"domain": pattern}, {"searched_domain": pattern}]
        candidates = await db["trainer_profile_leads"].find(query, {"_id": 0}).sort("created_at", -1).limit(50).to_list(50)
        for candidate in candidates:
            candidate_name = _re.sub(
                r"[^a-z0-9]+",
                "",
                str(candidate.get("trainer_name") or candidate.get("headline") or "").lower(),
            )
            if candidate_name and (name_key in candidate_name or candidate_name in name_key):
                lead = candidate
                break
    if not lead:
        return None

    now = utc_now()
    trainer_id = resume_profile.get("trainer_id") or ""
    await db["trainer_profile_leads"].update_one(
        {"lead_id": lead["lead_id"]},
        {"$set": {
            "verification_status": "resume_verified",
            "verified_trainer_id": trainer_id,
            "resume_verified_at": now,
            "linkedin_lead_verified": True,
            "verified_contact_email": resume_profile.get("email") or "",
            "updated_at": now,
        }},
    )

    placeholder_id = lead.get("verified_trainer_id")
    if placeholder_id:
        placeholder = await db["trainers"].find_one(
            {"trainer_id": placeholder_id, "linkedin_unverified": True},
            {"_id": 0},
        )
        if placeholder:
            merged = merge_linkedin_with_resume_profile(resume_profile, lead)
            doc = trainer_document_from_profile({**merged, "trainer_id": placeholder_id})
            doc["linkedin_unverified"] = False
            doc["needs_review"] = False
            doc["updated_at"] = now
            await db["trainers"].update_one(
                {"trainer_id": placeholder_id},
                {"$set": {k: v for k, v in doc.items() if k not in {"_id", "created_at"}}},
            )
    return lead


def _thread_datetime(value):
    if not value:
        return datetime.min
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
        except Exception:
            return datetime.min
    if hasattr(value, "tzinfo") and value.tzinfo is not None:
        return value.replace(tzinfo=None)
    return value


def _message_sort_key(message: dict) -> tuple:
    return (
        _thread_datetime(message.get("sort_at") or message.get("sent_at")),
        int(message.get("sort_order") or 50),
        str(message.get("message_id") or ""),
    )


def _client_conversation_key(doc: dict, requirement: dict = None) -> str:
    requirement = requirement or {}
    requirement_id = doc.get("requirement_id") or requirement.get("requirement_id") or ""
    if requirement_id:
        return f"req:{requirement_id}"
    thread_id = doc.get("thread_id") or ""
    if thread_id:
        return f"thread:{thread_id}"
    extracted = doc.get("extracted") or {}
    technology = extracted.get("technology_needed") or requirement.get("technology_needed") or "general"
    email = (doc.get("from_email") or doc.get("to_email") or extracted.get("client_email") or "client").lower()
    return f"client:{email}|domain:{str(technology).strip().lower() or 'general'}"


def _client_conversation_meta(doc: dict, requirement: dict = None) -> dict:
    requirement = requirement or {}
    extracted = doc.get("extracted") or {}
    client_email = doc.get("from_email") or doc.get("to_email") or requirement.get("client_email") or extracted.get("client_email") or ""
    client_name = (
        doc.get("from_name")
        or doc.get("client_name")
        or requirement.get("client_name")
        or extracted.get("client_name")
        or requirement.get("client_company")
        or extracted.get("client_company")
        or client_email
        or "Client"
    )
    company = requirement.get("client_company") or extracted.get("client_company") or sender_domain(client_email)
    technology = requirement.get("technology_needed") or extracted.get("technology_needed") or doc.get("technology") or "Training"
    return {
        "client_name": client_name,
        "client_email": client_email,
        "client_company": company,
        "domain": technology,
        "requirement_id": doc.get("requirement_id") or requirement.get("requirement_id") or "",
        "thread_id": doc.get("thread_id") or "",
        "status": doc.get("status") or requirement.get("status") or "",
    }


def _gmail_metadata(gmail_service, message_id: str) -> dict:
    msg = gmail_service.users().messages().get(
        userId="me",
        id=message_id,
        format="metadata",
        metadataHeaders=["From", "Reply-To", "Subject", "Message-ID"],
    ).execute()
    headers = {h.get("name", "").lower(): h.get("value", "") for h in (msg.get("payload") or {}).get("headers", [])}
    from_name, from_email = _parseaddr(headers.get("reply-to") or headers.get("from", ""))
    received_at = None
    if msg.get("internalDate"):
        try:
            received_at = utc_from_timestamp(int(msg["internalDate"]) / 1000)
        except Exception:
            received_at = None
    return {
        "email_id": message_id,
        "thread_id": msg.get("threadId"),
        "received_at": received_at or utc_now(),
        "from_name": from_name,
        "from_email": from_email,
        "subject": headers.get("subject", ""),
        "message_id_header": headers.get("message-id", ""),
        "snippet": msg.get("snippet", ""),
    }


async def _notify_vendor_about_client_email(db, inbox_doc: dict, request: Optional[Request] = None) -> bool:
    cfg = await _client_inbox_settings(db)
    vendor_number = cfg.get("vendorWhatsAppNumber", "")
    if not vendor_number:
        return False
    extracted = inbox_doc.get("extracted") or {}
    reply = inbox_doc.get("generated_reply") or {}
    message = (
        "New client training inquiry\n"
        f"From: {inbox_doc.get('from_name') or inbox_doc.get('from_email')}\n"
        f"Technology: {extracted.get('technology_needed') or '-'}\n"
        f"Urgency: {extracted.get('urgency') or 'normal'}\n"
        f"Confidence: {round(float(extracted.get('confidence') or 0) * 100)}%\n"
        f"Summary: {extracted.get('email_summary') or inbox_doc.get('subject') or ''}\n\n"
        f"Draft: {reply.get('whatsapp_message') or ''}"
    )
    result = await send_whatsapp_message(
        db,
        vendor_number,
        message[:1500],
        event_type="client_requirement_inbox",
        recipient_type="vendor",
        request_base_url=_request_base_url(request) if request else "",
        context={
            "source": "client_inbox",
            "email_id": inbox_doc.get("email_id"),
            "requirement_id": inbox_doc.get("requirement_id"),
        },
    )
    return bool(result.get("success"))


async def _save_post_interview_decision_email(db, meta: dict, decision_result: dict) -> None:
    now = utc_now()
    decision = decision_result.get("decision") or {}
    await db["client_emails"].update_one(
        {"email_id": meta.get("email_id")},
        {
            "$set": {
                "requirement_id": decision_result.get("requirement_id"),
                "status": decision_result.get("status") or "post_interview_decision",
                "confidence": decision.get("confidence", 0),
                "auto_send_eligible": False,
                "sent_at": now if "auto_sent" in str(decision_result.get("status") or "") else None,
                "sent_by": "auto" if "auto_sent" in str(decision_result.get("status") or "") else None,
                "post_interview_decision": decision_result,
                "extracted.is_training_request": False,
                "extracted.post_interview_decision": True,
                "extracted.decision": decision,
                "updated_at": now,
            },
            "$setOnInsert": {
                "email_id": meta.get("email_id"),
                "thread_id": meta.get("thread_id"),
                "received_at": meta.get("received_at"),
                "from_email": meta.get("from_email"),
                "from_name": meta.get("from_name"),
                "subject": meta.get("subject"),
                "raw_body": meta.get("raw_body"),
                "clean_body": meta.get("clean_body"),
                "generated_reply": {},
                "whatsapp_notified": False,
                "message_id_header": meta.get("message_id_header", ""),
                "created_at": now,
            },
        },
        upsert=True,
    )


async def _process_and_store_client_decision_message(
    db,
    message_id: str,
    gmail_service,
    request: Optional[Request] = None,
    meta_hint: Optional[dict] = None,
) -> Optional[dict]:
    full_meta = fetch_gmail_email(message_id, gmail_service)
    if meta_hint:
        full_meta = {**meta_hint, **full_meta}
    decision_result = await _process_client_interview_decision(db, full_meta, request)
    if not decision_result:
        return None
    await _save_post_interview_decision_email(db, full_meta, decision_result)
    return decision_result


def _extract_client_po_details(subject: str = "", body: str = "") -> Optional[dict]:
    text = f"{subject or ''}\n{body or ''}"
    clean = _re.sub(r"\s+", " ", text).strip()
    lower = clean.lower()
    if _re.search(r"\b(request\s+(?:for\s+)?purchase\s+order|request\s+you\s+to\s+kindly\s+issue|please\s+share\s+the\s+purchase\s+order|po\s+request\s+sent)\b", lower):
        return None
    if not _re.search(r"\b(purchase\s*order|po\s*(?:no|number|#|ref|reference)?|client\s*po)\b", lower):
        return None
    if not _re.search(r"\b(invoice|amount|total|gst|purchase\s*order|po\s*(?:no|number|#|ref|reference))\b", lower):
        return None

    po_number = ""
    for pattern in [
        r"\b(PO[-/_]?[A-Z0-9][A-Z0-9/_\-]{2,})\b",
        r"\bpurchase\s*order\s*#\s*[:\-]?\s*([A-Z0-9][A-Z0-9/_\-]{2,})",
        r"(?<![A-Z0-9/_\-])(?:po|client\s*po)\s*(?:number|no|#|ref|reference)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/_\-]{2,})",
    ]:
        match = _re.search(pattern, clean, flags=_re.IGNORECASE)
        if match:
            po_number = match.group(1).strip(" .,:;")
            break

    def amount_from(pattern: str) -> float:
        match = _re.search(pattern, clean, flags=_re.IGNORECASE)
        if match:
            try:
                return float(match.group(1).replace(",", ""))
            except Exception:
                return 0.0
        return 0.0

    subtotal_amount = amount_from(r"(?:sub\s*total|subtotal)\s*(?:in\s*)?(?:inr|rs\.?|₹)?\s*[:\-]?\s*([0-9][0-9,]*(?:\.\d{1,2})?)")
    total_amount = amount_from(r"(?:grand\s*total|total\s*amount|po\s*amount|total)\s*(?:in\s*)?(?:inr|rs\.?|₹)?\s*[:\-]?\s*([0-9][0-9,]*(?:\.\d{1,2})?)")
    currency_amount = amount_from(r"(?:inr|rs\.?|₹)\s*([0-9][0-9,]*(?:\.\d{1,2})?)")

    gst_rate = 0.0
    gst_match = _re.search(r"\b(?:gst|igst|cgst|sgst)\s*(?:rate)?\s*(?:\([^)]*\))?\s*[:\-]?\s*(\d{1,2}(?:\.\d+)?)\s*%", clean, flags=_re.IGNORECASE)
    if gst_match:
        gst_rate = _float_or_zero(gst_match.group(1))
    elif _re.search(r"\b(?:igst|cgst|sgst)\b", clean, flags=_re.IGNORECASE):
        gst_rate = 18.0

    amount = subtotal_amount if gst_rate > 0 and subtotal_amount > 0 else total_amount or currency_amount or subtotal_amount
    if not po_number or amount <= 0:
        return None

    gstin = ""
    gstin_match = _re.search(r"\b([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z])\b", clean, flags=_re.IGNORECASE)
    if gstin_match:
        gstin = gstin_match.group(1).upper()

    po_date = ""
    date_match = _re.search(r"\b(?:date|po\s*date)\s*[:#\-]?\s*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4}|[0-9]{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+[0-9]{4})", clean, flags=_re.IGNORECASE)
    if date_match:
        po_date = date_match.group(1).strip()

    payment_terms = ""
    terms_match = _re.search(r"\b(?:terms|payment\s*terms)\s*[:#\-]?\s*([A-Za-z0-9 ,./+-]{3,80}?)(?=\s+(?:ref|requestor|project|initiated\s+by|vendor|bill\s+to|$))", clean, flags=_re.IGNORECASE)
    if terms_match:
        payment_terms = terms_match.group(1).strip(" .,:;")

    ref_number = ""
    ref_match = _re.search(r"\b(?:reference|project\s*name|ref)\s*#?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/_\-]{2,})", clean, flags=_re.IGNORECASE)
    if ref_match:
        ref_number = ref_match.group(1).strip(" .,:;")

    start_date = ""
    end_date = ""
    range_match = _re.search(
        r"\b(?:start\s*date)\s*[:\-]?\s*([0-9]{1,2}\s*[/-]\s*[0-9]{1,2}(?:\s*[/-]\s*[0-9]{2,4})?).{0,80}?\b(?:end\s*date)\s*[:\-]?\s*([0-9]{1,2}\s*[/-]\s*[0-9]{1,2}(?:\s*[/-]\s*[0-9]{2,4})?)",
        clean,
        flags=_re.IGNORECASE,
    )
    if range_match:
        start_date = range_match.group(1).strip()
        end_date = range_match.group(2).strip()
    elif _re.search(r"\bstart\s*date\b.{0,30}\bend\s*date\b", clean, flags=_re.IGNORECASE):
        after_headers = _re.split(r"\bstart\s*date\b.{0,30}\bend\s*date\b", clean, flags=_re.IGNORECASE, maxsplit=1)
        date_candidates = _re.findall(r"\b[0-9]{1,2}\s*[/-]\s*[0-9]{1,2}(?:\s*[/-]\s*[0-9]{2,4})?\b", after_headers[-1] if after_headers else clean)
        if len(date_candidates) >= 2:
            start_date = _re.sub(r"\s+", "", date_candidates[0])
            end_date = _re.sub(r"\s+", "", date_candidates[1])

    hsn_sac = ""
    hsn_match = _re.search(r"\b(?:hsn|sac|hsn/sac)\s*(?:code)?\s*[:\-]?\s*([0-9]{4,8})\b", clean, flags=_re.IGNORECASE)
    if hsn_match:
        hsn_sac = hsn_match.group(1)
    elif _re.search(r"\bhsn\s*/?\s*sac\b", clean, flags=_re.IGNORECASE):
        generic_hsn = _re.search(r"\b(99[0-9]{4})\b", clean)
        if generic_hsn:
            hsn_sac = generic_hsn.group(1)

    return {
        "client_po_number": po_number,
        "client_po_date": po_date,
        "total_amount": amount,
        "gst_rate": gst_rate,
        "client_gstin": gstin,
        "payment_terms": payment_terms,
        "ref_number": ref_number,
        "start_date": start_date,
        "end_date": end_date,
        "hsn_sac": hsn_sac,
        "raw_text": clean[:4000],
        "confidence": 0.95,
    }


async def _match_client_po_requirement(db, meta: dict, po_details: dict) -> Optional[dict]:
    from_email = str(meta.get("from_email") or "").strip()
    if not from_email:
        return None
    text = _re.sub(r"\s+", " ", f"{meta.get('subject') or ''} {meta.get('clean_body') or meta.get('raw_body') or meta.get('snippet') or ''}".lower())
    candidates = await db["requirements"].find(
        {"client_email": {"$regex": f"^{_re.escape(from_email)}$", "$options": "i"}},
        {"_id": 0},
    ).sort("updated_at", -1).limit(30).to_list(30)
    if not candidates:
        domain = sender_domain(from_email)
        if domain:
            candidates = await db["requirements"].find(
                {"client_email_domain": domain},
                {"_id": 0},
            ).sort("updated_at", -1).limit(30).to_list(30)
    if not candidates:
        return None

    scored = []
    for req in candidates:
        po_was_requested = bool(req.get("po_requested_at") or req.get("po_request_status") == "requested")
        if not po_was_requested:
            continue
        req_id = str(req.get("requirement_id") or "").lower()
        tech = str(req.get("technology_needed") or "").lower()
        selected = bool(req.get("selected_trainer_id") or str(req.get("selection_status") or "").lower() in {"selected", "training_confirmed"})
        score = 0
        if req_id and req_id in text:
            score += 200
        if tech and tech in text:
            score += 60
        if selected:
            score += 80
        if req.get("po_requested_at") or req.get("po_request_status") == "requested":
            score += 50
        if req.get("invoice_id"):
            score -= 50
        scored.append((score, req))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1] if scored and scored[0][0] >= 50 else scored[0][1] if len(scored) == 1 else None


async def _process_client_purchase_order_email(db, processed: dict, request: Optional[Request] = None) -> Optional[dict]:
    po_details = _extract_client_po_details(
        processed.get("subject", ""),
        "\n\n".join([
            processed.get("clean_body") or processed.get("raw_body") or processed.get("snippet") or "",
            processed.get("attachments_text") or "",
        ]),
    )
    if not po_details:
        return None

    requirement = await _match_client_po_requirement(db, processed, po_details)
    if not requirement:
        return None
    if not (requirement.get("po_requested_at") or requirement.get("po_request_status") == "requested"):
        return None

    requirement_id = requirement.get("requirement_id")
    trainer_id = str(requirement.get("selected_trainer_id") or "").strip()
    client_email = str(requirement.get("client_email") or processed.get("from_email") or "").strip()
    now = utc_now()
    client_po_number = str(po_details.get("client_po_number") or "").strip()
    if not client_po_number:
        return None
    total_amount = _float_or_zero(po_details.get("total_amount"))
    if total_amount <= 0:
        return None

    existing_po = await db["client_purchase_orders"].find_one(
        {"requirement_id": requirement_id, "client_po_number": client_po_number},
        {"_id": 0},
    )
    if existing_po and existing_po.get("invoice_id") and str(existing_po.get("status") or "").lower() in {"invoice_generated", "invoice_sent"}:
        return {
            "status": "client_po_invoice_sent" if str(existing_po.get("status") or "").lower() == "invoice_sent" else "client_po_invoice_generated",
            "email_id": processed.get("email_id"),
            "requirement_id": requirement_id,
            "client_po_number": client_po_number,
            "invoice": {
                "invoice_id": existing_po.get("invoice_id"),
                "invoice_number": existing_po.get("invoice_number"),
            },
            "already_processed": True,
        }

    await db["client_purchase_orders"].update_one(
        {"requirement_id": requirement_id, "client_po_number": client_po_number},
        {"$set": {
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
            "trainer_name": requirement.get("selected_trainer_name") or "",
            "client_email": client_email,
            "client_name": requirement.get("client_name") or requirement.get("client_company") or processed.get("from_name") or client_email,
            "client_po_number": client_po_number,
            "client_po_date": po_details.get("client_po_date") or "",
            "client_gstin": po_details.get("client_gstin") or "",
            "total_amount": total_amount,
            "gst_rate": po_details.get("gst_rate") or 18,
            "payment_terms": po_details.get("payment_terms") or "",
            "ref_number": po_details.get("ref_number") or "",
            "start_date": po_details.get("start_date") or "",
            "end_date": po_details.get("end_date") or "",
            "hsn_sac": po_details.get("hsn_sac") or "",
            "status": "received",
            "source": "gmail_client_po",
            "source_email_id": processed.get("email_id"),
            "raw_text": po_details.get("raw_text") or "",
            "updated_at": now,
        }, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    await db["requirements"].update_one(
        {"requirement_id": requirement_id},
        {"$set": {
            "client_po_status": "received",
            "client_po_number": client_po_number,
            "client_po_received_at": now,
            "client_po_source_email_id": processed.get("email_id"),
        }},
    )

    invoice_result = None
    invoice_send_result = None
    training_confirmation_result = None
    if request and trainer_id and total_amount > 0:
        try:
            invoice_result = await generate_invoice_from_client_purchase_order(requirement_id, {
                "trainer_id": trainer_id,
                "client_email": client_email,
                "client_name": requirement.get("client_company") or requirement.get("client_name") or processed.get("from_name") or client_email,
                "client_po_number": client_po_number,
                "client_po_date": po_details.get("client_po_date") or "",
                "total_amount": total_amount,
                "gst_rate": po_details.get("gst_rate") or 18,
                "client_gstin": po_details.get("client_gstin") or "",
                "payment_terms": po_details.get("payment_terms") or "",
                "client_po_notes": "Generated automatically from client Gmail PO reply or attached PO PDF.",
                "ref_number": po_details.get("ref_number") or "",
                "start_date": po_details.get("start_date") or "",
                "end_date": po_details.get("end_date") or "",
                "hsn_sac": po_details.get("hsn_sac") or "",
                "technology": requirement.get("technology_needed") or "Training",
                "duration_days": requirement.get("duration_days") or "",
                "mode": requirement.get("mode") or "Online",
            }, request)
        except HTTPException as exc:
            invoice_result = {"success": False, "error": exc.detail}
        except Exception as exc:
            invoice_result = {"success": False, "error": str(exc)}
        if invoice_result and invoice_result.get("success") and (invoice_result.get("invoice") or {}).get("invoice_id"):
            try:
                invoice_send_result = await send_invoice(
                    (invoice_result.get("invoice") or {}).get("invoice_id"),
                    {"to_email": client_email},
                    request,
                )
            except HTTPException as exc:
                invoice_send_result = {"success": False, "error": exc.detail}
            except Exception as exc:
                invoice_send_result = {"success": False, "error": str(exc)}
        if invoice_send_result and invoice_send_result.get("success"):
            try:
                trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or {}
                training_confirmation_result = await _send_auto_training_confirmation(
                    db,
                    request,
                    trainer=trainer or {
                        "trainer_id": trainer_id,
                        "name": requirement.get("selected_trainer_name") or "",
                    },
                    requirement=requirement,
                    source="client_po_invoice_sent",
                )
            except HTTPException as exc:
                training_confirmation_result = {"success": False, "mail_type": "mail7_confirm", "error": exc.detail}
            except Exception as exc:
                training_confirmation_result = {"success": False, "mail_type": "mail7_confirm", "error": str(exc)}

    final_status = "client_po_received"
    if invoice_send_result and invoice_send_result.get("success"):
        final_status = "client_po_invoice_sent"
    elif invoice_result and invoice_result.get("success"):
        final_status = "client_po_invoice_generated"

    await db["client_emails"].update_one(
        {"email_id": processed.get("email_id")},
        {"$set": {
            "email_id": processed.get("email_id"),
            "thread_id": processed.get("thread_id"),
            "received_at": processed.get("received_at"),
            "from_email": processed.get("from_email"),
            "from_name": processed.get("from_name"),
            "subject": processed.get("subject"),
            "raw_body": processed.get("raw_body"),
            "clean_body": processed.get("clean_body"),
            "requirement_id": requirement_id,
            "status": final_status,
            "extracted": {
                "is_training_request": False,
                "client_purchase_order": True,
                "client_po_number": client_po_number,
                "total_amount": total_amount,
                "confidence": po_details.get("confidence"),
            },
            "generated_reply": {},
            "client_po": po_details,
            "invoice_result": invoice_result or {},
            "invoice_send_result": invoice_send_result or {},
            "training_confirmation_result": training_confirmation_result or {},
            "auto_send_eligible": False,
            "whatsapp_notified": False,
            "message_id_header": processed.get("message_id_header", ""),
            "updated_at": now,
        }, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return {
        "status": final_status,
        "email_id": processed.get("email_id"),
        "requirement_id": requirement_id,
        "client_po_number": client_po_number,
        "invoice": (invoice_result or {}).get("invoice") if invoice_result else None,
        "invoice_send": invoice_send_result or None,
        "training_confirmation": training_confirmation_result or None,
    }


async def _process_and_store_client_message(db, message_id: str, gmail_service, request: Optional[Request] = None) -> dict:
    settings = await _client_inbox_settings(db)
    processed = await process_client_email(message_id, gmail_service)
    existing = await db["client_emails"].find_one({"email_id": processed.get("email_id")}, {"_id": 1, "status": 1})
    if existing:
        return {"status": "already_processed", "email_id": processed.get("email_id")}

    trainer_thread = await find_matching_trainer_outbound_thread(
        db,
        processed.get("from_email", ""),
        processed.get("subject", ""),
        processed.get("clean_body") or processed.get("raw_body") or "",
    )
    if trainer_thread:
        inbox_doc = await record_trainer_reply_from_client_inbox(db, processed, trainer_thread)
        return {
            "status": "routed_to_trainer_reply",
            "email_id": inbox_doc.get("email_id"),
            "requirement_id": inbox_doc.get("requirement_id"),
            "trainer_id": inbox_doc.get("trainer_id"),
            "source_email_id": inbox_doc.get("trainer_reply_source_email_id"),
        }

    po_result = await _process_client_purchase_order_email(db, processed, request)
    if po_result:
        return po_result

    slot_doc = await _matching_client_slot_email(db, processed, processed.get("clean_body") or "")
    if slot_doc:
        slot_result = await _process_client_slot_reply_from_meta(
            db,
            processed.get("email_id") or message_id,
            request=request,
            meta_hint=processed,
            slot_doc=slot_doc,
        )
        if slot_result:
            return slot_result

    decision_result = await _process_client_interview_decision(db, processed, request)
    if decision_result:
        await _save_post_interview_decision_email(db, processed, decision_result)
        return decision_result

    extracted = processed.get("extracted") or {}
    extracted["sender_is_known_client"] = await _known_client_domain(db, processed.get("from_email", ""))

    domain = sender_domain(processed.get("from_email", ""))
    whitelist = set(_parse_domain_csv(settings.get("clientDomainsWhitelist", "")))
    domain_is_allowed = not whitelist or domain in whitelist

    duplicate_clarification = None
    if extracted.get("client_request_closed"):
        requirement_id = await mark_client_requirement_closed(
            db,
            from_email=processed.get("from_email", ""),
            requirement_id=processed.get("requirement_id") or "",
            reason=extracted.get("client_closed_reason") or extracted.get("email_summary") or "",
            email_id=processed.get("email_id") or message_id,
            subject=processed.get("subject", ""),
            body=processed.get("clean_body") or processed.get("raw_body") or "",
        )
        status = "client_closed_requirement"
        generated_reply = generate_client_requirement_closed_reply(
            processed,
            extracted.get("client_closed_reason") or extracted.get("email_summary") or "",
            settings.get("replySignature"),
        )
        auto_send_eligible = False
    elif processed.get("is_auto_reply") or not extracted.get("is_training_request"):
        status = "spam"
        generated_reply = {}
        requirement_id = None
    else:
        generated_reply = await generate_calhan_reply(extracted, {
            "subject": processed.get("subject", ""),
            "reply_signature": settings.get("replySignature"),
        })
        requirement_id = await ensure_requirement_from_email(extracted, message_id, db)
        confidence = float(extracted.get("confidence") or 0)
        auto_send_eligible = client_reply_auto_send_eligible(
            extracted,
            generated_reply,
            confidence,
            settings,
            domain_is_allowed,
        )
        duplicate_clarification = await find_existing_client_clarification_request(
            db,
            from_email=processed.get("from_email", ""),
            requirement_id=requirement_id or "",
            generated_reply=generated_reply,
            extracted=extracted,
            exclude_email_id=processed.get("email_id") or message_id,
        ) if auto_send_eligible else None
        if duplicate_clarification:
            auto_send_eligible = False
        status = "auto_sent" if auto_send_eligible and settings.get("autoSendEnabled") else "pending_approval"
        if duplicate_clarification:
            status = "auto_skipped_duplicate_clarification"

    confidence = float(extracted.get("confidence") or 0)
    if not duplicate_clarification:
        auto_send_eligible = client_reply_auto_send_eligible(
            extracted,
            generated_reply,
            confidence,
            settings,
            domain_is_allowed,
        )
    inbox_doc = {
        "email_id": processed.get("email_id"),
        "thread_id": processed.get("thread_id"),
        "received_at": processed.get("received_at"),
        "from_email": processed.get("from_email"),
        "from_name": processed.get("from_name"),
        "subject": processed.get("subject"),
        "raw_body": processed.get("raw_body"),
        "clean_body": processed.get("clean_body"),
        "extracted": extracted,
        "generated_reply": generated_reply,
        "requirement_id": requirement_id,
        "status": status,
        "confidence": confidence,
        "auto_send_eligible": auto_send_eligible,
        "sent_at": None,
        "sent_by": None,
        "duplicate_clarification_email_id": (duplicate_clarification or {}).get("email_id", ""),
        "duplicate_clarification_sent_at": (duplicate_clarification or {}).get("sent_at"),
        "whatsapp_notified": False,
        "message_id_header": processed.get("message_id_header", ""),
        "created_at": utc_now(),
    }

    inbox_doc["whatsapp_notified"] = await _notify_vendor_about_client_email(db, inbox_doc, request)

    if status == "auto_sent":
        send_result = send_gmail_reply(
            gmail_service,
            to_email=inbox_doc["from_email"],
            subject=generated_reply.get("subject", ""),
            body=generated_reply.get("body", ""),
            thread_id=inbox_doc.get("thread_id") or "",
            in_reply_to=inbox_doc.get("message_id_header") or "",
        )
        inbox_doc["gmail_send_result"] = send_result
        inbox_doc["sent_at"] = utc_now()
        inbox_doc["sent_by"] = "auto"
    elif extracted.get("client_request_closed") and settings.get("autoSendEnabled") and generated_reply.get("body"):
        try:
            send_result = send_gmail_reply(
                gmail_service,
                to_email=inbox_doc["from_email"],
                subject=generated_reply.get("subject", ""),
                body=generated_reply.get("body", ""),
                thread_id=inbox_doc.get("thread_id") or "",
                in_reply_to=inbox_doc.get("message_id_header") or "",
            )
            inbox_doc["gmail_send_result"] = send_result
            inbox_doc["sent_at"] = utc_now()
            inbox_doc["sent_by"] = "auto_client_closure_ack"
            inbox_doc["client_closure_ack_sent"] = True
            inbox_doc["client_closure_ack_error"] = ""
        except Exception as exc:
            inbox_doc["client_closure_ack_sent"] = False
            inbox_doc["client_closure_ack_error"] = str(exc)

    await db["client_emails"].insert_one(inbox_doc)
    if requirement_id and inbox_doc.get("status") != "client_closed_requirement":
        requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
        await send_teams_stage_notification(
            db,
            stage="new_requirement_created",
            trainer_name="Not assigned yet",
            requirement=requirement or {"requirement_id": requirement_id},
            request_base_url=_request_base_url(request) if request else "",
            context={"source": "client_inbox", "email_id": inbox_doc["email_id"]},
        )
    return {"status": inbox_doc["status"], "email_id": inbox_doc["email_id"], "requirement_id": requirement_id}


async def _auto_send_pending_client_reply(db, inbox_doc: dict, gmail_service, settings: dict) -> Optional[dict]:
    if not settings.get("autoSendEnabled"):
        return None
    if inbox_doc.get("status") != "pending_approval" or inbox_doc.get("sent_at"):
        return None

    extracted = inbox_doc.get("extracted") or {}
    domain = sender_domain(inbox_doc.get("from_email", ""))
    whitelist = set(_parse_domain_csv(settings.get("clientDomainsWhitelist", "")))
    domain_is_allowed = not whitelist or domain in whitelist
    confidence = float(inbox_doc.get("confidence") or extracted.get("confidence") or 0)

    generated_reply = inbox_doc.get("generated_reply") or {}
    if not client_reply_auto_send_eligible(extracted, generated_reply, confidence, settings, domain_is_allowed):
        return None
    if not inbox_doc.get("from_email") or not generated_reply.get("body"):
        return None

    existing_clarification = await find_existing_client_clarification_request(
        db,
        from_email=inbox_doc.get("from_email", ""),
        requirement_id=inbox_doc.get("requirement_id") or "",
        generated_reply=generated_reply,
        extracted=extracted,
        exclude_email_id=inbox_doc.get("email_id") or "",
    )
    if existing_clarification:
        await db["client_emails"].update_one(
            {"email_id": inbox_doc["email_id"], "status": "pending_approval", "sent_at": None},
            {"$set": {
                "status": "auto_skipped_duplicate_clarification",
                "auto_send_eligible": False,
                "duplicate_clarification_email_id": existing_clarification.get("email_id", ""),
                "duplicate_clarification_sent_at": existing_clarification.get("sent_at"),
                "duplicate_clarification_checked_at": utc_now(),
            }},
        )
        return {
            "status": "auto_skipped_duplicate_clarification",
            "email_id": inbox_doc["email_id"],
            "requirement_id": inbox_doc.get("requirement_id"),
            "existing_email_id": existing_clarification.get("email_id"),
        }

    send_result = send_gmail_reply(
        gmail_service,
        to_email=inbox_doc["from_email"],
        subject=generated_reply.get("subject") or f"Re: {inbox_doc.get('subject') or 'Training Requirement'}",
        body=generated_reply.get("body", ""),
        thread_id=inbox_doc.get("thread_id") or "",
        in_reply_to=inbox_doc.get("message_id_header") or "",
    )
    await db["client_emails"].update_one(
        {"email_id": inbox_doc["email_id"], "status": "pending_approval", "sent_at": None},
        {"$set": {
            "status": "auto_sent",
            "auto_send_eligible": True,
            "gmail_send_result": send_result,
            "sent_at": utc_now(),
            "sent_by": "auto",
        }},
    )
    return {
        "status": "auto_sent",
        "email_id": inbox_doc["email_id"],
        "requirement_id": inbox_doc.get("requirement_id"),
    }


def _parse_calendar_datetime(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _calendar_datetime_text(start_iso: str, end_iso: str = "") -> tuple[str, str]:
    start_dt = _parse_calendar_datetime(start_iso)
    end_dt = _parse_calendar_datetime(end_iso)
    if start_dt and not end_dt:
        end_dt = start_dt + timedelta(minutes=30)
    return (
        start_dt.isoformat() if start_dt else str(start_iso or "").strip(),
        end_dt.isoformat() if end_dt else str(end_iso or "").strip(),
    )


def _meet_link_from_event(event: dict) -> str:
    if event.get("hangoutLink"):
        return event["hangoutLink"]
    conference = event.get("conferenceData") or {}
    for entry in conference.get("entryPoints") or []:
        if entry.get("entryPointType") == "video" and entry.get("uri"):
            return entry["uri"]
    return ""


def _slot_reference_from_text(*values: str) -> str:
    text = "\n".join(str(value or "") for value in values)
    match = _re.search(r"\bSLOT-[A-Z0-9]{8,12}\b", text, flags=_re.IGNORECASE)
    return match.group(0).upper() if match else ""


async def _create_google_meet_event(
    *,
    trainer_email: str,
    trainer_name: str,
    client_email: str,
    client_name: str,
    requirement: dict,
    start_iso: str,
    end_iso: str = "",
    timezone_name: str = "Asia/Kolkata",
    slot_reply: str = "",
) -> dict:
    start_text, end_text = _calendar_datetime_text(start_iso, end_iso)
    if not start_text:
        raise RuntimeError("Client confirmed a slot, but no start date/time could be extracted")
    if not end_text:
        raise RuntimeError("Client confirmed a slot, but no end date/time could be prepared")

    technology = requirement.get("technology_needed") or "Training"
    requirement_id = requirement.get("requirement_id") or ""

    event_body = {
        "summary": f"{technology} Discussion - {requirement_id}".strip(),
        "description": (
            f"Clahan Technologies discussion/interview.\n\n"
            f"Requirement ID: {requirement_id}\n"
            f"Technology: {technology}\n"
            "Participants will be notified separately by Clahan Technologies.\n\n"
            f"Confirmed slot reply:\n{slot_reply[:2000]}"
        ),
        "start": {"dateTime": start_text, "timeZone": timezone_name},
        "end": {"dateTime": end_text, "timeZone": timezone_name},
        "conferenceData": {
            "createRequest": {
                "requestId": f"calhan-{uuid.uuid4().hex[:24]}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }

    def _insert_event():
        service = get_calendar_service()
        return service.events().insert(
            calendarId="primary",
            body=event_body,
            conferenceDataVersion=1,
            sendUpdates="none",
        ).execute()

    event = await asyncio.to_thread(_insert_event)
    meet_link = _meet_link_from_event(event)
    return {
        "event_id": event.get("id"),
        "html_link": event.get("htmlLink"),
        "meet_link": meet_link,
        "start": start_text,
        "end": end_text,
        "timezone": timezone_name,
        "raw_event": event,
    }


async def _trainer_contact_for_interview(db, trainer_id: str, requirement_id: str, fallback_name: str = "") -> dict:
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or {}
    email = (trainer.get("email") or "").strip()
    if not email:
        latest_log = await db["email_logs"].find_one(
            {
                "trainer_id": trainer_id,
                "requirement_id": requirement_id,
                "to_email": {"$nin": [None, ""]},
            },
            {"_id": 0, "to_email": 1},
            sort=[("sent_at", -1), ("created_at", -1)],
        )
        email = (latest_log or {}).get("to_email", "")
    return {
        "trainer": trainer,
        "email": email,
        "name": trainer.get("name") or fallback_name or "Trainer",
        "phone": trainer.get("phone") or "",
    }


async def _send_trainer_interview_schedule(
    db,
    request: Optional[Request],
    *,
    trainer_id: str,
    trainer_name: str,
    to_email: str,
    trainer_phone: str,
    requirement_id: str,
    date_time: str,
    interview_link: str,
    platform: str = "Google Meet",
    source: str = "client_slot_confirmation",
    calendar_event: Optional[dict] = None,
) -> dict:
    if not to_email:
        return {"success": False, "error": "Trainer email not found"}

    req = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    technology = req.get("technology_needed", "Training") if req else "Training"
    subject = f"Interview Schedule Confirmation - {technology}"
    body = (
        f"Dear {trainer_name or 'Trainer'},\n\n"
        f"The client has confirmed the interview/discussion slot. Please find the final details below:\n\n"
        f"Date & Time : {date_time or '[Date & Time]'}\n"
        f"Platform    : {platform}\n"
        f"Meeting Link: {interview_link or '[Meeting Link]'}\n\n"
        f"Please join on time. Let us know if you need any assistance.\n\n"
        f"Regards,\nRecruitment Team,\nClahan Technologies"
    )

    email_id = f"EMAIL-{uuid.uuid4().hex[:8].upper()}"
    tracking_url = build_tracking_url(request, email_id) if request else ""
    smtp_config = await get_admin_email_config(db)
    trainer_phone = await _trainer_phone(db, trainer_id, trainer_phone)
    trainer_for_teams = await _trainer_for_direct_teams(
        db,
        trainer_id,
        {"trainer_id": trainer_id, "name": trainer_name, "email": to_email, "phone": trainer_phone},
    )

    email_result, whatsapp_result, teams_direct_result = await asyncio.gather(
        send_email_async(to_email, subject, body, smtp_config, tracking_url),
        send_interview_whatsapp(
            db,
            trainer_phone=trainer_phone,
            trainer_name=trainer_name,
            requirement_id=requirement_id,
            technology=technology,
            date_time=date_time,
            platform=platform,
            interview_link=interview_link,
            email_id=email_id,
            request_base_url=_request_base_url(request) if request else "",
        ),
        send_trainer_teams_direct_message(
            db,
            trainer=trainer_for_teams,
            subject=subject,
            body=body,
            requirement_id=requirement_id,
            mail_type="mail4",
            email_id=email_id,
        ),
    )
    success, error = email_result
    now = utc_now()

    await db["conversations"].insert_one({
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "to_email": to_email,
        "requirement_id": requirement_id,
        "subject": subject,
        "body": body,
        "mail_type": "mail4",
        "direction": "sent",
        "status": "sent" if success else "failed",
        "error": error if not success else "",
        "sent_at": now,
        "platform": platform,
        "interview_link": interview_link,
        "date_time": date_time,
        "source": source,
        "calendar_event": calendar_event or {},
    })

    email_log_doc = {
        "email_id": email_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "requirement_id": requirement_id,
        "to_email": to_email,
        "subject": subject,
        "body": body,
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "sent_at": now if success else None,
        "reply_received": False,
        "opened": False,
        "open_count": 0,
        "tracking_url": tracking_url,
        "retry_count": 0,
        "mail_type": "mail4",
        "interview_scheduled": success,
        "interview_date": date_time,
        "interview_link": interview_link,
        "platform": platform,
        "technology": technology,
        "trainer_phone": trainer_phone,
        "teams_direct_summary": teams_direct_result,
        "calendar_event": calendar_event or {},
        **interview_reminder_fields(date_time),
        "interview_reminder_status": "not_scheduled",
        "whatsapp_reminder_status": "not_scheduled",
        "created_at": now,
    }
    await db["email_logs"].insert_one(email_log_doc)

    if success:
        await db["trainers"].update_one(
            {"trainer_id": trainer_id},
            {"$set": {"status": "interview_scheduled"}},
        )
        reminder_schedule = await schedule_interview_reminder(
            db,
            email_log=email_log_doc,
            request_base_url=_request_base_url(request) if request else "",
        )
        teams_result = await send_teams_stage_notification(
            db,
            stage="interview_scheduled",
            trainer_name=trainer_name,
            requirement=req or {"requirement_id": requirement_id, "technology_needed": technology},
            request_base_url=_request_base_url(request) if request else "",
            context={
                "source": source,
                "email_id": email_id,
                "mail_type": "mail4",
                "trainer_id": trainer_id,
                "recipient_type": "trainer",
                "to_email": to_email,
                "to_phone": trainer_phone,
                "subject": subject,
                "body": body,
                "email_status": "sent",
                "whatsapp_status": whatsapp_result.get("status", ""),
                "teams_direct_status": teams_direct_result.get("status", ""),
                "interview_date": date_time,
            },
        )
    else:
        reminder_schedule = {"scheduled": False, "status": "email_failed", "error": error}
        teams_result = {"status": "not_sent", "error": "email_failed"}

    return {
        "success": success,
        "error": error,
        "email_id": email_id,
        "whatsapp": whatsapp_result,
        "teams_direct": teams_direct_result,
        "teams": teams_result,
        "reminder_schedule": reminder_schedule,
    }


def _client_missing_training_detail_labels(requirement: Optional[dict]) -> list[str]:
    requirement = requirement or {}

    def text_value(*keys: str) -> str:
        for key in keys:
            value = requirement.get(key)
            if value not in (None, ""):
                return str(value).strip()
        return ""

    def has_number(*keys: str) -> bool:
        for key in keys:
            value = requirement.get(key)
            if value in (None, ""):
                continue
            try:
                return float(value) > 0
            except Exception:
                return bool(str(value).strip())
        return False

    def is_deferred(value: str) -> bool:
        lowered = str(value or "").strip().lower()
        if not lowered:
            return True
        markers = (
            "after interview", "post interview", "after discussion", "post discussion",
            "will share", "will provide", "will confirm", "will update",
            "later", "future", "tbd", "tba", "to be confirmed", "to be decided",
        )
        return any(marker in lowered for marker in markers)

    missing = []
    if not has_number("duration_days", "duration_hours") and is_deferred(text_value("duration", "duration_text", "training_duration")):
        missing.append("Training duration")
    if is_deferred(text_value("timeline_start", "timeline_end", "training_dates", "start_date", "end_date")):
        missing.append("Preferred training dates")
    if is_deferred(text_value("daily_timing", "timing", "training_timing", "daily_timings")):
        missing.append("Daily training timings")
    if is_deferred(text_value("audience_level", "level")):
        missing.append("Audience level (Beginner / Intermediate / Advanced)")
    if is_deferred(text_value("mode", "training_mode", "preferred_mode")):
        missing.append("Training mode (Online / Offline / Hybrid)")
    if not has_number("budget_per_day", "budget_total") and is_deferred(text_value("commercials", "budget", "expected_charges_per_day")):
        missing.append("Budget or expected commercial charges per day/session")
    return missing


async def _send_client_interview_schedule(
    db,
    request: Optional[Request],
    *,
    client_email: str,
    client_name: str,
    requirement_id: str,
    date_time: str,
    interview_link: str,
    platform: str = "Google Meet",
    source: str = "client_slot_confirmation",
    calendar_event: Optional[dict] = None,
    client_slot_email_id: str = "",
) -> dict:
    if not client_email:
        return {"success": False, "error": "Client email not found"}

    req = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    technology = req.get("technology_needed", "Training") if req else "Training"
    client_phone = str((req or {}).get("client_phone") or (req or {}).get("client_whatsapp") or "").strip()
    missing_details = _client_missing_training_detail_labels(req)
    missing_details_text = ""
    if missing_details:
        missing_lines = "\n".join(f"* {item}" for item in missing_details)
        missing_details_text = (
            "\n\nPost-interview follow-up details required:\n"
            "To proceed smoothly after the discussion and finalize the training plan, kindly share the below details when available:\n\n"
            f"{missing_lines}\n"
        )
    subject = f"Discussion Schedule Confirmation - {technology}"
    body = (
        f"Hi {client_name or 'Client'},\n\n"
        f"The {technology} discussion/interview has been scheduled. Please find the final details below:\n\n"
        f"Date & Time : {date_time or '[Date & Time]'}\n"
        f"Platform    : {platform}\n"
        f"Meeting Link: {interview_link or '[Meeting Link]'}\n\n"
        "Clahan Technologies will coordinate the discussion. Please join on time and let us know if you need any assistance."
        f"{missing_details_text}\n\n"
        "Regards,\nRecruitment Team,\nClahan Technologies"
    )

    email_id = f"CLIENT-SCHEDULE-{uuid.uuid4().hex[:8].upper()}"
    tracking_url = build_tracking_url(request, email_id) if request else ""
    smtp_config = await get_admin_email_config(db)
    success, error = await send_email_async(client_email, subject, body, smtp_config, tracking_url)
    whatsapp_result = {"status": "skipped", "error": "Client phone not found"}
    if success and client_phone:
        whatsapp_result = await send_whatsapp_message(
            db,
            client_phone,
            body,
            event_type="client_interview_schedule",
            recipient_type="client",
            request_base_url=_request_base_url(request) if request else "",
            context={
                "source": source,
                "email_id": email_id,
                "mail_type": "client_interview_schedule",
                "recipient_name": client_name,
                "client_name": client_name,
                "client_email": client_email,
                "requirement_id": requirement_id,
                "subject": subject,
                "date_time": date_time,
                "platform": platform,
                "interview_link": interview_link,
            },
        )
    now = utc_now()

    log_doc = {
        "email_id": email_id,
        "trainer_id": "",
        "trainer_name": "",
        "requirement_id": requirement_id,
        "to_email": client_email,
        "client_phone": client_phone,
        "subject": subject,
        "body": body,
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "sent_at": now if success else None,
        "reply_received": False,
        "opened": False,
        "open_count": 0,
        "tracking_url": tracking_url,
        "retry_count": 0,
        "mail_type": "client_interview_schedule",
        "interview_scheduled": success,
        "interview_date": date_time,
        "interview_link": interview_link,
        "platform": platform,
        "technology": technology,
        "calendar_event": calendar_event or {},
        "missing_details_requested": missing_details,
        "client_slot_email_id": client_slot_email_id,
        "whatsapp_summary": whatsapp_result,
        "source": source,
        "created_at": now,
    }
    await db["email_logs"].insert_one(log_doc)

    await db["client_messages"].insert_one({
        **log_doc,
        "direction": "sent",
        "client_email": client_email,
        "client_name": client_name,
    })

    teams_result = {"status": "not_sent", "error": "email_failed"}
    if success:
        teams_result = await send_teams_stage_notification(
            db,
            stage="client_message_sent",
            trainer_name=client_name,
            requirement=req or {"requirement_id": requirement_id, "technology_needed": technology},
            request_base_url=_request_base_url(request) if request else "",
            context={
                "source": source,
                "email_id": email_id,
                "mail_type": "client_interview_schedule",
                "recipient_type": "client",
                "client_email": client_email,
                "client_phone": client_phone,
                "subject": subject,
                "body": body,
                "email_status": "sent",
                "whatsapp_status": whatsapp_result.get("status", ""),
                "interview_date": date_time,
            },
        )
        await db["email_logs"].update_one(
            {"email_id": email_id},
            {"$set": {"teams_summary": teams_result}},
        )
        await db["client_messages"].update_one(
            {"email_id": email_id},
            {"$set": {"teams_summary": teams_result}},
        )

    return {"success": success, "error": error, "email_id": email_id, "whatsapp": whatsapp_result, "teams": teams_result}


def _recent_enough(sent_at, received_at, days: int = 21) -> bool:
    if not sent_at or not received_at:
        return True
    try:
        if isinstance(sent_at, str):
            sent_at = datetime.fromisoformat(sent_at.replace("Z", "+00:00")).replace(tzinfo=None)
        if isinstance(received_at, str):
            received_at = datetime.fromisoformat(received_at.replace("Z", "+00:00")).replace(tzinfo=None)
        return timedelta(0) <= (received_at - sent_at) <= timedelta(days=days)
    except Exception:
        return True


async def _matching_client_slot_email(db, meta: dict, clean_body: str = "") -> Optional[dict]:
    from_email = (meta.get("from_email") or "").strip()
    if not from_email:
        return None

    slot_ref = _slot_reference_from_text(meta.get("subject", ""), meta.get("snippet", ""), clean_body)
    if slot_ref:
        exact = await db["client_slot_emails"].find_one(
            {
                "slot_ref": slot_ref,
                "to_email": {"$regex": f"^{_re.escape(from_email)}$", "$options": "i"},
            },
            {"_id": 0},
        )
        if exact:
            return exact

    received_at = meta.get("received_at") or utc_now()
    candidates = await db["client_slot_emails"].find(
        {
            "to_email": {"$regex": f"^{_re.escape(from_email)}$", "$options": "i"},
            "status": {"$in": ["sent", "confirmed_scheduled", "calendar_failed", "trainer_email_failed", "client_email_failed"]},
            "$or": [{"sent_at": {"$lte": received_at}}, {"sent_at": None}],
        },
        {"_id": 0},
    ).sort("sent_at", -1).limit(25).to_list(25)
    if not candidates:
        return None

    subject_norm = _norm_subject(meta.get("subject", ""))
    body_norm = _re.sub(r"\s+", " ", (clean_body or meta.get("snippet") or "").lower())
    scored = []
    for item in candidates:
        if not _recent_enough(item.get("sent_at"), received_at):
            continue
        slot_subject = _norm_subject(item.get("subject", ""))
        trainer_name = str(item.get("trainer_name") or "").lower()
        requirement_id = str(item.get("requirement_id") or "").lower()
        score = 0
        if slot_subject and (slot_subject in subject_norm or subject_norm in slot_subject):
            score += 140
        if "slot" in subject_norm or "availability" in subject_norm:
            score += 60
        if requirement_id and (requirement_id in subject_norm or requirement_id in body_norm):
            score += 50
        if trainer_name and trainer_name in body_norm:
            score += 40
        if _re.search(r"\b(confirm|confirmed|works|okay|ok|fine|available|schedule|book)\b", body_norm):
            score += 35
        if _re.search(r"\b(\d{1,2}(:\d{2})?\s*(am|pm)?|today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", body_norm):
            score += 35
        scored.append((score, item))

    if not scored:
        return None
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored[0][1] if scored[0][0] >= 100 else None


async def _process_client_slot_reply_from_meta(
    db,
    message_id: str,
    request: Optional[Request] = None,
    meta_hint: Optional[dict] = None,
    slot_doc: Optional[dict] = None,
) -> Optional[dict]:
    existing = await db["client_slot_confirmations"].find_one({"gmail_message_id": message_id}, {"_id": 0})
    if not existing and slot_doc and slot_doc.get("email_id"):
        existing = await db["client_slot_confirmations"].find_one(
            {
                "client_slot_email_id": slot_doc.get("email_id"),
                "status": {"$in": ["calendar_failed", "trainer_email_failed", "needs_manual_review"]},
            },
            {"_id": 0},
            sort=[("updated_at", -1), ("created_at", -1)],
        )
        if existing:
            message_id = existing.get("gmail_message_id") or message_id
    if existing and existing.get("status") not in {"calendar_failed", "trainer_email_failed", "needs_manual_review"}:
        return {
            "status": "already_processed_client_slot_reply",
            "email_id": message_id,
            "requirement_id": existing.get("requirement_id"),
            "trainer_id": existing.get("trainer_id"),
        }

    meta = meta_hint or {}
    clean_body = _strip_quoted_reply_text(meta.get("clean_body") or meta.get("raw_body") or meta.get("snippet") or "")
    slot_doc = slot_doc or await _matching_client_slot_email(db, meta, clean_body)
    if not slot_doc:
        return None
    if slot_doc.get("status") == "confirmed_scheduled":
        return {
            "status": "already_processed_client_slot_reply",
            "email_id": message_id,
            "requirement_id": slot_doc.get("requirement_id"),
            "trainer_id": slot_doc.get("trainer_id"),
        }

    requirement_id = slot_doc.get("requirement_id", "")
    trainer_id = slot_doc.get("trainer_id", "")
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    trainer_contact = await _trainer_contact_for_interview(
        db,
        trainer_id,
        requirement_id,
        slot_doc.get("trainer_name", ""),
    )
    client_name = slot_doc.get("client_name") or meta.get("from_name") or "Client"
    timezone_name = requirement.get("timezone") or "Asia/Kolkata"

    parsed = await extract_client_slot_confirmation(
        clean_body,
        slot_doc.get("slot_text", ""),
        {
            "timezone": timezone_name,
            "requirement_id": requirement_id,
            "technology": requirement.get("technology_needed") or "",
            "trainer_name": trainer_contact.get("name") or slot_doc.get("trainer_name", ""),
            "client_email": meta.get("from_email") or slot_doc.get("to_email"),
        },
    )

    now = utc_now()
    confirmation_id = existing.get("confirmation_id") if existing else f"CLIENT-CONF-{uuid.uuid4().hex[:8].upper()}"
    base_doc = {
        "confirmation_id": confirmation_id,
        "gmail_message_id": message_id,
        "thread_id": meta.get("thread_id"),
        "client_slot_email_id": slot_doc.get("email_id"),
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer_contact.get("name") or slot_doc.get("trainer_name"),
        "trainer_email": trainer_contact.get("email"),
        "client_email": meta.get("from_email") or slot_doc.get("to_email"),
        "client_name": client_name,
        "subject": meta.get("subject"),
        "reply_text": clean_body,
        "parsed_slot": parsed,
        "updated_at": now,
    }
    if not existing:
        base_doc["created_at"] = now

    if not parsed.get("confirmed") or not parsed.get("start_iso") or float(parsed.get("confidence") or 0) < 0.5:
        await db["client_slot_confirmations"].update_one(
            {"confirmation_id": confirmation_id},
            {"$set": {**base_doc, "status": "needs_manual_review", "error": parsed.get("reason") or ""}},
            upsert=True,
        )
        await db["client_slot_emails"].update_one(
            {"email_id": slot_doc.get("email_id")},
            {"$set": {
                "last_client_reply_at": now,
                "last_client_reply_text": clean_body,
                "last_client_reply_parse": parsed,
            }},
        )
        return {
            "status": "client_slot_needs_review",
            "email_id": message_id,
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
            "reason": parsed.get("reason"),
        }

    if not trainer_contact.get("email"):
        await db["client_slot_confirmations"].update_one(
            {"confirmation_id": confirmation_id},
            {"$set": {**base_doc, "status": "trainer_email_missing", "error": "Trainer email not found"}},
            upsert=True,
        )
        return {
            "status": "trainer_email_missing",
            "email_id": message_id,
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
        }

    try:
        calendar_event = await _create_google_meet_event(
            trainer_email=trainer_contact["email"],
            trainer_name=trainer_contact["name"],
            client_email=meta.get("from_email") or slot_doc.get("to_email") or "",
            client_name=client_name,
            requirement=requirement or {"requirement_id": requirement_id},
            start_iso=parsed.get("start_iso", ""),
            end_iso=parsed.get("end_iso", ""),
            timezone_name=parsed.get("timezone") or timezone_name,
            slot_reply=clean_body,
        )
    except Exception as exc:
        error = str(exc)
        await db["client_slot_confirmations"].update_one(
            {"confirmation_id": confirmation_id},
            {"$set": {**base_doc, "status": "calendar_failed", "error": error}},
            upsert=True,
        )
        await db["client_slot_emails"].update_one(
            {"email_id": slot_doc.get("email_id")},
            {"$set": {
                "status": "calendar_failed",
                "client_confirmed_at": now,
                "client_confirmed_slot": parsed,
                "calendar_error": error,
            }},
        )
        return {
            "status": "calendar_failed",
            "email_id": message_id,
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
            "error": error,
        }

    meet_link = calendar_event.get("meet_link") or calendar_event.get("html_link") or ""
    date_time = parsed.get("date_time_text") or parsed.get("start_iso") or calendar_event.get("start")
    client_email = meta.get("from_email") or slot_doc.get("to_email") or ""
    send_result, client_send_result = await asyncio.gather(
        _send_trainer_interview_schedule(
            db,
            request,
            trainer_id=trainer_id,
            trainer_name=trainer_contact["name"],
            to_email=trainer_contact["email"],
            trainer_phone=trainer_contact.get("phone", ""),
            requirement_id=requirement_id,
            date_time=date_time,
            interview_link=meet_link,
            platform="Google Meet",
            source="client_slot_confirmation",
            calendar_event=calendar_event,
        ),
        _send_client_interview_schedule(
            db,
            request,
            client_email=client_email,
            client_name=client_name,
            requirement_id=requirement_id,
            date_time=date_time,
            interview_link=meet_link,
            platform="Google Meet",
            source="client_slot_confirmation",
            calendar_event=calendar_event,
            client_slot_email_id=slot_doc.get("email_id", ""),
        ),
    )
    if send_result.get("success") and client_send_result.get("success"):
        final_status = "confirmed_scheduled"
    elif not send_result.get("success"):
        final_status = "trainer_email_failed"
    else:
        final_status = "client_email_failed"
    await db["client_slot_confirmations"].update_one(
        {"confirmation_id": confirmation_id},
        {"$set": {
            **base_doc,
            "status": final_status,
            "calendar_event": calendar_event,
            "trainer_schedule_email": send_result,
            "client_schedule_email": client_send_result,
            "scheduled_at": now,
            "error": send_result.get("error") or client_send_result.get("error") or "",
        }},
        upsert=True,
    )
    await db["client_slot_emails"].update_one(
        {"email_id": slot_doc.get("email_id")},
        {
            "$set": {
                "status": final_status,
                "client_confirmed_at": now,
                "client_confirmed_slot": parsed,
                "client_reply_message_id": message_id,
                "calendar_event": calendar_event,
                "trainer_schedule_email": send_result,
                "client_schedule_email": client_send_result,
            },
            "$unset": {"calendar_error": ""},
        },
    )
    return {
        "status": final_status,
        "email_id": message_id,
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
        "trainer_email_sent": bool(send_result.get("success")),
        "client_email_sent": bool(client_send_result.get("success")),
        "meet_link": meet_link,
        "calendar_event_id": calendar_event.get("event_id"),
    }


async def _process_client_slot_reply(
    db,
    message_id: str,
    gmail_service,
    request: Optional[Request] = None,
    meta_hint: Optional[dict] = None,
    slot_doc: Optional[dict] = None,
) -> Optional[dict]:
    meta = fetch_gmail_email(message_id, gmail_service)
    if meta_hint:
        meta = {**meta_hint, **meta}
    return await _process_client_slot_reply_from_meta(
        db,
        message_id,
        request=request,
        meta_hint=meta,
        slot_doc=slot_doc,
    )


async def _sync_recent_client_inbox(db, request: Optional[Request] = None, max_results: int = 25) -> dict:
    settings = await _client_inbox_settings(db)
    if settings.get("inboxProvider") in {"smtp_only", "smtp"}:
        auto_sent_existing = await auto_send_pending_client_replies_smtp(db)
        await db["gmail_sync"].update_one(
            {"sync_id": "default"},
            {"$set": {
                "last_manual_sync_at": utc_now(),
                "last_manual_sync_provider": "smtp_only",
                "last_manual_sync_processed": 0,
                "last_manual_sync_auto_sent_existing": len(auto_sent_existing),
                "last_manual_sync_skipped": 0,
                "last_manual_sync_errors": [],
            }},
            upsert=True,
        )
        return {
            "success": True,
            "provider": "smtp_only",
            "processed": [],
            "processed_count": 0,
            "skipped": 0,
            "already_processed": 0,
            "auto_sent_existing": auto_sent_existing,
            "auto_sent_existing_count": len(auto_sent_existing),
            "errors": [],
            "message": "SMTP-only mode can send eligible pending replies, but it cannot read new inbox mail.",
        }

    if settings.get("inboxProvider") in {"imap", "imap_poll", "imap_polling"}:
        result = await poll_imap_client_inbox(db)
        await db["gmail_sync"].update_one(
            {"sync_id": "default"},
            {"$set": {
                "last_manual_sync_at": utc_now(),
                "last_manual_sync_provider": "imap",
                "last_manual_sync_processed": int(result.get("processed") or 0),
                "last_manual_sync_auto_sent_existing": int(result.get("auto_sent_existing") or 0),
                "last_manual_sync_skipped": 1 if result.get("skipped") else 0,
                "last_manual_sync_errors": [result.get("error")] if result.get("error") else [],
            }},
            upsert=True,
        )
        return {
            "success": True,
            "provider": "imap",
            "processed": [],
            "processed_count": int(result.get("processed") or 0),
            "skipped": 1 if result.get("skipped") else 0,
            "already_processed": 0,
            "auto_sent_existing": [],
            "auto_sent_existing_count": int(result.get("auto_sent_existing") or 0),
            "errors": [result.get("error")] if result.get("error") else [],
            "imap": result,
        }

    service = get_gmail_service()
    whitelist = _parse_domain_csv(settings.get("clientDomainsWhitelist", ""))
    processed = []
    skipped = 0
    already_processed = 0
    auto_sent_existing = []
    errors = []
    sync_limit = max(1, min(int(max_results or 25), 100))
    search_queries = [
        ("training_request", "newer_than:14d {training trainer requirement}", sync_limit),
        ("devops_request", "newer_than:14d devops", 20),
        ("share_trainer", "newer_than:14d \"share a suitable trainer\"", 20),
        ("recent", "newer_than:7d", min(sync_limit, 30)),
        ("selected", "newer_than:30d selected", 25),
        ("approved", "newer_than:30d approved", 15),
        ("proceed", "newer_than:30d proceed", 15),
    ]
    listed_messages = []
    seen_message_ids = set()
    for _, query, limit in search_queries:
        if len(listed_messages) >= sync_limit:
            break
        try:
            listed = service.users().messages().list(
                userId="me",
                labelIds=["INBOX"],
                q=query,
                maxResults=max(1, min(int(limit or sync_limit), 100)),
            ).execute()
        except Exception as exc:
            errors.append({"query": query, "error": str(exc)})
            continue
        for message in listed.get("messages", []) or []:
            message_id = message.get("id")
            if message_id and message_id not in seen_message_ids:
                seen_message_ids.add(message_id)
                listed_messages.append(message)
                if len(listed_messages) >= sync_limit:
                    break

    for item in listed_messages:
        message_id = item.get("id")
        if not message_id:
            continue
        existing = await db["client_emails"].find_one({"email_id": message_id}, {"_id": 0})
        if existing:
            has_decision = bool(
                existing.get("post_interview_decision")
                or (existing.get("extracted") or {}).get("post_interview_decision")
            )
            if not has_decision and existing.get("status") != "spam":
                decision_attempt = await _process_and_store_client_decision_message(db, message_id, service, request)
                if decision_attempt:
                    processed.append(decision_attempt)
                    continue
            if (
                has_decision
                or existing.get("status") in {"spam", "needs_manual_review", "trainer_decision_email_failed"}
            ):
                decision_retry = await _process_and_store_client_decision_message(db, message_id, service, request)
                if decision_retry:
                    processed.append(decision_retry)
                    continue
            auto_sent = await _auto_send_pending_client_reply(db, existing, service, settings)
            if auto_sent:
                auto_sent_existing.append(auto_sent)
            already_processed += 1
            continue
        try:
            meta = _gmail_metadata(service, message_id)
            slot_doc = await _matching_client_slot_email(db, meta)
            if slot_doc:
                slot_result = await _process_client_slot_reply(
                    db,
                    message_id,
                    service,
                    request,
                    meta_hint=meta,
                    slot_doc=slot_doc,
                )
                if slot_result:
                    processed.append(slot_result)
                    continue
            decision_result = await _process_and_store_client_decision_message(
                db,
                message_id,
                service,
                request,
                meta_hint=meta,
            )
            if decision_result:
                processed.append(decision_result)
                continue
            known_domain = await _known_client_domain(db, meta.get("from_email", ""))
            likely_training = known_domain or is_likely_training_email(
                meta.get("subject", ""),
                meta.get("from_email", ""),
                whitelist,
                meta.get("snippet", ""),
            )
            if not likely_training:
                skipped += 1
                continue
            processed.append(await _process_and_store_client_message(db, message_id, service, request))
        except Exception as exc:
            errors.append({"email_id": message_id, "error": str(exc)})

    await db["gmail_sync"].update_one(
        {"sync_id": "default"},
        {"$set": {
            "last_manual_sync_at": utc_now(),
            "last_manual_sync_processed": len(processed),
            "last_manual_sync_skipped": skipped,
            "last_manual_sync_auto_sent_existing": len(auto_sent_existing),
            "last_manual_sync_errors": errors[-5:],
        }},
        upsert=True,
    )
    return {
        "success": True,
        "processed": processed,
        "processed_count": len(processed),
        "auto_sent_existing": auto_sent_existing,
        "auto_sent_existing_count": len(auto_sent_existing),
        "skipped": skipped,
        "already_processed": already_processed,
        "errors": errors,
    }


TOC_SYSTEM_PROMPT = """You are an expert curriculum designer and corporate trainer with 15+ years of experience
designing professional training programs for IT companies, MNCs, and corporate clients.

Your task is to generate a detailed, professional Training Table of Contents (TOC) / Course Curriculum.

RULES:
1. Structure the curriculum day-by-day with clear session breakdowns
2. Each day has Morning Session (9:30 AM – 1:00 PM) and Afternoon Session (2:00 PM – 5:30 PM)
3. Each session has 3-5 topics with 10-20 minute time slots per topic
4. Include hands-on Lab Exercises at the end of each session (45-60 mins)
5. Include a Recap & Q&A (15 mins) at start of each day (except Day 1)
6. Day 1 starts with: Introduction & Expectations (30 mins) + Environment Setup (30 mins)
7. Last day ends with: Final Project / Capstone (2 hrs) + Assessment & Certification Guidance (30 mins) + Feedback & Closing (15 mins)
8. Topics must be technically accurate, industry-relevant, and progressive (basic to advanced)
9. Lab exercises must be practical, hands-on, and relevant to the day's topics
10. Adjust depth and complexity based on audience_level (beginner/intermediate/advanced)
11. For Online mode: include "Check-in Poll" at session start, "Breakout Room Activity" for labs
12. For Offline mode: include "Whiteboard Activity" and "Group Discussion" segments

OUTPUT FORMAT (respond ONLY with valid JSON, no markdown, no explanation):
{
  "title": "Complete [Technology] Training Program",
  "subtitle": "[Duration]-Day [Level] Training | [Mode] Mode",
  "overview": "2-3 sentence program overview",
  "prerequisites": ["prereq1", "prereq2"],
  "learning_outcomes": ["outcome1", "outcome2", "outcome3", "outcome4", "outcome5"],
  "days": [
    {
      "day": 1,
      "title": "Day 1: [Theme]",
      "morning_session": {
        "time": "9:30 AM – 1:00 PM",
        "title": "Session Title",
        "topics": [
          { "time": "9:30 – 10:00", "topic": "Introduction & Expectations", "type": "lecture" },
          { "time": "10:00 – 10:45", "topic": "Topic Name", "type": "lecture" },
          { "time": "10:45 – 11:00", "topic": "Break", "type": "break" },
          { "time": "11:00 – 12:00", "topic": "Topic Name", "type": "demo" },
          { "time": "12:00 – 1:00", "topic": "Lab: Lab Title", "type": "lab" }
        ]
      },
      "afternoon_session": {
        "time": "2:00 PM – 5:30 PM",
        "title": "Session Title",
        "topics": [
          { "time": "2:00 – 3:00", "topic": "Topic Name", "type": "lecture" },
          { "time": "3:00 – 3:15", "topic": "Break", "type": "break" },
          { "time": "3:15 – 4:15", "topic": "Topic Name", "type": "demo" },
          { "time": "4:15 – 5:15", "topic": "Lab: Lab Title", "type": "lab" },
          { "time": "5:15 – 5:30", "topic": "Day Summary & Q&A", "type": "qa" }
        ]
      }
    }
  ],
  "tools_software": ["tool1", "tool2"],
  "certification_guidance": "What certification this training prepares for",
  "trainer_notes": "Special instructions or tips for the trainer"
}
"""

TOC_SYSTEM_PROMPT = TOC_SYSTEM_PROMPT + """

STRICT CLIENT TIMING OVERRIDE:
- Use the client-provided daily timing exactly.
- If the client says 9:00 AM to 4:00 PM, every generated time slot must stay inside 9:00 AM to 4:00 PM.
- Do not generate 5:00 PM or 5:30 PM timings unless the client explicitly gave that end time.
- Split each day into Morning Session, Lunch/Break, and Afternoon Session inside the client timing window.
- Use only ASCII hyphen "-" for time ranges. Do not use en dash or em dash.
"""


def _toc_user_prompt(payload: dict) -> str:
    technology = payload.get("technology") or "Training"
    duration_days = int(payload.get("duration_days") or 1)
    audience_level = payload.get("audience_level") or "intermediate"
    mode = payload.get("mode") or "Online"
    training_dates = payload.get("training_dates") or payload.get("schedule") or "Not specified"
    timing = payload.get("timing") or payload.get("daily_timing") or payload.get("duration_hours") or "Use 9:00 AM to 4:00 PM with breaks"
    client_notes = (payload.get("client_notes") or payload.get("content_scope") or "").strip()
    custom_topics = (payload.get("custom_topics") or "").strip()
    if payload.get("toc_type") == "custom":
        return f"""Generate a structured Training Table of Contents for:
- Technology/Domain: {technology}
- Duration: {duration_days} days
- Training Dates: {training_dates}
- Daily Timing / Hours: {timing}
- Audience Level: {audience_level}
- Training Mode: {mode}
- Client has specified these topics to cover: {custom_topics}
- Client Content Scope / Notes: {client_notes or custom_topics}

Structure these exact topics into a logical day-by-day curriculum with proper time slots and lab exercises.
Do not add extra topics beyond what's specified, but you can add sub-topics and labs for each.
Use the daily timing exactly and keep all sessions inside the given time window.
Use only ASCII hyphen "-" for time ranges.
"""
    return f"""Generate a complete Training Table of Contents for:
- Technology/Domain: {technology}
- Duration: {duration_days} days
- Training Dates: {training_dates}
- Daily Timing / Hours: {timing}
- Audience Level: {audience_level}
- Training Mode: {mode}
- Client Content Scope / Notes: {client_notes}
- Generate comprehensive, industry-standard curriculum covering all major topics
Use the daily timing exactly and keep all sessions inside the given time window.
Use only ASCII hyphen "-" for time ranges.
"""


def _json_object_from_ai_text(raw: str, provider: str = "AI") -> dict:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else ""
    if raw.endswith("```"):
        raw = raw[:-3]
    raw = raw.strip()
    if raw.startswith("`") and raw.endswith("`"):
        raw = raw[1:-1]
    raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"{provider} did not return valid JSON for TOC. Response: {raw[:300]}")
    return _json.loads(raw[start:end + 1])


async def _repair_toc_json_with_ollomo(raw: str, api_url: str, headers: dict, model: str, timeout_seconds: int) -> dict:
    import httpx as _httpx

    repair_prompt = f"""Fix the following malformed JSON and return only valid JSON.
Do not summarize. Do not add markdown. Do not add explanation.
Preserve all fields, days, sessions, topics, and values as much as possible.
Use only ASCII hyphen "-" for time ranges.

Malformed JSON:
{raw[:70000]}
"""
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You repair malformed JSON. Return only valid JSON."},
            {"role": "user", "content": repair_prompt},
        ],
        "temperature": 0,
        "max_tokens": 12000,
    }
    async with _httpx.AsyncClient(timeout=timeout_seconds) as client:
        res = await client.post(api_url, headers=headers, json=body)
        res.raise_for_status()
        data = res.json()
    choices = data.get("choices") or []
    fixed = ""
    if choices:
        message = choices[0].get("message") or {}
        fixed = message.get("content") or choices[0].get("text") or ""
    if not fixed:
        fixed = data.get("output_text") or data.get("response") or data.get("text") or ""
    return _json_object_from_ai_text(fixed, "Ollomo JSON repair")


def _normalise_toc_timing_for_payload(toc: dict, payload: dict) -> dict:
    timing = str(payload.get("timing") or payload.get("daily_timing") or "").lower()
    if not ("9" in timing and "4" in timing):
        return toc
    template_morning = [
        ("9:00 - 9:30", "Recap / Introduction & Expectations", "lecture"),
        ("9:30 - 10:45", None, "lecture"),
        ("10:45 - 11:00", "Break", "break"),
        ("11:00 - 12:15", None, "demo"),
        ("12:15 - 1:00", None, "qa"),
    ]
    template_afternoon = [
        ("1:00 - 2:15", None, "lecture"),
        ("2:15 - 2:30", "Break", "break"),
        ("2:30 - 3:30", None, "lab"),
        ("3:30 - 4:00", "Day Summary & Q&A", "qa"),
    ]

    def apply_template(session: dict, template: list[tuple[str, Optional[str], str]], time_label: str) -> None:
        session["time"] = time_label
        topics = list(session.get("topics") or [])
        agenda_topics = []
        for item in topics:
            if not isinstance(item, dict):
                continue
            topic_text = str(item.get("topic") or "").strip()
            topic_type = str(item.get("type") or "").strip().lower()
            if not topic_text:
                continue
            if topic_type == "break" or topic_text.lower() in {"break", "lunch", "tea break"}:
                continue
            agenda_topics.append(item)
        agenda_cursor = 0

        def next_agenda_topic(fallback_type: str) -> dict:
            nonlocal agenda_cursor
            if agenda_cursor < len(agenda_topics):
                item = agenda_topics[agenda_cursor]
                agenda_cursor += 1
                topic_text = str(item.get("topic") or "").strip()
                topic_type = str(item.get("type") or fallback_type).strip().lower()
                if topic_type == "break":
                    topic_type = fallback_type
                return {"topic": topic_text, "type": topic_type or fallback_type}
            return {"topic": "Topic discussion, demo, and guided practice", "type": fallback_type}

        rebuilt = []
        for slot, forced_topic, fallback_type in template:
            if forced_topic:
                rebuilt.append({
                    "time": slot,
                    "topic": forced_topic,
                    "type": fallback_type,
                })
                continue
            agenda = next_agenda_topic(fallback_type)
            rebuilt.append({
                "time": slot,
                "topic": agenda["topic"],
                "type": agenda["type"],
            })
        session["topics"] = rebuilt

    for day in toc.get("days") or []:
        if isinstance(day.get("morning_session"), dict):
            apply_template(day["morning_session"], template_morning, "9:00 AM - 1:00 PM")
        if isinstance(day.get("afternoon_session"), dict):
            apply_template(day["afternoon_session"], template_afternoon, "1:00 PM - 4:00 PM")
    return toc


async def _generate_toc_with_ollomo_chunked(payload: dict, api_url: str, headers: dict, model: str, timeout_seconds: int) -> dict:
    import httpx as _httpx

    duration_days = int(payload.get("duration_days") or 1)
    base = generate_toc_from_dataset(
        payload.get("technology"),
        duration_days,
        payload.get("audience_level") or "intermediate",
        payload.get("mode") or "Online",
        payload.get("custom_topics") or payload.get("client_notes") or "",
    )
    base = _normalise_toc_timing_for_payload(base, payload)
    rewritten = 0
    day_prompt_prefix = f"""Rewrite this single training day as valid JSON only.
Technology: {payload.get("technology")}
Audience Level: {payload.get("audience_level") or "Intermediate"}
Mode: {payload.get("mode") or "Online"}
Daily Timing: {payload.get("timing") or "9:00 AM to 4:00 PM with breaks"}
Client Scope: {payload.get("client_notes") or payload.get("custom_topics") or ""}

Rules:
- Return only one JSON object for the day.
- Keep all times inside the daily timing window.
- Use Morning Session 9:00 AM - 1:00 PM and Afternoon Session 1:00 PM - 4:00 PM when timing is 9:00 AM to 4:00 PM.
- Include lecture/demo/lab/break/qa topic types.
- Use only ASCII hyphen "-" in time ranges.
"""
    async with _httpx.AsyncClient(timeout=timeout_seconds) as client:
        for index, day in enumerate(list(base.get("days") or [])):
            prompt = day_prompt_prefix + "\nBase day JSON:\n" + _json.dumps(day, ensure_ascii=False)
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You generate one valid JSON object. No markdown."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 2200,
            }
            try:
                res = await client.post(api_url, headers=headers, json=body)
                res.raise_for_status()
                data = res.json()
                choices = data.get("choices") or []
                raw = ""
                if choices:
                    message = choices[0].get("message") or {}
                    raw = message.get("content") or choices[0].get("text") or ""
                if not raw:
                    raw = data.get("output_text") or data.get("response") or data.get("text") or ""
                fixed_day = _json_object_from_ai_text(raw, f"Ollomo day {index + 1}")
                base["days"][index] = fixed_day
                rewritten += 1
            except Exception:
                continue
    base = _normalise_toc_timing_for_payload(base, payload)
    base["agent"] = {
        **(base.get("agent") or {}),
        "source": "ollomo_chunked",
        "provider": "ollomo",
        "model": model,
        "days_rewritten": rewritten,
        "requested_days": duration_days,
    }
    base["trainer_notes"] = (
        str(base.get("trainer_notes") or "").strip()
        or "Generated with local Ollama day-wise enhancement and validated timing."
    )
    return base


async def _generate_toc_with_ollomo(payload: dict) -> dict:
    import httpx as _httpx

    settings = get_settings()
    api_key = (
        os.getenv("OLLOMO_API_KEY", "")
        or getattr(settings, "ollomo_api_key", "")
    ).strip()
    if _is_placeholder_api_key(api_key):
        raise ValueError("OLLOMO_API_KEY is not configured")

    api_url = (
        os.getenv("OLLOMO_API_URL", "").strip()
        or getattr(settings, "ollomo_api_url", "").strip()
        or "https://api.ollomo.ai/v1/chat/completions"
    )
    model = (
        os.getenv("OLLOMO_MODEL", "").strip()
        or getattr(settings, "ollomo_model", "").strip()
        or "ollomo-chat"
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-API-Key": api_key,
        "Content-Type": "application/json",
    }
    timeout_seconds = int(os.getenv("OLLOMO_TIMEOUT_SECONDS", "600") or "600")
    if int(payload.get("duration_days") or 0) >= 10:
        return await _generate_toc_with_ollomo_chunked(payload, api_url, headers, model, timeout_seconds)

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": TOC_SYSTEM_PROMPT},
            {"role": "user", "content": _toc_user_prompt(payload)},
        ],
        "temperature": 0.2,
        "max_tokens": int(os.getenv("OLLOMO_TOC_MAX_TOKENS", "12000") or "12000"),
    }
    async with _httpx.AsyncClient(timeout=timeout_seconds) as client:
        res = await client.post(api_url, headers=headers, json=body)
        res.raise_for_status()
        data = res.json()

    raw = ""
    choices = data.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        raw = message.get("content") or choices[0].get("text") or ""
    if not raw:
        raw = data.get("output_text") or data.get("response") or data.get("text") or ""
    if not raw:
        raw = str(data)

    try:
        toc = _json_object_from_ai_text(raw, "Ollomo")
    except Exception:
        toc = await _repair_toc_json_with_ollomo(raw, api_url, headers, model, timeout_seconds)
    toc["agent"] = {
        **(toc.get("agent") or {}),
        "source": "ollomo_api",
        "provider": "ollomo",
        "model": model,
    }
    return toc


async def _generate_toc_with_gemini(payload: dict) -> dict:
    import httpx as _httpx
    technology = str(payload.get("technology") or "")
    duration_days = int(payload.get("duration_days") or 0)
    if "devops" in technology.lower() and duration_days >= 8:
        return _fallback_toc_data(payload, "")
    settings = get_settings()
    api_key = os.getenv("GEMINI_API_KEY", "") or getattr(settings, "gemini_api_key", "")
    if _is_placeholder_api_key(api_key):
        raise ValueError("GEMINI_API_KEY is not configured")
    model = os.getenv("GEMINI_MODEL", "") or getattr(settings, "gemini_model", "") or "gemini-2.0-flash"
    full_prompt = TOC_SYSTEM_PROMPT + "\n\n" + _toc_user_prompt(payload)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    async with _httpx.AsyncClient(timeout=120) as client:
        res = await client.post(url, json={
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 8000},
        })
        res.raise_for_status()
        data = res.json()
    raw = (data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")).strip()
    return _json_object_from_ai_text(raw, "Gemini")


async def _polish_toc_with_gemini(toc_data: dict, payload: dict) -> dict:
    import httpx as _httpx

    settings = get_settings()
    api_key = (os.getenv("GEMINI_API_KEY", "") or getattr(settings, "gemini_api_key", "")).strip()
    if _is_placeholder_api_key(api_key):
        raise ValueError("GEMINI_API_KEY is not configured")
    model = (os.getenv("GEMINI_MODEL", "") or getattr(settings, "gemini_model", "") or "gemini-2.0-flash").strip()
    max_tokens = int(os.getenv("GEMINI_TOC_MAX_OUTPUT_TOKENS", "12000") or "12000")
    technology = payload.get("technology") or "Training"
    duration_days = int(payload.get("duration_days") or len(toc_data.get("days") or []) or 1)
    prompt = f"""You are polishing a training Table of Contents JSON for a corporate training proposal.

Rules:
- Return ONLY valid JSON.
- Preserve the same schema and fields.
- Preserve exactly {duration_days} days.
- Preserve every day number.
- Preserve all time ranges exactly as given.
- Preserve break rows as breaks, but do not add lunch/break rows.
- Do not replace teaching topics with Break, Lunch, or empty text.
- Improve topic wording, subtopics, overview, learning outcomes, labs, assessment, tools, and certification guidance.
- Keep the curriculum technically accurate for {technology}.
- Do not add marketing text or explanations outside JSON.

Input JSON:
{_json.dumps(toc_data, default=str)}
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    async with _httpx.AsyncClient(timeout=180) as client:
        res = await client.post(url, json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.15,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
            },
        })
        res.raise_for_status()
        data = res.json()
    raw = (data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")).strip()
    polished = _json_object_from_ai_text(raw, "Gemini ToC polish")
    polished["agent"] = {
        **(polished.get("agent") or toc_data.get("agent") or {}),
        "polisher": "gemini",
        "polish_model": model,
    }
    return polished


async def _maybe_polish_toc_with_gemini(toc_data: dict, payload: dict) -> tuple[dict, str]:
    enabled = str(os.getenv("GEMINI_TOC_POLISH_ENABLED", "true")).strip().lower() not in {"0", "false", "no", "off"}
    if not enabled:
        return toc_data, "disabled"
    try:
        polished = await _polish_toc_with_gemini(toc_data, payload)
        return validate_toc(polished, int(payload.get("duration_days") or 1)), "gemini"
    except Exception as exc:
        logger.warning("Gemini ToC polish skipped: %s", exc)
        return toc_data, f"skipped: {exc}"


def _validate_toc_agent_output(toc_data: dict, payload: dict) -> dict:
    toc_data = dict(toc_data or {})
    expected_days = max(1, min(int(payload.get("duration_days") or 1), 100))
    fallback = _fallback_toc_data({**payload, "duration_days": expected_days}, "")
    days = list(toc_data.get("days") or [])

    if len(days) < expected_days:
        days.extend((fallback.get("days") or [])[len(days):expected_days])
    elif len(days) > expected_days:
        days = days[:expected_days]

    for index in range(expected_days):
        source_day = days[index] if index < len(days) else {}
        fallback_day = (fallback.get("days") or [])[index]
        day = {**fallback_day, **(source_day or {})}
        day["day"] = index + 1
        if not day.get("title"):
            day["title"] = fallback_day.get("title") or f"Day {index + 1}"
        if not day.get("focus_area"):
            day["focus_area"] = fallback_day.get("focus_area") or str(day.get("title", "")).split(":", 1)[-1].strip()
        if not day.get("tools"):
            day["tools"] = fallback_day.get("tools") or ", ".join((fallback.get("tools_software") or [])[:3])
        if not day.get("jira_focus"):
            day["jira_focus"] = fallback_day.get("jira_focus") or "Update sprint board, log time, and move cards"
        for key in ("morning_session", "afternoon_session"):
            session = dict(day.get(key) or {})
            fallback_session = fallback_day.get(key) or {}
            if not session.get("time"):
                session["time"] = fallback_session.get("time")
            if not session.get("title"):
                session["title"] = fallback_session.get("title")
            topics = list(session.get("topics") or [])
            if not topics:
                topics = list(fallback_session.get("topics") or [])
            if not any(str(topic.get("type", "")).lower() == "lab" or "lab" in str(topic.get("topic", "")).lower() for topic in topics):
                topics.append({"time": "2:45 - 4:00", "topic": f"Lab: Apply {day.get('focus_area')} in a guided real-world exercise", "type": "lab"})
            session["topics"] = topics[:5]
            day[key] = session
        if not day.get("learning_objectives"):
            day["learning_objectives"] = fallback_day.get("learning_objectives") or [
                f"Understand {day.get('focus_area')} concepts",
                f"Use {day.get('tools')} in practical exercises",
                "Complete hands-on activities with review",
            ]
        if not day.get("jira_practice"):
            day["jira_practice"] = fallback_day.get("jira_practice") or [
                day.get("jira_focus"),
                "Create or update stories, subtasks, acceptance criteria, and story points",
                "Move tasks across the sprint board and review progress",
            ]
        days[index] = day

    if days:
        last = days[-1]
        if "capstone" not in str(last.get("title", "")).lower() and expected_days >= 5:
            last["title"] = f"Day {expected_days}: Capstone Project + Certification Roadmap"
            last["focus_area"] = "Capstone Project + Certification Roadmap"
            last["jira_focus"] = "Final sprint review, retrospective, release notes, and stakeholder demo"
            last["learning_objectives"] = [
                "Integrate the complete training toolchain into one end-to-end solution",
                "Demonstrate the final project and explain design decisions",
                "Review certification roadmap and interview preparation areas",
            ]
            last["jira_practice"] = [
                "Run final sprint review and retrospective",
                "Create release notes and close completed epics",
                "Export sprint metrics for stakeholder reporting",
            ]

    toc_data["days"] = days
    toc_data.setdefault("title", fallback.get("title"))
    toc_data.setdefault("subtitle", fallback.get("subtitle"))
    toc_data.setdefault("overview", fallback.get("overview"))
    toc_data["overview_table"] = [
        {
            "day": day.get("day"),
            "focus_area": day.get("focus_area"),
            "primary_tools": day.get("tools"),
            "jira_focus": day.get("jira_focus"),
        }
        for day in days
    ]
    for key in ("prerequisites", "learning_outcomes", "tools_software", "tools_reference", "certification_roadmap"):
        if not toc_data.get(key):
            toc_data[key] = fallback.get(key) or []
    if not toc_data.get("certification_guidance"):
        toc_data["certification_guidance"] = fallback.get("certification_guidance")
    if not toc_data.get("trainer_notes"):
        toc_data["trainer_notes"] = "Generated by the Training TOC Agent with day-count validation."
    toc_data["validation"] = {
        "requested_days": expected_days,
        "generated_days": len(days),
        "valid": len(days) == expected_days,
        "rules": [
            "Exact day count matched",
            "Every day has topics, tools, lab content, and Jira practice",
            "Capstone/certification roadmap reserved for final stage",
        ],
    }
    return toc_data


def _clean_filename(value: str) -> str:
    cleaned = _re.sub(r"[^A-Za-z0-9._-]+", "_", value or "toc").strip("_")
    return cleaned[:80] or "toc"


def _toc_html(doc: dict) -> str:
    toc = doc.get("toc_data") or {}

    def esc(value):
        return _html.escape(str(value or ""))

    def li(items):
        return "".join(f"<li>{esc(item)}</li>" for item in (items or []))

    day_blocks = []
    for day in toc.get("days") or []:
        sessions = []
        for key, label in (("morning_session", "Morning Session"), ("afternoon_session", "Afternoon Session")):
            session = day.get(key) or {}
            rows = "".join(
                f"<tr><td>{esc(topic.get('time'))}</td><td>{esc(topic.get('topic'))}</td><td>{esc(topic.get('type'))}</td></tr>"
                for topic in (session.get("topics") or [])
            )
            sessions.append(f"""
              <div class="session">
                <h4>{label}: {esc(session.get('title'))}</h4>
                <p class="time">{esc(session.get('time'))}</p>
                <table>
                  <thead><tr><th>Time</th><th>Topic</th><th>Type</th></tr></thead>
                  <tbody>{rows}</tbody>
                </table>
              </div>
            """)
        day_blocks.append(f"""
          <section class="day">
            <h3>{esc(day.get('title') or f"Day {day.get('day', '')}")}</h3>
            {''.join(sessions)}
          </section>
        """)

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>{esc(toc.get('title'))}</title>
  <style>
    body {{ font-family: Arial, sans-serif; color:#1f2937; margin:0; background:#f8fafc; }}
    .page {{ width: 900px; margin: 0 auto; background:#fff; padding: 44px; }}
    .brand {{ color:#2563eb; font-weight:700; font-size:13px; letter-spacing:.08em; text-transform:uppercase; }}
    h1 {{ margin:8px 0 6px; font-size:30px; color:#0f172a; }}
    h2 {{ margin:0 0 18px; font-size:16px; color:#475569; font-weight:500; }}
    h3 {{ margin:26px 0 12px; padding:10px 12px; background:#eff6ff; color:#1d4ed8; border-radius:8px; }}
    h4 {{ margin:14px 0 4px; font-size:15px; color:#0f172a; }}
    .meta, .overview, .box {{ border:1px solid #e2e8f0; border-radius:10px; padding:14px; margin:14px 0; }}
    .meta {{ display:grid; grid-template-columns:repeat(2,1fr); gap:8px; font-size:13px; }}
    .time {{ margin:0 0 8px; color:#64748b; font-size:12px; }}
    table {{ width:100%; border-collapse:collapse; margin:8px 0 14px; font-size:12px; }}
    th {{ text-align:left; background:#f1f5f9; color:#334155; }}
    th, td {{ border:1px solid #e2e8f0; padding:8px; vertical-align:top; }}
    ul {{ margin:8px 0 0 20px; padding:0; }}
    li {{ margin:5px 0; }}
    .footer {{ margin-top:28px; padding-top:14px; border-top:1px solid #e2e8f0; color:#64748b; font-size:12px; }}
  </style>
</head>
<body>
  <div class="page">
    <div class="brand">Clahan Technologies · TrainerSync</div>
    <h1>{esc(toc.get('title'))}</h1>
    <h2>{esc(toc.get('subtitle'))}</h2>
    <div class="meta">
      <div><strong>Technology:</strong> {esc(doc.get('technology'))}</div>
      <div><strong>Trainer:</strong> {esc(doc.get('trainer_name'))}</div>
      <div><strong>Duration:</strong> {esc(doc.get('duration_days'))} day(s)</div>
      <div><strong>Mode:</strong> {esc(doc.get('mode'))}</div>
      <div><strong>Audience:</strong> {esc(doc.get('audience_level'))}</div>
      <div><strong>Reference:</strong> {esc(doc.get('toc_id'))}</div>
    </div>
    <div class="overview"><strong>Program Overview</strong><br>{esc(toc.get('overview'))}</div>
    <div class="box"><strong>Prerequisites</strong><ul>{li(toc.get('prerequisites'))}</ul></div>
    <div class="box"><strong>Learning Outcomes</strong><ul>{li(toc.get('learning_outcomes'))}</ul></div>
    {''.join(day_blocks)}
    <div class="box"><strong>Tools & Software</strong><ul>{li(toc.get('tools_software'))}</ul></div>
    <div class="box"><strong>Hiring & Test Preparation</strong><ul>{li(toc.get('hiring_preparation'))}</ul></div>
    <div class="box"><strong>Assessment Plan</strong><ul>{li(toc.get('assessment_plan'))}</ul></div>
    <div class="box"><strong>Certification Guidance</strong><br>{esc(toc.get('certification_guidance'))}</div>
    <div class="box"><strong>Trainer Notes</strong><br>{esc(toc.get('trainer_notes'))}</div>
    <div class="footer">Generated by TrainerSync for Clahan Technologies.</div>
  </div>
</body>
</html>"""


def _toc_pdf_bytes(doc: dict) -> bytes:
    toc = doc.get("toc_data") or {}
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    margin = 42
    y = 42

    def new_page():
        nonlocal page, y
        page = pdf.new_page(width=595, height=842)
        y = 42

    def write(text: str, size: int = 10, color=(31 / 255, 41 / 255, 55 / 255), bold: bool = False, gap: int = 8):
        nonlocal y
        text = str(text or "")
        font = "helv"
        rect = fitz.Rect(margin, y, 553, 820)
        needed = max(18, (len(text) // 85 + 1) * (size + 4))
        if y + needed > 810:
            new_page()
            rect = fitz.Rect(margin, y, 553, 820)
        consumed = page.insert_textbox(rect, text, fontsize=size, fontname=font, color=color, align=0)
        y += max(needed, abs(consumed) if consumed < 0 else needed) + gap

    def bullet_list(title: str, items: list):
        write(title, size=13, bold=True, color=(15 / 255, 23 / 255, 42 / 255), gap=4)
        for item in items or []:
            write(f"- {item}", size=9, gap=2)
        y_gap(6)

    def y_gap(amount: int):
        nonlocal y
        y += amount

    write("Clahan Technologies | TrainerSync", size=9, bold=True, color=(37 / 255, 99 / 255, 235 / 255), gap=10)
    write(toc.get("title", "Training Table of Contents"), size=20, bold=True, color=(15 / 255, 23 / 255, 42 / 255), gap=4)
    write(toc.get("subtitle", ""), size=11, color=(71 / 255, 85 / 255, 105 / 255), gap=14)
    write(f"Technology: {doc.get('technology', '')} | Duration: {doc.get('duration_days', '')} day(s) | Mode: {doc.get('mode', '')} | Trainer: {doc.get('trainer_name', '')}", size=9, gap=12)
    write("Program Overview", size=13, bold=True, color=(15 / 255, 23 / 255, 42 / 255), gap=4)
    write(toc.get("overview", ""), size=10, gap=10)
    if toc.get("overview_table"):
        write("Program Roadmap", size=13, bold=True, color=(15 / 255, 23 / 255, 42 / 255), gap=4)
        for row in toc.get("overview_table") or []:
            write(
                f"Day {row.get('day')}: {row.get('focus_area')} | Tools: {row.get('primary_tools')} | Jira: {row.get('jira_focus')}",
                size=8,
                gap=2,
            )
        y_gap(8)
    bullet_list("Prerequisites", toc.get("prerequisites", []))
    bullet_list("Learning Outcomes", toc.get("learning_outcomes", []))

    for day in toc.get("days") or []:
        write(day.get("title") or f"Day {day.get('day', '')}", size=14, bold=True, color=(29 / 255, 78 / 255, 216 / 255), gap=6)
        if day.get("tools") or day.get("jira_focus"):
            write(f"Tools: {day.get('tools', '')} | Jira Focus: {day.get('jira_focus', '')}", size=9, gap=5)
        for key, label in (("morning_session", "Morning Session"), ("afternoon_session", "Afternoon Session")):
            session = day.get(key) or {}
            write(f"{label}: {session.get('title', '')} ({session.get('time', '')})", size=11, bold=True, gap=4)
            for topic in session.get("topics") or []:
                write(f"{topic.get('time', '')} - {topic.get('topic', '')} [{topic.get('type', '')}]", size=8, gap=1)
            y_gap(5)
        bullet_list("Learning Objectives", day.get("learning_objectives", []))
        bullet_list("Jira Practice", day.get("jira_practice", []))

    bullet_list("Tools & Software", toc.get("tools_software", []))
    bullet_list("Hiring & Test Preparation", toc.get("hiring_preparation", []))
    bullet_list("Assessment Plan", toc.get("assessment_plan", []))
    for ref in toc.get("tools_reference") or []:
        bullet_list(ref.get("category") or "Tools Reference", ref.get("items") or [])
    if toc.get("certification_roadmap"):
        bullet_list("Certification Roadmap", toc.get("certification_roadmap", []))
    write("Certification Guidance", size=13, bold=True, gap=4)
    write(toc.get("certification_guidance", ""), size=10, gap=8)
    write("Trainer Notes", size=13, bold=True, gap=4)
    write(toc.get("trainer_notes", ""), size=10, gap=8)

    out = pdf.tobytes()
    pdf.close()
    return out


def _send_toc_email_with_attachment(to_email: str, subject: str, body: str, filename: str, pdf_bytes: bytes, smtp_config: dict) -> tuple:
    smtp_config = smtp_config or {}
    settings = get_settings()
    gmail_user = smtp_config.get("smtpUser") or getattr(settings, "gmail_user", "")
    gmail_pass = (smtp_config.get("smtpPass") or get_gmail_password()).replace(" ", "")
    from_name = smtp_config.get("fromName") or getattr(settings, "from_name", "TrainerSync")
    from_email = smtp_config.get("fromEmail") or getattr(settings, "from_email", "") or gmail_user
    smtp_host = smtp_config.get("smtpHost") or "smtp.gmail.com"
    smtp_port = int(smtp_config.get("smtpPort") or 587)
    can_use_gmail_oauth = (
        "gmail" in str(smtp_host or "").lower()
        or str(gmail_user or "").lower().endswith("@gmail.com")
        or str(from_email or "").lower().endswith("@gmail.com")
        or bool(smtp_config.get("useGmailOAuth"))
    )

    if not gmail_user or not gmail_pass:
        if can_use_gmail_oauth:
            return send_gmail_oauth_message(
                to_email,
                subject,
                body,
                from_name,
                attachments=[{"filename": filename, "content": pdf_bytes, "subtype": "pdf"}],
            )
        return False, "Gmail credentials not set in .env or Admin email settings"

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email
    msg["Reply-To"] = from_email
    msg.attach(MIMEText(body, "plain", "utf-8"))
    attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
    attachment.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(attachment)

    try:
        try:
            ssl_port = 465 if smtp_port == 587 else smtp_port
            with smtplib.SMTP_SSL(smtp_host, ssl_port, timeout=20) as server:
                server.login(gmail_user, gmail_pass)
                server.sendmail(from_email, [to_email], msg.as_string())
        except Exception:
            starttls_port = smtp_port if smtp_port != 465 else 587
            with smtplib.SMTP(smtp_host, starttls_port, timeout=20) as server:
                server.ehlo()
                server.starttls()
                server.login(gmail_user, gmail_pass)
                server.sendmail(from_email, [to_email], msg.as_string())
        return True, ""
    except Exception as exc:
        if can_use_gmail_oauth:
            return send_gmail_oauth_message(
                to_email,
                subject,
                body,
                from_name,
                attachments=[{"filename": filename, "content": pdf_bytes, "subtype": "pdf"}],
            )
        return False, str(exc)


def _send_email_with_file_attachment(
    to_email: str,
    subject: str,
    body: str,
    filename: str,
    file_bytes: bytes,
    smtp_config: dict,
    subtype: str = "octet-stream",
) -> tuple:
    smtp_config = smtp_config or {}
    settings = get_settings()
    smtp_user = smtp_config.get("smtpUser") or getattr(settings, "gmail_user", "")
    smtp_pass = (smtp_config.get("smtpPass") or get_gmail_password()).replace(" ", "")
    from_name = smtp_config.get("fromName") or getattr(settings, "from_name", "TrainerSync")
    from_email = smtp_config.get("fromEmail") or getattr(settings, "from_email", "") or smtp_user
    smtp_host = smtp_config.get("smtpHost") or "smtp.gmail.com"
    smtp_port = int(smtp_config.get("smtpPort") or 587)
    can_use_gmail_oauth = (
        "gmail" in str(smtp_host or "").lower()
        or str(smtp_user or "").lower().endswith("@gmail.com")
        or str(from_email or "").lower().endswith("@gmail.com")
        or bool(smtp_config.get("useGmailOAuth"))
    )

    if not smtp_user or not smtp_pass:
        if can_use_gmail_oauth:
            return send_gmail_oauth_message(
                to_email,
                subject,
                body,
                from_name,
                attachments=[{"filename": filename, "content": file_bytes, "subtype": subtype}],
            )
        return False, "SMTP credentials not set in Admin email settings"

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email
    msg["Reply-To"] = from_email
    msg.attach(MIMEText(body, "plain", "utf-8"))
    attachment = MIMEApplication(file_bytes, _subtype=subtype)
    attachment.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(attachment)

    try:
        try:
            ssl_port = 465 if smtp_port == 587 else smtp_port
            with smtplib.SMTP_SSL(smtp_host, ssl_port, timeout=30) as server:
                server.login(smtp_user, smtp_pass)
                server.sendmail(from_email, [to_email], msg.as_string())
        except Exception:
            starttls_port = smtp_port if smtp_port != 465 else 587
            with smtplib.SMTP(smtp_host, starttls_port, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(from_email, [to_email], msg.as_string())
        return True, ""
    except Exception as exc:
        if can_use_gmail_oauth:
            return send_gmail_oauth_message(
                to_email,
                subject,
                body,
                from_name,
                attachments=[{"filename": filename, "content": file_bytes, "subtype": subtype}],
            )
        return False, str(exc)


def _list_text(value) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    if isinstance(value, dict):
        return " ".join(f"{key} {val}" for key, val in value.items())
    return str(value or "")


def _category_combined_text(trainer: dict, category_data: dict) -> str:
    parts = [
        trainer.get("name", ""),
        trainer.get("technologies", ""),
        _list_text(trainer.get("skills", [])),
        _list_text(trainer.get("certifications", [])),
        trainer.get("summary", ""),
        category_data.get("primary_category", ""),
        category_data.get("domain", ""),
        _list_text(category_data.get("secondary_categories", [])),
        _list_text(category_data.get("specialisation_tags", [])),
        _list_text(category_data.get("industry_focus", [])),
        _list_text(category_data.get("language_of_delivery", [])),
        _list_text(category_data.get("skill_level_map", {})),
        trainer.get("resume", "")[:50000],
    ]
    return " ".join(parts).lower()


async def _distinct_non_empty(db, field: str) -> List[str]:
    values = await db["trainers"].distinct(field, {field: {"$nin": [None, ""]}})
    cleaned = {str(value).strip() for value in values if str(value).strip()}
    return sorted(cleaned, key=lambda item: item.lower())


async def _software_domains(db) -> List[str]:
    existing = await _distinct_non_empty(db, "domain")
    software_existing = [domain for domain in existing if is_software_domain(domain)]
    return sorted(set(SOFTWARE_TECH_DOMAINS + software_existing), key=lambda item: item.lower())


async def _categorise_and_update_trainer(db, trainer: dict) -> dict:
    category_data = await categorise_trainer(trainer)
    update_fields = category_update_fields(category_data)
    update_fields["combined_text"] = _category_combined_text(trainer, category_data)
    await db["trainers"].update_one(
        {"trainer_id": trainer["trainer_id"]},
        {
            "$set": update_fields,
            "$unset": {"categorisation_error": "", "categorisation_failed_at": ""},
        },
    )
    updated = await db["trainers"].find_one({"trainer_id": trainer["trainer_id"]}, {"_id": 0})
    return {"category": category_data, "trainer": updated}


async def _categorise_trainer_by_id(db, trainer_id: str) -> dict:
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0})
    if not trainer:
        raise HTTPException(404, "Trainer not found")
    return await _categorise_and_update_trainer(db, trainer)


async def _categorise_trainers_background(trainer_ids: List[str]):
    db = get_db()
    for trainer_id in dict.fromkeys(trainer_ids):
        try:
            await _categorise_trainer_by_id(db, trainer_id)
        except Exception as exc:
            await db["trainers"].update_one(
                {"trainer_id": trainer_id},
                {"$set": {
                    "categorisation_error": str(exc),
                    "categorisation_failed_at": utc_now(),
                }},
            )


async def _run_categorisation_job(job_id: str):
    db = get_db()
    CATEGORISATION_JOBS[job_id].update({
        "status": "running",
        "started_at": utc_now(),
    })
    try:
        result = await bulk_categorise_all(db)
        CATEGORISATION_JOBS[job_id].update({
            **result,
            "status": "completed",
            "completed_at": utc_now(),
        })
    except Exception as exc:
        CATEGORISATION_JOBS[job_id].update({
            "status": "failed",
            "error": str(exc),
            "completed_at": utc_now(),
        })


# --- Admin Settings ---------------------------------------------------------

@router.get("/admin/settings")
async def get_admin_settings():
    db = get_db()
    settings = await db["admin_settings"].find_one(
        {"settings_id": "default"},
        {"_id": 0},
    )
    return settings or {}


@router.post("/admin/settings")
async def save_admin_settings(payload: dict):
    db = get_db()
    existing = await db["admin_settings"].find_one(
        {"settings_id": "default"},
        {"_id": 0, "emailCfg": 1, "teamsDirectCfg": 1},
    ) or {}
    incoming_email = payload.get("emailCfg")
    if isinstance(incoming_email, dict):
        existing_email = existing.get("emailCfg") or {}
        for password_key in ("smtpPass", "imapPass"):
            if not incoming_email.get(password_key) and existing_email.get(password_key):
                incoming_email[password_key] = existing_email.get(password_key)

    incoming_teams_direct = payload.get("teamsDirectCfg")
    if isinstance(incoming_teams_direct, dict):
        existing_teams_direct = existing.get("teamsDirectCfg") or {}
        for token_key in ("accessToken", "refreshToken", "expiresAt"):
            if not incoming_teams_direct.get(token_key) and existing_teams_direct.get(token_key):
                incoming_teams_direct[token_key] = existing_teams_direct.get(token_key)

    payload = {
        **payload,
        "settings_id": "default",
        "updated_at": utc_now(),
    }
    await db["admin_settings"].update_one(
        {"settings_id": "default"},
        {"$set": payload},
        upsert=True,
    )
    return {"message": "Admin settings saved"}


@router.post("/admin/email/test")
async def test_email_settings(payload: dict = {}):
    db = get_db()
    cfg = await get_admin_email_config(db)
    to_email = str(
        payload.get("to_email")
        or cfg.get("fromEmail")
        or cfg.get("smtpUser")
        or getattr(get_settings(), "from_email", "")
        or getattr(get_settings(), "gmail_user", "")
    ).strip()
    if not to_email:
        raise HTTPException(400, "Enter SMTP username or From Email before testing email")

    subject = "TrainerSync SMTP Test"
    body = (
        "Hello,\n\n"
        "This is a TrainerSync SMTP test email. Your email sending configuration is connected.\n\n"
        "Regards,\nTrainerSync Team"
    )
    success, error = await send_email_async(to_email, subject, body, cfg)
    if not success:
        raise HTTPException(400, error or "Email test failed")
    return {"message": "Test email sent", "to_email": to_email}


@router.post("/admin/whatsapp/test")
async def test_whatsapp_settings(request: Request):
    db = get_db()
    cfg = await get_twilio_config(db)
    provider_name = (
        "AiSensy" if cfg.get("provider") == "aisensy"
        else "Meta Cloud API" if cfg.get("provider") == "meta"
        else "Twilio"
    )
    campaign_note = ""
    if cfg.get("provider") == "aisensy":
        campaign_note = f"\nCampaign: {cfg.get('aisensyCampaignName') or '-'}\nTemplate Params: {cfg.get('aisensyTemplateParamFields') or 'message'}"
    elif cfg.get("provider") == "meta":
        campaign_note = f"\nTemplate: {cfg.get('metaTemplateName') or 'text message'}\nLanguage: {cfg.get('metaLanguageCode') or 'en_US'}"
    result = await send_whatsapp_message(
        db,
        cfg.get("vendorWhatsAppNumber", ""),
        (
            "Dear Admin,\n\n"
            f"TrainerSync WhatsApp test message. Your {provider_name} configuration is connected."
            f"{campaign_note}\n\n"
            "Regards,\nTrainerSync Team"
        ),
        event_type="admin_test",
        recipient_type="vendor",
        request_base_url=_request_base_url(request),
        context={"source": "admin_settings", "provider": cfg.get("provider")},
    )
    if not result.get("success"):
        raise HTTPException(400, result.get("error") or "WhatsApp test failed")
    return {"message": "WhatsApp test sent", **result}


@router.get("/teams-direct/oauth-url")
async def teams_direct_oauth_url():
    db = get_db()
    cfg = await get_teams_direct_config(db)
    missing = [name for name in ("clientId", "redirectUri") if not cfg.get(name)]
    if missing:
        raise HTTPException(400, f"Missing Microsoft Graph settings: {', '.join(missing)}")
    return {
        "auth_url": microsoft_oauth_url(cfg),
        "redirect_uri": cfg.get("redirectUri"),
    }


@router.get("/teams-direct/status")
async def teams_direct_status():
    db = get_db()
    cfg = await get_teams_direct_config(db)
    now_ts = int(datetime.now(timezone.utc).timestamp())
    token_valid = bool(cfg.get("accessToken")) and int(cfg.get("expiresAt") or 0) > now_ts + 60
    has_refresh_token = bool(cfg.get("refreshToken"))
    return {
        "enabled": bool(cfg.get("enabled")),
        "connected": bool(cfg.get("enabled")) and (token_valid or has_refresh_token),
        "token_valid": token_valid,
        "has_refresh_token": has_refresh_token,
        "sender_user": cfg.get("senderUser", ""),
        "redirect_uri": cfg.get("redirectUri", ""),
    }


@router.get("/teams-direct/oauth-callback")
async def teams_direct_oauth_callback(code: str = "", error: str = "", error_description: str = ""):
    db = get_db()
    if error:
        message = error_description or error
        return Response(
            content=f"<h2>Teams authorization failed</h2><p>{_html.escape(message)}</p>",
            media_type="text/html",
            status_code=400,
        )
    if not code:
        return Response(
            content="<h2>Teams authorization failed</h2><p>Missing authorization code.</p>",
            media_type="text/html",
            status_code=400,
        )
    result = await exchange_microsoft_code(db, code)
    if not result.get("success"):
        return Response(
            content=f"<h2>Teams authorization failed</h2><p>{_html.escape(result.get('error', 'Unknown error'))}</p>",
            media_type="text/html",
            status_code=400,
        )
    return Response(
        content=(
            "<h2>Teams direct chat connected</h2>"
            "<p>You can close this tab and return to TrainerSync.</p>"
        ),
        media_type="text/html",
    )


@router.post("/admin/teams-direct/test")
async def test_teams_direct_settings(payload: dict):
    db = get_db()
    teams_email = str(payload.get("teams_email") or "").strip()
    if not teams_email:
        raise HTTPException(400, "Enter a trainer Teams email for the direct chat test")
    result = await send_trainer_teams_direct_message(
        db,
        trainer={
            "trainer_id": "TEAMS-DIRECT-TEST",
            "name": payload.get("trainer_name") or "Teams Direct Test",
            "teams_email": teams_email,
        },
        subject="TrainerSync Teams Direct Chat Test",
        body=(
            "Dear Trainer,\n\n"
            "This is a TrainerSync direct Microsoft Teams test message.\n\n"
            "Regards,\nTrainerSync Team"
        ),
        requirement_id="ADMIN-TEST",
        mail_type="admin_test",
        email_id=f"EMAIL-{uuid.uuid4().hex[:8].upper()}",
    )
    if not result.get("success"):
        raise HTTPException(400, result.get("error") or "Teams direct chat test failed")
    return {"message": "Teams direct chat test sent", **result}


@router.post("/auth/forgot-password")
async def forgot_password(payload: dict):
    email = (payload.get("email") or "").strip()
    if not email or "@" not in email:
        raise HTTPException(400, "Enter a valid email address")

    db = get_db()
    reset_link = "http://localhost:5173/login?reset=1"
    subject = "Reset your TrainerSync password"
    body = (
        "Hello,\n\n"
        "We received a request to reset your TrainerSync password.\n\n"
        f"Reset link: {reset_link}\n\n"
        "If you did not request this, you can ignore this email.\n\n"
        "Regards,\n"
        "TrainerSync Team"
    )
    smtp_config = await get_admin_email_config(db)
    success, error = await send_email_async(email, subject, body, smtp_config)
    if not success:
        raise HTTPException(500, error or "Could not send reset email")

    await db["password_reset_logs"].insert_one({
        "email": email,
        "status": "sent",
        "sent_at": utc_now(),
    })
    return {"message": "Reset email sent"}


@router.get("/email-open/{email_id}", name="track_email_open")
async def track_email_open(email_id: str, request: Request):
    db = get_db()
    now = utc_now()
    user_agent = request.headers.get("user-agent", "")
    client_ip = request.client.host if request.client else ""
    existing = await db["email_logs"].find_one({"email_id": email_id}, {"_id": 0, "opened_at": 1, "open_count": 1})

    set_fields = {
        "opened": True,
        "last_opened_at": now,
        "last_open_user_agent": user_agent,
        "last_open_ip": client_ip,
    }
    if not existing or not existing.get("opened_at"):
        set_fields["opened_at"] = now
    await db["email_logs"].update_one(
        {"email_id": email_id},
        {
            "$set": set_fields,
            "$inc": {"open_count": 1},
        },
    )
    log = await db["email_logs"].find_one({"email_id": email_id}, {"_id": 0})
    if log:
        await db["conversations"].update_one(
            {"email_id": email_id},
            {
                "$set": {
                    "opened": True,
                    "opened_at": log.get("opened_at") or now,
                    "last_opened_at": now,
                    "open_count": (existing or {}).get("open_count", 0) + 1,
                }
            },
        )

    return Response(
        content=TRACKING_PIXEL,
        media_type="image/gif",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@router.post("/whatsapp/status-callback")
async def whatsapp_status_callback(request: Request):
    db = get_db()
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload = await request.json()
    else:
        form = await request.form()
        payload = dict(form)
    return await update_whatsapp_status(db, payload)


@router.post("/whatsapp/inbound-callback")
async def whatsapp_inbound_callback(request: Request):
    db = get_db()
    form = await request.form()
    payload = dict(form)
    from_number = payload.get("From", "")
    to_number = payload.get("To", "")
    body = payload.get("Body", "")
    message_sid = payload.get("MessageSid") or payload.get("SmsSid") or ""
    existing = await db["whatsapp_logs"].find_one({"twilio_sid": message_sid}, {"_id": 1}) if message_sid else None
    if not existing:
        await db["whatsapp_logs"].insert_one({
            "whatsapp_id": f"WA-{uuid.uuid4().hex[:10].upper()}",
            "direction": "inbound",
            "event_type": "whatsapp_reply",
            "recipient_type": "trainer",
            "to_number": to_number,
            "from_number": from_number,
            "body": body,
            "status": "received",
            "twilio_sid": message_sid,
            "twilio_response": payload,
            "context": {"source": "twilio_inbound"},
            "created_at": utc_now(),
            "updated_at": utc_now(),
        })
    reply_text = "Thanks for your response. TrainerSync has received your WhatsApp message and will update the trainer pipeline shortly."
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Message>{_html.escape(reply_text)}</Message></Response>"
    )
    return Response(content=twiml, media_type="application/xml")


async def _meta_whatsapp_verify_token(db) -> str:
    settings_doc = await db["admin_settings"].find_one(
        {"settings_id": "default"},
        {"_id": 0, "twilioCfg.metaVerifyToken": 1},
    )
    cfg = (settings_doc or {}).get("twilioCfg") or {}
    return (
        str(cfg.get("metaVerifyToken") or "").strip()
        or os.getenv("META_WHATSAPP_VERIFY_TOKEN", "").strip()
        or "trainersync_whatsapp_verify_2026"
    )


def _meta_message_text(message: dict) -> str:
    msg_type = str(message.get("type") or "").strip().lower()
    if msg_type == "text":
        return str((message.get("text") or {}).get("body") or "").strip()
    if msg_type == "button":
        return str((message.get("button") or {}).get("text") or "").strip()
    if msg_type == "interactive":
        interactive = message.get("interactive") or {}
        button_reply = interactive.get("button_reply") or {}
        list_reply = interactive.get("list_reply") or {}
        return str(button_reply.get("title") or list_reply.get("title") or "").strip()
    return str(message.get(msg_type) or "").strip()


@router.get("/whatsapp/meta/webhook")
async def whatsapp_meta_webhook_verify(request: Request):
    db = get_db()
    params = request.query_params
    mode = params.get("hub.mode") or params.get("hub_mode")
    token = params.get("hub.verify_token") or params.get("hub_verify_token")
    challenge = params.get("hub.challenge") or params.get("hub_challenge")
    expected_token = await _meta_whatsapp_verify_token(db)

    if mode == "subscribe" and token == expected_token and challenge:
        return Response(content=str(challenge), media_type="text/plain")
    raise HTTPException(status_code=403, detail="WhatsApp webhook verification failed")


@router.post("/whatsapp/meta/webhook")
async def whatsapp_meta_webhook(request: Request):
    db = get_db()
    payload = await request.json()
    processed = {"statuses": 0, "messages": 0}

    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value") or {}
            metadata = value.get("metadata") or {}
            display_phone = metadata.get("display_phone_number") or ""
            phone_number_id = metadata.get("phone_number_id") or ""

            for status_item in value.get("statuses", []) or []:
                errors = status_item.get("errors") or []
                status_payload = {
                    **status_item,
                    "messageId": status_item.get("id") or "",
                    "status": status_item.get("status") or "",
                    "recipient": status_item.get("recipient_id") or "",
                    "phone_number_id": phone_number_id,
                    "display_phone_number": display_phone,
                }
                if errors:
                    status_payload["error_message"] = (
                        errors[0].get("message")
                        or errors[0].get("title")
                        or errors[0].get("details")
                        or ""
                    )
                    status_payload["error_code"] = errors[0].get("code") or ""
                await update_whatsapp_status(db, status_payload)
                processed["statuses"] += 1

            contacts_by_wa_id = {
                str(contact.get("wa_id") or ""): contact
                for contact in value.get("contacts", []) or []
            }
            for message in value.get("messages", []) or []:
                from_number = str(message.get("from") or "").strip()
                message_id = str(message.get("id") or "").strip()
                if not message_id:
                    continue
                existing = await db["whatsapp_logs"].find_one(
                    {"meta_message_id": message_id, "direction": "inbound"},
                    {"_id": 1},
                )
                if existing:
                    continue
                contact = contacts_by_wa_id.get(from_number) or {}
                await db["whatsapp_logs"].insert_one({
                    "whatsapp_id": f"WA-{uuid.uuid4().hex[:10].upper()}",
                    "provider": "meta",
                    "direction": "inbound",
                    "event_type": "whatsapp_reply",
                    "recipient_type": "trainer",
                    "from_number": from_number,
                    "to_number": display_phone,
                    "body": _meta_message_text(message),
                    "status": "received",
                    "meta_message_id": message_id,
                    "meta_phone_number_id": phone_number_id,
                    "meta_contact": contact,
                    "meta_payload": message,
                    "context": {"source": "meta_webhook"},
                    "created_at": utc_now(),
                    "updated_at": utc_now(),
                })
                processed["messages"] += 1

    return {"received": True, **processed}


# --- AI Training TOC Generator ---------------------------------------------

TOC_LEVELS = ("foundation", "core", "advanced", "observability", "security", "projects", "revision", "capstone")


def _toc_key(value: str) -> str:
    return str(value or "").lower().strip().replace(" ", "_").replace(".", "_").replace("/", "_").replace("-", "_")


def _toc_key_tokens(value: str) -> set:
    stopwords = {
        "and", "or", "plus", "with", "for", "training", "course", "program",
        "technology", "technologies", "basic", "basics", "advanced",
    }
    return {token for token in _toc_key(value).split("_") if token and token not in stopwords}


def _clean_toc_topic(item: dict) -> dict:
    item = item or {}
    return {
        "topic": str(item.get("topic") or "").strip(),
        "subtopics": [str(v).strip() for v in (item.get("subtopics") or []) if str(v).strip()],
        "tools": [str(v).strip() for v in (item.get("tools") or []) if str(v).strip()],
        "lab": str(item.get("lab") or "").strip(),
    }


def _domain_doc_to_agent_domain(doc: dict) -> dict:
    doc = doc or {}
    source_map = doc.get("level_map") or {}
    level_map = {}
    for level in TOC_LEVELS:
        topics = [_clean_toc_topic(item) for item in (source_map.get(level) or [])]
        level_map[level] = [item for item in topics if item.get("topic")]
    return {
        "name": doc.get("name") or doc.get("key") or "Training",
        "icon": doc.get("icon") or "book",
        "level_map": level_map,
        "jira_practice": {
            "daily": [str(v).strip() for v in ((doc.get("jira_practice") or {}).get("daily") or []) if str(v).strip()],
            "weekly": [str(v).strip() for v in ((doc.get("jira_practice") or {}).get("weekly") or []) if str(v).strip()],
        },
        "certifications": [str(v).strip() for v in (doc.get("certifications") or []) if str(v).strip()],
    }


def _public_toc_domain_doc(doc: dict) -> dict:
    public = _public_doc(doc or {})
    public.setdefault("aliases", [])
    public.setdefault("level_map", {})
    public.setdefault("jira_practice", {"daily": [], "weekly": []})
    public.setdefault("certifications", [])
    return public


def _split_toc_list(value) -> list:
    if isinstance(value, list):
        values = value
    else:
        values = _re.split(r"[\n,]+", str(value or ""))
    return [str(item).strip(" -\t\r") for item in values if str(item).strip(" -\t\r")]


def _parse_toc_topic_section(raw: str, tools: list, labs: list) -> list:
    topics = []
    current = None
    for line in str(raw or "").splitlines():
        if not line.strip():
            continue
        stripped = line.strip()
        topic_match = _re.match(r"^\d+\.\s+(.+)$", stripped)
        bullet_match = _re.match(r"^[-*]\s+(.+)$", stripped)
        is_indented = bool(_re.match(r"^\s{2,}[-*]\s+", line))

        if topic_match or (bullet_match and not is_indented):
            if current and current.get("topic"):
                topics.append(current)
            name = (topic_match.group(1) if topic_match else bullet_match.group(1)).strip()
            current = {
                "topic": name,
                "subtopics": [],
                "tools": tools[:],
                "lab": labs[len(topics) % len(labs)] if labs else f"Hands-on practice for {name}",
            }
            continue

        subtopic_match = _re.match(r"^[-*]\s+(.+)$", stripped)
        if subtopic_match and current:
            current["subtopics"].append(subtopic_match.group(1).strip())
        elif current:
            current["subtopics"].append(stripped)
        else:
            current = {
                "topic": stripped,
                "subtopics": [],
                "tools": tools[:],
                "lab": labs[0] if labs else f"Hands-on practice for {stripped}",
            }

    if current and current.get("topic"):
        topics.append(current)
    return [_clean_toc_topic(item) for item in topics if item.get("topic")]


def _parse_toc_knowledge_blocks(text: str) -> list:
    clean_text = _re.sub(r"^\s*```.*?$", "", str(text or ""), flags=_re.MULTILINE).replace("\r\n", "\n")
    matches = list(_re.finditer(r"(?im)^Technology Name:\s*(.+?)\s*$", clean_text))
    parsed = []
    section_pattern = _re.compile(
        r"(?im)^(Aliases|Foundation Topics|Core Topics|Advanced Topics|Project Topics|Projects|Capstone|Tools|Labs|Certifications):\s*$"
    )

    for index, match in enumerate(matches):
        block = clean_text[match.start(): matches[index + 1].start() if index + 1 < len(matches) else len(clean_text)]
        name = match.group(1).strip()
        sections = {}
        section_matches = list(section_pattern.finditer(block))
        for sec_index, sec_match in enumerate(section_matches):
            label = sec_match.group(1).lower().replace(" ", "_")
            start = sec_match.end()
            end = section_matches[sec_index + 1].start() if sec_index + 1 < len(section_matches) else len(block)
            sections[label] = block[start:end].strip()

        aliases = [_toc_key(item) for item in _split_toc_list(sections.get("aliases"))]
        tools = _split_toc_list(sections.get("tools"))
        labs = _split_toc_list(sections.get("labs"))
        certifications = _split_toc_list(sections.get("certifications"))
        projects_raw = sections.get("project_topics") or sections.get("projects") or ""

        level_map = {level: [] for level in TOC_LEVELS}
        level_map["foundation"] = _parse_toc_topic_section(sections.get("foundation_topics", ""), tools, labs)
        level_map["core"] = _parse_toc_topic_section(sections.get("core_topics", ""), tools, labs)
        level_map["advanced"] = _parse_toc_topic_section(sections.get("advanced_topics", ""), tools, labs)
        level_map["projects"] = _parse_toc_topic_section(projects_raw, tools, labs)
        capstone_text = sections.get("capstone", "").strip()
        if capstone_text:
            capstone_topics = _parse_toc_topic_section(capstone_text, tools, labs)
            if not capstone_topics:
                capstone_topics = [{
                    "topic": capstone_text.strip(" -"),
                    "subtopics": [],
                    "tools": tools[:],
                    "lab": labs[-1] if labs else f"Capstone project for {name}",
                }]
            level_map["capstone"] = capstone_topics[:1]

        if not any(level_map.values()):
            continue
        parsed.append({
            "key": _toc_key(name),
            "name": name,
            "icon": "book",
            "aliases": sorted({item for item in aliases if item and item != _toc_key(name)}),
            "active": True,
            "level_map": level_map,
            "jira_practice": {
                "daily": ["Create/update training task", "Log lab evidence", "Move cards across sprint board"],
                "weekly": ["Sprint review", "Project demo", "Retrospective"],
            },
            "certifications": certifications,
        })
    return parsed


def _toc_knowledge_doc_from_payload(payload: dict) -> dict:
    name = str(payload.get("name") or payload.get("key") or "").strip()
    if not name:
        raise HTTPException(400, "Domain name is required")
    key = _toc_key(payload.get("key") or name)
    aliases = sorted({_toc_key(value) for value in (payload.get("aliases") or []) if _toc_key(value)})
    level_map = {}
    for level in TOC_LEVELS:
        topics = [_clean_toc_topic(item) for item in ((payload.get("level_map") or {}).get(level) or [])]
        level_map[level] = [item for item in topics if item.get("topic")]
    if not any(level_map.values()):
        raise HTTPException(400, "Add at least one topic")
    now = utc_now()
    return {
        "key": key,
        "name_key": _toc_key(name),
        "name": name,
        "icon": str(payload.get("icon") or "book").strip() or "book",
        "aliases": aliases,
        "level_map": level_map,
        "jira_practice": {
            "daily": [str(v).strip() for v in ((payload.get("jira_practice") or {}).get("daily") or []) if str(v).strip()],
            "weekly": [str(v).strip() for v in ((payload.get("jira_practice") or {}).get("weekly") or []) if str(v).strip()],
        },
        "certifications": [str(v).strip() for v in (payload.get("certifications") or []) if str(v).strip()],
        "active": bool(payload.get("active", True)),
        "source": "admin",
        "updated_at": now,
    }


async def _admin_toc_domain_for(db, name: str) -> Optional[dict]:
    key = _toc_key(name)
    if not key:
        return None
    exact = await db["toc_domain_knowledge"].find_one({
        "active": {"$ne": False},
        "$or": [{"key": key}, {"aliases": key}, {"name_key": key}],
    }, {"_id": 0})
    if exact:
        return exact

    requested_tokens = _toc_key_tokens(key)
    if not requested_tokens:
        return None
    docs = await db["toc_domain_knowledge"].find({"active": {"$ne": False}}, {"_id": 0}).to_list(1000)
    best_doc = None
    best_score = 0
    for doc in docs:
        candidates = [doc.get("key"), doc.get("name_key"), doc.get("name"), *(doc.get("aliases") or [])]
        for candidate in candidates:
            candidate_key = _toc_key(candidate)
            candidate_tokens = _toc_key_tokens(candidate_key)
            if not candidate_tokens:
                continue
            phrase_match = candidate_key in key or key in candidate_key
            overlap = len(requested_tokens & candidate_tokens)
            if not phrase_match and overlap <= 0:
                continue
            score = overlap * 10
            if phrase_match:
                score += 25
            if candidate_key == doc.get("key"):
                score += 3
            if score > best_score:
                best_score = score
                best_doc = doc
    return best_doc if best_score >= 10 else None


async def _generate_toc_from_best_knowledge(db, payload: dict, duration_days: int) -> dict:
    custom = await _admin_toc_domain_for(db, payload.get("technology"))
    return generate_toc_from_dataset(
        payload.get("technology"),
        duration_days,
        payload.get("audience_level") or "intermediate",
        payload.get("mode") or "Online",
        payload.get("client_notes") or payload.get("custom_topics") or "",
        domain_override=_domain_doc_to_agent_domain(custom) if custom else None,
    )

@router.get("/toc/domains")
async def get_toc_domains():
    db = get_db()
    static_domains = list_domains()
    custom_docs = await db["toc_domain_knowledge"].find({"active": {"$ne": False}}, {"_id": 0}).sort("name", 1).to_list(500)
    custom_keys = {doc.get("key") for doc in custom_docs}
    domains = [
        {"key": doc.get("key"), "name": doc.get("name"), "icon": doc.get("icon", "book"), "source": "admin", "aliases": doc.get("aliases", [])}
        for doc in custom_docs
    ]
    domains.extend({**item, "source": "built_in"} for item in static_domains if item.get("key") not in custom_keys)
    return {"success": True, "domains": domains}


@router.get("/toc/knowledge")
async def list_toc_knowledge():
    db = get_db()
    docs = await db["toc_domain_knowledge"].find({}, {"_id": 0}).sort("updated_at", -1).to_list(500)
    return {"success": True, "domains": [_public_toc_domain_doc(doc) for doc in docs]}


@router.get("/toc/knowledge/{key}")
async def get_toc_knowledge(key: str):
    db = get_db()
    doc = await db["toc_domain_knowledge"].find_one({"key": _toc_key(key)}, {"_id": 0})
    if not doc:
        builtin = get_domain(key)
        if not builtin:
            raise HTTPException(404, "ToC domain not found")
        doc = {
            "key": _toc_key(key),
            "name": builtin.get("name"),
            "icon": builtin.get("icon", "book"),
            "aliases": [],
            "level_map": builtin.get("level_map") or {},
            "jira_practice": builtin.get("jira_practice") or {"daily": [], "weekly": []},
            "certifications": builtin.get("certifications") or [],
            "active": True,
            "source": "built_in",
        }
    return {"success": True, "domain": _public_toc_domain_doc(doc)}


@router.post("/toc/knowledge")
async def save_toc_knowledge(payload: dict):
    db = get_db()
    doc = _toc_knowledge_doc_from_payload(payload)
    now = doc["updated_at"]
    await db["toc_domain_knowledge"].update_one(
        {"key": doc["key"]},
        {"$set": doc, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    saved = await db["toc_domain_knowledge"].find_one({"key": doc["key"]}, {"_id": 0})
    return {"success": True, "domain": _public_toc_domain_doc(saved)}


@router.post("/toc/knowledge/import")
async def import_toc_knowledge(payload: dict):
    raw_text = str(payload.get("text") or "")
    if not raw_text.strip():
        raise HTTPException(400, "Paste ToC knowledge text first")
    domains = _parse_toc_knowledge_blocks(raw_text)
    if not domains:
        raise HTTPException(400, "No valid Technology Name blocks found")
    db = get_db()
    saved = []
    for domain_payload in domains:
        doc = _toc_knowledge_doc_from_payload(domain_payload)
        await db["toc_domain_knowledge"].update_one(
            {"key": doc["key"]},
            {"$set": doc, "$setOnInsert": {"created_at": doc["updated_at"]}},
            upsert=True,
        )
        saved_doc = await db["toc_domain_knowledge"].find_one({"key": doc["key"]}, {"_id": 0})
        saved.append(_public_toc_domain_doc(saved_doc))
    return {"success": True, "imported": len(saved), "domains": saved}


@router.delete("/toc/knowledge/{key}")
async def delete_toc_knowledge(key: str):
    db = get_db()
    result = await db["toc_domain_knowledge"].delete_one({"key": _toc_key(key)})
    if not result.deleted_count:
        raise HTTPException(404, "ToC domain not found")
    return {"success": True, "deleted": _toc_key(key)}


@router.post("/toc/generate")
async def generate_training_toc(payload: dict, request: Request):
    required = ["requirement_id", "trainer_id", "technology", "duration_days"]
    missing = [field for field in required if not payload.get(field)]
    if missing:
        raise HTTPException(400, f"Missing required fields: {', '.join(missing)}")

    try:
        duration_days = int(payload.get("duration_days"))
    except Exception:
        raise HTTPException(400, "duration_days must be a number")
    if duration_days < 1 or duration_days > 100:
        raise HTTPException(400, "duration_days must be between 1 and 100")
    if payload.get("toc_type") == "custom" and not (payload.get("custom_topics") or "").strip():
        raise HTTPException(400, "custom_topics is required for custom TOC mode")

    db = get_db()
    requirement = await db["requirements"].find_one({"requirement_id": payload.get("requirement_id")}, {"_id": 0}) or {}
    trainer_doc = await db["trainers"].find_one({"trainer_id": payload.get("trainer_id")}, {"_id": 0}) or {}
    trainer_name = (
        str(payload.get("trainer_name") or "").strip()
        or str(trainer_doc.get("name") or trainer_doc.get("trainer_name") or "").strip()
        or "Trainer"
    )
    trainer_email = (
        str(payload.get("trainer_email") or "").strip()
        or str(trainer_doc.get("email") or trainer_doc.get("trainer_email") or "").strip()
    )
    trainer = {
        "trainer_id": payload.get("trainer_id"),
        "name": trainer_name,
        "email": trainer_email,
    }
    missing_client_inputs = _toc_missing_client_inputs(requirement, {**payload, "duration_days": duration_days})

    generation_error = ""
    toc_payload = {**payload, "duration_days": duration_days}
    try:
        if payload.get("toc_type") == "custom":
            toc_data = await _generate_toc_with_ollomo(toc_payload)
        else:
            toc_data = await _generate_toc_from_best_knowledge(db, toc_payload, duration_days)
    except Exception as exc:
        generation_error = f"Primary ToC generation unavailable, used fallback: {exc!r}"
        try:
            toc_data = await _generate_toc_from_best_knowledge(db, toc_payload, duration_days)
        except Exception as dataset_exc:
            generation_error = f"{generation_error}; dataset fallback failed: {dataset_exc}"
            toc_data = _fallback_toc_data(toc_payload, generation_error)
    toc_data = validate_toc(toc_data, duration_days)

    toc_id = f"TOC-{uuid.uuid4().hex[:8].upper()}"
    doc = {
        "toc_id": toc_id,
        "requirement_id": payload.get("requirement_id"),
        "trainer_id": payload.get("trainer_id"),
        "trainer_name": trainer_name,
        "trainer_email": trainer_email,
        "technology": payload.get("technology"),
        "duration_days": duration_days,
        "audience_level": payload.get("audience_level") or "intermediate",
        "mode": payload.get("mode") or "Online",
        "toc_type": payload.get("toc_type") or "standard",
        "custom_topics": payload.get("custom_topics") or "",
        "toc_data": toc_data,
        "missing_client_inputs": missing_client_inputs,
        "generation_error": generation_error,
        "ai_provider": "ollomo" if payload.get("toc_type") == "custom" and not generation_error else ("knowledge_base" if not generation_error else "dataset_fallback"),
        "status": "draft",
        "created_at": utc_now(),
    }
    await db["toc_documents"].insert_one(doc)
    return {
        "toc_id": toc_id,
        "toc_data": toc_data,
        "generation_error": generation_error,
        "used_fallback": bool(generation_error),
        "missing_client_inputs": missing_client_inputs,
        "warning": "Generated with assumptions because some client TOC inputs are missing" if missing_client_inputs else "",
        "provider": doc["ai_provider"],
        "message": "TOC generated successfully from the knowledge base" if doc["ai_provider"] == "knowledge_base" else ("TOC generated successfully with Ollomo" if doc["ai_provider"] == "ollomo" else "TOC generated with fallback rules"),
    }


@router.post("/toc/generate-pdf")
async def generate_toc_pdf(payload: dict):
    toc_id = payload.get("toc_id")
    if not toc_id:
        raise HTTPException(400, "toc_id is required")
    db = get_db()
    doc = await db["toc_documents"].find_one({"toc_id": toc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "TOC document not found")

    html = _toc_html(doc)
    pdf_bytes = _toc_pdf_bytes(doc)
    await db["toc_documents"].update_one(
        {"toc_id": toc_id},
        {"$set": {"html": html, "pdf_generated_at": utc_now()}},
    )
    filename = f"{_clean_filename(doc.get('technology', 'training'))}_{toc_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/toc/send-email")
async def send_toc_email(payload: dict):
    toc_id = payload.get("toc_id")
    if not toc_id:
        raise HTTPException(400, "toc_id is required")
    db = get_db()
    doc = await db["toc_documents"].find_one({"toc_id": toc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "TOC document not found")
    if doc.get("status") == "sent" or doc.get("sent_at"):
        return {
            "success": True,
            "skipped": True,
            "status": "already_sent",
            "message": "TOC was already sent once",
            "toc_id": toc_id,
        }
    existing_sent = await db["email_logs"].find_one(
        {
            "toc_id": toc_id,
            "mail_type": {"$in": ["mail6_toc", "toc_generated"]},
            "status": "sent",
        },
        {"_id": 0, "email_id": 1},
        sort=[("sent_at", -1), ("created_at", -1)],
    )
    if existing_sent:
        return {
            "success": True,
            "skipped": True,
            "status": "already_sent",
            "message": "TOC was already sent once",
            "toc_id": toc_id,
            "email_id": existing_sent.get("email_id"),
        }

    toc = doc.get("toc_data") or {}
    subject = payload.get("subject") or f"Training TOC / Course Agenda - {doc.get('technology', 'Training')}"
    body = payload.get("body") or (
        f"Dear {doc.get('trainer_name') or 'Trainer'},\n\n"
        f"Please find attached the AI-generated Training Table of Contents for "
        f"{doc.get('technology', 'the training requirement')}.\n\n"
        "Kindly review the curriculum and share any changes or additions required before we share it with the client.\n\n"
        "Regards,\n"
        "TrainerSync Team"
    )
    if not str(doc.get("trainer_email") or "").strip():
        raise HTTPException(400, "Trainer email is missing. TOC was generated, but add trainer email before sending it.")
    pdf_bytes = _toc_pdf_bytes(doc)
    filename = f"{_clean_filename(doc.get('technology', 'training'))}_{toc_id}.pdf"
    smtp_config = await get_admin_email_config(db)
    success, error = _send_toc_email_with_attachment(
        doc.get("trainer_email", ""),
        subject,
        body,
        filename,
        pdf_bytes,
        smtp_config,
    )

    sent_at = utc_now()
    await db["toc_documents"].update_one(
        {"toc_id": toc_id},
        {"$set": {
            "status": "sent" if success else "send_failed",
            "sent_at": sent_at if success else None,
            "send_error": error,
            "email_subject": subject,
            "email_body": body,
        }},
    )
    await db["conversations"].insert_one({
        "trainer_id": doc.get("trainer_id"),
        "trainer_name": doc.get("trainer_name"),
        "to_email": doc.get("trainer_email"),
        "requirement_id": doc.get("requirement_id"),
        "subject": subject,
        "body": body,
        "mail_type": "toc_generated",
        "direction": "sent",
        "status": "sent" if success else "failed",
        "error": error if not success else "",
        "sent_at": sent_at,
        "toc_id": toc_id,
        "toc_title": toc.get("title", ""),
    })
    if not success:
        raise HTTPException(500, error or "TOC email failed")
    return {"success": True, "message": "TOC sent to trainer successfully", "toc_id": toc_id}


@router.post("/toc/auto-generate")
async def auto_generate_toc(payload: dict, request: Request):
    db = get_db()
    requirement_id = payload.get("requirement_id") or ""
    trainer_id = payload.get("trainer_id") or ""
    if not requirement_id or not trainer_id:
        raise HTTPException(400, "requirement_id and trainer_id are required")

    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    if not requirement:
        raise HTTPException(404, "Requirement not found")
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0})
    if not trainer:
        latest_log = await db["email_logs"].find_one(
            {"requirement_id": requirement_id, "trainer_id": trainer_id, "to_email": {"$nin": [None, ""]}},
            {"_id": 0},
            sort=[("sent_at", -1), ("created_at", -1)],
        )
        trainer = {
            "trainer_id": trainer_id,
            "name": (latest_log or {}).get("trainer_name") or "Trainer",
            "email": (latest_log or {}).get("to_email") or "",
            "phone": (latest_log or {}).get("trainer_phone") or "",
        }
    result = await _auto_generate_and_send_toc(
        db,
        request,
        trainer=trainer,
        requirement=requirement,
        source=payload.get("source") or "auto_selection_toc",
    )
    if not result.get("success"):
        raise HTTPException(500, result.get("error") or "Auto TOC generation failed")
    if payload.get("send_confirmation", True):
        result["training_confirmation"] = await _send_auto_training_confirmation(
            db,
            request,
            trainer=trainer,
            requirement=requirement,
            source=payload.get("source") or "auto_selection_toc",
        )
    return result


# --- Document Agent: Purchase Orders ---------------------------------------

async def _next_purchase_order_number(db) -> str:
    year = utc_now().year
    doc = await db["counters"].find_one_and_update(
        {"_id": f"purchase_orders:{year}"},
        {
            "$inc": {"sequence": 1},
            "$setOnInsert": {"created_at": utc_now(), "type": "purchase_orders", "year": year},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return f"PO-{year}-{int(doc.get('sequence', 1)):04d}"


def _purchase_order_download_url(request: Request, po_id: str) -> str:
    return str(request.url_for("download_purchase_order", po_id=po_id))


def _purchase_order_pdf_from_doc(po_doc: dict) -> bytes:
    encoded = po_doc.get("pdf_base64")
    if encoded:
        return _base64.b64decode(encoded)
    html = po_doc.get("html") or render_purchase_order_html(po_doc)
    return purchase_order_pdf_bytes(po_doc, html)


async def _next_invoice_number(db) -> str:
    year = utc_now().year
    doc = await db["counters"].find_one_and_update(
        {"_id": f"invoices:{year}"},
        {
            "$inc": {"sequence": 1},
            "$setOnInsert": {"created_at": utc_now(), "type": "invoices", "year": year},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return f"INV-{year}-{int(doc.get('sequence', 1)):04d}"


def _invoice_download_url(request: Request, invoice_id: str) -> str:
    return str(request.url_for("download_invoice", invoice_id=invoice_id))


def _invoice_filename(invoice_doc: dict) -> str:
    number = _re.sub(r"[^A-Za-z0-9._-]+", "_", str(invoice_doc.get("invoice_number") or "invoice")).strip("_")
    client = _re.sub(r"[^A-Za-z0-9._-]+", "_", str((invoice_doc.get("client") or {}).get("name") or "client")).strip("_")
    return f"{number}_{client}.pdf"


def _public_invoice(invoice_doc: dict) -> dict:
    public = {k: v for k, v in invoice_doc.items() if k not in {"_id", "html", "pdf_base64"}}
    for key in ("issue_date", "created_at", "pdf_generated_at", "sent_at"):
        if isinstance(public.get(key), datetime):
            public[key] = public[key].isoformat()
    return public


def _money_text(value) -> str:
    try:
        return f"INR {float(value or 0):,.2f}"
    except Exception:
        return "INR 0.00"


def _money_number(value) -> str:
    try:
        return f"{float(value or 0):,.2f}"
    except Exception:
        return "0.00"


def _invoice_due_date_display(invoice_doc: dict) -> str:
    if invoice_doc.get("due_date_display"):
        return str(invoice_doc.get("due_date_display"))
    issue = invoice_doc.get("issue_date")
    if isinstance(issue, datetime):
        return (issue + timedelta(days=30)).strftime("%d-%m-%Y")
    try:
        parsed = datetime.fromisoformat(str(issue).replace("Z", "+00:00"))
        return (parsed + timedelta(days=30)).strftime("%d-%m-%Y")
    except Exception:
        return ""


def _amount_words_indian(value) -> str:
    try:
        number = int(round(float(value or 0)))
    except Exception:
        number = 0
    if number <= 0:
        return "Zero Rupees Only"
    ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def below_hundred(n):
        if n < 20:
            return ones[n]
        return " ".join(part for part in [tens[n // 10], ones[n % 10]] if part)

    def below_thousand(n):
        if n < 100:
            return below_hundred(n)
        return " ".join(part for part in [ones[n // 100], "Hundred", below_hundred(n % 100)] if part)

    parts = []
    crore, number = divmod(number, 10000000)
    lakh, number = divmod(number, 100000)
    thousand, number = divmod(number, 1000)
    if crore:
        parts.append(f"{below_thousand(crore)} Crore")
    if lakh:
        parts.append(f"{below_thousand(lakh)} Lakh")
    if thousand:
        parts.append(f"{below_thousand(thousand)} Thousand")
    if number:
        parts.append(below_thousand(number))
    return f"{', '.join(parts)} Rupees Only"


def _invoice_asset_data_uri(filename: str, mime: str) -> str:
    try:
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", filename)
        with open(path, "rb") as handle:
            return f"data:{mime};base64,{_base64.b64encode(handle.read()).decode('ascii')}"
    except Exception:
        return ""


def _render_invoice_html(invoice_doc: dict) -> str:
    esc = _html.escape
    company = _invoice_display_company(invoice_doc)
    trainer = invoice_doc.get("trainer") or {}
    client = invoice_doc.get("client") or {}
    requirement = invoice_doc.get("requirement") or {}
    commercials = invoice_doc.get("commercials") or {}
    qty = (
        invoice_doc.get("quantity")
        or requirement.get("duration_days")
        or requirement.get("duration")
        or 1
    )
    rate = commercials.get("day_rate") or (
        round(float(commercials.get("total_amount") or 0) / float(qty), 2)
        if str(qty).replace(".", "", 1).isdigit() and float(qty or 0) else 0
    )
    start_date = invoice_doc.get("start_date") or requirement.get("start_date") or requirement.get("training_dates") or "As per PO"
    end_date = invoice_doc.get("end_date") or requirement.get("end_date") or requirement.get("training_dates") or "As per PO"
    hsn_sac = invoice_doc.get("hsn_sac") or "999293"
    po_date = invoice_doc.get("po_date") or invoice_doc.get("client_po_date") or ""
    payment_terms = invoice_doc.get("payment_terms") or "As per client PO."
    gst_rate = float(commercials.get("gst_rate") or 0)
    gst_label = invoice_doc.get("tax_type") or ("IGST" if gst_rate else "Tax")
    due_date = _invoice_due_date_display(invoice_doc)
    amount_words = invoice_doc.get("amount_words") or _amount_words_indian(commercials.get("grand_total"))
    bank = invoice_doc.get("bank") or invoice_doc.get("bank_details") or {}
    bank = {
        "account_name": bank.get("account_name") or "Beulix Solutions Pvt Ltd",
        "account_number": bank.get("account_number") or "232805003625",
        "ifsc": bank.get("ifsc") or "ICIC0002328",
    }
    logo_uri = invoice_doc.get("logo_data_uri") or _invoice_asset_data_uri("invoice_sample_image_1.png", "image/png")
    signature_uri = invoice_doc.get("signature_data_uri") or _invoice_asset_data_uri("invoice_sample_image_0.jpeg", "image/jpeg")
    items = invoice_doc.get("items") or []
    if items:
        item_rows = "\n".join(
            f"""<tr>
      <td class="center">{idx}</td>
      <td>{esc(str(item.get('description') or requirement.get('technology') or 'Training'))}<br><span style="color:#4b5563">Trainer: {esc(trainer.get('name') or 'Trainer')}</span></td>
      <td>{esc(str(item.get('hsn_sac') or hsn_sac))}</td>
      <td class="right">{esc(str(item.get('quantity') or 1))}</td>
      <td class="right">{_money_number(item.get('rate') or 0)}</td>
      <td class="right">{_money_number(item.get('amount') or 0)}</td>
    </tr>"""
            for idx, item in enumerate(items, start=1)
        )
    else:
        item_rows = f"""<tr>
      <td class="center">1</td>
      <td>{esc(requirement.get('technology') or 'Training')}<br><span style="color:#4b5563">Trainer: {esc(trainer.get('name') or 'Trainer')}</span></td>
      <td>{esc(str(hsn_sac))}</td>
      <td class="right">{esc(str(qty))}</td>
      <td class="right">{_money_number(rate)}</td>
      <td class="right">{_money_number(commercials.get('total_amount'))}</td>
    </tr>"""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{esc(invoice_doc.get('invoice_number') or 'Invoice')}</title>
<style>
@page {{ size:A4; margin:13mm 12mm; }}
body {{ font-family:Arial,sans-serif; color:#111827; font-size:11px; line-height:1.32; }}
h1,h2,h3,p {{ margin:0; }}
.top {{ display:grid; grid-template-columns:1fr 230px; align-items:center; gap:20px; border-bottom:3px solid #183b70; padding-bottom:12px; margin-bottom:14px; }}
.logo {{ width:255px; max-height:72px; object-fit:contain; }}
.invoice-title {{ text-align:right; color:#183b70; font-size:25px; font-weight:900; letter-spacing:.5px; }}
.invoice-no {{ text-align:right; color:#183b70; font-size:13px; font-weight:800; margin-top:2px; }}
.header {{ display:block; margin-bottom:12px; border-bottom:1px solid #9ca3af; padding-bottom:12px; }}
.company h1 {{ font-size:15px; font-weight:900; margin-bottom:5px; }}
.company p,.bill p,.bank p,.terms p {{ margin:2px 0; }}
.meta-row {{ display:grid; grid-template-columns:95px 1fr; gap:8px; margin-bottom:20px; }}
.meta-label {{ color:#374151; font-weight:700; }}
.bill-wrap {{ display:grid; grid-template-columns:1.15fr .95fr; gap:28px; margin:14px 0 16px; }}
.section-label {{ font-weight:800; margin-bottom:5px; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ border:1px solid #b7bcc4; padding:9px 9px; vertical-align:top; }}
th {{ background:#1f4578; color:white; font-weight:900; text-align:left; font-size:12px; }}
.center {{ text-align:center; }}
.right {{ text-align:right; }}
.amount-panel {{ width:300px; margin-left:auto; margin-top:10px; }}
.amount-panel td {{ border:1px solid #d1d5db; padding:8px 9px; }}
.amount-panel .value {{ text-align:right; }}
.total td {{ font-weight:800; font-size:14px; }}
.balance td {{ font-weight:800; }}
.words {{ margin-top:12px; font-weight:800; text-transform:uppercase; }}
.bottom {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:24px; margin-top:20px; border-top:1px solid #9ca3af; padding-top:18px; }}
.bank,.terms {{ min-height:82px; }}
.signature-box {{ text-align:center; }}
.signature-img {{ width:170px; max-height:70px; object-fit:contain; margin-top:12px; }}
.signature {{ margin-top:8px; font-weight:800; font-size:14px; }}
</style></head><body>
<div class="top">
  <div>{f'<img class="logo" src="{logo_uri}" />' if logo_uri else f'<h1>{esc(company.get("name") or "BEULIX SOLUTIONS PRIVATE LIMITED")}</h1>'}</div>
  <div><div class="invoice-title">TAX INVOICE</div><div class="invoice-no"># {esc(invoice_doc.get('invoice_number') or '')}</div></div>
</div>
<div class="header">
  <div class="company">
    <h1>{esc(company.get('name') or 'Clahan Technologies')}</h1>
    <p>{esc(company.get('address') or '')}</p>
    <p>Email: {esc(company.get('email') or '')} | Contact: {esc(company.get('phone') or '')}</p>
    <p>PAN: {esc(company.get('pan') or '')} | GST: {esc(company.get('gstin') or '')}</p>
  </div>
</div>
<div class="bill-wrap">
  <div class="bill">
    <div class="section-label">Bill To:</div>
    <p><strong>{esc(client.get('name') or 'Client')}</strong></p>
    <p>{esc(client.get('billing_address') or '')}</p>
    <p>PONO: {esc(invoice_doc.get('po_number') or '')}</p>
    <p>PAN: {esc(client.get('pan') or '')}</p>
    <p>GST: {esc(client.get('gstin') or '')}</p>
    <p>Place of Supply: {esc(invoice_doc.get('place_of_supply') or client.get('place_of_supply') or '')}</p>
  </div>
  <div>
    <div class="meta-row"><div class="meta-label">Invoice Date:</div><div class="right">{esc(invoice_doc.get('issue_date_display') or '')}</div></div>
    <div class="meta-row"><div class="meta-label">Due Date:</div><div class="right">{esc(due_date)}</div></div>
  </div>
</div>
<table>
  <thead>
    <tr><th class="center">S.No</th><th>Item & Description</th><th>HSN/SAC</th><th class="right">Qty</th><th class="right">Rate</th><th class="right">Amount</th></tr>
  </thead>
  <tbody>
    {item_rows}
  </tbody>
</table>
<table class="amount-panel">
  <tr><td>Sub Total</td><td class="value">{_money_number(commercials.get('total_amount'))}</td></tr>
  <tr><td>{esc(gst_label)} ({esc(str(commercials.get('gst_rate', 0)))}%)</td><td class="value">{_money_number(commercials.get('gst_amount'))}</td></tr>
  <tr class="total"><td>Total</td><td class="value">Rs:{_money_number(commercials.get('grand_total'))}</td></tr>
  <tr class="balance"><td>Balance Due</td><td class="value">Rs:{_money_number(commercials.get('grand_total'))}</td></tr>
</table>
<div class="words">AMOUNT IN WORDS: {esc(amount_words)}</div>
<div class="bottom">
  <div class="bank"><div class="section-label">Bank Details:</div><p>{esc(bank.get('account_name') or company.get('name') or 'Clahan Technologies')}</p><p>A/C No: {esc(bank.get('account_number') or '')}</p><p>IFSC: {esc(bank.get('ifsc') or '')}</p></div>
  <div class="terms"><div class="section-label">Terms & Conditions:</div><p>{esc(invoice_doc.get('terms_conditions') or 'Once payment is done, it cannot be reversed.')}</p></div>
  <div class="signature-box">{f'<img class="signature-img" src="{signature_uri}" />' if signature_uri else ''}<div class="signature">Authorized Signature</div></div>
</div>
</body></html>"""


def _invoice_pdf_from_doc(invoice_doc: dict) -> bytes:
    try:
        return _simple_invoice_pdf_bytes(invoice_doc)
    except Exception:
        return _simple_invoice_pdf_bytes(invoice_doc)


def _invoice_display_company(invoice_doc: dict) -> dict:
    company = dict(invoice_doc.get("company") or {})
    invoice_type = str(invoice_doc.get("invoice_type") or "").lower()
    name = str(company.get("name") or "").strip().lower()
    if invoice_type == "beulix" or not company or name in {"calhan technologies", "calhan"}:
        company.update({
            "name": "BEULIX SOLUTIONS PRIVATE LIMITED",
            "address": "No.29/2, 1st Main Road, Maruthinagar, Madivala, Bangalore - Karnataka 560068",
            "email": "finance@beulixsolutions.com",
            "phone": "8179147889",
            "pan": "AANCB2798",
            "gstin": "29AANCB2798L1ZS",
        })
    return company


def _simple_invoice_pdf_bytes(invoice_doc: dict) -> bytes:
    company = _invoice_display_company(invoice_doc)
    trainer = invoice_doc.get("trainer") or {}
    client = invoice_doc.get("client") or {}
    requirement = invoice_doc.get("requirement") or {}
    commercials = invoice_doc.get("commercials") or {}
    qty = invoice_doc.get("quantity") or requirement.get("duration_days") or requirement.get("duration") or 1
    rate = commercials.get("day_rate") or (
        round(float(commercials.get("total_amount") or 0) / float(qty), 2)
        if str(qty).replace(".", "", 1).isdigit() and float(qty or 0) else 0
    )
    due_date = _invoice_due_date_display(invoice_doc)
    bank = invoice_doc.get("bank") or invoice_doc.get("bank_details") or {}

    def draw_wrapped(page, text, x, y, max_width, size=10, color=(0, 0, 0), bold=False, line_height=14):
        font = "helv"
        words = str(text or "").replace("\n", " \n ").split(" ")
        line = ""
        for word in words:
            if word == "\n":
                page.insert_text((x, y), line, fontsize=size, fontname=font, color=color)
                y += line_height
                line = ""
                continue
            trial = f"{line} {word}".strip()
            if fitz.get_text_length(trial, fontname=font, fontsize=size) <= max_width:
                line = trial
            else:
                page.insert_text((x, y), line, fontsize=size, fontname=font, color=color)
                y += line_height
                line = word
        if line:
            page.insert_text((x, y), line, fontsize=size, fontname=font, color=color)
            y += line_height
        return y

    def text(page, x, y, value, size=10, color=(0, 0, 0)):
        page.insert_text((x, y), str(value or ""), fontsize=size, fontname="helv", color=color)

    def text_right(page, x, y, value, size=10, color=(0, 0, 0)):
        value = str(value or "")
        page.insert_text((x - fitz.get_text_length(value, fontname="helv", fontsize=size), y), value, fontsize=size, fontname="helv", color=color)

    def draw_water_drop(page, rect):
        cx = (rect.x0 + rect.x1) / 2
        shape = page.new_shape()
        top = fitz.Point(cx, rect.y0)
        bottom = fitz.Point(cx, rect.y1)
        left_mid = fitz.Point(rect.x0 + rect.width * 0.08, rect.y0 + rect.height * 0.58)
        right_mid = fitz.Point(rect.x1 - rect.width * 0.08, rect.y0 + rect.height * 0.58)
        shape.draw_bezier(top, fitz.Point(rect.x0 + rect.width * 0.08, rect.y0 + rect.height * 0.16), left_mid, bottom)
        shape.draw_bezier(bottom, right_mid, fitz.Point(rect.x1 - rect.width * 0.08, rect.y0 + rect.height * 0.16), top)
        shape.finish(color=(0.16, 0.46, 0.78), fill=(0.63, 0.84, 1.0), width=1.0, fill_opacity=0.16, stroke_opacity=0.22)
        shape.commit()

    navy = (31 / 255, 69 / 255, 120 / 255)
    grey = (0.72, 0.72, 0.72)
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    margin = 42

    logo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "invoice_sample_image_1.png")
    sig_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "invoice_sample_image_0.jpeg")
    if os.path.exists(logo_path):
        watermark = fitz.Rect(172, 410, 423, 468)
        page.insert_image(watermark, filename=logo_path, keep_proportion=True)
        try:
            page.draw_rect(watermark + (-10, -10, 10, 10), color=None, fill=(1, 1, 1), fill_opacity=0.78)
        except TypeError:
            page.draw_rect(watermark + (-10, -10, 10, 10), color=None, fill=(1, 1, 1))
    if os.path.exists(logo_path):
        page.insert_image(fitz.Rect(margin - 4, 28, 236, 80), filename=logo_path, keep_proportion=True)
    else:
        text(page, margin, 62, company.get("name") or "BEULIX SOLUTIONS PRIVATE LIMITED", 14, navy)
    text_right(page, 553, 54, "TAX INVOICE", 22, navy)
    text_right(page, 553, 76, f"# {invoice_doc.get('invoice_number') or ''}", 12, navy)
    page.draw_line((margin, 94), (553, 94), color=navy, width=2.2)

    y = 112
    text(page, margin, y, company.get("name") or "BEULIX SOLUTIONS PRIVATE LIMITED", 13)
    y += 17
    y = draw_wrapped(page, company.get("address") or "", margin, y, 505, 10, line_height=13)
    text(page, margin, y, f"Email: {company.get('email') or ''} | Contact: {company.get('phone') or ''}", 10)
    y += 14
    text(page, margin, y, f"PAN: {company.get('pan') or ''} | GST: {company.get('gstin') or ''}", 10)
    y += 16
    page.draw_line((margin, y), (553, y), color=grey, width=0.8)

    y += 24
    text(page, margin, y, "Bill To:", 10, navy)
    text(page, 330, y, "Invoice Date:", 10)
    text_right(page, 553, y, invoice_doc.get("issue_date_display") or "", 10)
    y += 18
    text(page, margin, y, client.get("name") or "Client", 12)
    bill_y = y + 15
    bill_y = draw_wrapped(page, client.get("billing_address") or "", margin, bill_y, 260, 10, line_height=14)
    text(page, 330, y + 32, "Due Date:", 10)
    text_right(page, 553, y + 32, due_date, 10)
    for label, value in [
        ("PONO", invoice_doc.get("po_number") or invoice_doc.get("client_po_number") or ""),
        ("PAN", client.get("pan") or ""),
        ("GST", client.get("gstin") or ""),
        ("Place of Supply", invoice_doc.get("place_of_supply") or client.get("place_of_supply") or ""),
    ]:
        text(page, margin, bill_y, f"{label}: {value}", 10)
        bill_y += 15

    table_x = margin
    table_y = max(bill_y + 12, 318)
    widths = [34, 205, 76, 58, 82, 86]
    headers = ["S.No", "Item & Description", "HSN/SAC", "Qty", "Rate", "Amount"]
    row_h = 43
    x = table_x
    for w, header in zip(widths, headers):
        page.draw_rect(fitz.Rect(x, table_y, x + w, table_y + row_h), color=grey, fill=navy, width=0.8)
        text(page, x + 7, table_y + 25, header, 10, (1, 1, 1))
        x += w

    items = invoice_doc.get("items") or [{
        "description": requirement.get("technology") or "Training",
        "hsn_sac": invoice_doc.get("hsn_sac") or "999293",
        "quantity": qty,
        "rate": rate,
        "amount": commercials.get("total_amount"),
    }]
    y = table_y + row_h
    for idx, item in enumerate(items[:3], start=1):
        row_amount = _float_or_zero(item.get("amount"))
        row_qty = _float_or_zero(item.get("quantity") or 1)
        row_rate = _float_or_zero(item.get("rate")) or (round(row_amount / row_qty, 2) if row_amount and row_qty else 0)
        x = table_x
        for w in widths:
            page.draw_rect(fitz.Rect(x, y, x + w, y + 35), color=grey, width=0.6)
            x += w
        text(page, table_x + 14, y + 21, idx, 10)
        text(page, table_x + widths[0] + 7, y + 21, item.get("description") or requirement.get("technology") or "Training", 10)
        text(page, table_x + widths[0] + widths[1] + 20, y + 21, item.get("hsn_sac") or invoice_doc.get("hsn_sac") or "999293", 10)
        text_right(page, table_x + sum(widths[:4]) - 10, y + 21, item.get("quantity") or 1, 10)
        text_right(page, table_x + sum(widths[:5]) - 8, y + 21, _money_number(row_rate), 10)
        text_right(page, table_x + sum(widths) - 8, y + 21, _money_number(row_amount), 10)
        y += 35

    for _ in range(max(0, 3 - len(items[:3]))):
        x = table_x
        for w in widths:
            page.draw_rect(fitz.Rect(x, y, x + w, y + 35), color=grey, width=0.45)
            x += w
        y += 35

    for label, value, tall in [
        ("Sub Total", commercials.get("total_amount"), 32),
        (f"{invoice_doc.get('tax_type') or 'IGST'} ({commercials.get('gst_rate', 0)}%)", commercials.get("gst_amount"), 32),
        ("Total", commercials.get("grand_total"), 45),
        ("Balance Due", commercials.get("grand_total"), 45),
    ]:
        x_label = table_x + sum(widths[:4])
        page.draw_rect(fitz.Rect(table_x, y, x_label, y + tall), color=grey, width=0.6)
        page.draw_rect(fitz.Rect(x_label, y, x_label + widths[4], y + tall), color=grey, width=0.6)
        page.draw_rect(fitz.Rect(x_label + widths[4], y, table_x + sum(widths), y + tall), color=grey, width=0.6)
        text_right(page, x_label + widths[4] - 8, y + (22 if tall == 32 else 28), label, 10, navy if label in {"Total", "Balance Due"} else (0, 0, 0))
        text_right(page, table_x + sum(widths) - 8, y + (22 if tall == 32 else 28), f"Rs:{_money_number(value)}" if label in {"Total", "Balance Due"} else _money_number(value), 10, navy if label in {"Total", "Balance Due"} else (0, 0, 0))
        y += tall

    y += 18
    text(page, margin, y, f"AMOUNT IN WORDS: {_amount_words_indian(commercials.get('grand_total'))}", 10, navy)
    y += 20
    page.draw_line((margin, y), (553, y), color=grey, width=0.8)
    y += 26
    text(page, margin, y, "Bank Details:", 11)
    text(page, margin, y + 18, bank.get("account_name") or company.get("name") or "BEULIX SOLUTIONS PRIVATE LIMITED", 10)
    text(page, margin, y + 34, f"A/C No: {bank.get('account_number') or ''}", 10)
    text(page, margin, y + 50, f"IFSC: {bank.get('ifsc') or ''}", 10)
    text(page, 225, y, "Terms & Conditions:", 11)
    draw_wrapped(page, invoice_doc.get("terms_conditions") or "Once payment is done, it cannot be reversed.", 225, y + 18, 160, 10, line_height=14)
    if os.path.exists(sig_path):
        sig_rect = fitz.Rect(382, y + 0, 555, y + 62)
        page.insert_image(sig_rect, filename=sig_path, keep_proportion=True)
        page.draw_rect(fitz.Rect(374, y + 43, 560, y + 92), color=None, fill=(1, 1, 1))
    text(page, 408, y + 78, "Authorized Signature", 12)
    data = pdf.tobytes()
    pdf.close()
    return data


def _gst_amount_for_invoice(total_amount, gst_rate=18):
    try:
        return round(float(total_amount or 0) * (float(gst_rate or 0) / 100), 2)
    except Exception:
        return 0


def _float_or_zero(value) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0


@router.post("/purchase-orders/generate")
async def generate_purchase_order(payload: dict, request: Request):
    trainer_id = payload.get("trainer_id")
    requirement_id = payload.get("requirement_id")
    if not trainer_id or not requirement_id:
        raise HTTPException(400, "trainer_id and requirement_id are required")

    db = get_db()
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0})
    if not trainer:
        raise HTTPException(404, "Trainer not found")
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    if not requirement:
        raise HTTPException(404, "Requirement not found")

    po_number = await _next_purchase_order_number(db)
    po_id = f"PO-DOC-{uuid.uuid4().hex[:8].upper()}"
    po_doc = build_purchase_order_doc(trainer, requirement, payload, po_number)
    if (po_doc.get("commercials") or {}).get("total_amount", 0) <= 0:
        raise HTTPException(400, "day_rate or total_amount is required to generate a purchase order")
    po_doc.update({
        "po_id": po_id,
        "download_url": _purchase_order_download_url(request, po_id),
        "source": "shortlist",
    })

    try:
        html = render_purchase_order_html(po_doc)
        pdf_bytes = purchase_order_pdf_bytes(po_doc, html)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Purchase order PDF generation failed: {exc}")

    po_doc.update({
        "html": html,
        "pdf_base64": _base64.b64encode(pdf_bytes).decode("ascii"),
        "pdf_content_type": "application/pdf",
        "pdf_filename": purchase_order_filename(po_doc),
        "pdf_generated_at": utc_now(),
    })
    await db["purchase_orders"].insert_one(po_doc)
    await send_teams_stage_notification(
        db,
        stage="po_generated",
        trainer=po_doc.get("trainer") or {},
        requirement=po_doc.get("requirement") or {},
        request_base_url=_request_base_url(request),
        context={"source": "purchase_order", "po_id": po_id, "po_number": po_doc.get("po_number")},
    )

    return {
        "success": True,
        "message": "Purchase order generated",
        "purchase_order": public_purchase_order(po_doc),
    }


@router.post("/requirements/{requirement_id}/request-client-po")
async def request_client_purchase_order(requirement_id: str, payload: dict, request: Request):
    db = get_db()
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    if not requirement:
        raise HTTPException(404, "Requirement not found")

    trainer_id = str(payload.get("trainer_id") or requirement.get("selected_trainer_id") or "").strip()
    trainer = {}
    if trainer_id:
        trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or {}
    trainer_name = (
        payload.get("trainer_name")
        or trainer.get("name")
        or requirement.get("selected_trainer_name")
        or "the trainer"
    )
    client_email = str(
        payload.get("client_email")
        or requirement.get("client_email")
        or ""
    ).strip()
    if not client_email:
        raise HTTPException(400, "Client email is required to request PO")

    client_name = (
        payload.get("client_name")
        or requirement.get("client_name")
        or requirement.get("client_company")
        or "Client"
    )
    technology = requirement.get("technology_needed") or payload.get("technology") or "training"
    training_dates = (
        payload.get("training_dates")
        or requirement.get("training_dates")
        or requirement.get("timeline_start")
        or ""
    )
    project_name = (
        payload.get("project_name")
        or requirement.get("project_name")
        or f"{technology} Training"
    )
    requirement_text = (
        payload.get("requirement")
        or requirement.get("requirement")
        or f"{technology} training service with {trainer_name}"
    )
    quantity = (
        payload.get("quantity")
        or requirement.get("duration")
        or requirement.get("duration_days")
        or requirement.get("participants")
        or "As applicable"
    )
    expected_delivery = payload.get("expected_delivery_date") or "Within 1 day"
    billing_company = payload.get("billing_company") or "Clahan Technologies"
    billing_address = payload.get("billing_address") or "As per registered billing details"
    gst_number = payload.get("gst_number") or "As applicable"
    subject = payload.get("subject") or "Request for Purchase Order (PO)"
    body = payload.get("body") or (
        f"Dear {client_name},\n\n"
        "I hope you are doing well.\n\n"
        "We would like to request you to kindly issue the Purchase Order (PO) for the following requirement:\n\n"
        "Project Details:\n\n"
        f"* Project Name: {project_name}\n"
        f"* Requirement: {requirement_text}\n"
        f"* Quantity: {quantity}\n"
        f"* Expected Delivery Date: {expected_delivery}\n"
        f"* Requirement ID: {requirement_id}\n"
        f"* Trainer: {trainer_name}\n"
        f"* Training Dates: {training_dates or 'As confirmed'}\n\n"
        "Billing Details:\n\n"
        f"* Company Name: {billing_company}\n"
        f"* Address: {billing_address}\n"
        f"* GST Number: {gst_number}\n\n"
        "Please share the Purchase Order within 1 day so that we can proceed with the next steps.\n\n"
        "If you need any additional information, feel free to contact us.\n\n"
        "Looking forward to your confirmation.\n\n"
        "Thank you & regards,\n"
        "Recruitment Team\n"
        "Clahan Technologies"
    )

    email_id = f"CLIENT-PO-REQ-{uuid.uuid4().hex[:8].upper()}"
    tracking_url = build_tracking_url(request, email_id)
    smtp_config = await get_admin_email_config(db)
    success, error = await send_email_async(client_email, subject, body, smtp_config, tracking_url)
    now = utc_now()

    log_doc = {
        "email_id": email_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "requirement_id": requirement_id,
        "to_email": client_email,
        "client_name": client_name,
        "client_email": client_email,
        "subject": subject,
        "body": body,
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "sent_at": now if success else None,
        "reply_received": False,
        "opened": False,
        "open_count": 0,
        "tracking_url": tracking_url,
        "retry_count": 0,
        "mail_type": "client_po_request",
        "source": "client_po_request",
        "created_at": now,
    }
    await db["email_logs"].insert_one(log_doc)
    await db["conversations"].insert_one({
        **log_doc,
        "direction": "client_sent",
        "error": error if not success else "",
    })
    if success:
        await db["requirements"].update_one(
            {"requirement_id": requirement_id},
            {"$set": {
                "po_request_status": "requested",
                "po_requested_at": now,
                "po_requested_email_id": email_id,
                "selection_status": requirement.get("selection_status") or "training_confirmed",
            }},
        )

    if not success:
        raise HTTPException(500, error or "Could not send PO request to client")
    return {
        "success": True,
        "message": "PO request sent to client",
        "email_id": email_id,
        "to_email": client_email,
    }


@router.post("/requirements/{requirement_id}/request-client-budget-increase")
async def request_client_budget_increase(requirement_id: str, payload: dict, request: Request):
    db = get_db()
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    if not requirement:
        raise HTTPException(404, "Requirement not found")

    client_email = str(payload.get("client_email") or requirement.get("client_email") or "").strip()
    if not client_email:
        raise HTTPException(400, "Client email is required to request budget revision")

    client_name = (
        payload.get("client_name")
        or requirement.get("client_name")
        or requirement.get("client_company")
        or "Client"
    )
    technology = requirement.get("technology_needed") or payload.get("technology") or "training"
    current_budget = _float_or_zero(payload.get("current_budget") or requirement.get("budget_per_day") or requirement.get("budget_total"))
    requested_budget = _float_or_zero(payload.get("requested_budget"))
    increment = _float_or_zero(payload.get("increment") or 5000)
    unit = str(payload.get("unit") or "day").strip().lower()
    unit_label = "hour" if unit.startswith("hour") else "day"
    if requested_budget <= 0 and current_budget > 0:
        requested_budget = current_budget + increment
    if requested_budget <= 0:
        raise HTTPException(400, "requested_budget is required")
    trainer_id = str(payload.get("trainer_id") or "")
    existing_request = await db["email_logs"].find_one(
        {
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
            "mail_type": "client_budget_revision_request",
            "status": "sent",
        },
        {"_id": 0, "email_id": 1, "to_email": 1, "commercials": 1},
        sort=[("sent_at", -1), ("created_at", -1)],
    )
    if existing_request:
        return {
            "success": True,
            "skipped": True,
            "message": "Budget revision request already sent to client",
            "email_id": existing_request.get("email_id"),
            "to_email": existing_request.get("to_email"),
            "requested_budget": (existing_request.get("commercials") or {}).get("requested_budget"),
            "unit": (existing_request.get("commercials") or {}).get("unit") or unit_label,
        }

    subject = payload.get("subject") or f"Commercial Revision Request - {technology} Training"
    body = payload.get("body") or (
        f"Dear {client_name},\n\n"
        f"Thank you for the update regarding the {technology} training requirement.\n\n"
        "Based on current trainer availability, required experience level, and the quality expectations for this engagement, "
        f"we request you to kindly consider revising the commercial budget to INR {requested_budget:,.0f} per {unit_label}.\n\n"
        "This revision will help us align with a suitable trainer profile and proceed without delays.\n\n"
        "Please confirm if this revised commercial is workable from your side, so we can move ahead with the next steps.\n\n"
        "Regards,\n"
        "Recruitment Team\n"
        "Clahan Technologies"
    )

    email_id = f"CLIENT-BUDGET-{uuid.uuid4().hex[:8].upper()}"
    tracking_url = build_tracking_url(request, email_id)
    smtp_config = await get_admin_email_config(db)
    success, error = await send_email_async(client_email, subject, body, smtp_config, tracking_url)
    now = utc_now()
    log_doc = {
        "email_id": email_id,
        "trainer_id": trainer_id,
        "trainer_name": str(payload.get("trainer_name") or ""),
        "requirement_id": requirement_id,
        "to_email": client_email,
        "client_name": client_name,
        "client_email": client_email,
        "subject": subject,
        "body": body,
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "sent_at": now if success else None,
        "reply_received": False,
        "opened": False,
        "open_count": 0,
        "tracking_url": tracking_url,
        "retry_count": 0,
        "mail_type": "client_budget_revision_request",
        "source": "trainer_commercial_negotiation",
        "commercials": {
            "current_budget": current_budget,
            "requested_budget": requested_budget,
            "increment": increment,
            "unit": unit_label,
        },
        "created_at": now,
    }
    await db["email_logs"].insert_one(log_doc)
    await db["client_messages"].insert_one({
        **log_doc,
        "direction": "sent",
    })
    if success:
        await db["requirements"].update_one(
            {"requirement_id": requirement_id},
            {"$set": {
                "client_budget_revision_requested_at": now,
                "client_budget_revision_email_id": email_id,
                "client_budget_revision_requested": requested_budget,
                "client_budget_revision_unit": unit_label,
            }},
        )

    if not success:
        raise HTTPException(500, error or "Could not send budget revision request to client")
    return {
        "success": True,
        "message": "Budget revision request sent to client",
        "email_id": email_id,
        "to_email": client_email,
        "requested_budget": requested_budget,
        "unit": unit_label,
    }


def _commercial_amount_label(amount: float, unit: str = "") -> str:
    try:
        amount = float(amount or 0)
    except (TypeError, ValueError):
        amount = 0
    amount_text = f"{amount:,.0f}" if amount else "the requested"
    unit_text = str(unit or "").strip()
    return f"INR {amount_text} per {unit_text}" if unit_text else f"INR {amount_text}"


def _commercial_log_details(log: dict) -> dict:
    commercials = (log or {}).get("commercials") or {}
    amount = _float_or_zero(commercials.get("requested_trainer_commercial"))
    unit = str(commercials.get("unit") or "day").strip().lower()
    return {"amount": amount, "unit": "hour" if unit.startswith("hour") else "day"}


def _amount_match_to_number(match) -> float:
    if not match:
        return 0.0
    raw = str(match.group(1) or "").replace(",", "")
    multiplier = 1000 if str(match.group(2) or "").strip().lower() == "k" else 1
    try:
        return float(raw) * multiplier
    except ValueError:
        return 0.0


def _trainer_counter_commercial(reply_text: str, log: dict) -> dict:
    text = _strip_quoted_reply_text(reply_text or "")
    if not text:
        return {}
    lower = text.lower()
    base = _commercial_log_details(log)
    unit = base.get("unit") or "day"
    target_amount = _float_or_zero(base.get("amount"))

    extra_patterns = [
        r"(?:extra|more|additional|increase)\D{0,30}(?:inr|rs\.?|₹)?\s*([0-9][0-9,]*(?:\.\d+)?)(\s*k)?\b",
        r"(?:inr|rs\.?|₹)?\s*([0-9][0-9,]*(?:\.\d+)?)(\s*k)?\b\D{0,20}(?:extra|more|additional)",
    ]
    for pattern in extra_patterns:
        match = _re.search(pattern, lower, flags=_re.IGNORECASE)
        amount = _amount_match_to_number(match)
        if amount > 0 and target_amount > 0:
            counter = target_amount + amount
            return {"amount": counter, "unit": unit, "is_extra": True, "extra_amount": amount}

    parsed = extract_trainer_commercial_details(text)
    if parsed and _float_or_zero(parsed.get("amount")) > 0:
        parsed["unit"] = parsed.get("unit") or unit
        return parsed

    amount_patterns = [
        r"(?:inr|rs\.?|₹)\s*([0-9][0-9,]*(?:\.\d+)?)(\s*k)?\b",
        r"\b([0-9][0-9,]*(?:\.\d+)?)(\s*k)\b",
        r"\b(?:need|want|asking|quote|rate|commercial|charges?)\D{0,30}([0-9][0-9,]*(?:\.\d+)?)(\s*k)?\b",
    ]
    for pattern in amount_patterns:
        match = _re.search(pattern, lower, flags=_re.IGNORECASE)
        amount = _amount_match_to_number(match)
        if amount > 0:
            return {"amount": amount, "unit": unit}
    return {}


def _trainer_accepted_commercial(reply: dict, log: dict) -> bool:
    body = str(reply.get("body") or "").lower()
    if reply.get("action") == "mark_declined" or reply.get("sentiment") == "negative":
        return False
    if any(phrase in body for phrase in ["not ok", "not okay", "not possible", "not acceptable", "cannot", "can't"]):
        return False
    return any(phrase in body for phrase in ["ok", "okay", "works", "agree", "accepted", "fine", "confirm", "confirmed", "yes", "sure"])


async def _latest_trainer_slot_reply_text(db, requirement_id: str, trainer_id: str) -> str:
    slot_log = await db["email_logs"].find_one(
        {
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
            "mail_type": {"$in": ["mail3", "mail3_slot_followup"]},
            "reply_text": {"$nin": [None, ""]},
        },
        {"_id": 0, "reply_text": 1},
        sort=[("replied_at", -1), ("created_at", -1)],
    )
    if slot_log and slot_log.get("reply_text"):
        return slot_log.get("reply_text") or ""
    latest_reply = await db["conversations"].find_one(
        {
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
            "direction": "received",
        },
        {"_id": 0, "body": 1},
        sort=[("sent_at", -1), ("created_at", -1)],
    )
    return (latest_reply or {}).get("body") or ""


async def _handle_trainer_commercial_negotiation_reply(
    db,
    request: Request,
    *,
    log: dict,
    reply: dict,
) -> dict | None:
    if (log or {}).get("mail_type") != "trainer_commercial_negotiation":
        return None

    requirement_id = log.get("requirement_id") or ""
    trainer_id = log.get("trainer_id") or ""
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    target = _commercial_log_details(log)
    target_amount = _float_or_zero(target.get("amount"))
    unit = target.get("unit") or "day"
    counter = _trainer_counter_commercial(reply.get("body") or "", log)
    accepted_target = not counter and _trainer_accepted_commercial(reply, log)

    if accepted_target and target_amount > 0:
        slot_text = await _latest_trainer_slot_reply_text(db, requirement_id, trainer_id)
        if slot_text:
            target_text = _commercial_amount_label(target_amount, unit)
            result = await send_client_slot_options_email(
                db,
                {
                    "trainer_id": trainer_id,
                    "trainer_name": log.get("trainer_name") or "the trainer",
                    "trainer_email": log.get("to_email") or "",
                    "requirement_id": requirement_id,
                    "slot_text": slot_text,
                    "trainer_commercial": target_text,
                    "force": True,
                    "source_email_id": log.get("email_id") or "",
                    "source_message_id": log.get("reply_message_id") or "",
                },
                tracking_url_builder=lambda email_id: build_tracking_url(request, email_id),
                source="trainer_commercial_accepted",
                request_base_url=_request_base_url(request),
            )
        else:
            result = {"success": False, "error": "Trainer accepted commercial, but previous slot reply was not found"}
        await db["trainers"].update_one({"trainer_id": trainer_id}, {"$set": {"status": "commercial_accepted"}})
        await db["shortlists"].update_one(
            {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
            {"$set": {
                "top_trainers.$.status": "commercial_accepted",
                "top_trainers.$.pipeline_status": "commercial_accepted",
                "top_trainers.$.commercial_accepted_at": utc_now(),
            }},
        )
        return {"status": "trainer_commercial_accepted", "client_slot_result": result}

    if counter and _float_or_zero(counter.get("amount")) > 0:
        client_budget = client_budget_for_trainer_commercial(requirement, counter)
        trainer_amount = _float_or_zero(counter.get("amount"))
        requested_client_amount = trainer_amount + CLAHAN_CLIENT_COMMERCIAL_MARKUP_INR
        budget_amount = _float_or_zero((client_budget or {}).get("amount"))
        trainer_text = _commercial_amount_label(trainer_amount, counter.get("unit") or unit)
        client_text = _commercial_amount_label(requested_client_amount, counter.get("unit") or unit)

        if budget_amount and requested_client_amount <= budget_amount:
            slot_text = await _latest_trainer_slot_reply_text(db, requirement_id, trainer_id)
            result = await send_client_slot_options_email(
                db,
                {
                    "trainer_id": trainer_id,
                    "trainer_name": log.get("trainer_name") or "the trainer",
                    "trainer_email": log.get("to_email") or "",
                    "requirement_id": requirement_id,
                    "slot_text": slot_text or reply.get("body") or "",
                    "trainer_commercial": trainer_text,
                    "force": True,
                    "source_email_id": log.get("email_id") or "",
                    "source_message_id": log.get("reply_message_id") or "",
                },
                tracking_url_builder=lambda email_id: build_tracking_url(request, email_id),
                source="trainer_commercial_counter_within_budget",
                request_base_url=_request_base_url(request),
            )
            return {"status": "trainer_counter_within_budget", "client_slot_result": result}

        technology = requirement.get("technology_needed") or "training"
        current_budget = budget_amount or _float_or_zero(requirement.get("budget_per_day") or requirement.get("budget_total"))
        client_name = requirement.get("client_name") or requirement.get("client_company") or "Client"
        body = (
            f"Dear {client_name},\n\n"
            f"The trainer shortlisted for the {technology} requirement has requested {trainer_text}.\n\n"
            f"Including Clahan Technologies coordination, the revised commercial will be {client_text}.\n\n"
            "Please confirm if this is acceptable to proceed with this trainer. "
            "If this is not workable, we will continue searching and share another suitable trainer profile.\n\n"
            "Regards,\n"
            "Recruitment Team\n"
            "Clahan Technologies"
        )
        result = await request_client_budget_increase(
            requirement_id,
            {
                "trainer_id": trainer_id,
                "trainer_name": log.get("trainer_name") or "",
                "current_budget": current_budget,
                "requested_budget": requested_client_amount,
                "increment": max(0, requested_client_amount - current_budget) if current_budget else CLAHAN_CLIENT_COMMERCIAL_MARKUP_INR,
                "unit": counter.get("unit") or unit,
                "subject": f"Commercial Confirmation Required - {technology} Training",
                "body": body,
            },
            request,
        )
        await db["trainers"].update_one({"trainer_id": trainer_id}, {"$set": {"status": "client_budget_approval_requested"}})
        await db["shortlists"].update_one(
            {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
            {"$set": {
                "top_trainers.$.status": "client_budget_approval_requested",
                "top_trainers.$.pipeline_status": "client_budget_approval_requested",
                "top_trainers.$.client_budget_requested_at": utc_now(),
            }},
        )
        return {"status": "client_budget_approval_requested", "client_budget_request": result}

    if reply.get("action") == "mark_declined" or reply.get("sentiment") == "negative":
        await db["trainers"].update_one({"trainer_id": trainer_id}, {"$set": {"status": "declined"}})
        followup = await _send_next_trainer_after_decline(db, request, declined_log=log, reply=reply)
        return {"status": "trainer_commercial_declined", "next_trainer": followup}

    await db["trainers"].update_one({"trainer_id": trainer_id}, {"$set": {"status": "commercial_needs_review"}})
    return {"status": "trainer_commercial_needs_review", "reason": "Commercial reply is unclear"}


@router.get("/purchase-orders/{po_id}/download", name="download_purchase_order")
async def download_purchase_order(po_id: str):
    db = get_db()
    doc = await db["purchase_orders"].find_one({"po_id": po_id})
    if not doc:
        raise HTTPException(404, "Purchase order not found")

    try:
        pdf_bytes = _purchase_order_pdf_from_doc(doc)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Purchase order PDF download failed: {exc}")

    if not doc.get("pdf_base64"):
        await db["purchase_orders"].update_one(
            {"po_id": po_id},
            {"$set": {
                "pdf_base64": _base64.b64encode(pdf_bytes).decode("ascii"),
                "pdf_generated_at": utc_now(),
            }},
        )

    filename = doc.get("pdf_filename") or purchase_order_filename(doc)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/purchase-orders/{po_id}/send")
async def send_purchase_order(po_id: str, payload: dict, request: Request):
    db = get_db()
    doc = await db["purchase_orders"].find_one({"po_id": po_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Purchase order not found")

    trainer = doc.get("trainer") or {}
    requirement = doc.get("requirement") or {}
    commercials = doc.get("commercials") or {}
    to_email = payload.get("to_email") or trainer.get("email")
    if not to_email:
        raise HTTPException(400, "Trainer email is required to send PO")

    try:
        pdf_bytes = _purchase_order_pdf_from_doc(doc)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Purchase order PDF generation failed: {exc}")

    filename = doc.get("pdf_filename") or purchase_order_filename(doc)
    subject = payload.get("subject") or f"Purchase Order {doc.get('po_number')} - {requirement.get('technology', 'Training')}"
    body = payload.get("body") or (
        f"Dear {trainer.get('name') or 'Trainer'},\n\n"
        f"Please find attached Purchase Order {doc.get('po_number')} for the "
        f"{requirement.get('technology', 'training')} engagement.\n\n"
        f"Grand Total: {commercials.get('currency', 'INR')} {commercials.get('grand_total', 0):,.2f}\n"
        f"Payment Terms: {doc.get('payment_terms')}\n\n"
        "Kindly acknowledge receipt and share your invoice as per the agreed terms.\n\n"
        "Regards,\n"
        "TrainerSync Team"
    )

    smtp_config = await get_admin_email_config(db)
    email_success, email_error = _send_toc_email_with_attachment(
        to_email,
        subject,
        body,
        filename,
        pdf_bytes,
        smtp_config,
    )

    download_url = _purchase_order_download_url(request, po_id)
    whatsapp_body = (
        "TrainerSync purchase order\n"
        f"PO: {doc.get('po_number')}\n"
        f"Trainer: {trainer.get('name') or 'Trainer'}\n"
        f"Technology: {requirement.get('technology') or 'Training'}\n"
        f"Grand Total: {commercials.get('currency', 'INR')} {commercials.get('grand_total', 0):,.2f}\n"
        "Please review and acknowledge the attached PO."
    )
    whatsapp_result = await send_whatsapp_message(
        db,
        trainer.get("phone", ""),
        whatsapp_body,
        event_type="purchase_order_document",
        recipient_type="trainer",
        request_base_url=_request_base_url(request),
        media_url=download_url,
        context={
            "po_id": po_id,
            "po_number": doc.get("po_number"),
            "trainer_id": trainer.get("trainer_id"),
            "trainer_name": trainer.get("name"),
            "requirement_id": requirement.get("requirement_id"),
            "technology": requirement.get("technology"),
        },
    )

    status = "sent" if email_success or whatsapp_result.get("success") else "send_failed"
    sent_at = utc_now()
    await db["purchase_orders"].update_one(
        {"po_id": po_id},
        {"$set": {
            "status": status,
            "sent_at": sent_at if status == "sent" else None,
            "email_status": "sent" if email_success else "failed",
            "email_error": email_error,
            "whatsapp_summary": whatsapp_result,
            "download_url": download_url,
        }},
    )
    await db["conversations"].insert_one({
        "trainer_id": trainer.get("trainer_id"),
        "trainer_name": trainer.get("name"),
        "to_email": to_email,
        "requirement_id": requirement.get("requirement_id"),
        "subject": subject,
        "body": body,
        "mail_type": "purchase_order",
        "direction": "sent",
        "status": "sent" if status == "sent" else "failed",
        "error": "" if status == "sent" else email_error or whatsapp_result.get("error", ""),
        "sent_at": sent_at,
        "po_id": po_id,
        "po_number": doc.get("po_number"),
    })

    updated = await db["purchase_orders"].find_one({"po_id": po_id}, {"_id": 0})
    if status != "sent":
        raise HTTPException(500, {
            "message": "Purchase order send failed",
            "email_error": email_error,
            "whatsapp": whatsapp_result,
        })

    return {
        "success": True,
        "message": "Purchase order sent",
        "purchase_order": public_purchase_order(updated),
        "email": {"success": email_success, "error": email_error},
        "whatsapp": whatsapp_result,
    }


@router.post("/purchase-orders/{po_id}/acknowledge")
async def acknowledge_purchase_order(po_id: str):
    db = get_db()
    result = await db["purchase_orders"].update_one(
        {"po_id": po_id},
        {"$set": {"status": "acknowledged", "acknowledged_at": utc_now()}},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Purchase order not found")
    doc = await db["purchase_orders"].find_one({"po_id": po_id}, {"_id": 0})
    return {"success": True, "purchase_order": public_purchase_order(doc)}


@router.post("/purchase-orders/{po_id}/generate-invoice")
async def generate_invoice_from_purchase_order(po_id: str, payload: dict, request: Request):
    db = get_db()
    po_doc = await db["purchase_orders"].find_one({"po_id": po_id}, {"_id": 0})
    if not po_doc:
        raise HTTPException(404, "Purchase order not found")

    trainer = po_doc.get("trainer") or {}
    requirement = po_doc.get("requirement") or {}
    requirement_id = requirement.get("requirement_id") or ""
    full_requirement = {}
    if requirement_id:
        full_requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}

    client_email = str(
        requirement.get("client_email")
        or full_requirement.get("client_email")
        or payload.get("client_email")
        or ""
    ).strip()
    requested_client_email = str(payload.get("client_email") or "").strip()
    saved_client_email = str(full_requirement.get("client_email") or requirement.get("client_email") or "").strip()
    if saved_client_email and requested_client_email and saved_client_email.lower() != requested_client_email.lower():
        raise HTTPException(400, "Client email mismatch. Invoice can only be sent to the client saved on this requirement.")
    if not client_email:
        raise HTTPException(400, "Client email is required before generating invoice")

    client_name = (
        payload.get("client_name")
        or requirement.get("client_name")
        or full_requirement.get("client_company")
        or full_requirement.get("client_name")
        or client_email
    )
    invoice_number = await _next_invoice_number(db)
    invoice_id = f"INV-DOC-{uuid.uuid4().hex[:8].upper()}"
    now = utc_now()
    invoice_doc = {
        "invoice_id": invoice_id,
        "invoice_number": invoice_number,
        "po_id": po_id,
        "po_number": po_doc.get("po_number"),
        "po_date": po_doc.get("issue_date_display") or "",
        "ref_number": payload.get("ref_number") or requirement_id,
        "hsn_sac": payload.get("hsn_sac") or "999293",
        "quantity": payload.get("quantity") or (po_doc.get("requirement") or {}).get("duration_days") or 1,
        "status": "generated",
        "issue_date": now,
        "issue_date_display": now.strftime("%d %b %Y"),
        "company": po_doc.get("company") or {},
        "trainer": trainer,
        "client": {
            "name": client_name,
            "email": client_email,
        },
        "requirement": {
            **requirement,
            "requirement_id": requirement_id,
            "client_email": client_email,
            "client_name": client_name,
        },
        "commercials": po_doc.get("commercials") or {},
        "payment_terms": payload.get("payment_terms") or po_doc.get("payment_terms") or DEFAULT_PAYMENT_TERMS if "DEFAULT_PAYMENT_TERMS" in globals() else po_doc.get("payment_terms", ""),
        "source": "purchase_order",
        "created_at": now,
        "download_url": _invoice_download_url(request, invoice_id),
    }

    try:
        html = _render_invoice_html(invoice_doc)
        pdf_bytes = _invoice_pdf_from_doc(invoice_doc)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Invoice PDF generation failed: {exc}")

    invoice_doc.update({
        "html": html,
        "pdf_base64": _base64.b64encode(pdf_bytes).decode("ascii"),
        "pdf_content_type": "application/pdf",
        "pdf_filename": _invoice_filename(invoice_doc),
        "pdf_generated_at": utc_now(),
    })
    await db["invoices"].insert_one(invoice_doc)
    await db["purchase_orders"].update_one(
        {"po_id": po_id},
        {"$set": {
            "invoice_id": invoice_id,
            "invoice_number": invoice_number,
            "invoice_status": "generated",
            "invoice_generated_at": utc_now(),
        }},
    )
    return {
        "success": True,
        "message": "Invoice generated",
        "invoice": _public_invoice(invoice_doc),
    }


@router.post("/requirements/{requirement_id}/client-po/generate-invoice")
async def generate_invoice_from_client_purchase_order(requirement_id: str, payload: dict, request: Request):
    db = get_db()
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    if not requirement:
        raise HTTPException(404, "Requirement not found")

    trainer_id = str(payload.get("trainer_id") or requirement.get("selected_trainer_id") or "").strip()
    if not trainer_id:
        raise HTTPException(400, "trainer_id is required to generate invoice from client PO")
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0})
    if not trainer:
        raise HTTPException(404, "Trainer not found")

    client_email = str(payload.get("client_email") or requirement.get("client_email") or "").strip()
    saved_client_email = str(requirement.get("client_email") or "").strip()
    if saved_client_email and client_email and saved_client_email.lower() != client_email.lower():
        raise HTTPException(400, "Client email mismatch. Invoice can only be generated for the saved requirement client.")
    if not client_email:
        raise HTTPException(400, "Client email is required before generating invoice")

    client_po_number = str(payload.get("client_po_number") or payload.get("po_number") or "").strip()
    if not client_po_number:
        raise HTTPException(400, "Client PO number is required")

    try:
        total_amount = float(payload.get("total_amount") or 0)
    except Exception:
        total_amount = 0
    if total_amount <= 0:
        raise HTTPException(400, "Client PO total amount is required")

    gst_rate = _float_or_zero(payload.get("gst_rate") or 18)
    gst_amount = _gst_amount_for_invoice(total_amount, gst_rate)
    grand_total = round(total_amount + gst_amount, 2)
    client_name = (
        payload.get("client_name")
        or requirement.get("client_company")
        or requirement.get("client_name")
        or client_email
    )
    training_dates = (
        payload.get("training_dates")
        or requirement.get("training_dates")
        or requirement.get("timeline_start")
        or "As per client PO"
    )
    duration_days = payload.get("duration_days") or requirement.get("duration_days") or ""
    duration = payload.get("duration") or (f"{duration_days} day(s)" if duration_days else "As per client PO")
    invoice_number = str(payload.get("invoice_number") or "").strip() or await _next_invoice_number(db)
    invoice_id = f"INV-DOC-{uuid.uuid4().hex[:8].upper()}"
    now = utc_now()
    invoice_type = str(payload.get("invoice_type") or "").lower()
    default_company = {
        "name": "BEULIX SOLUTIONS PRIVATE LIMITED",
        "address": "No.29/2, 1st Main Road, Maruthinagar, Madivala, Bangalore - Karnataka 560068",
        "email": "finance@beulixsolutions.com",
        "phone": "8179147889",
        "pan": "AANCB2798",
        "gstin": "29AANCB2798L1ZS",
    } if invoice_type == "beulix" else {
        "name": "Clahan Technologies",
        "tagline": "Corporate Training and Technology Consulting",
        "address": payload.get("calhan_address") or "",
        "email": payload.get("calhan_email") or getattr(get_settings(), "from_email", "") or getattr(get_settings(), "gmail_user", ""),
        "phone": payload.get("calhan_phone") or "",
        "gstin": payload.get("calhan_gstin") or "",
    }
    invoice_doc = {
        "invoice_id": invoice_id,
        "invoice_number": invoice_number,
        "client_po_number": client_po_number,
        "po_number": client_po_number,
        "po_date": payload.get("client_po_date") or payload.get("po_date") or "",
        "ref_number": payload.get("ref_number") or payload.get("project_name") or requirement_id,
        "project_name": payload.get("project_name") or requirement.get("project_name") or requirement.get("technology_needed") or "",
        "start_date": payload.get("start_date") or "",
        "end_date": payload.get("end_date") or "",
        "hsn_sac": payload.get("hsn_sac") or "999293",
        "quantity": payload.get("quantity") or duration_days or 1,
        "items": payload.get("items") or [],
        "tax_type": payload.get("tax_type") or "",
        "invoice_type": invoice_type,
        "status": "generated",
        "issue_date": now,
        "issue_date_display": payload.get("invoice_date") or now.strftime("%d %b %Y"),
        "due_date_display": payload.get("due_date") or "",
        "company": payload.get("company") or default_company,
        "trainer": {
            "trainer_id": trainer.get("trainer_id"),
            "name": trainer.get("name") or payload.get("trainer_name") or "Trainer",
            "email": trainer.get("email") or "",
            "phone": trainer.get("phone") or "",
            "location": trainer.get("location") or "",
        },
        "client": {
            "name": client_name,
            "email": client_email,
            "billing_address": payload.get("client_billing_address") or "",
            "gstin": payload.get("client_gstin") or "",
            "pan": payload.get("client_pan") or "",
        },
        "requirement": {
            "requirement_id": requirement_id,
            "technology": payload.get("technology") or requirement.get("technology_needed") or "Training",
            "client_email": client_email,
            "client_name": client_name,
            "mode": payload.get("mode") or requirement.get("mode") or "Online",
            "course_name": payload.get("course_name") or "",
            "classroom_location": payload.get("classroom_location") or "",
            "mode_of_lecture": payload.get("mode_of_lecture") or "",
            "contact_person": payload.get("contact_person") or "",
            "contact_number": payload.get("contact_number") or "",
            "training_dates": training_dates,
            "duration": duration,
            "duration_days": duration_days,
        },
        "commercials": {
            "currency": payload.get("currency") or requirement.get("budget_currency") or "INR",
            "day_rate": _float_or_zero(payload.get("day_rate")),
            "total_amount": total_amount,
            "gst_rate": gst_rate,
            "gst_amount": gst_amount,
            "grand_total": grand_total,
        },
        "payment_terms": payload.get("payment_terms") or "As per client PO.",
        "client_po_notes": payload.get("client_po_notes") or "",
        "source": "client_purchase_order",
        "created_at": now,
        "download_url": _invoice_download_url(request, invoice_id),
    }

    try:
        html = _render_invoice_html(invoice_doc)
        pdf_bytes = _invoice_pdf_from_doc(invoice_doc)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Invoice PDF generation failed: {exc}")

    invoice_doc.update({
        "html": html,
        "pdf_base64": _base64.b64encode(pdf_bytes).decode("ascii"),
        "pdf_content_type": "application/pdf",
        "pdf_filename": _invoice_filename(invoice_doc),
        "pdf_generated_at": utc_now(),
    })
    await db["invoices"].insert_one(invoice_doc)
    await db["client_purchase_orders"].update_one(
        {"requirement_id": requirement_id, "trainer_id": trainer_id, "client_po_number": client_po_number},
        {"$set": {
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
            "trainer_name": trainer.get("name"),
            "client_email": client_email,
            "client_name": client_name,
            "client_po_number": client_po_number,
            "client_po_date": invoice_doc.get("po_date"),
            "total_amount": total_amount,
            "gst_rate": gst_rate,
            "gst_amount": gst_amount,
            "grand_total": grand_total,
            "invoice_id": invoice_id,
            "invoice_number": invoice_number,
            "status": "invoice_generated",
            "updated_at": utc_now(),
        }, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    await db["requirements"].update_one(
        {"requirement_id": requirement_id},
        {"$set": {
            "client_po_status": "received",
            "client_po_number": client_po_number,
            "client_po_received_at": now,
            "invoice_id": invoice_id,
            "invoice_number": invoice_number,
            "invoice_status": "generated",
            "invoice_generated_at": utc_now(),
        }},
    )
    return {
        "success": True,
        "message": "Invoice generated from client PO",
        "invoice": _public_invoice(invoice_doc),
    }


@router.get("/invoices/{invoice_id}/download", name="download_invoice")
async def download_invoice(invoice_id: str):
    db = get_db()
    doc = await db["invoices"].find_one({"invoice_id": invoice_id})
    if not doc:
        raise HTTPException(404, "Invoice not found")
    try:
        pdf_bytes = _invoice_pdf_from_doc(doc)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Invoice PDF download failed: {exc}")
    filename = doc.get("pdf_filename") or _invoice_filename(doc)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/invoices/{invoice_id}/send")
async def send_invoice(invoice_id: str, payload: dict, request: Request):
    db = get_db()
    doc = await db["invoices"].find_one({"invoice_id": invoice_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Invoice not found")

    client = doc.get("client") or {}
    trainer = doc.get("trainer") or {}
    requirement = doc.get("requirement") or {}
    to_email = str(client.get("email") or "").strip()
    requested_to = str(payload.get("to_email") or "").strip()
    if requested_to and requested_to.lower() != to_email.lower():
        raise HTTPException(400, "Client email mismatch. Invoice can only be sent to the saved invoice client.")
    if not to_email:
        raise HTTPException(400, "Client email is required to send invoice")

    try:
        pdf_bytes = _invoice_pdf_from_doc(doc)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Invoice PDF generation failed: {exc}")

    filename = doc.get("pdf_filename") or _invoice_filename(doc)
    subject = payload.get("subject") or f"Invoice {doc.get('invoice_number')} for PO {doc.get('po_number')} - {requirement.get('technology', 'Training')}"
    body = payload.get("body") or (
        f"Dear {client.get('name') or 'Client'},\n\n"
        f"Please find attached invoice {doc.get('invoice_number')} for the {requirement.get('technology', 'training')} engagement.\n\n"
        f"PO Reference: {doc.get('po_number')}\n"
        f"Trainer: {trainer.get('name') or 'Trainer'}\n"
        f"Grand Total: {_money_text((doc.get('commercials') or {}).get('grand_total'))}\n\n"
        "Kindly process as per the agreed terms.\n\n"
        "Regards,\nTrainerSync Team"
    )
    smtp_config = await get_admin_email_config(db)
    email_success, email_error = _send_toc_email_with_attachment(
        to_email,
        subject,
        body,
        filename,
        pdf_bytes,
        smtp_config,
    )

    sent_at = utc_now()
    status = "sent" if email_success else "send_failed"
    await db["invoices"].update_one(
        {"invoice_id": invoice_id},
        {"$set": {
            "status": status,
            "sent_at": sent_at if email_success else None,
            "email_status": "sent" if email_success else "failed",
            "email_error": email_error,
        }},
    )
    await db["purchase_orders"].update_one(
        {"po_id": doc.get("po_id")},
        {"$set": {
            "invoice_status": status,
            "invoice_sent_at": sent_at if email_success else None,
        }},
    )
    requirement_id = requirement.get("requirement_id") or ""
    trainer_id = trainer.get("trainer_id") or ""
    client_po_number = doc.get("client_po_number") or doc.get("po_number")
    if doc.get("source") == "client_purchase_order":
        client_po_query = {
            "invoice_id": invoice_id,
        }
        if requirement_id and trainer_id and client_po_number:
            client_po_query = {
                "requirement_id": requirement_id,
                "trainer_id": trainer_id,
                "client_po_number": client_po_number,
            }
        await db["client_purchase_orders"].update_one(
            client_po_query,
            {"$set": {
                "status": "invoice_sent" if email_success else "invoice_send_failed",
                "invoice_status": status,
                "invoice_sent_at": sent_at if email_success else None,
                "updated_at": utc_now(),
                "email_error": "" if email_success else email_error,
            }},
        )
    if requirement_id:
        await db["requirements"].update_one(
            {"requirement_id": requirement_id},
            {"$set": {
                "invoice_id": invoice_id,
                "invoice_number": doc.get("invoice_number"),
                "invoice_status": status,
                "invoice_sent_at": sent_at if email_success else None,
                "client_po_status": "invoice_sent" if email_success else requirement.get("client_po_status", "received"),
            }},
        )
    await db["client_messages"].insert_one({
        "message_id": f"CLIENT-MSG-{uuid.uuid4().hex[:8].upper()}",
        "client_email": to_email,
        "client_name": client.get("name") or "",
        "requirement_id": requirement.get("requirement_id") or "",
        "trainer_id": trainer.get("trainer_id") or "",
        "trainer_name": trainer.get("name") or "",
        "subject": subject,
        "body": body,
        "mail_type": "invoice",
        "direction": "sent",
        "status": "sent" if email_success else "failed",
        "error": "" if email_success else email_error,
        "sent_at": sent_at,
        "invoice_id": invoice_id,
        "invoice_number": doc.get("invoice_number"),
        "po_id": doc.get("po_id"),
        "po_number": doc.get("po_number"),
        "source": "invoice",
    })
    updated = await db["invoices"].find_one({"invoice_id": invoice_id}, {"_id": 0})
    if not email_success:
        raise HTTPException(500, email_error or "Invoice send failed")
    return {
        "success": True,
        "message": "Invoice sent to client",
        "invoice": _public_invoice(updated),
    }


def _client_pipeline_dt(value):
    if isinstance(value, datetime):
        return value
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def _client_pipeline_preview(text: str = "", limit: int = 220) -> str:
    clean = _re.sub(r"\s+", " ", str(text or "")).strip()
    return clean[:limit]


def _client_pipeline_stage_status(requirement: dict, shortlist: dict, client_po: dict, invoice: dict) -> dict:
    selected = bool(requirement.get("selected_trainer_id") or requirement.get("selection_status") == "selected")
    po_status = str(requirement.get("client_po_status") or client_po.get("status") or "").lower()
    po_requested = str(requirement.get("po_request_status") or "").lower() == "requested" or bool(requirement.get("po_requested_at"))
    invoice_status = str(requirement.get("invoice_status") or invoice.get("status") or "").lower()
    commercial_revision_requested = bool(requirement.get("client_budget_revision_requested_at"))
    commercial_done = selected and (
        not commercial_revision_requested
        or po_requested
        or po_status in {"requested", "received", "invoice_generated", "invoice_sent"}
        or bool(client_po)
        or invoice_status in {"generated", "sent"}
    )
    return {
        "client_request": "done" if requirement.get("requirement_id") else "pending",
        "shortlist": "done" if shortlist.get("top_trainers") else "pending",
        "selection": "done" if selected else "pending",
        "commercial_alignment": "done" if commercial_done else ("pending" if selected else "locked"),
        "po_request": "done" if po_requested or po_status in {"requested", "received", "invoice_generated", "invoice_sent"} or client_po else ("ready" if selected else "locked"),
        "client_po": "done" if po_status in {"received", "invoice_generated", "invoice_sent"} or client_po.get("client_po_number") else "pending",
        "invoice": "done" if invoice.get("invoice_id") or invoice_status in {"generated", "sent"} else "pending",
        "invoice_sent": "done" if invoice_status == "sent" or po_status == "invoice_sent" else "pending",
    }


@router.get("/client-pipeline")
async def get_client_pipeline(q: Optional[str] = None, domain: Optional[str] = None, limit: int = 80):
    db = get_db()
    limit = max(10, min(int(limit or 80), 200))
    filters = []
    if domain:
        pattern = {"$regex": _re.escape(domain.strip()), "$options": "i"}
        filters.append({"$or": [
            {"technology_needed": pattern},
            {"job_title": pattern},
            {"job_description": pattern},
        ]})
    if q:
        pattern = {"$regex": _re.escape(q.strip()), "$options": "i"}
        filters.append({"$or": [
            {"requirement_id": pattern},
            {"technology_needed": pattern},
            {"job_title": pattern},
            {"client_email": pattern},
            {"client_name": pattern},
            {"client_company": pattern},
            {"selected_trainer_name": pattern},
        ]})
    query = {"$and": filters} if filters else {}
    requirements = await db["requirements"].find(query, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    requirement_ids = [doc.get("requirement_id") for doc in requirements if doc.get("requirement_id")]
    trainer_ids = [doc.get("selected_trainer_id") for doc in requirements if doc.get("selected_trainer_id")]

    shortlists = {}
    client_emails = []
    client_messages = []
    client_slots = []
    confirmations = []
    invoices = {}
    client_pos = {}
    trainers = {}
    email_logs = []
    if requirement_ids:
        shortlist_docs = await db["shortlists"].find({"requirement_id": {"$in": requirement_ids}}, {"_id": 0}).to_list(len(requirement_ids))
        shortlists = {doc.get("requirement_id"): doc for doc in shortlist_docs}
        client_emails = await db["client_emails"].find({"requirement_id": {"$in": requirement_ids}}, {"_id": 0}).sort("received_at", -1).limit(300).to_list(300)
        client_messages = await db["client_messages"].find({"requirement_id": {"$in": requirement_ids}}, {"_id": 0}).sort("created_at", -1).limit(400).to_list(400)
        client_slots = await db["client_slot_emails"].find({"requirement_id": {"$in": requirement_ids}}, {"_id": 0}).sort("created_at", -1).limit(300).to_list(300)
        confirmations = await db["client_slot_confirmations"].find({"requirement_id": {"$in": requirement_ids}}, {"_id": 0}).sort("created_at", -1).limit(300).to_list(300)
        invoice_docs = await db["invoices"].find({"requirement.requirement_id": {"$in": requirement_ids}}, {"_id": 0}).sort("created_at", -1).limit(300).to_list(300)
        po_docs = await db["client_purchase_orders"].find({"requirement_id": {"$in": requirement_ids}}, {"_id": 0}).sort("updated_at", -1).limit(300).to_list(300)
        email_logs = await db["email_logs"].find({"requirement_id": {"$in": requirement_ids}}, {"_id": 0}).sort("created_at", -1).limit(500).to_list(500)
        for doc in invoice_docs:
            req_id = (doc.get("requirement") or {}).get("requirement_id")
            if req_id and req_id not in invoices:
                invoices[req_id] = doc
        for doc in po_docs:
            req_id = doc.get("requirement_id")
            if req_id and req_id not in client_pos:
                client_pos[req_id] = doc
        if trainer_ids:
            trainer_docs = await db["trainers"].find({"trainer_id": {"$in": trainer_ids}}, {"_id": 0}).to_list(len(trainer_ids))
            trainers = {doc.get("trainer_id"): doc for doc in trainer_docs}

    by_req = {req_id: {"client_emails": [], "client_messages": [], "client_slots": [], "confirmations": [], "email_logs": []} for req_id in requirement_ids}
    for collection_name, docs in [
        ("client_emails", client_emails),
        ("client_messages", client_messages),
        ("client_slots", client_slots),
        ("confirmations", confirmations),
        ("email_logs", email_logs),
    ]:
        for doc in docs:
            req_id = doc.get("requirement_id")
            if req_id in by_req:
                by_req[req_id][collection_name].append(doc)

    items = []
    for requirement in requirements:
        req_id = requirement.get("requirement_id")
        grouped = by_req.get(req_id, {})
        shortlist = shortlists.get(req_id) or {}
        invoice = invoices.get(req_id) or {}
        client_po = client_pos.get(req_id) or {}
        selected_trainer = trainers.get(requirement.get("selected_trainer_id")) or {}
        if not selected_trainer and shortlist.get("top_trainers"):
            selected_trainer = next(
                (item for item in shortlist.get("top_trainers", []) if str(item.get("trainer_id")) == str(requirement.get("selected_trainer_id"))),
                {},
            )

        messages = []
        for doc in grouped.get("client_emails", []):
            reply = doc.get("generated_reply") or {}
            messages.append({
                "direction": "received",
                "type": "client_request",
                "label": "Client email received",
                "subject": doc.get("subject") or "",
                "body": doc.get("clean_body") or doc.get("raw_body") or doc.get("snippet") or "",
                "at": doc.get("received_at") or doc.get("created_at"),
                "status": doc.get("status") or "",
            })
            if reply.get("body"):
                messages.append({
                    "direction": "sent",
                    "type": "calhan_reply",
                    "label": "Clahan reply",
                    "subject": reply.get("subject") or f"Re: {doc.get('subject', '')}",
                    "body": reply.get("body"),
                    "at": doc.get("sent_at") or doc.get("created_at"),
                    "status": doc.get("status") or "draft",
                })
        for doc in grouped.get("client_slots", []):
            messages.append({
                "direction": "sent",
                "type": "client_slots",
                "label": "Trainer slots sent to client",
                "subject": doc.get("subject") or "",
                "body": doc.get("body") or doc.get("slot_text") or "",
                "at": doc.get("sent_at") or doc.get("created_at"),
                "status": doc.get("status") or "",
            })
            if doc.get("last_client_reply_text"):
                messages.append({
                    "direction": "received",
                    "type": "client_slot_reply",
                    "label": "Client selected slot",
                    "subject": f"Re: {doc.get('subject', '')}",
                    "body": doc.get("last_client_reply_text"),
                    "at": doc.get("last_client_reply_at") or doc.get("client_confirmed_at"),
                    "status": doc.get("status") or "",
                })
        for doc in grouped.get("confirmations", []):
            messages.append({
                "direction": "received",
                "type": "client_confirmation",
                "label": "Client confirmation",
                "subject": doc.get("subject") or "Client confirmation",
                "body": doc.get("reply_text") or "",
                "at": doc.get("created_at") or doc.get("updated_at"),
                "status": doc.get("status") or "",
            })
        for doc in grouped.get("client_messages", []):
            messages.append({
                "direction": doc.get("direction") or "sent",
                "type": doc.get("mail_type") or "client_message",
                "label": str(doc.get("mail_type") or "Client message").replace("_", " ").title(),
                "subject": doc.get("subject") or "",
                "body": doc.get("body") or "",
                "at": doc.get("sent_at") or doc.get("created_at"),
                "status": doc.get("status") or "",
            })
        if client_po:
            messages.append({
                "direction": "received",
                "type": "client_po",
                "label": "Client PO received",
                "subject": client_po.get("client_po_number") or "Client PO",
                "body": f"Client PO {client_po.get('client_po_number') or ''} received. Amount: {_money_text(client_po.get('grand_total') or client_po.get('total_amount'))}",
                "at": client_po.get("updated_at") or client_po.get("created_at"),
                "status": client_po.get("status") or "received",
            })
        if invoice:
            messages.append({
                "direction": "sent",
                "type": "invoice",
                "label": "Invoice generated" if invoice.get("status") != "sent" else "Invoice sent",
                "subject": invoice.get("invoice_number") or "Invoice",
                "body": f"Invoice {invoice.get('invoice_number') or ''} for PO {invoice.get('po_number') or ''}. Grand total: {_money_text((invoice.get('commercials') or {}).get('grand_total'))}",
                "at": invoice.get("sent_at") or invoice.get("created_at"),
                "status": invoice.get("status") or "generated",
                "invoice_id": invoice.get("invoice_id"),
                "download_url": invoice.get("download_url"),
            })

        messages = sorted(messages, key=lambda item: _client_pipeline_dt(item.get("at")))
        latest = messages[-1] if messages else {}
        domain_label = requirement.get("technology_needed") or requirement.get("job_title") or "Training"
        items.append({
            "requirement_id": req_id,
            "domain": domain_label,
            "client": {
                "name": requirement.get("client_name") or requirement.get("client_company") or requirement.get("client_email") or "Client",
                "email": requirement.get("client_email") or "",
                "company": requirement.get("client_company") or requirement.get("client_name") or "",
                "phone": requirement.get("client_phone") or requirement.get("client_whatsapp") or "",
            },
            "requirement": requirement,
            "shortlist_count": len(shortlist.get("top_trainers") or []),
            "selected_trainer": {
                "trainer_id": selected_trainer.get("trainer_id") or requirement.get("selected_trainer_id") or "",
                "name": selected_trainer.get("name") or selected_trainer.get("trainer_name") or requirement.get("selected_trainer_name") or "",
                "email": selected_trainer.get("email") or selected_trainer.get("to_email") or "",
                "phone": selected_trainer.get("phone") or "",
            },
            "client_po": client_po,
            "invoice": _public_invoice(invoice) if invoice else {},
            "stages": _client_pipeline_stage_status(requirement, shortlist, client_po, invoice),
            "messages": [_public_doc(message) for message in messages],
            "latest_at": latest.get("at") or requirement.get("updated_at") or requirement.get("created_at"),
            "last_preview": _client_pipeline_preview(latest.get("body") or latest.get("subject") or ""),
        })

    facet_reqs = await db["requirements"].find({}, {"_id": 0, "technology_needed": 1}).sort("created_at", -1).limit(500).to_list(500)
    domains = sorted({str(doc.get("technology_needed") or "").strip() for doc in facet_reqs if str(doc.get("technology_needed") or "").strip()})
    return {"items": items, "domains": domains, "total": len(items)}


# Resume upload helpers

def _zip_display_name(path: str) -> str:
    return path.replace("\\", "/").split("/")[-1] or path


def _is_resume_file(path: str) -> bool:
    lower = path.lower()
    return lower.endswith((".pdf", ".docx"))


async def _collect_resume_files(uploaded_files: List[UploadFile]) -> List[dict]:
    collected = []
    for upload in uploaded_files:
        filename = upload.filename or "resume"
        content = await upload.read()
        if not content:
            collected.append({"filename": filename, "error": "Empty file uploaded"})
            continue

        lower = filename.lower()
        if lower.endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    resume_names = [
                        name for name in archive.namelist()
                        if not name.endswith("/")
                        and not name.replace("\\", "/").split("/")[-1].startswith(".")
                        and not name.replace("\\", "/").startswith("__MACOSX/")
                        and _is_resume_file(name)
                    ]
                    unsupported_count = len([
                        name for name in archive.namelist()
                        if not name.endswith("/")
                        and not name.replace("\\", "/").split("/")[-1].startswith(".")
                        and not name.replace("\\", "/").startswith("__MACOSX/")
                        and not _is_resume_file(name)
                    ])
                    if not resume_names:
                        collected.append({
                            "filename": filename,
                            "error": "ZIP contains no PDF or DOCX resume files",
                            "source_archive": filename,
                            "archive_file_count": unsupported_count,
                        })
                    for resume_name in resume_names:
                        collected.append({
                            "filename": _zip_display_name(resume_name),
                            "bytes": archive.read(resume_name),
                            "source_archive": filename,
                            "archive_path": resume_name,
                            "archive_resume_count": len(resume_names),
                            "archive_unsupported_count": unsupported_count,
                        })
            except zipfile.BadZipFile:
                collected.append({"filename": filename, "error": "Invalid ZIP file"})
            continue

        if lower.endswith((".pdf", ".docx")):
            collected.append({"filename": filename, "bytes": content})
        else:
            collected.append({"filename": filename, "error": "Only PDF, DOCX, or ZIP files are accepted"})

    return collected


def _resume_processing_concurrency() -> int:
    try:
        return max(1, min(5, int(os.getenv("RESUME_UPLOAD_CONCURRENCY", "3"))))
    except ValueError:
        return 3


async def _cache_resume_preview(db, processed: dict, item: dict) -> str:
    now = utc_now()
    upload_id = processed.get("upload_id") or f"RES-{uuid.uuid4().hex[:12].upper()}"
    processed["upload_id"] = upload_id

    upload_doc = {
        "upload_id": upload_id,
        "trainer_id": processed.get("trainer_id"),
        "filename": processed.get("filename"),
        "file_size": len(processed.get("raw_text", "")),
        "processing_status": "previewed",
        "extracted_data": public_resume_result(processed),
        "extracted_text": processed.get("raw_text", "")[:50000],
        "confidence_score": processed.get("confidence_score", 0),
        "created_at": now,
        "processed_at": now,
        "previewed_at": now,
    }
    for key in ("source_archive", "archive_path", "archive_resume_count", "archive_unsupported_count"):
        if item.get(key) is not None:
            upload_doc[key] = item.get(key)

    await db["resume_uploads"].update_one(
        {"upload_id": upload_id},
        {"$set": upload_doc},
        upsert=True,
    )
    return upload_id


def _profile_from_resume_upload(upload: dict, corrections: Optional[dict] = None) -> dict:
    extracted = dict(upload.get("extracted_data") or {})
    if corrections:
        extracted.update(corrections)

    return {
        **extracted,
        "success": True,
        "upload_id": upload.get("upload_id"),
        "trainer_id": extracted.get("trainer_id") or upload.get("trainer_id"),
        "filename": extracted.get("filename") or upload.get("filename"),
        "raw_text": upload.get("extracted_text") or upload.get("raw_text") or "",
        "source_archive": upload.get("source_archive") or extracted.get("source_archive"),
        "archive_path": upload.get("archive_path") or extracted.get("archive_path"),
        "confidence_score": extracted.get("confidence_score") or upload.get("confidence_score") or 0,
    }


def _resume_upload_corrections(corrections: Optional[dict], upload_id: str) -> dict:
    if not isinstance(corrections, dict):
        return {}
    scoped = corrections.get(upload_id)
    if isinstance(scoped, dict):
        return scoped
    known_profile_fields = {
        "name", "email", "phone", "location", "linkedin", "experience_years",
        "teams_email", "microsoft_teams_email", "teams_upn",
        "experience_raw", "role_designation", "education", "skills", "technologies",
        "certifications", "past_clients", "training_count", "day_rate", "hourly_rate",
        "technology_category", "secondary_categories", "category", "summary",
    }
    if any(key in known_profile_fields for key in corrections):
        return corrections
    return {}


async def _handle_resume_upload_item(db, item: dict, confirm: bool) -> tuple[dict, Optional[str]]:
    if item.get("error"):
        return {
            "filename": item["filename"],
            "success": False,
            "error": item["error"],
            "saved": False,
        }, None

    try:
        processed = await process_resume(item["bytes"], item["filename"], db)
        for key in ("source_archive", "archive_path", "archive_resume_count", "archive_unsupported_count"):
            if item.get(key) is not None:
                processed[key] = item.get(key)

        save_result = {"saved": False}
        saved_trainer_id = None
        if processed.get("success"):
            if confirm:
                save_result = await save_trainer_from_resume(processed, db, use_ai_tags=False)
                saved_trainer_id = save_result.get("trainer_id") if save_result.get("saved") else None
                if saved_trainer_id:
                    verified_lead = await _auto_verify_lead_on_resume_upload(
                        db,
                        {**processed, "trainer_id": saved_trainer_id},
                    )
                    if verified_lead:
                        save_result["linkedin_lead_verified"] = verified_lead.get("lead_id")
            else:
                await _cache_resume_preview(db, processed, item)

        return {
            **public_resume_result(processed),
            **save_result,
        }, saved_trainer_id
    except Exception as exc:
        return {
            "filename": item.get("filename", "resume"),
            "success": False,
            "error": str(exc),
            "saved": False,
        }, None


@router.post("/trainers/upload-resume")
async def upload_resume(
    background_tasks: BackgroundTasks,
    files: Optional[List[UploadFile]] = File(None),
    file: Optional[UploadFile] = File(None),
    confirm: bool = False,
):
    uploaded_files = []
    if files:
        uploaded_files.extend(files)
    if file:
        uploaded_files.append(file)
    if not uploaded_files:
        raise HTTPException(400, "Upload at least one PDF, DOCX, or ZIP file")

    db = get_db()
    collected = await _collect_resume_files(uploaded_files)
    semaphore = asyncio.Semaphore(_resume_processing_concurrency())

    async def run_item(item: dict):
        async with semaphore:
            return await _handle_resume_upload_item(db, item, confirm)

    item_results = await asyncio.gather(*(run_item(item) for item in collected))
    results = [result for result, _trainer_id in item_results]
    saved_trainer_ids = [trainer_id for _result, trainer_id in item_results if trainer_id]
    if confirm and saved_trainer_ids:
        background_tasks.add_task(_categorise_trainers_background, saved_trainer_ids)

    success_count = sum(1 for r in results if r.get("success"))
    error_count = sum(1 for r in results if not r.get("success"))
    saved_count = sum(1 for r in results if r.get("saved"))
    inserted = sum(1 for r in results if r.get("saved") and r.get("action") == "inserted")
    updated = sum(1 for r in results if r.get("saved") and r.get("action") == "updated")
    archive_resume_count = sum(1 for item in collected if item.get("source_archive") and item.get("bytes"))
    archive_names = sorted({item["source_archive"] for item in collected if item.get("source_archive")})
    return {
        "confirm": confirm,
        "total": len(results),
        "success_count": success_count,
        "error_count": error_count,
        "archive_count": len(archive_names),
        "archive_resume_count": archive_resume_count,
        "archives": archive_names,
        "saved_count": saved_count,
        "inserted": inserted,
        "updated": updated,
        "results": results,
    }


# ─── Clear Database ───────────────────────────────────────────────────────────

@router.post("/trainers/confirm-resumes")
async def confirm_resume_previews(payload: dict, background_tasks: BackgroundTasks):
    upload_ids = payload.get("upload_ids") or payload.get("uploadIds") or []
    if isinstance(upload_ids, str):
        upload_ids = [upload_ids]
    upload_ids = [str(upload_id).strip() for upload_id in upload_ids if str(upload_id).strip()]
    if not upload_ids:
        raise HTTPException(400, "Provide at least one preview upload_id to confirm")

    db = get_db()
    corrections = payload.get("corrections") or {}
    results = []
    saved_trainer_ids = []

    for upload_id in upload_ids:
        try:
            upload = await db["resume_uploads"].find_one({"upload_id": upload_id})
            if not upload:
                results.append({
                    "upload_id": upload_id,
                    "success": False,
                    "saved": False,
                    "error": "Resume preview not found. Please extract preview again.",
                })
                continue

            profile = _profile_from_resume_upload(
                upload,
                _resume_upload_corrections(corrections, upload_id),
            )
            save_result = await save_trainer_from_resume(profile, db, use_ai_tags=False)
            if save_result.get("saved") and save_result.get("trainer_id"):
                saved_trainer_ids.append(save_result["trainer_id"])
                verified_lead = await _auto_verify_lead_on_resume_upload(
                    db,
                    {**profile, "trainer_id": save_result["trainer_id"]},
                )
                if verified_lead:
                    save_result["linkedin_lead_verified"] = verified_lead.get("lead_id")

            results.append({
                "upload_id": upload_id,
                "filename": upload.get("filename"),
                "success": bool(save_result.get("saved")),
                **save_result,
            })
        except Exception as exc:
            results.append({
                "upload_id": upload_id,
                "success": False,
                "saved": False,
                "error": str(exc),
            })

    if saved_trainer_ids:
        background_tasks.add_task(_categorise_trainers_background, saved_trainer_ids)

    saved_count = sum(1 for r in results if r.get("saved"))
    return {
        "confirm": True,
        "total": len(results),
        "success_count": saved_count,
        "error_count": sum(1 for r in results if not r.get("saved")),
        "saved_count": saved_count,
        "inserted": sum(1 for r in results if r.get("saved") and r.get("action") == "inserted"),
        "updated": sum(1 for r in results if r.get("saved") and r.get("action") == "updated"),
        "background_categorisation": bool(saved_trainer_ids),
        "results": results,
    }


@router.delete("/database/clear")
async def clear_database():
    db = get_db()
    results = {}
    for col in ["trainers", "requirements", "shortlists", "email_logs"]:
        r = await db[col].delete_many({})
        results[col] = r.deleted_count
    return {"message": "✅ Database cleared", "deleted": results}


# ─── Get All Trainers ─────────────────────────────────────────────────────────

@router.get("/trainers")
async def get_trainers(
    status: Optional[str] = None,
    search: Optional[str] = None,
    category: Optional[str] = None,
    domain: Optional[str] = None,
    industry: Optional[str] = None,
    experience: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
):
    db = get_db()
    clauses = []
    if status:
        clauses.append({"status": status})
    if category:
        clauses.append({"$or": [
            {"primary_category": category},
            {"secondary_categories": category},
            {"technology_category": category},
            {"category": category},
        ]})
    if domain:
        domain_pattern = _re.escape(domain.strip())
        clauses.append({"$or": [
            {"domain": {"$regex": domain_pattern, "$options": "i"}},
            {"primary_category": {"$regex": domain_pattern, "$options": "i"}},
            {"technology_category": {"$regex": domain_pattern, "$options": "i"}},
            {"category": {"$regex": domain_pattern, "$options": "i"}},
            {"secondary_categories": {"$regex": domain_pattern, "$options": "i"}},
            {"technologies": {"$regex": domain_pattern, "$options": "i"}},
            {"skills": {"$regex": domain_pattern, "$options": "i"}},
            {"specialty_tags": {"$regex": domain_pattern, "$options": "i"}},
            {"specialisation_tags": {"$regex": domain_pattern, "$options": "i"}},
            {"summary": {"$regex": domain_pattern, "$options": "i"}},
            {"combined_text": {"$regex": domain_pattern, "$options": "i"}},
            {"resume": {"$regex": domain_pattern, "$options": "i"}},
        ]})
    if industry:
        clauses.append({"industry_focus": industry})
    if experience == "0-3":
        clauses.append({"experience_years": {"$gte": 0, "$lt": 3}})
    elif experience == "3-7":
        clauses.append({"experience_years": {"$gte": 3, "$lt": 7}})
    elif experience == "7+":
        clauses.append({"experience_years": {"$gte": 7}})
    if search:
        pattern = _re.escape(search.strip())
        clauses.append({"$or": [
            {"name": {"$regex": pattern, "$options": "i"}},
            {"technologies": {"$regex": pattern, "$options": "i"}},
            {"skills": {"$regex": pattern, "$options": "i"}},
            {"specialty_tags": {"$regex": pattern, "$options": "i"}},
            {"specialisation_tags": {"$regex": pattern, "$options": "i"}},
            {"primary_category": {"$regex": pattern, "$options": "i"}},
            {"secondary_categories": {"$regex": pattern, "$options": "i"}},
            {"technology_category": {"$regex": pattern, "$options": "i"}},
            {"domain": {"$regex": pattern, "$options": "i"}},
            {"industry_focus": {"$regex": pattern, "$options": "i"}},
            {"language_of_delivery": {"$regex": pattern, "$options": "i"}},
            {"location": {"$regex": pattern, "$options": "i"}},
            {"email": {"$regex": pattern, "$options": "i"}},
            {"teams_email": {"$regex": pattern, "$options": "i"}},
            {"microsoft_teams_email": {"$regex": pattern, "$options": "i"}},
            {"teams_upn": {"$regex": pattern, "$options": "i"}},
            {"summary": {"$regex": pattern, "$options": "i"}},
            {"resume": {"$regex": pattern, "$options": "i"}},
            {"combined_text": {"$regex": pattern, "$options": "i"}},
            {"role_designation": {"$regex": pattern, "$options": "i"}},
            {"certifications": {"$regex": pattern, "$options": "i"}},
            {"past_clients": {"$regex": pattern, "$options": "i"}},
        ]})

    query = {"$and": clauses} if len(clauses) > 1 else (clauses[0] if clauses else {})
    total = await db["trainers"].count_documents(query)
    skip = (page - 1) * limit
    trainers = await db["trainers"].find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    for trainer in trainers:
        trainer["verification_summary"] = get_contact_verification_summary(trainer)
    return {
        "trainers": trainers,
        "total": total,
        "page": page,
        "pages": -(-total // limit),
        "categories": await get_all_categories(db),
        "domains": await _software_domains(db),
        "industries": await _distinct_non_empty(db, "industry_focus"),
    }


@router.get("/trainers/categories")
async def trainer_categories():
    db = get_db()
    return {"categories": await get_all_categories(db)}


@router.get("/trainers/domains")
async def trainer_domains():
    db = get_db()
    return {"domains": await _software_domains(db)}


@router.get("/trainers/industries")
async def trainer_industries():
    db = get_db()
    return {"industries": await _distinct_non_empty(db, "industry_focus")}


@router.post("/trainers/categorise-all")
async def categorise_all_trainers(background_tasks: BackgroundTasks):
    db = get_db()
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
    total_pending = await db["trainers"].count_documents(pending_query)
    job_id = f"CAT-{uuid.uuid4().hex[:8].upper()}"
    CATEGORISATION_JOBS[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "total_pending": total_pending,
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "created_at": utc_now(),
    }
    background_tasks.add_task(_run_categorisation_job, job_id)
    return {
        "message": "Categorisation job started",
        "job_id": job_id,
        "total_pending": total_pending,
    }


@router.get("/trainers/categorise-jobs/{job_id}")
async def get_categorisation_job(job_id: str):
    job = CATEGORISATION_JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Categorisation job not found")
    return job


@router.post("/trainers/{trainer_id}/categorise")
async def categorise_single_trainer(trainer_id: str):
    db = get_db()
    result = await _categorise_trainer_by_id(db, trainer_id)
    return {
        "trainer_id": trainer_id,
        **result,
    }


def _wanted_resume_email_body(trainer_name: str, domain: str) -> str:
    domain_label = domain or "the relevant"
    return (
        f"Dear {trainer_name or 'Trainer'},\n\n"
        f"We are currently looking for trainer profiles for {domain_label} training requirements.\n\n"
        "Kindly share your latest resume / trainer profile along with your updated experience, key skills, "
        "training expertise, availability, and commercial expectations.\n\n"
        "This will help us consider your profile for suitable upcoming opportunities.\n\n"
        "Regards,\n"
        "TrainerSync Team"
    )


def _single_trainer_mail_context(trainer: dict, payload: dict) -> dict:
    domain = str(
        payload.get("domain")
        or payload.get("technology")
        or trainer.get("primary_category")
        or trainer.get("technology_category")
        or trainer.get("domain")
        or trainer.get("technologies")
        or "Training"
    ).strip()
    return {
        "domain": domain,
        "duration": str(payload.get("duration") or payload.get("duration_days") or "").strip(),
        "mode": str(payload.get("mode") or "Online").strip(),
        "participants": str(payload.get("participants") or payload.get("participant_count") or "").strip(),
        "trainer_budget": str(
            payload.get("trainer_visible_budget_per_session")
            or payload.get("trainer_requested_budget_per_session")
            or payload.get("trainer_budget")
            or ""
        ).strip(),
        "client_name": str(payload.get("client_name") or payload.get("client_company") or "").strip(),
        "client_email": str(payload.get("client_email") or "").strip(),
        "requirement_id": str(payload.get("requirement_id") or "").strip(),
    }


def _single_trainer_greeting(trainer_name: str) -> str:
    return f"Dear {trainer_name or 'Trainer'},"


def _has_proper_interview_slots(text: str = "") -> bool:
    clean = _strip_quoted_reply_text(text or "").lower()
    if not clean:
        return False
    date_hits = 0
    for pattern in [
        r"\b\d{1,2}\s*[/-]\s*\d{1,2}(?:\s*[/-]\s*\d{2,4})?\b",
        r"\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b",
        r"\b(?:mon|tue|wed|thu|fri|sat|sun)(?:day)?\b",
    ]:
        date_hits += len(_re.findall(pattern, clean, flags=_re.IGNORECASE))
    time_hits = 0
    for pattern in [
        r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",
        r"\b\d{1,2}(?::\d{2})?\s*[-–]\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",
    ]:
        time_hits += len(_re.findall(pattern, clean, flags=_re.IGNORECASE))
    slot_hints = len(_re.findall(r"\b(?:slot|option|available|availability)\b", clean, flags=_re.IGNORECASE))
    has_one_exact_slot = date_hits >= 1 and time_hits >= 1
    has_three_slot_options = (date_hits >= 3 and time_hits >= 3) or (date_hits >= 3 and time_hits >= 2 and slot_hints >= 1)
    return has_one_exact_slot or has_three_slot_options


def _single_trainer_pipeline_template(trainer_name: str, payload: dict, context: dict) -> dict:
    mail_type = str(payload.get("mail_type") or payload.get("template") or "mail1").strip()
    allowed = {
        "mail1",
        "mail2",
        "mail2_followup",
        "mail3",
        "mail4",
        "mail5_ok",
        "mail5_no",
        "mail6_toc",
        "mail7_confirm",
        "mail3_slot_followup",
    }
    if mail_type not in allowed:
        mail_type = "mail1"

    domain = context.get("domain") or "Training"
    greeting = _single_trainer_greeting(trainer_name)
    duration = context.get("duration") or "[Hours/Days]"
    mode = context.get("mode") or "[Online/Offline]"
    participants = context.get("participants") or "[Number]"
    slots = str(payload.get("slots") or payload.get("trainer_dates") or "").strip()
    interview_link = str(payload.get("interview_link") or "").strip()
    platform = str(payload.get("platform") or "Google Meet / Zoom").strip()
    date_time = str(payload.get("date_time") or payload.get("interview_date") or "").strip()
    training_date = str(payload.get("training_date") or "").strip()
    venue = str(payload.get("venue") or mode or "").strip()
    contact_name = str(payload.get("contact_name") or "Clahan Technologies Team").strip()
    contact_phone = str(payload.get("contact_phone") or "").strip()
    contact_email = str(payload.get("contact_email") or getattr(get_settings(), "from_email", "") or "").strip()
    trainer_budget = str(context.get("trainer_budget") or "").strip()
    known_detail_lines = [f"* Domain/Technology: {domain}"]
    if duration and duration != "[Hours/Days]":
        known_detail_lines.append(f"* Duration: {duration}")
    if mode and mode != "[Online/Offline]":
        known_detail_lines.append(f"* Mode: {mode}")
    if participants and participants != "[Number]":
        known_detail_lines.append(f"* Participants: {participants}")
    training_dates = str(payload.get("training_dates") or payload.get("timeline_start") or "").strip()
    if training_dates:
        known_detail_lines.append(f"* Training dates: {training_dates}")
    else:
        known_detail_lines.append("* Training dates: To be shared once finalized by the client")
    if trainer_budget:
        known_detail_lines.append(f"* Commercial budget: INR {trainer_budget} per session")
    requested_detail_lines = [
        "* Total years of experience",
        "* Number of trainings conducted previously",
        "* Relevant certifications",
        "* Preferred training mode (Online / Offline)",
        "* Availability for Full-Day or Half-Day sessions",
        "" if trainer_budget else "* Expected commercial charges per day/session",
        "* Current location",
        "* Availability for the mentioned dates",
    ]
    requested_detail_text = "\n".join(line for line in requested_detail_lines if line)

    if mail_type == "mail2":
        return {
            "mail_type": mail_type,
            "subject": f"Training Requirement - {domain} | Additional Details Required",
            "body": (
                f"{greeting}\n\n"
                "Thank you for your response.\n\n"
                "Please find the current requirement details below:\n\n"
                f"{chr(10).join(known_detail_lines)}\n\n"
                "To proceed further, kindly share the below details:\n\n"
                f"{requested_detail_text}\n\n"
                "Best Regards,\nRecruitment Team\nClahan Technologies"
            ),
        }

    if mail_type == "mail2_followup":
        return {
            "mail_type": mail_type,
            "subject": f"Re: Training Requirement - {domain} | Details Required",
            "body": (
                f"{greeting}\n\n"
                "Thank you for confirming your interest.\n\n"
                "To proceed further, kindly share the above requested details:\n\n"
                "* Total years of experience\n"
                "* Number of trainings conducted previously\n"
                "* Relevant certifications\n"
                "* Preferred training mode (Online / Offline)\n"
                "* Availability for Full-Day or Half-Day sessions\n"
                "* Expected commercial charges per day/session\n"
                "* Current location\n"
                "* Availability for the mentioned dates\n\n"
                "Once we receive these details, we can move ahead with the next step.\n\n"
                "Regards,\nTrainerSync Team"
            ),
        }

    if mail_type == "mail3":
        slot_lines = slots or "* [Slot 1]\n* [Slot 2]\n* [Slot 3]"
        return {
            "mail_type": mail_type,
            "subject": f"Interview Slot Booking - {domain}",
            "body": (
                f"{greeting}\n\n"
                "Thank you for sharing your details.\n\n"
                "We would like to book an interview slot with you. Based on your availability, "
                "please confirm one of the following slots:\n\n"
                f"{slot_lines}\n\n"
                "Kindly confirm your preferred slot at the earliest.\n\n"
                "Regards,\nTrainerSync Team"
            ),
        }

    if mail_type == "mail4":
        return {
            "mail_type": mail_type,
            "subject": f"Interview Schedule Confirmation - {domain}",
            "body": (
                f"{greeting}\n\n"
                "Your interview has been scheduled. Please find the details below:\n\n"
                f"Date & Time: {date_time or '[Date & Time]'}\n"
                f"Platform: {platform or '[Platform]'}\n"
                f"Meeting Link: {interview_link or '[Meeting Link]'}\n\n"
                "Please join on time. Let us know if you need any assistance.\n\n"
                "Regards,\nTrainerSync Team"
            ),
        }

    if mail_type == "mail3_slot_followup":
        return {
            "mail_type": mail_type,
            "subject": "Interview Slot Details Required",
            "body": (
                f"Hi {trainer_name or 'Trainer'},\n\n"
                "Thank you for sharing the slot. Could you please provide the exact interview date and time, including whether it is AM or PM?\n\n"
                "Also, please share 3 available slots with the corresponding dates so that we can schedule the interview accordingly.\n\n"
                "Thanks."
            ),
        }

    if mail_type == "mail5_ok":
        return {
            "mail_type": mail_type,
            "subject": f"Congratulations! You have been Selected - {domain}",
            "body": (
                f"{greeting}\n\n"
                f"Congratulations! We are pleased to inform you that you have been selected for the {domain} training requirement.\n\n"
                "To proceed further, kindly share the following:\n\n"
                "* Table of Contents (ToC) / Course Agenda for the training\n"
                "* Any prerequisite materials or tools required\n\n"
                "We look forward to working with you!\n\n"
                "Regards,\nTrainerSync Team"
            ),
        }

    if mail_type == "mail5_no":
        return {
            "mail_type": mail_type,
            "subject": f"Update on Training Requirement - {domain}",
            "body": (
                f"{greeting}\n\n"
                f"Thank you for your time and interest in the {domain} training requirement.\n\n"
                "After careful consideration, we regret to inform you that we have decided to proceed with another trainer at this time.\n\n"
                "We will keep your profile on record and reach out for future opportunities.\n\n"
                "Thank you once again for your cooperation.\n\n"
                "Regards,\nTrainerSync Team"
            ),
        }

    if mail_type == "mail6_toc":
        return {
            "mail_type": mail_type,
            "subject": f"Action Required: ToC / Course Agenda - {domain}",
            "body": (
                f"{greeting}\n\n"
                f"Congratulations again on being selected for the {domain} training!\n\n"
                "To initiate the onboarding process, kindly share the following at the earliest:\n\n"
                "* Detailed Table of Contents (ToC) / Course Agenda\n"
                "* Day-wise session breakdown\n"
                "* Tools, software, or prerequisites required by participants\n"
                "* Estimated preparation time needed\n\n"
                "Please revert at the earliest so we can coordinate with the client on schedule.\n\n"
                "Regards,\nTrainerSync Team"
            ),
        }

    if mail_type == "mail7_confirm":
        return {
            "mail_type": mail_type,
            "subject": f"Training Schedule Confirmed - {domain}",
            "body": (
                f"{greeting}\n\n"
                f"We are pleased to confirm your engagement for the {domain} training. Please find the final details below:\n\n"
                f"Training Date: {training_date or '[Training Date]'}\n"
                f"Venue / Platform: {venue or '[Venue / Platform]'}\n\n"
                "Action Items Before Training:\n"
                "* Ensure all materials and slides are ready\n"
                "* Share soft copies of training content with us 2 days prior\n"
                "* Confirm your availability 24 hours before the training\n\n"
                "For any questions or additional information, please contact:\n\n"
                f"Contact Name: {contact_name or '[Contact Name]'}\n"
                f"Phone: {contact_phone or '[Phone Number]'}\n"
                f"Email: {contact_email or '[Email]'}\n\n"
                "We look forward to a successful training session!\n\n"
                "Regards,\nTrainerSync Team"
            ),
        }

    return {
        "mail_type": "mail1",
        "subject": f"Training Requirement - {domain}",
        "body": compose_shortlist_first_email(
            trainer_name,
            domain,
            context.get("duration") or "",
            context.get("mode") or "",
            context.get("participants") or "",
        ),
    }


@router.post("/trainers/{trainer_id}/request-resume")
async def request_trainer_resume(trainer_id: str, payload: dict, request: Request):
    db = get_db()
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0})
    if not trainer:
        raise HTTPException(404, "Trainer not found")

    trainer_name = str(payload.get("trainer_name") or trainer.get("name") or "Trainer").strip()
    to_email = str(payload.get("to_email") or trainer.get("email") or trainer.get("trainer_email") or "").strip()
    if not to_email:
        raise HTTPException(400, "Trainer email is required to request a resume")

    domain = str(
        payload.get("domain")
        or payload.get("technology")
        or trainer.get("primary_category")
        or trainer.get("technology_category")
        or trainer.get("domain")
        or trainer.get("technologies")
        or "Training"
    ).strip()
    subject = str(payload.get("subject") or f"Updated Trainer Profile / Resume Request - {domain}").strip()
    body = str(payload.get("body") or _wanted_resume_email_body(trainer_name, domain)).strip()

    email_id = f"EMAIL-{uuid.uuid4().hex[:8].upper()}"
    tracking_url = build_tracking_url(request, email_id)
    smtp_config = await get_admin_email_config(db)
    success, error = await send_email_async(to_email, subject, body, smtp_config, tracking_url)

    sent_at = utc_now()
    await db["email_logs"].insert_one({
        "email_id": email_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "requirement_id": payload.get("requirement_id") or "",
        "to_email": to_email,
        "subject": subject,
        "body": body,
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "sent_at": sent_at if success else None,
        "reply_received": False,
        "opened": False,
        "open_count": 0,
        "tracking_url": tracking_url,
        "retry_count": 0,
        "mail_type": "wanted_resume",
        "created_at": sent_at,
    })
    await db["conversations"].insert_one({
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "to_email": to_email,
        "requirement_id": payload.get("requirement_id") or "",
        "subject": subject,
        "body": body,
        "mail_type": "wanted_resume",
        "direction": "sent",
        "status": "sent" if success else "failed",
        "error": error if not success else "",
        "sent_at": sent_at,
        "email_id": email_id,
    })

    if not success:
        raise HTTPException(500, error or "Resume request email failed")

    await db["trainers"].update_one(
        {"trainer_id": trainer_id},
        {"$set": {
            "status": "contacted",
            "resume_requested_at": sent_at,
            "resume_requested_domain": domain,
            "updated_at": sent_at,
        }},
    )
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or trainer
    return {
        "success": True,
        "message": "Resume request mail sent",
        "email_id": email_id,
        "trainer": trainer,
    }


# ─── Create Requirement & Run Pipeline ───────────────────────────────────────

@router.post("/trainers/{trainer_id}/send-automation-mail")
async def send_single_trainer_automation_mail(trainer_id: str, payload: dict, request: Request):
    db = get_db()
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0})
    if not trainer:
        raise HTTPException(404, "Trainer not found")

    trainer_name = str(payload.get("trainer_name") or trainer.get("name") or "Trainer").strip()
    to_email = str(payload.get("to_email") or trainer.get("email") or trainer.get("trainer_email") or "").strip()
    if not to_email:
        raise HTTPException(400, "Trainer email is required to send automation mail")

    context = _single_trainer_mail_context(trainer, payload)
    template = _single_trainer_pipeline_template(trainer_name, payload, context)
    mail_type = template["mail_type"]
    subject = str(payload.get("subject") or template["subject"]).strip()
    body = str(payload.get("body") or template["body"]).strip()
    custom_note = str(payload.get("message") or payload.get("custom_message") or "").strip()
    if custom_note:
        body = f"{custom_note}\n\n---\n{body}"

    email_id = f"EMAIL-{uuid.uuid4().hex[:8].upper()}"
    tracking_url = build_tracking_url(request, email_id)
    smtp_config = await get_admin_email_config(db)
    trainer_phone = await _trainer_phone(db, trainer_id, trainer.get("phone") or "")
    trainer_for_teams = await _trainer_for_direct_teams(
        db,
        trainer_id,
        {
            "trainer_id": trainer_id,
            "name": trainer_name,
            "email": to_email,
            "phone": trainer_phone,
        },
    )

    email_result, whatsapp_result, teams_direct_result = await asyncio.gather(
        send_email_async(to_email, subject, body, smtp_config, tracking_url),
        send_shortlist_whatsapp(
            db,
            trainer_phone=trainer_phone,
            trainer_name=trainer_name,
            subject=subject,
            body=body,
            mail_type=mail_type,
            requirement_id=context["requirement_id"],
            email_id=email_id,
            request_base_url=_request_base_url(request),
        ),
        send_trainer_teams_direct_message(
            db,
            trainer=trainer_for_teams,
            subject=subject,
            body=body,
            requirement_id=context["requirement_id"],
            mail_type=mail_type,
            email_id=email_id,
        ),
    )
    success, error = email_result
    sent_at = utc_now()
    email_stage = {
        "mail1": 1,
        "mail2": 2,
        "mail2_followup": 2,
        "mail3": 3,
        "mail3_slot_followup": 3,
        "mail4": 4,
        "mail5_ok": 5,
        "mail5_no": 5,
        "mail6_toc": 6,
        "mail7_confirm": 7,
    }.get(mail_type, 1)

    await db["email_logs"].insert_one({
        "email_id": email_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "requirement_id": context["requirement_id"],
        "to_email": to_email,
        "subject": subject,
        "body": body,
        "status": "sent" if success else "failed",
        "email_stage": email_stage,
        "error_message": error if not success else "",
        "sent_at": sent_at if success else None,
        "reply_received": False,
        "opened": False,
        "open_count": 0,
        "tracking_url": tracking_url,
        "retry_count": 0,
        "mail_type": mail_type,
        "source": "single_resume_automation",
        "technology": context["domain"],
        "client_name": context["client_name"],
        "client_email": context["client_email"],
        "trainer_phone": trainer_phone,
        "whatsapp_summary": whatsapp_result,
        "teams_direct_summary": teams_direct_result,
        "created_at": sent_at,
    })
    await db["conversations"].insert_one({
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "to_email": to_email,
        "requirement_id": context["requirement_id"],
        "subject": subject,
        "body": body,
        "mail_type": mail_type,
        "direction": "sent",
        "status": "sent" if success else "failed",
        "error": error if not success else "",
        "sent_at": sent_at,
        "email_id": email_id,
        "source": "single_resume_automation",
        "client_name": context["client_name"],
        "client_email": context["client_email"],
    })

    teams_result = {"status": "not_sent", "error": "email_failed"}
    if success:
        status_by_type = {
            "mail1": "contacted",
            "mail2": "pending_review",
            "mail2_followup": "pending_review",
            "mail3": "pending_review",
            "mail3_slot_followup": "pending_review",
            "mail4": "interview_scheduled",
            "mail5_ok": "selected",
            "mail5_no": "rejected",
            "mail6_toc": "toc_requested",
            "mail7_confirm": "training_confirmed",
        }
        await db["trainers"].update_one(
            {"trainer_id": trainer_id},
            {"$set": {
                "status": status_by_type.get(mail_type, "contacted"),
                "last_automation_mail_at": sent_at,
                "last_automation_mail_domain": context["domain"],
                "last_automation_mail_type": mail_type,
                "last_automation_client_name": context["client_name"],
                "last_automation_client_email": context["client_email"],
                "updated_at": sent_at,
            }},
        )
        teams_stage_by_type = {
            "mail1": "trainer_contacted",
            "mail4": "interview_scheduled",
            "mail5_ok": "trainer_selected",
        }
        teams_stage = teams_stage_by_type.get(mail_type, "pipeline_message_sent")
        teams_result = await send_teams_stage_notification(
            db,
            stage=teams_stage,
            trainer_name=trainer_name,
            requirement={
                "requirement_id": context["requirement_id"],
                "technology_needed": context["domain"],
                "mode": context["mode"],
                "duration": context["duration"],
                "participant_count": context["participants"],
                "client_name": context["client_name"],
                "client_email": context["client_email"],
            },
            request_base_url=_request_base_url(request),
            context={
                "source": "single_resume_automation",
                "email_id": email_id,
                "mail_type": mail_type,
                "trainer_id": trainer_id,
                "recipient_type": "trainer",
                "to_email": to_email,
                "client_name": context["client_name"],
                "client_email": context["client_email"],
                "to_phone": trainer_phone,
                "subject": subject,
                "body": body,
                "email_status": "sent",
                "whatsapp_status": whatsapp_result.get("status", ""),
                "teams_direct_status": teams_direct_result.get("status", ""),
            },
        )
        await db["email_logs"].update_one(
            {"email_id": email_id},
            {"$set": {"teams_summary": teams_result}},
        )

    updated_trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or trainer
    if not success:
        raise HTTPException(500, error or "Automation mail failed")
    return {
        "success": True,
        "message": "Automation mail sent",
        "email_id": email_id,
        "trainer": updated_trainer,
        "whatsapp": whatsapp_result,
        "teams_direct": teams_direct_result,
        "teams": teams_result,
    }


@router.get("/trainers/{trainer_id}/automation-status")
async def get_single_trainer_automation_status(trainer_id: str):
    db = get_db()
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0})
    if not trainer:
        raise HTTPException(404, "Trainer not found")

    logs = await db["email_logs"].find(
        {"trainer_id": trainer_id, "source": "single_resume_automation"},
        {"_id": 0},
    ).sort("created_at", -1).limit(20).to_list(20)
    latest = logs[0] if logs else {}
    return {
        "trainer_id": trainer_id,
        "trainer": trainer,
        "logs": logs,
        "latest_mail_type": latest.get("mail_type", ""),
        "latest_status": latest.get("status", ""),
        "latest_reply_received": bool(latest.get("reply_received")),
    }


@router.post("/trainers/{trainer_id}/automation-pipeline/tick")
async def tick_single_trainer_automation_pipeline(trainer_id: str, payload: dict, request: Request):
    db = get_db()
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0})
    if not trainer:
        raise HTTPException(404, "Trainer not found")

    await manual_reply_check(request)
    logs = await db["email_logs"].find(
        {"trainer_id": trainer_id, "source": "single_resume_automation"},
        {"_id": 0},
    ).sort("created_at", -1).limit(30).to_list(30)

    def sent_logs(mail_types: set[str]) -> list[dict]:
        return [
            item for item in logs
            if item.get("status") == "sent" and item.get("mail_type") in mail_types
        ]

    def latest_sent(mail_types: set[str]) -> dict:
        items = sent_logs(mail_types)
        return items[0] if items else {}

    def log_time(item: dict, *fields: str) -> datetime:
        for field in fields:
            value = item.get(field)
            if isinstance(value, datetime):
                return value
            if isinstance(value, str) and value:
                try:
                    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
                except ValueError:
                    continue
        return datetime.min

    next_mail_type = ""
    reason = "waiting"
    if not sent_logs({"mail1"}):
        next_mail_type = "mail1"
        reason = "start_pipeline"
    else:
        mail1 = latest_sent({"mail1"})
        mail2 = latest_sent({"mail2", "mail2_followup"})
        mail3 = latest_sent({"mail3"})
        slot_mail = latest_sent({"mail3", "mail3_slot_followup"})
        if mail1.get("reply_received") and not mail2:
            next_mail_type = "mail2"
            reason = "mail1_replied"
        elif mail2.get("reply_received") and not mail3:
            next_mail_type = "mail3"
            reason = "mail2_replied"
        elif slot_mail.get("reply_received"):
            slot_reply = slot_mail.get("reply_text") or ""
            if _has_proper_interview_slots(slot_reply):
                reason = "mail3_replied_manual_interview_step"
            else:
                reply_time = log_time(slot_mail, "replied_at", "created_at", "sent_at")
                followup_after_reply = any(
                    item.get("status") == "sent"
                    and item.get("mail_type") == "mail3_slot_followup"
                    and log_time(item, "created_at", "sent_at") > reply_time
                    for item in logs
                )
                if followup_after_reply:
                    reason = "waiting_clear_slot_reply"
                else:
                    next_mail_type = "mail3_slot_followup"
                    reason = "mail3_replied_without_proper_slots"
        elif latest_sent({"mail3_slot_followup"}):
            reason = "waiting_clear_slot_reply"
        elif mail2:
            reason = "waiting_mail2_reply"
        else:
            reason = "waiting_mail1_reply"

    if not next_mail_type:
        return {
            "success": True,
            "sent_next": False,
            "reason": reason,
            "trainer": trainer,
            "logs": logs,
        }

    send_payload = {
        **payload,
        "mail_type": next_mail_type,
        "domain": payload.get("domain") or trainer.get("last_automation_mail_domain") or trainer.get("primary_category") or trainer.get("domain") or "Training",
        "client_name": payload.get("client_name") or trainer.get("last_automation_client_name") or "",
        "client_email": payload.get("client_email") or trainer.get("last_automation_client_email") or "",
    }
    result = await send_single_trainer_automation_mail(trainer_id, send_payload, request)
    return {
        **result,
        "sent_next": True,
        "next_mail_type": next_mail_type,
        "reason": reason,
    }


@router.post("/requirements")
async def create_requirement(req: RequirementCreate, request: Request):
    db = get_db()
    req_id = f"REQ-{uuid.uuid4().hex[:8].upper()}"
    req_dict = req.dict()
    req_dict["client_name"] = str(req_dict.get("client_name") or "").strip()
    req_dict["client_company"] = str(req_dict.get("client_company") or "").strip()
    req_dict["client_email"] = str(req_dict.get("client_email") or "").strip()
    req_dict["client_phone"] = str(req_dict.get("client_phone") or "").strip()
    req_dict["client_whatsapp"] = str(req_dict.get("client_whatsapp") or "").strip()
    req_dict["timeline_start"] = str(req_dict.get("timeline_start") or "").strip()
    req_dict["timeline_end"] = str(req_dict.get("timeline_end") or "").strip()
    req_dict["timing"] = str(req_dict.get("timing") or "").strip()
    req_dict["training_dates"] = str(req_dict.get("training_dates") or "").strip()
    if not req_dict["training_dates"] and (req_dict["timeline_start"] or req_dict["timeline_end"]):
        req_dict["training_dates"] = " to ".join(
            part for part in [req_dict["timeline_start"], req_dict["timeline_end"]] if part
        )
    if req_dict.get("duration_days") not in (None, ""):
        try:
            req_dict["duration_days"] = float(req_dict["duration_days"])
        except Exception:
            req_dict["duration_days"] = None
    if req_dict.get("duration_hours") not in (None, ""):
        try:
            req_dict["duration_hours"] = float(req_dict["duration_hours"])
        except Exception:
            req_dict["duration_hours"] = None
    if not req_dict.get("duration_days") and req_dict.get("duration_hours"):
        req_dict["duration_days"] = max(1, round(float(req_dict["duration_hours"]) / 7, 2))
    if req_dict["client_email"]:
        req_dict["client_email_domain"] = sender_domain(req_dict["client_email"])
    req_dict.update({"requirement_id": req_id, "status": "active", "created_at": utc_now()})

    all_trainers = await db["trainers"].find({}, {"_id": 0}).to_list(10000)
    if not all_trainers:
        raise HTTPException(400, "No trainers in database. Upload trainer resumes first.")

    excluded_statuses = ["interested", "confirmed", "declined"]
    filtered_trainers = [t for t in all_trainers
                        if t.get("status") not in excluded_statuses]

    result = await run_pipeline(filtered_trainers, req_dict)
    top_trainers   = result.get("top_trainers", [])
    email_payloads = result.get("email_payloads", [])

    req_dict["total_matched"] = len(result.get("ranked_trainers", []))
    req_dict["top_count"] = len(top_trainers)
    await db["requirements"].insert_one(req_dict)

    await db["shortlists"].insert_one({
        "shortlist_id": f"SL-{uuid.uuid4().hex[:8].upper()}",
        "requirement_id": req_id,
        "technology_needed": req.technology_needed,
        "top_trainers": [{k: v for k, v in t.items() if k != "_id"} for t in top_trainers],
        "total_matched": len(result.get("ranked_trainers", [])),
        "category_filter_applied": result.get("category_filter_applied", False),
        "no_category_match": result.get("no_category_match", False),
        "category_match_count": result.get("category_match_count", 0),
        "created_at": utc_now()
    })
    await send_teams_stage_notification(
        db,
        stage="new_requirement_created",
        trainer_name="Not assigned yet",
        requirement=req_dict,
        request_base_url=_request_base_url(request),
        context={"source": "requirements_api", "top_count": len(top_trainers)},
    )

    for t in top_trainers:
        await db["trainers"].update_one(
            {"trainer_id": t["trainer_id"]},
            {"$set": {"match_score": t["match_score"], "rank": t["rank"],
                      "status": "contacted" if req_dict.get("send_emails") else "pending_review"}}
        )

    send_emails = req_dict.get('send_emails', False)
    smtp_config = await get_admin_email_config(db)
    email_results = []
    if send_emails and email_payloads:
        for payload in email_payloads:
            email_id = f"EMAIL-{uuid.uuid4().hex[:8].upper()}"
            tracking_url = build_tracking_url(request, email_id)
            trainer_phone = await _trainer_phone(db, payload.get("trainer_id", ""))
            trainer_for_teams = await _trainer_for_direct_teams(
                db,
                payload.get("trainer_id", ""),
                {
                    "trainer_id": payload.get("trainer_id", ""),
                    "name": payload.get("trainer_name", ""),
                    "email": payload.get("to", ""),
                    "phone": trainer_phone,
                },
            )
            email_result, whatsapp_result, teams_direct_result = await asyncio.gather(
                send_email_async(
                    payload["to"],
                    payload["subject"],
                    payload["body"],
                    smtp_config,
                    tracking_url,
                ),
                send_shortlist_whatsapp(
                    db,
                    trainer_phone=trainer_phone,
                    trainer_name=payload.get("trainer_name", ""),
                    subject=payload.get("subject", ""),
                    body=payload.get("body", ""),
                    mail_type="mail1",
                    requirement_id=req_id,
                    email_id=email_id,
                    request_base_url=_request_base_url(request),
                ),
                send_trainer_teams_direct_message(
                    db,
                    trainer=trainer_for_teams,
                    subject=payload.get("subject", ""),
                    body=payload.get("body", ""),
                    requirement_id=req_id,
                    mail_type="mail1",
                    email_id=email_id,
                ),
            )
            success, error = email_result
            email_results.append({
                **payload,
                "email_id": email_id,
                "status": "sent" if success else "failed",
                "error_message": error if not success else "",
                "sent_at": utc_now().isoformat() if success else None,
                "tracking_url": tracking_url,
                "whatsapp": whatsapp_result,
                "teams_direct": teams_direct_result,
            })

    for er in email_results:
        await db["email_logs"].insert_one({
            "email_id":      er["email_id"],
            "trainer_id":    er["trainer_id"],
            "trainer_name":  er["trainer_name"],
            "requirement_id": req_id,
            "to_email":      er["to"],
            "subject":       er["subject"],
            "body":          er["body"],
            "status":        er["status"],
            "email_stage":   1,
            "error_message": er.get("error_message", ""),
            "sent_at":       datetime.fromisoformat(er["sent_at"]) if er.get("sent_at") else None,
            "reply_received": False,
            "opened":         False,
            "open_count":     0,
            "tracking_url":   er.get("tracking_url", ""),
            "whatsapp_summary": er.get("whatsapp", {}),
            "teams_direct_summary": er.get("teams_direct", {}),
            "retry_count":   0,
            "created_at":    utc_now()
        })
        if er["status"] == "sent":
            await send_teams_stage_notification(
                db,
                stage="trainer_contacted",
                trainer_name=er["trainer_name"],
                requirement=req_dict,
                request_base_url=_request_base_url(request),
                context={
                    "source": "requirements_api",
                    "email_id": er["email_id"],
                    "trainer_id": er["trainer_id"],
                    "recipient_type": "trainer",
                    "to_email": er.get("to", ""),
                    "to_phone": (er.get("whatsapp") or {}).get("to_number", ""),
                    "subject": er.get("subject", ""),
                    "body": er.get("body", ""),
                    "mail_type": "mail1",
                    "email_status": "sent",
                    "whatsapp_status": (er.get("whatsapp") or {}).get("status", ""),
                    "teams_direct_status": (er.get("teams_direct") or {}).get("status", ""),
                },
            )

    return {
        "requirement_id": req_id,
        "total_trainers_scanned": len(all_trainers),
        "total_available": len(filtered_trainers),
        "total_matched": len(result.get("ranked_trainers", [])),
        "top_trainers": len(top_trainers),
        "emails_sent": sum(1 for e in email_results if e["status"] == "sent"),
        "emails_failed": sum(1 for e in email_results if e["status"] == "failed"),
        "top_trainers_list": top_trainers,
        "category_filter_applied": result.get("category_filter_applied", False),
        "no_category_match": result.get("no_category_match", False),
        "category_match_count": result.get("category_match_count", 0),
    }


# ─── Retry Single Failed Email ────────────────────────────────────────────────

@router.post("/emails/{email_id}/retry")
async def retry_email(email_id: str, request: Request):
    db = get_db()
    log = await db["email_logs"].find_one({"email_id": email_id})
    if not log:
        raise HTTPException(404, "Email log not found")
    if log.get("retry_count", 0) >= 3:
        raise HTTPException(400, "Max retry attempts (3) reached")

    allowed, blocked_response, _ = await _requirement_trainer_send_guard(
        db,
        log.get("requirement_id", ""),
        log.get("trainer_id", ""),
    )
    if not allowed:
        blocked_response["email_id"] = email_id
        blocked_response["mail_type"] = log.get("mail_type", "")
        return blocked_response

    smtp_config = await get_admin_email_config(db)
    trainer_phone = await _trainer_phone(db, log.get("trainer_id", ""), log.get("trainer_phone", ""))
    trainer_for_teams = await _trainer_for_direct_teams(
        db,
        log.get("trainer_id", ""),
        {
            "trainer_id": log.get("trainer_id", ""),
            "name": log.get("trainer_name", ""),
            "email": log.get("to_email", ""),
            "phone": trainer_phone,
        },
    )
    email_result, whatsapp_result, teams_direct_result = await asyncio.gather(
        send_email_async(
            log["to_email"],
            log["subject"],
            log["body"],
            smtp_config,
            build_tracking_url(request, email_id),
        ),
        send_shortlist_whatsapp(
            db,
            trainer_phone=trainer_phone,
            trainer_name=log.get("trainer_name", ""),
            subject=log.get("subject", ""),
            body=log.get("body", ""),
            mail_type=log.get("mail_type", "mail1_reminder"),
            requirement_id=log.get("requirement_id", ""),
            email_id=email_id,
            request_base_url=_request_base_url(request),
        ),
        send_trainer_teams_direct_message(
            db,
            trainer=trainer_for_teams,
            subject=log.get("subject", ""),
            body=log.get("body", ""),
            requirement_id=log.get("requirement_id", ""),
            mail_type=log.get("mail_type", "mail1_reminder"),
            email_id=email_id,
        ),
    )
    success, error = email_result
    teams_result = {"status": "not_sent", "error": "email_failed"}
    if success:
        requirement = await db["requirements"].find_one(
            {"requirement_id": log.get("requirement_id", "")},
            {"_id": 0},
        )
        teams_result = await send_teams_stage_notification(
            db,
            stage="pipeline_message_sent",
            trainer_name=log.get("trainer_name", ""),
            requirement=requirement or {"requirement_id": log.get("requirement_id", "")},
            request_base_url=_request_base_url(request),
            context={
                "source": "email_retry",
                "email_id": email_id,
                "mail_type": log.get("mail_type", "mail1_reminder"),
                "trainer_id": log.get("trainer_id", ""),
                "recipient_type": "trainer",
                "to_email": log.get("to_email", ""),
                "to_phone": trainer_phone,
                "subject": log.get("subject", ""),
                "body": log.get("body", ""),
                "email_status": "sent",
                "whatsapp_status": whatsapp_result.get("status", ""),
                "teams_direct_status": teams_direct_result.get("status", ""),
            },
        )
    await db["email_logs"].update_one(
        {"email_id": email_id},
        {"$set": {
            "status": "sent" if success else "failed",
            "error_message": error if not success else "",
            "sent_at": utc_now() if success else None,
            "whatsapp_summary": whatsapp_result,
            "teams_direct_summary": teams_direct_result,
            "teams_summary": teams_result,
        },
         "$inc": {"retry_count": 1}}
    )
    return {"success": success, "error": error, "email_id": email_id, "whatsapp": whatsapp_result, "teams_direct": teams_direct_result, "teams": teams_result}


# ─── Schedule Interview ───────────────────────────────────────────────────────

@router.post("/emails/{email_id}/schedule-interview")
async def schedule_interview(email_id: str, request: Request, interview_date: str = "", interview_link: str = ""):
    db = get_db()
    log = await db["email_logs"].find_one({"email_id": email_id})
    if not log:
        raise HTTPException(404, "Email log not found")

    req = await db["requirements"].find_one({"requirement_id": log["requirement_id"]})
    allowed, blocked_response, req_for_guard = await _requirement_trainer_send_guard(
        db,
        log.get("requirement_id", ""),
        log.get("trainer_id", ""),
    )
    if not allowed:
        blocked_response["email_id"] = email_id
        blocked_response["mail_type"] = "mail4"
        return blocked_response
    req = req_for_guard or req
    technology = req.get("technology_needed", "Training") if req else "Training"

    body = compose_interview_email(
        trainer_name=log["trainer_name"],
        technology=technology,
        req_id=log["requirement_id"],
        interview_date=interview_date,
        interview_link=interview_link,
    )
    subject = f"Interview Scheduled — {technology} | {log['requirement_id']}"
    smtp_config = await get_admin_email_config(db)
    success, error = await send_email_async(
        log["to_email"],
        subject,
        body,
        smtp_config,
        build_tracking_url(request, email_id),
    )

    reminder_fields = interview_reminder_fields(interview_date)
    await db["email_logs"].update_one(
        {"email_id": email_id},
        {"$set": {
            "interview_scheduled": success,
            "interview_date": interview_date,
            "interview_link": interview_link,
            "platform": "Online",
            "trainer_phone": await _trainer_phone(db, log.get("trainer_id", "")),
            "interview_email_sent_at": utc_now() if success else None,
            "technology": technology,
            **reminder_fields,
            "interview_reminder_status": "not_scheduled",
            "whatsapp_reminder_status": "not_scheduled",
        }}
    )
    trainer_phone = await _trainer_phone(db, log.get("trainer_id", ""))
    trainer_for_teams = await _trainer_for_direct_teams(
        db,
        log.get("trainer_id", ""),
        {
            "trainer_id": log.get("trainer_id", ""),
            "name": log.get("trainer_name", ""),
            "email": log.get("to_email", ""),
            "phone": trainer_phone,
        },
    )
    whatsapp_result, teams_direct_result = await asyncio.gather(
        send_interview_whatsapp(
            db,
            trainer_phone=trainer_phone,
            trainer_name=log.get("trainer_name", ""),
            requirement_id=log.get("requirement_id", ""),
            technology=technology,
            date_time=interview_date,
            platform="Online",
            interview_link=interview_link,
            email_id=email_id,
            request_base_url=_request_base_url(request),
        ),
        send_trainer_teams_direct_message(
            db,
            trainer=trainer_for_teams,
            subject=subject,
            body=body,
            requirement_id=log.get("requirement_id", ""),
            mail_type="mail4",
            email_id=email_id,
        ),
    )
    await db["email_logs"].update_one(
        {"email_id": email_id},
        {"$set": {"whatsapp_summary": whatsapp_result, "teams_direct_summary": teams_direct_result}},
    )
    await db["trainers"].update_one(
        {"trainer_id": log["trainer_id"]},
        {"$set": {"status": "confirmed"}}
    )
    updated_log = {
        **log,
        "interview_scheduled": success,
        "interview_date": interview_date,
        "interview_link": interview_link,
        "platform": "Online",
        "trainer_phone": await _trainer_phone(db, log.get("trainer_id", "")),
        "technology": technology,
        **reminder_fields,
    }
    reminder_schedule = await schedule_interview_reminder(
        db,
        email_log=updated_log,
        request_base_url=_request_base_url(request),
    ) if success else {"scheduled": False, "status": "email_failed", "error": error}
    if success:
        await send_teams_stage_notification(
            db,
            stage="interview_scheduled",
            trainer_name=log.get("trainer_name", ""),
            requirement=req or {"requirement_id": log.get("requirement_id"), "technology_needed": technology},
            request_base_url=_request_base_url(request),
            context={
                "source": "email_schedule_interview",
                "email_id": email_id,
                "mail_type": "mail4",
                "trainer_id": log.get("trainer_id", ""),
                "recipient_type": "trainer",
                "to_email": log.get("to_email", ""),
                "to_phone": trainer_phone,
                "subject": subject,
                "body": body,
                "email_status": "sent",
                "whatsapp_status": whatsapp_result.get("status", ""),
                "teams_direct_status": teams_direct_result.get("status", ""),
                "interview_date": interview_date,
            },
        )
    return {"success": success, "error": error, "whatsapp": whatsapp_result, "teams_direct": teams_direct_result, "reminder_schedule": reminder_schedule}


# ─── Send Interview Link ──────────────────────────────────────────────────────

@router.post("/shortlists/send-interview-link")
async def send_interview_link_auto(payload: dict, request: Request):
    db = get_db()
    trainer_id     = payload.get("trainer_id")
    trainer_name   = payload.get("trainer_name")
    to_email       = payload.get("to_email")
    trainer_phone  = payload.get("trainer_phone") or payload.get("phone") or ""
    requirement_id = payload.get("requirement_id")
    platform       = payload.get("platform", "Zoom")
    date_time      = payload.get("date_time", "")
    interview_link = payload.get("interview_link", "")

    if not to_email:
        raise HTTPException(400, "to_email is required")

    req = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    allowed, blocked_response, req_for_guard = await _requirement_trainer_send_guard(
        db,
        requirement_id,
        trainer_id,
    )
    if not allowed:
        blocked_response["mail_type"] = "mail4"
        return blocked_response
    req = req_for_guard or req
    technology = req.get("technology_needed", "Training") if req else "Training"

    subject = f"Interview Schedule Confirmation – {technology}"
    body = (
        f"Dear {trainer_name},\n\n"
        f"Your interview has been scheduled. Please find the details below:\n\n"
        f"Date & Time : {date_time or '[Date & Time]'}\n"
        f"Platform    : {platform}\n"
        f"Meeting Link: {interview_link or '[Meeting Link]'}\n\n"
        f"Please join on time. Let us know if you need any assistance.\n\n"
        f"Regards,\nTrainerSync Team"
    )

    email_id = f"EMAIL-{uuid.uuid4().hex[:8].upper()}"
    tracking_url = build_tracking_url(request, email_id)
    smtp_config = await get_admin_email_config(db)
    trainer_phone = await _trainer_phone(db, trainer_id, trainer_phone)
    trainer_for_teams = await _trainer_for_direct_teams(
        db,
        trainer_id,
        {"trainer_id": trainer_id, "name": trainer_name, "email": to_email, "phone": trainer_phone},
    )

    email_result, whatsapp_result, teams_direct_result = await asyncio.gather(
        send_email_async(to_email, subject, body, smtp_config, tracking_url),
        send_interview_whatsapp(
            db,
            trainer_phone=trainer_phone,
            trainer_name=trainer_name,
            requirement_id=requirement_id,
            technology=technology,
            date_time=date_time,
            platform=platform,
            interview_link=interview_link,
            email_id=email_id,
            request_base_url=_request_base_url(request),
        ),
        send_trainer_teams_direct_message(
            db,
            trainer=trainer_for_teams,
            subject=subject,
            body=body,
            requirement_id=requirement_id,
            mail_type="mail4",
            email_id=email_id,
        ),
    )
    success, error = email_result

    await db["conversations"].insert_one({
        "trainer_id": trainer_id, "trainer_name": trainer_name,
        "to_email": to_email, "requirement_id": requirement_id,
        "subject": subject, "body": body, "mail_type": "mail4",
        "direction": "sent", "status": "sent" if success else "failed",
        "error": error if not success else "", "sent_at": utc_now(),
        "platform": platform, "interview_link": interview_link, "date_time": date_time,
    })

    email_log_doc = {
        "email_id": email_id, "trainer_id": trainer_id, "trainer_name": trainer_name,
        "requirement_id": requirement_id, "to_email": to_email,
        "subject": subject, "body": body,
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "sent_at": utc_now() if success else None,
        "reply_received": False, "opened": False, "open_count": 0,
        "tracking_url": tracking_url, "retry_count": 0, "mail_type": "mail4",
        "interview_scheduled": success, "interview_date": date_time,
        "interview_link": interview_link, "platform": platform,
        "technology": technology,
        "trainer_phone": trainer_phone,
        "teams_direct_summary": teams_direct_result,
        **interview_reminder_fields(date_time),
        "interview_reminder_status": "not_scheduled",
        "whatsapp_reminder_status": "not_scheduled",
        "created_at": utc_now(),
    }
    await db["email_logs"].insert_one(email_log_doc)

    if success:
        await db["trainers"].update_one(
            {"trainer_id": trainer_id},
            {"$set": {"status": "interview_scheduled"}}
        )
        reminder_schedule = await schedule_interview_reminder(
            db,
            email_log=email_log_doc,
            request_base_url=_request_base_url(request),
        )
        teams_result = await send_teams_stage_notification(
            db,
            stage="interview_scheduled",
            trainer_name=trainer_name,
            requirement=req or {"requirement_id": requirement_id, "technology_needed": technology},
            request_base_url=_request_base_url(request),
            context={
                "source": "shortlist_interview_link",
                "email_id": email_id,
                "mail_type": "mail4",
                "trainer_id": trainer_id,
                "recipient_type": "trainer",
                "to_email": to_email,
                "to_phone": trainer_phone,
                "subject": subject,
                "body": body,
                "email_status": "sent",
                "whatsapp_status": whatsapp_result.get("status", ""),
                "teams_direct_status": teams_direct_result.get("status", ""),
                "interview_date": date_time,
            },
        )
    else:
        reminder_schedule = {"scheduled": False, "status": "email_failed", "error": error}
        teams_result = {"status": "not_sent", "error": "email_failed"}

    return {"success": success, "error": error, "email_id": email_id, "whatsapp": whatsapp_result,
            "teams_direct": teams_direct_result,
            "teams": teams_result,
            "reminder_schedule": reminder_schedule,
            "message": f"Interview link email {'sent' if success else 'failed'} to {trainer_name}"}


# ─── Get Requirements ─────────────────────────────────────────────────────────

# --- Celery Interview Reminder Admin ---------------------------------------

def _public_reminder_doc(doc: dict) -> dict:
    clean = {k: v for k, v in (doc or {}).items() if k != "_id"}
    for key, value in list(clean.items()):
        if isinstance(value, datetime):
            clean[key] = value.isoformat()
    return clean


@router.get("/interview-reminders")
async def list_interview_reminders(
    status: Optional[str] = None,
    requirement_id: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
):
    db = get_db()
    query = {}
    if status:
        query["status"] = status
    if requirement_id:
        query["requirement_id"] = requirement_id
    skip = max(page - 1, 0) * limit
    total = await db["interview_reminders"].count_documents(query)
    docs = await db["interview_reminders"].find(query, {"_id": 0}).sort("reminder_at", -1).skip(skip).limit(limit).to_list(limit)
    return {
        "reminders": [_public_reminder_doc(doc) for doc in docs],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.post("/interview-reminders/{reminder_id}/cancel")
async def cancel_interview_reminder_route(reminder_id: str, payload: dict = {}):
    db = get_db()
    result = await cancel_interview_reminder(
        db,
        reminder_id=reminder_id,
        reason=payload.get("reason") or "cancelled_by_user",
    )
    if not result.get("cancelled"):
        raise HTTPException(404, "Pending reminder not found")
    return result


@router.post("/admin/teams/test")
async def test_teams_settings(request: Request):
    db = get_db()
    result = await send_teams_stage_notification(
        db,
        stage="new_requirement_created",
        trainer_name="Test Trainer",
        requirement_id="REQ-TEAMS-TEST",
        technology="TrainerSync Teams Test",
        request_base_url=_request_base_url(request),
        context={"source": "admin_test"},
    )
    if not result.get("success"):
        raise HTTPException(400, result)
    return result


@router.post("/interview-reminders/{reminder_id}/reschedule")
async def reschedule_interview_reminder_route(reminder_id: str, payload: dict, request: Request):
    date_time = payload.get("date_time") or payload.get("interview_date")
    if not date_time:
        raise HTTPException(400, "date_time is required")

    db = get_db()
    reminder = await db["interview_reminders"].find_one({"reminder_id": reminder_id}, {"_id": 0})
    if not reminder:
        raise HTTPException(404, "Reminder not found")

    await cancel_interview_reminder(db, reminder_id=reminder_id, reason="rescheduled")

    email_log = await db["email_logs"].find_one({"email_id": reminder.get("email_id")}, {"_id": 0}) or {}
    platform = payload.get("platform") or reminder.get("platform") or email_log.get("platform") or "Online"
    interview_link = payload.get("interview_link") or reminder.get("interview_link") or email_log.get("interview_link") or ""
    reminder_fields = interview_reminder_fields(date_time)
    update_fields = {
        "interview_date": date_time,
        "interview_link": interview_link,
        "platform": platform,
        "technology": reminder.get("technology") or email_log.get("technology", ""),
        **reminder_fields,
        "interview_reminder_status": "not_scheduled",
        "whatsapp_reminder_status": "not_scheduled",
    }
    if email_log.get("email_id"):
        await db["email_logs"].update_one({"email_id": email_log["email_id"]}, {"$set": update_fields})
    email_log = {
        **email_log,
        "email_id": email_log.get("email_id") or reminder.get("email_id"),
        "trainer_id": reminder.get("trainer_id"),
        "trainer_name": reminder.get("trainer_name"),
        "to_email": reminder.get("trainer_email"),
        "trainer_phone": reminder.get("trainer_phone", ""),
        "requirement_id": reminder.get("requirement_id"),
        **update_fields,
    }
    schedule = await schedule_interview_reminder(
        db,
        email_log=email_log,
        request_base_url=_request_base_url(request),
        replace_existing=True,
    )
    return {"rescheduled": schedule.get("scheduled", False), "reminder_schedule": schedule}


@router.get("/requirements")
async def get_requirements():
    db = get_db()
    reqs = await db["requirements"].find({}, {"_id": 0}).sort("created_at", -1).to_list(100)
    return {"requirements": reqs}


# ─── Send Shortlist Mail ──────────────────────────────────────────────────────

@router.patch("/requirements/{requirement_id}")
async def update_requirement(requirement_id: str, payload: dict, request: Request):
    db = get_db()
    existing = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Requirement not found")

    allowed = {"client_name", "client_company", "client_email", "client_phone", "client_whatsapp"}
    update_fields = {}
    for key in allowed:
        if key in payload:
            update_fields[key] = str(payload.get(key) or "").strip()
    if "client_email" in update_fields:
        update_fields["client_email_domain"] = sender_domain(update_fields["client_email"])

    if update_fields:
        update_fields["updated_at"] = utc_now()
        await db["requirements"].update_one(
            {"requirement_id": requirement_id},
            {"$set": update_fields},
        )

    updated = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    pending = await send_pending_client_slot_replies(
        db,
        limit=50,
        requirement_id=requirement_id,
        tracking_url_builder=lambda email_id: build_tracking_url(request, email_id),
        source="requirement_client_contact_saved",
        request_base_url=_request_base_url(request),
    )
    return {"success": True, "requirement": updated, "client_slot_pending": pending}


@router.post("/shortlists/send-mail")
async def send_shortlist_mail(payload: dict, request: Request):
    db = get_db()
    trainer_id     = str(payload.get("trainer_id") or "").strip()
    trainer_name   = str(payload.get("trainer_name") or "").strip()
    to_email       = str(payload.get("to_email") or "").strip()
    trainer_phone  = str(payload.get("trainer_phone") or payload.get("phone") or "").strip()
    requirement_id = str(payload.get("requirement_id") or "").strip()
    subject        = str(payload.get("subject") or "").strip()
    body           = str(payload.get("body") or "").strip()
    mail_type      = str(payload.get("mail_type") or "first").strip()
    client_email   = str(payload.get("client_email") or "").strip()
    client_name    = str(payload.get("client_name") or "").strip()
    client_company = str(payload.get("client_company") or "").strip()
    client_phone   = str(payload.get("client_phone") or payload.get("client_whatsapp") or "").strip()

    if trainer_id and not to_email:
        trainer_doc = await db["trainers"].find_one(
            {"trainer_id": trainer_id},
            {"_id": 0, "email": 1, "trainer_email": 1, "name": 1, "trainer_name": 1, "phone": 1},
        )
        if trainer_doc:
            to_email = str(trainer_doc.get("email") or trainer_doc.get("trainer_email") or "").strip()
            trainer_name = trainer_name or str(trainer_doc.get("name") or trainer_doc.get("trainer_name") or "").strip()
            trainer_phone = trainer_phone or str(trainer_doc.get("phone") or "").strip()

    if not to_email:
        raise HTTPException(400, "Trainer email is missing. Add a valid email to this trainer before sending mail.")
    if not body:
        raise HTTPException(400, "Email body is missing. Choose a valid mail stage/template before sending.")

    if requirement_id and trainer_id and mail_type in {"mail1", "first"}:
        existing_mail1 = await db["email_logs"].find_one(
            {
                "requirement_id": requirement_id,
                "trainer_id": trainer_id,
                "mail_type": {"$in": ["mail1", "first"]},
                "status": "sent",
            },
            {"_id": 0, "email_id": 1, "sent_at": 1, "trainer_name": 1},
            sort=[("sent_at", -1), ("created_at", -1)],
        )
        if existing_mail1:
            return {
                "success": True,
                "skipped": True,
                "status": "already_sent",
                "message": "Mail 1 already sent to this trainer for this requirement",
                "email_id": existing_mail1.get("email_id"),
                "mail_type": mail_type,
                "trainer_id": trainer_id,
                "trainer_name": existing_mail1.get("trainer_name") or trainer_name,
            }

    requirement_for_guard = {}
    if requirement_id:
        allowed, blocked_response, requirement_for_guard = await _requirement_trainer_send_guard(
            db,
            requirement_id,
            trainer_id,
        )
        if not allowed:
            blocked_response["mail_type"] = mail_type
            return blocked_response

    if mail_type == "mail3" and requirement_id:
        requirement = requirement_for_guard or await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
        saved_client_email = str(requirement.get("client_email") or "").strip()
        if not (client_email or saved_client_email):
            raise HTTPException(
                400,
                "Client email is required before sending Slot Booking Mail. Add the client email to this requirement so trainer slots can be sent automatically.",
            )

        update_fields = {}
        if client_email:
            update_fields["client_email"] = client_email
            update_fields["client_email_domain"] = sender_domain(client_email)
        if client_name:
            update_fields["client_name"] = client_name
        if client_company:
            update_fields["client_company"] = client_company
        if client_phone:
            update_fields["client_phone"] = client_phone
        if update_fields:
            update_fields["updated_at"] = utc_now()
            await db["requirements"].update_one(
                {"requirement_id": requirement_id},
                {"$set": update_fields},
            )

    email_id = f"EMAIL-{uuid.uuid4().hex[:8].upper()}"
    tracking_url = build_tracking_url(request, email_id)
    smtp_config = await get_admin_email_config(db)
    trainer_phone = await _trainer_phone(db, trainer_id, trainer_phone)
    trainer_for_teams = await _trainer_for_direct_teams(
        db,
        trainer_id,
        {"trainer_id": trainer_id, "name": trainer_name, "email": to_email, "phone": trainer_phone},
    )

    email_result, whatsapp_result, teams_direct_result = await asyncio.gather(
        send_email_async(to_email, subject, body, smtp_config, tracking_url),
        send_shortlist_whatsapp(
            db,
            trainer_phone=trainer_phone,
            trainer_name=trainer_name,
            subject=subject,
            body=body,
            mail_type=mail_type,
            requirement_id=requirement_id,
            email_id=email_id,
            request_base_url=_request_base_url(request),
        ),
        send_trainer_teams_direct_message(
            db,
            trainer=trainer_for_teams,
            subject=subject,
            body=body,
            requirement_id=requirement_id,
            mail_type=mail_type,
            email_id=email_id,
        ),
    )
    success, error = email_result

    sent_at = utc_now()
    await db["conversations"].insert_one({
        "trainer_id": trainer_id, "trainer_name": trainer_name,
        "to_email": to_email, "requirement_id": requirement_id,
        "subject": subject, "body": body, "mail_type": mail_type,
        "direction": "sent", "status": "sent" if success else "failed",
        "error": error if not success else "", "sent_at": sent_at,
        "email_id": email_id, "opened": False, "open_count": 0,
    })

    await db["email_logs"].insert_one({
        "email_id": email_id, "trainer_id": trainer_id, "trainer_name": trainer_name,
        "requirement_id": requirement_id, "to_email": to_email,
        "subject": subject, "body": body,
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "sent_at": sent_at if success else None,
        "reply_received": False, "opened": False, "open_count": 0,
        "tracking_url": tracking_url, "retry_count": 0,
        "mail_type": mail_type, "trainer_phone": trainer_phone,
        "whatsapp_summary": whatsapp_result,
        "teams_direct_summary": teams_direct_result,
        "created_at": utc_now(),
    })

    teams_result = {"status": "not_applicable"}
    if success:
        status_by_type = {
            "first": "contacted",
            "mail1": "contacted",
            "mail5_ok": "selected",
            "mail5_no": "rejected",
            "mail6_toc": "toc_requested",
            "mail7_confirm": "training_confirmed",
        }
        new_status = status_by_type.get(mail_type, "pending_review")
        await db["trainers"].update_one({"trainer_id": trainer_id}, {"$set": {"status": new_status}})
        teams_stage_by_type = {
            "first": "trainer_contacted",
            "mail1": "trainer_contacted",
            "mail4": "interview_scheduled",
            "mail5_ok": "trainer_selected",
        }
        teams_stage = teams_stage_by_type.get(mail_type, "pipeline_message_sent")
        if mail_type == "mail5_ok":
            await _mark_requirement_selected_and_stop_others(
                db,
                requirement_id=requirement_id,
                trainer_id=trainer_id,
                trainer_name=trainer_name,
                selected_at=sent_at,
            )
        requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
        teams_result = await send_teams_stage_notification(
            db,
            stage=teams_stage,
            trainer_name=trainer_name,
            requirement=requirement or {"requirement_id": requirement_id},
            request_base_url=_request_base_url(request),
            context={
                "source": "shortlist_send_mail",
                "email_id": email_id,
                "mail_type": mail_type,
                "trainer_id": trainer_id,
                "recipient_type": "trainer",
                "to_email": to_email,
                "to_phone": trainer_phone,
                "subject": subject,
                "body": body,
                "email_status": "sent",
                "whatsapp_status": whatsapp_result.get("status", ""),
                "teams_direct_status": teams_direct_result.get("status", ""),
            },
        )
        await db["email_logs"].update_one(
            {"email_id": email_id},
            {"$set": {"teams_summary": teams_result}},
        )

    return {"success": success, "error": error, "email_id": email_id, "whatsapp": whatsapp_result, "teams_direct": teams_direct_result, "teams": teams_result}


# ─── Get Conversation Thread ──────────────────────────────────────────────────

@router.post("/shortlists/send-client-slots")
async def send_client_slot_options(payload: dict, request: Request):
    db = get_db()
    try:
        return await send_client_slot_options_email(
            db,
            payload,
            tracking_url_builder=lambda email_id: build_tracking_url(request, email_id),
            source=payload.get("source") or "manual",
            request_base_url=_request_base_url(request),
        )
    except ClientSlotError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/emails/{email_id}/send-client-slots")
async def send_email_log_client_slots(email_id: str, payload: dict, request: Request):
    db = get_db()
    try:
        return await send_client_slots_for_email_log(
            db,
            email_id,
            force=bool(payload.get("force", True)),
            overrides=payload,
            tracking_url_builder=lambda new_email_id: build_tracking_url(request, new_email_id),
            source=payload.get("source") or "email_log_button",
            request_base_url=_request_base_url(request),
        )
    except ClientSlotError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/shortlists/thread")
async def get_conversation_thread(trainer_id: str, requirement_id: str):
    db = get_db()

    all_msgs = await db["conversations"].find(
        {"trainer_id": trainer_id, "requirement_id": requirement_id},
        {"_id": 0}
    ).sort("sent_at", 1).to_list(200)

    email_replies = await db["email_logs"].find(
        {"trainer_id": trainer_id, "requirement_id": requirement_id, "reply_received": True},
        {
            "_id": 0, "trainer_id": 1, "trainer_name": 1, "requirement_id": 1,
            "subject": 1, "reply_text": 1, "replied_at": 1, "created_at": 1,
        }
    ).sort("replied_at", 1).to_list(100)

    messages = []
    for m in all_msgs:
        direction = m.get("direction") or "sent"
        messages.append({**m, "direction": direction})

    existing_bodies = {m.get("body", "") for m in messages if m.get("direction") == "received"}
    for r in email_replies:
        reply_body = r.get("reply_text", "")
        if reply_body and reply_body not in existing_bodies:
            messages.append({
                "trainer_id":     r.get("trainer_id"),
                "trainer_name":   r.get("trainer_name"),
                "requirement_id": r.get("requirement_id"),
                "subject":        f"Re: {r.get('subject', '')}",
                "body":           reply_body,
                "direction":      "received",
                "sent_at":        r.get("replied_at") or r.get("created_at"),
                "mail_type":      "reply",
            })

    def sort_key(x):
        val = x.get("sent_at")
        if val is None:
            return datetime.min
        if isinstance(val, str):
            try:
                return datetime.fromisoformat(val.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                return datetime.min
        if hasattr(val, "tzinfo") and val.tzinfo is not None:
            return val.replace(tzinfo=None)
        return val

    messages.sort(key=sort_key)
    return {"messages": messages, "total": len(messages)}


@router.get("/trainers/{trainer_id}/conversation-thread")
async def get_trainer_conversation_thread(trainer_id: str, limit: int = 250):
    db = get_db()
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0})
    if not trainer:
        raise HTTPException(404, "Trainer not found")

    conversations = await db["conversations"].find(
        {"trainer_id": trainer_id},
        {"_id": 0},
    ).sort("sent_at", 1).limit(limit).to_list(limit)

    email_replies = await db["email_logs"].find(
        {"trainer_id": trainer_id, "reply_received": True},
        {
            "_id": 0,
            "email_id": 1,
            "trainer_id": 1,
            "trainer_name": 1,
            "requirement_id": 1,
            "to_email": 1,
            "subject": 1,
            "reply_text": 1,
            "replied_at": 1,
            "created_at": 1,
            "mail_type": 1,
            "source": 1,
            "client_name": 1,
            "client_email": 1,
        },
    ).sort("replied_at", 1).limit(limit).to_list(limit)

    client_slots = await db["client_slot_emails"].find(
        {"trainer_id": trainer_id},
        {"_id": 0},
    ).sort("created_at", 1).limit(limit).to_list(limit)

    client_slot_ids = [doc.get("email_id") for doc in client_slots if doc.get("email_id")]
    confirmations = []
    if client_slot_ids:
        confirmations = await db["client_slot_confirmations"].find(
            {"client_slot_email_id": {"$in": client_slot_ids}},
            {"_id": 0},
        ).sort("updated_at", 1).limit(limit).to_list(limit)

    messages = []
    seen = set()

    def add_message(item: dict):
        body = str(item.get("body") or "")
        key = (
            item.get("direction") or "",
            item.get("mail_type") or "",
            item.get("sent_at") or "",
            item.get("subject") or "",
            body[:500],
        )
        if key in seen:
            return
        seen.add(key)
        messages.append(item)

    for msg in conversations:
        add_message({
            **msg,
            "direction": msg.get("direction") or "sent",
            "channel": "trainer",
        })

    for reply in email_replies:
        body = reply.get("reply_text") or ""
        if not body:
            continue
        add_message({
            "email_id": reply.get("email_id"),
            "trainer_id": reply.get("trainer_id"),
            "trainer_name": reply.get("trainer_name"),
            "requirement_id": reply.get("requirement_id"),
            "to_email": reply.get("to_email"),
            "subject": f"Re: {reply.get('subject', '')}",
            "body": body,
            "direction": "received",
            "sent_at": reply.get("replied_at") or reply.get("created_at"),
            "mail_type": reply.get("mail_type") or "reply",
            "source": reply.get("source") or "email_reply",
            "client_name": reply.get("client_name"),
            "client_email": reply.get("client_email"),
            "channel": "trainer",
        })

    for slot in client_slots:
        add_message({
            "email_id": slot.get("email_id"),
            "trainer_id": trainer_id,
            "trainer_name": slot.get("trainer_name"),
            "requirement_id": slot.get("requirement_id"),
            "to_email": slot.get("to_email"),
            "subject": slot.get("subject") or "Client slot options",
            "body": slot.get("body") or slot.get("slot_text") or "",
            "direction": "client_sent",
            "sent_at": slot.get("sent_at") or slot.get("created_at"),
            "mail_type": "client_slot_options",
            "status": slot.get("status"),
            "client_name": slot.get("client_name"),
            "client_email": slot.get("to_email"),
            "slot_ref": slot.get("slot_ref"),
            "channel": "client",
        })
        if slot.get("last_client_reply_text"):
            add_message({
                "email_id": slot.get("client_reply_message_id") or slot.get("email_id"),
                "trainer_id": trainer_id,
                "trainer_name": slot.get("trainer_name"),
                "requirement_id": slot.get("requirement_id"),
                "to_email": slot.get("to_email"),
                "subject": f"Re: {slot.get('subject', '')}",
                "body": slot.get("last_client_reply_text"),
                "direction": "client_received",
                "sent_at": slot.get("client_confirmed_at") or slot.get("updated_at") or slot.get("created_at"),
                "mail_type": "client_slot_reply",
                "status": slot.get("status"),
                "client_name": slot.get("client_name"),
                "client_email": slot.get("to_email"),
                "slot_ref": slot.get("slot_ref"),
                "channel": "client",
            })

    for confirmation in confirmations:
        trainer_email = confirmation.get("trainer_schedule_email") or {}
        client_email = confirmation.get("client_schedule_email") or {}
        calendar_event = confirmation.get("calendar_event") or {}
        if trainer_email.get("email_id"):
            add_message({
                "email_id": trainer_email.get("email_id"),
                "trainer_id": trainer_id,
                "trainer_name": confirmation.get("trainer_name"),
                "requirement_id": confirmation.get("requirement_id"),
                "to_email": confirmation.get("trainer_email"),
                "subject": "Interview Schedule Confirmation",
                "body": (
                    f"Selected slot: {(confirmation.get('parsed_slot') or {}).get('date_time_text') or ''}\n"
                    f"Meet link: {calendar_event.get('meet_link') or calendar_event.get('html_link') or ''}"
                ).strip(),
                "direction": "sent",
                "sent_at": confirmation.get("scheduled_at") or confirmation.get("updated_at"),
                "mail_type": "mail4",
                "status": "sent" if trainer_email.get("success") else "failed",
                "client_name": confirmation.get("client_name"),
                "client_email": confirmation.get("client_email"),
                "channel": "trainer",
            })
        if client_email.get("email_id"):
            add_message({
                "email_id": client_email.get("email_id"),
                "trainer_id": trainer_id,
                "trainer_name": confirmation.get("trainer_name"),
                "requirement_id": confirmation.get("requirement_id"),
                "to_email": confirmation.get("client_email"),
                "subject": "Client Schedule Confirmation",
                "body": (
                    f"Selected slot: {(confirmation.get('parsed_slot') or {}).get('date_time_text') or ''}\n"
                    f"Meet link: {calendar_event.get('meet_link') or calendar_event.get('html_link') or ''}"
                ).strip(),
                "direction": "client_sent",
                "sent_at": confirmation.get("scheduled_at") or confirmation.get("updated_at"),
                "mail_type": "client_interview_schedule",
                "status": "sent" if client_email.get("success") else "failed",
                "client_name": confirmation.get("client_name"),
                "client_email": confirmation.get("client_email"),
                "channel": "client",
            })

    def sort_key(x):
        val = x.get("sent_at")
        if val is None:
            return datetime.min
        if isinstance(val, str):
            try:
                return datetime.fromisoformat(val.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                return datetime.min
        if hasattr(val, "tzinfo") and val.tzinfo is not None:
            return val.replace(tzinfo=None)
        return val

    messages.sort(key=sort_key)
    return {"trainer": trainer, "messages": messages[-limit:], "total": len(messages)}


@router.get("/shortlists/thread-states")
async def get_shortlist_thread_states(requirement_id: str):
    db = get_db()

    conversation_docs = await db["conversations"].find(
        {"requirement_id": requirement_id},
        {"_id": 0, "trainer_id": 1, "direction": 1, "mail_type": 1, "sent_at": 1, "body": 1},
    ).sort("sent_at", 1).to_list(1000)

    reply_docs = await db["email_logs"].find(
        {"requirement_id": requirement_id, "reply_received": True},
        {
            "_id": 0, "trainer_id": 1, "mail_type": 1,
            "reply_text": 1, "replied_at": 1, "created_at": 1,
        },
    ).sort("replied_at", 1).to_list(500)

    threads = {}
    seen_replies = set()
    for msg in conversation_docs:
        trainer_id = msg.get("trainer_id")
        if not trainer_id:
            continue
        item = {
            "direction": msg.get("direction") or "sent",
            "mail_type": msg.get("mail_type"),
            "sent_at": msg.get("sent_at"),
            "body": msg.get("body", ""),
        }
        threads.setdefault(str(trainer_id), []).append(item)
        if item["direction"] == "received" and item["body"]:
            seen_replies.add((str(trainer_id), item["body"]))

    for reply in reply_docs:
        trainer_id = reply.get("trainer_id")
        body = reply.get("reply_text", "")
        if not trainer_id or not body:
            continue
        key = (str(trainer_id), body)
        if key in seen_replies:
            continue
        threads.setdefault(str(trainer_id), []).append({
            "direction": "received",
            "mail_type": "reply",
            "sent_at": reply.get("replied_at") or reply.get("created_at"),
            "body": body,
        })

    return {"threads": threads}


# ─── Get Shortlists ───────────────────────────────────────────────────────────

async def _build_shortlist_for_existing_requirement(db, requirement: dict) -> dict:
    req_id = requirement.get("requirement_id")
    if not req_id:
        raise HTTPException(400, "Requirement id missing")

    all_trainers = await db["trainers"].find({}, {"_id": 0}).to_list(10000)
    if not all_trainers:
        shortlist_doc = {
            "shortlist_id": f"SL-{uuid.uuid4().hex[:8].upper()}",
            "requirement_id": req_id,
            "technology_needed": requirement.get("technology_needed", ""),
            "top_trainers": [],
            "total_matched": 0,
            "category_filter_applied": False,
            "no_category_match": True,
            "category_match_count": 0,
            "created_at": utc_now(),
            "auto_created": True,
        }
        await db["shortlists"].update_one(
            {"requirement_id": req_id},
            {"$setOnInsert": shortlist_doc},
            upsert=True,
        )
        return await db["shortlists"].find_one({"requirement_id": req_id}, {"_id": 0}) or shortlist_doc

    excluded_statuses = ["interested", "confirmed", "declined"]
    filtered_trainers = [
        trainer for trainer in all_trainers
        if trainer.get("status") not in excluded_statuses
    ]
    result = await run_pipeline(filtered_trainers, requirement)
    top_trainers = [
        {k: v for k, v in trainer.items() if k != "_id"}
        for trainer in result.get("top_trainers", [])
    ]
    total_matched = len(result.get("ranked_trainers", []))
    shortlist_doc = {
        "shortlist_id": f"SL-{uuid.uuid4().hex[:8].upper()}",
        "requirement_id": req_id,
        "technology_needed": requirement.get("technology_needed", ""),
        "top_trainers": top_trainers,
        "total_matched": total_matched,
        "category_filter_applied": result.get("category_filter_applied", False),
        "no_category_match": result.get("no_category_match", False),
        "category_match_count": result.get("category_match_count", 0),
        "created_at": utc_now(),
        "auto_created": True,
    }
    await db["shortlists"].update_one(
        {"requirement_id": req_id},
        {"$setOnInsert": shortlist_doc},
        upsert=True,
    )
    await db["requirements"].update_one(
        {"requirement_id": req_id},
        {"$set": {"total_matched": total_matched, "top_count": len(top_trainers)}},
    )
    for trainer in top_trainers:
        trainer_id = trainer.get("trainer_id")
        if not trainer_id:
            continue
        await db["trainers"].update_one(
            {"trainer_id": trainer_id},
            {"$set": {
                "match_score": trainer.get("match_score"),
                "rank": trainer.get("rank"),
                "status": "pending_review",
            }},
        )
    return await db["shortlists"].find_one({"requirement_id": req_id}, {"_id": 0}) or shortlist_doc


@router.get("/shortlists/{requirement_id}")
async def get_shortlist(requirement_id: str):
    db = get_db()
    s = await db["shortlists"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    if not s:
        requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
        if not requirement:
            raise HTTPException(404, "Requirement not found")
        s = await _build_shortlist_for_existing_requirement(db, requirement)
    return s


# ─── Email Logs ───────────────────────────────────────────────────────────────

@router.get("/emails")
async def get_email_logs(requirement_id: Optional[str] = None, page: int = 1, limit: int = 20):
    db = get_db()
    query = {"requirement_id": requirement_id} if requirement_id else {}
    total = await db["email_logs"].count_documents(query)
    skip = (page - 1) * limit
    logs = await db["email_logs"].find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    return {"emails": logs, "total": total, "page": page}


@router.get("/whatsapp/logs")
async def get_whatsapp_logs(requirement_id: Optional[str] = None, page: int = 1, limit: int = 20):
    db = get_db()
    query = {"context.requirement_id": requirement_id} if requirement_id else {}
    total = await db["whatsapp_logs"].count_documents(query)
    skip = (page - 1) * limit
    logs = await db["whatsapp_logs"].find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    return {"whatsapp_logs": logs, "total": total, "page": page}


# ─── Check Replies ────────────────────────────────────────────────────────────

async def _auto_send_client_slots_from_trainer_reply(db, request: Request, log: dict, reply: dict) -> dict:
    return {"skipped": True, "reason": "Client slot mails are manual only"}
    if (log or {}).get("mail_type") not in {"mail3", "mail3_slot_followup"}:
        return {"skipped": True, "reason": "Not an interview slot booking reply"}
    if not looks_like_trainer_slots(reply.get("body") or ""):
        return {"skipped": True, "reason": "Trainer reply does not contain concrete interview slots"}
    previous_result = (log or {}).get("client_slot_auto_result") or {}
    if previous_result.get("success"):
        return {
            "skipped": True,
            "reason": "Client slot options already sent",
            "already_sent": True,
            "email_id": previous_result.get("email_id"),
        }

    payload = {
        "trainer_id": log.get("trainer_id") or "",
        "trainer_name": log.get("trainer_name") or "the trainer",
        "requirement_id": log.get("requirement_id") or "",
        "slot_text": reply.get("body") or "",
        "force": False,
        "client_email": log.get("client_email") or "",
        "client_name": log.get("client_name") or "",
        "source_email_id": log.get("email_id") or "",
        "source_message_id": reply.get("message_id_header") or "",
    }
    try:
        result = await send_client_slot_options_email(
            db,
            payload,
            tracking_url_builder=lambda email_id: build_tracking_url(request, email_id),
            source="trainer_reply_auto",
            request_base_url=_request_base_url(request),
        )
    except ClientSlotError as exc:
        result = {"success": False, "error": str(exc), "already_sent": False}
    except Exception as exc:
        result = {"success": False, "error": str(exc), "already_sent": False}

    await db["email_logs"].update_one(
        {"email_id": log.get("email_id")},
        {"$set": {
            "client_slot_auto_result": result,
            "client_slot_auto_checked_at": utc_now(),
        }},
    )
    return result


async def _handle_client_slot_confirmation_reply(
    db,
    request: Request,
    *,
    log: dict,
    reply: dict,
    from_email: str,
    replied_at: datetime,
) -> dict:
    if (log or {}).get("mail_type") != "client_slot_options":
        return {"skipped": True, "reason": "Not a client slot options reply"}

    message_id = (
        reply.get("message_id_header")
        or f"imap:{reply.get('msg_id') or log.get('email_id') or uuid.uuid4().hex}"
    )
    slot_doc = await db["client_slot_emails"].find_one({"email_id": log.get("email_id")}, {"_id": 0})
    if not slot_doc:
        return {"success": False, "status": "slot_doc_missing", "error": "Client slot email record not found"}

    from_name, parsed_from_email = _parseaddr(reply.get("from_raw") or reply.get("from_email") or "")
    clean_body = _strip_quoted_reply_text(reply.get("body") or "")
    meta = {
        "email_id": message_id,
        "thread_id": "",
        "received_at": replied_at,
        "from_email": parsed_from_email or from_email,
        "from_name": from_name,
        "subject": reply.get("subject") or f"Re: {log.get('subject', '')}",
        "headers": {},
        "message_id_header": reply.get("message_id_header") or "",
        "raw_body": reply.get("body") or "",
        "clean_body": clean_body,
        "snippet": clean_body[:300],
    }
    result = await _process_client_slot_reply_from_meta(
        db,
        message_id,
        request=request,
        meta_hint=meta,
        slot_doc=slot_doc,
    )
    if result:
        return result
    return {"success": False, "status": "client_slot_not_matched", "error": "Could not match client slot reply"}


async def _process_pending_client_slot_confirmations_from_logs(
    db,
    request: Request,
    *,
    limit: int = 25,
) -> dict:
    logs = await db["email_logs"].find(
        {
            "mail_type": "client_slot_options",
            "status": "sent",
            "reply_received": True,
            "reply_text": {"$nin": [None, ""]},
        },
        {"_id": 0},
    ).sort("replied_at", -1).limit(limit).to_list(limit)

    processed = []
    skipped = 0
    failed = 0
    for log in logs:
        already = await db["client_slot_confirmations"].find_one(
            {"client_slot_email_id": log.get("email_id")},
            {"_id": 0, "status": 1},
        )
        if already and already.get("status") not in {"calendar_failed", "trainer_email_failed", "needs_manual_review"}:
            skipped += 1
            continue
        replied_at = log.get("replied_at") or utc_now()
        if isinstance(replied_at, str):
            try:
                replied_at = datetime.fromisoformat(replied_at.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                replied_at = utc_now()
        reply = {
            "msg_id": log.get("reply_message_id") or log.get("email_id"),
            "message_id_header": log.get("reply_message_id") or "",
            "from_email": log.get("to_email") or "",
            "from_raw": log.get("to_email") or "",
            "subject": f"Re: {log.get('subject', '')}",
            "body": log.get("reply_text") or "",
        }
        result = await _handle_client_slot_confirmation_reply(
            db,
            request,
            log=log,
            reply=reply,
            from_email=log.get("to_email") or "",
            replied_at=replied_at,
        )
        processed.append(result)
        if result and result.get("status") in {"confirmed_scheduled", "already_processed_client_slot_reply"}:
            continue
        if result and result.get("success") is False:
            failed += 1

    return {"checked": len(logs), "processed": processed, "skipped": skipped, "failed": failed}


def _looks_like_extra_training_question(text: str = "") -> bool:
    body = str(text or "").strip().lower()
    if not body:
        return False
    question_terms = [
        "?", "what", "when", "where", "how", "can you", "could you", "please confirm",
        "duration", "timing", "time", "date", "start date", "end date", "schedule",
        "mode", "online", "classroom", "hybrid", "client", "company", "location",
        "rate", "budget", "payment", "invoice", "po", "purchase order",
        "toc", "agenda", "content", "syllabus", "tools", "labs", "interview",
        "meeting", "link", "slot", "availability", "hours", "training",
    ]
    return any(term in body for term in question_terms)


def _looks_like_profile_details_request_stage(log: dict, question: str = "") -> bool:
    mail_type = str((log or {}).get("mail_type") or "").strip().lower()
    text = str(question or "").lower()
    positive_interest = any(
        phrase in text
        for phrase in [
            "yes",
            "interested",
            "available",
            "can deliver",
            "can take",
            "can handle",
            "please share",
            "share the detailed requirement",
            "share detailed requirement",
            "share the toc",
            "share toc",
            "share agenda",
            "other details",
        ]
    )
    asks_requirement_before_profile = any(
        phrase in text
        for phrase in [
            "share the detailed requirement",
            "share detailed requirement",
            "please share the requirement",
            "please share requirement",
            "share the toc",
            "share toc",
            "share agenda",
            "other details",
            "detailed requirement",
            "toc and other details",
        ]
    )
    return mail_type in {"mail1", "mail1_reminder", "trainer_interest_check"} and positive_interest and asks_requirement_before_profile


def _trainer_profile_details_reply(log: dict, reply: dict, requirement: dict | None) -> dict:
    requirement = requirement or {}
    trainer_name = log.get("trainer_name") or "Trainer"
    technology = (
        requirement.get("technology_needed")
        or log.get("technology")
        or log.get("domain")
        or "the training"
    )
    known_detail_lines = [f"* Domain/Technology: {technology}"]

    def add_known(label: str, *values) -> None:
        for value in values:
            text = str(value or "").strip()
            if text:
                known_detail_lines.append(f"* {label}: {text}")
                return

    add_known("Duration", requirement.get("duration_days") and f"{requirement.get('duration_days')} day(s)", requirement.get("duration"), requirement.get("training_duration"))
    add_known("Training dates", requirement.get("training_dates"), " ".join([str(requirement.get("timeline_start") or ""), str(requirement.get("timeline_end") or "")]).strip())
    add_known("Daily timing", requirement.get("daily_timing"), requirement.get("timing"), requirement.get("training_timing"))
    add_known("Mode", requirement.get("mode"), requirement.get("training_mode"))
    add_known("Audience level", requirement.get("audience_level"), requirement.get("level"))

    if len(known_detail_lines) == 1:
        known_detail_lines.append("* Detailed schedule, duration, participant count, and TOC will be shared once finalized by the client")

    return {
        "subject": f"Re: {reply.get('subject') or log.get('subject') or f'Training Requirement - {technology}'}",
        "body": (
            f"Dear {trainer_name},\n\n"
            f"Thank you for confirming your interest in the {technology} training requirement.\n\n"
            "Please find the currently available requirement details below:\n\n"
            f"{chr(10).join(known_detail_lines)}\n\n"
            "To proceed further, kindly share your updated trainer profile/resume along with the below details:\n\n"
            "* Total years of experience\n"
            "* Number of trainings conducted previously\n"
            "* Relevant certifications, if any\n"
            "* Preferred training mode: Online / Offline / Hybrid\n"
            "* Availability for Full-Day or Half-Day sessions\n"
            "* Current location\n"
            "* Commercial expectation per day/session\n\n"
            "Once we receive the above details, we will review your profile and share the next steps accordingly.\n\n"
            "Best Regards,\n"
            "Recruitment Team\n"
            "Clahan Technologies"
        ),
        "ai_used": False,
        "fallback": True,
        "reply_kind": "profile_details_request",
    }


def _looks_like_slot_count_question(question: str = "") -> bool:
    text = _re.sub(r"\s+", " ", str(question or "").lower()).strip()
    if not text or "slot" not in text:
        return False
    question_terms = [
        "how many",
        "no of",
        "number of",
        "count",
        "enough",
        "sufficient",
        "required",
        "needed",
        "need to",
        "should i",
        "should we",
        "do i need",
        "do we need",
        "can i share",
        "can we share",
        "please confirm",
    ]
    action_terms = [
        "book",
        "provide",
        "share",
        "send",
        "give",
    ]
    has_count_context = any(term in text for term in question_terms) or bool(_re.search(r"\b\d+\s+slots?\b", text))
    has_action_context = any(term in text for term in action_terms) or bool(_re.search(r"\b\d+\s+slots?\b", text))
    has_question_context = "?" in text or any(term in text for term in question_terms)
    if not has_question_context:
        return False
    if not has_action_context and not any(term in text for term in ["how many", "number of", "no of", "count", "enough", "sufficient"]):
        return False
    return has_count_context and has_question_context


def _extra_training_reply_fallback(log: dict, reply: dict, requirement: dict | None) -> dict:
    requirement = requirement or {}
    trainer_name = log.get("trainer_name") or "Trainer"
    technology = (
        requirement.get("technology_needed")
        or log.get("technology")
        or log.get("domain")
        or "the training"
    )
    question = _strip_quoted_reply_text(reply.get("body") or "").lower()

    if _looks_like_profile_details_request_stage(log, question):
        return _trainer_profile_details_reply(log, reply, requirement)

    if _looks_like_slot_count_question(question):
        return {
            "subject": f"Re: {reply.get('subject') or log.get('subject') or 'Interview Slot Booking'}",
            "body": (
                f"Dear {trainer_name},\n\n"
                "Thank you for checking.\n\n"
                "Three interview slot options are enough at this stage. You do not need to share five slots unless you would like to provide additional flexibility.\n\n"
                "Kindly share any 3 convenient slots with the full date, month, year, time, AM/PM, and timezone clearly mentioned.\n\n"
                "Example format:\n"
                "Slot 1: [Date Month Year], [Start Time] - [End Time] IST\n"
                "Slot 2: [Date Month Year], [Start Time] - [End Time] IST\n"
                "Slot 3: [Date Month Year], [Start Time] - [End Time] IST\n\n"
                "Once you share the slots in this format, we will coordinate with the client accordingly.\n\n"
                "Best Regards,\n"
                "Recruitment Team\n"
                "Clahan Technologies"
            ),
            "ai_used": False,
            "fallback": True,
            "reply_kind": "slot_count_guidance",
        }

    def asked(*terms: str) -> bool:
        return any(term in question for term in terms)

    def first_value(*values) -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return ""

    def duration_value() -> str:
        if requirement.get("duration_days"):
            return f"{requirement.get('duration_days')} day(s)"
        if requirement.get("duration_hours"):
            return f"{requirement.get('duration_hours')} hour(s)"
        return first_value(requirement.get("duration"), requirement.get("training_duration"))

    def dates_value() -> str:
        return first_value(
            requirement.get("training_dates"),
            " ".join([str(requirement.get("timeline_start") or ""), str(requirement.get("timeline_end") or "")]).strip(),
        )

    def commercial_value() -> str:
        amount = (
            requirement.get("trainer_visible_budget_per_session")
            or requirement.get("trainer_requested_budget_per_session")
            or (log.get("commercials") or {}).get("requested_trainer_commercial")
            or requirement.get("trainer_visible_budget_per_hour")
            or requirement.get("trainer_commercial_per_hour")
        )
        if not amount:
            return ""
        unit = "hour" if requirement.get("trainer_visible_budget_per_hour") or requirement.get("trainer_commercial_per_hour") else "session"
        try:
            amount_text = f"{float(amount):,.0f}"
        except Exception:
            amount_text = str(amount)
        return f"INR {amount_text} per {unit}"

    asked_fields = []
    if asked("duration", "how many days", "how many hours", "hours", "days"):
        asked_fields.append(("Duration", duration_value(), "The duration has not been finalized yet. We will share it once confirmed by the client."))
    if asked("date", "dates", "start date", "end date", "schedule", "when"):
        asked_fields.append(("Training dates", dates_value(), "The client has not confirmed the training dates yet. We will share them once finalized by the client."))
    if asked("timing", "time", "daily timing", "daily timings", "slot"):
        asked_fields.append(("Daily timing", first_value(requirement.get("daily_timing"), requirement.get("timing"), requirement.get("training_timing")), "The daily timing has not been finalized yet. We will share it once confirmed by the client."))
    if asked("mode", "online", "offline", "classroom", "hybrid"):
        asked_fields.append(("Training mode", first_value(requirement.get("mode"), requirement.get("training_mode")), "The training mode has not been finalized yet. We will share it once confirmed by the client."))
    if asked("commercial", "commercials", "rate", "budget", "payment", "charges", "price", "cost"):
        asked_fields.append(("Commercial", commercial_value(), "The commercial is not finalized yet. We will confirm it shortly."))
    if asked("location", "venue", "city", "place"):
        asked_fields.append(("Location", first_value(requirement.get("location"), requirement.get("preferred_location"), requirement.get("venue")), "The location/venue has not been finalized yet. We will share it once confirmed by the client."))
    if asked("participant", "participants", "audience", "batch size", "count"):
        asked_fields.append(("Participants", first_value(requirement.get("participant_count"), requirement.get("participants")), "The participant count has not been finalized yet. We will share it once confirmed by the client."))
    if asked("level", "beginner", "intermediate", "advanced"):
        asked_fields.append(("Audience level", first_value(requirement.get("audience_level"), requirement.get("level")), "The audience level has not been finalized yet. We will share it once confirmed by the client."))
    if asked("client", "company"):
        asked_fields.append(("Client", first_value(requirement.get("client_company"), requirement.get("client_name"), log.get("client_name")), "Client details will be shared once confirmed for the next step."))
    if asked("toc", "agenda", "content", "syllabus"):
        asked_fields.append(("TOC/Agenda", first_value(requirement.get("toc_summary"), requirement.get("job_description")), "The TOC/agenda is not finalized yet. We will share it once confirmed."))

    if not asked_fields:
        asked_fields = [("Requirement", technology, "The requirement details are under coordination and will be shared once confirmed.")]

    lines = []
    for label, value, missing_text in asked_fields:
        lines.append(f"{label}: {value}" if value else missing_text)
    answer_block = "\n".join(lines)
    return {
        "subject": f"Re: {reply.get('subject') or log.get('subject') or f'Training Requirement - {technology}'}",
        "body": (
            f"Dear {trainer_name},\n\n"
            "Thank you for your question.\n\n"
            f"{answer_block}\n\n"
            "Best Regards,\n"
            "Recruitment Team\n"
            "Clahan Technologies"
        ),
        "ai_used": False,
        "fallback": True,
    }


async def _generate_extra_training_question_reply(db, log: dict, reply: dict, requirement: dict | None) -> dict:
    fallback = _extra_training_reply_fallback(log, reply, requirement)
    if fallback.get("reply_kind") == "profile_details_request":
        return fallback
    api_key = (os.getenv("GEMINI_API_KEY", "") or getattr(settings, "gemini_api_key", "")).strip()
    if _is_placeholder_api_key(api_key):
        return fallback

    requirement = requirement or {}
    model = (os.getenv("GEMINI_MODEL", "") or getattr(settings, "gemini_model", "") or "gemini-2.0-flash").strip()
    trainer_name = log.get("trainer_name") or "Trainer"
    technology = requirement.get("technology_needed") or log.get("technology") or log.get("domain") or "Training"
    prompt = f"""
You are a professional training coordination assistant for Clahan Technologies.

Write a short, helpful email reply to the trainer/client's extra question.

Rules:
- Answer only the specific question(s) asked by the trainer/client.
- If they ask multiple items together, answer those items together.
- If this is the first trainer interest reply and they ask for TOC/details/detailed requirement before sharing profile, ask for updated trainer profile/resume and trainer details first. Share only known requirement details; say missing details will be updated after client confirmation.
- If they ask how many interview slots to share, or ask whether they should book/share 5 slots, gently say 3 slot options are enough. Ask them to share any 3 convenient slots with full date, month, year, time, AM/PM, and timezone. Include this blank format: "Slot 1: [Date Month Year], [Start Time] - [End Time] IST", "Slot 2: [Date Month Year], [Start Time] - [End Time] IST", "Slot 3: [Date Month Year], [Start Time] - [End Time] IST".
- If a requested detail is available in the known context, share it.
- If a requested detail is missing, say it is not finalized yet and will be shared once confirmed by the client.
- Do not add unrelated reminders, requests, or commercial/profile follow-ups unless the question asks about them.
- Do not invent dates, rates, links, or commitments.
- Keep it concise and professional.
- Do not mention AI, Gemini, internal systems, or tokens.
- Return only the email body, no subject.

Recipient name: {trainer_name}
Original subject: {reply.get('subject') or log.get('subject') or ''}
Incoming question:
{str(reply.get('body') or '')[:6000]}

Training context:
Technology: {technology}
Client: {requirement.get('client_name') or requirement.get('client_company') or log.get('client_name') or ''}
Client email: {requirement.get('client_email') or log.get('client_email') or ''}
Duration days: {requirement.get('duration_days') or ''}
Duration hours: {requirement.get('duration_hours') or ''}
Training dates: {requirement.get('training_dates') or ''}
Start date: {requirement.get('timeline_start') or ''}
End date: {requirement.get('timeline_end') or ''}
Timing: {requirement.get('timing') or ''}
Mode: {requirement.get('mode') or ''}
Level: {requirement.get('level') or requirement.get('audience_level') or ''}
Requirement notes: {requirement.get('job_description') or requirement.get('client_notes') or ''}
Latest mail stage: {log.get('mail_type') or ''}
"""
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        async with _httpx.AsyncClient(timeout=30) as client:
            res = await client.post(url, json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.25, "maxOutputTokens": 700},
            })
            res.raise_for_status()
            data = res.json()
        body = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
            .strip()
        )
        if not body:
            return fallback
        usage = data.get("usageMetadata") or {}
        input_tokens = int(usage.get("promptTokenCount") or max(1, len(prompt) // 4))
        output_tokens = int(usage.get("candidatesTokenCount") or max(1, len(body) // 4))
        rates = await _dashboard_cost_rates(db)
        cost_inr = (
            (input_tokens / 1000) * rates["gemini_input_1k_tokens"]
            + (output_tokens / 1000) * rates["gemini_output_1k_tokens"]
        )
        await db["ai_usage_logs"].insert_one({
            "usage_id": f"AI-{uuid.uuid4().hex[:10].upper()}",
            "provider": "gemini",
            "model": model,
            "feature": "extra_training_question_reply",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_inr": _money(cost_inr),
            "metadata": {
                "email_id": log.get("email_id"),
                "trainer_id": log.get("trainer_id"),
                "requirement_id": log.get("requirement_id"),
                "mail_type": log.get("mail_type"),
            },
            "created_at": utc_now(),
        })
        return {
            "subject": fallback["subject"],
            "body": body,
            "ai_used": True,
            "fallback": False,
        }
    except Exception as exc:
        logger.warning("Extra training question Gemini reply failed; using fallback: %s", exc)
        return fallback


async def _auto_reply_extra_training_question(
    db,
    request: Request,
    *,
    log: dict,
    reply: dict,
    from_email: str,
    replied_at: datetime,
    message_id_header: str = "",
) -> dict | None:
    if not _looks_like_extra_training_question(reply.get("body") or ""):
        return None
    action = (reply.get("action") or "").strip()
    sentiment = (reply.get("sentiment") or "").strip().lower()
    if action == "mark_declined" or sentiment == "negative":
        return None
    if action not in {"requires_review", "", "mark_interested"} and sentiment not in {"neutral", "positive"}:
        return None

    existing = await db["conversations"].find_one({
        "direction": "sent",
        "mail_type": "ai_extra_question_reply",
        "$or": [
            {"in_reply_to": message_id_header} if message_id_header else {"source_email_id": log.get("email_id")},
            {"source_email_id": log.get("email_id"), "to_email": {"$regex": f"^{_re.escape(from_email)}$", "$options": "i"}},
        ],
    })
    if existing:
        return {"skipped": True, "reason": "AI extra question reply already sent", "email_id": existing.get("email_id")}

    requirement = None
    if log.get("requirement_id"):
        requirement = await db["requirements"].find_one({"requirement_id": log.get("requirement_id")}, {"_id": 0})

    generated = await _generate_extra_training_question_reply(db, log, reply, requirement)
    email_id = f"AI-EXTRA-{uuid.uuid4().hex[:8].upper()}"
    tracking_url = build_tracking_url(request, email_id)
    smtp_config = await get_admin_email_config(db)
    success, error = await send_email_async(
        from_email,
        generated["subject"],
        generated["body"],
        smtp_config,
        tracking_url,
    )
    now = utc_now()
    log_doc = {
        "email_id": email_id,
        "trainer_id": log.get("trainer_id"),
        "trainer_name": log.get("trainer_name"),
        "requirement_id": log.get("requirement_id"),
        "to_email": from_email,
        "subject": generated["subject"],
        "body": generated["body"],
        "direction": "sent",
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "sent_at": now if success else None,
        "reply_received": False,
        "opened": False,
        "open_count": 0,
        "tracking_url": tracking_url,
        "retry_count": 0,
        "mail_type": "ai_extra_question_reply",
        "source": "ai_extra_training_question",
        "source_email_id": log.get("email_id"),
        "in_reply_to": message_id_header,
        "ai_used": generated.get("ai_used", False),
        "fallback": generated.get("fallback", False),
        "created_at": now,
    }
    await db["email_logs"].insert_one(log_doc)
    await db["conversations"].insert_one({
        **log_doc,
        "status": "sent" if success else "failed",
        "error": error if not success else "",
    })
    await db["email_logs"].update_one(
        {"email_id": log.get("email_id")},
        {"$set": {
            "extra_question_reply_result": {
                "success": success,
                "error": error,
                "email_id": email_id,
                "ai_used": generated.get("ai_used", False),
                "fallback": generated.get("fallback", False),
            },
            "extra_question_reply_checked_at": now,
        }},
    )
    return {
        "success": success,
        "error": error,
        "email_id": email_id,
        "ai_used": generated.get("ai_used", False),
        "fallback": generated.get("fallback", False),
    }


def _extract_toc_detail_fields(text: str = "") -> dict:
    body = str(text or "").strip()
    if not body:
        return {}

    def field(label: str) -> str:
        match = _re.search(
            rf"(?im)^\s*(?:[-*]\s*)?{label}\s*:\s*(.+?)(?=\n\s*(?:[-*]\s*)?(?:Duration|Dates?|Timings?|Audience\s+Level|Mode|Content\s+Scope)\s*:|\n\s*(?:Please|Regards|Thanks|Thank you)\b|\Z)",
            body,
            flags=_re.IGNORECASE | _re.DOTALL,
        )
        return " ".join(match.group(1).strip().split()) if match else ""

    duration_text = field("Duration")
    dates_text = field("Dates?")
    timing_text = field("Timings?")
    audience_level = field("Audience\\s+Level")
    mode = field("Mode")
    content_scope = field("Content\\s+Scope")

    if not timing_text and duration_text:
        time_match = _re.search(
            r"(\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)\s*(?:-|to|–|—)\s*\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm))",
            duration_text,
        )
        if time_match:
            timing_text = time_match.group(1)

    duration_days = None
    day_match = _re.search(r"\b(\d{1,3})\s*(?:day|days)\b", duration_text, flags=_re.IGNORECASE)
    if day_match:
        duration_days = max(1, min(int(day_match.group(1)), 100))

    update = {}
    if duration_days:
        update["duration_days"] = float(duration_days)
    if duration_text:
        update["duration_text"] = duration_text
    if dates_text:
        update["training_dates"] = dates_text
        date_match = _re.search(r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s*(?:to|-|–|—)\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", dates_text)
        if date_match:
            update["timeline_start"] = date_match.group(1)
            update["timeline_end"] = date_match.group(2)
    if timing_text:
        update["timing"] = timing_text
    if audience_level:
        clean_level = audience_level.strip().lower()
        if any(level in clean_level for level in ("basic", "beginner")):
            update["audience_level"] = "Basic"
        elif "advanced" in clean_level:
            update["audience_level"] = "Advanced"
        elif "mixed" in clean_level:
            update["audience_level"] = "Mixed"
        elif "intermediate" in clean_level:
            update["audience_level"] = "Intermediate"
        else:
            update["audience_level"] = audience_level.strip()
    if mode:
        clean_mode = mode.strip().lower()
        if "class" in clean_mode:
            update["mode"] = "Classroom"
        elif "hybrid" in clean_mode:
            update["mode"] = "Hybrid"
        elif "online" in clean_mode or "virtual" in clean_mode:
            update["mode"] = "Online"
        else:
            update["mode"] = mode.strip()
    if content_scope:
        update["content_scope"] = content_scope.strip()
        update["client_notes"] = content_scope.strip()
    return update


async def _process_client_toc_details_reply(db, request: Request, *, log: dict, reply: dict, from_email: str, replied_at: datetime) -> dict | None:
    body = reply.get("body") or ""
    subject = reply.get("subject") or ""
    if not any(marker in f"{subject}\n{body}".lower() for marker in ("audience level", "content scope", "prepare and share the toc", "training details")):
        return None
    requirement_id = log.get("requirement_id") or ""
    if not requirement_id:
        return None
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    if not requirement:
        return None
    details = _extract_toc_detail_fields(body)
    if not details:
        return None

    now = utc_now()
    details.update({
        "toc_input_status": "details_received",
        "toc_input_received_at": now,
        "toc_input_source_email": from_email,
        "toc_input_reply_text": body,
        "updated_at": now,
    })
    await db["requirements"].update_one({"requirement_id": requirement_id}, {"$set": details})
    updated_requirement = {**requirement, **details}

    trainer = {}
    trainer_id = log.get("trainer_id") or requirement.get("selected_trainer_id") or ""
    if trainer_id:
        trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or {}
    trainer.setdefault("trainer_id", trainer_id)
    trainer.setdefault("name", log.get("trainer_name") or requirement.get("selected_trainer_name") or "")
    trainer.setdefault("email", log.get("trainer_email") or trainer.get("email") or "")

    toc_result = await _auto_generate_and_send_toc(
        db,
        request,
        trainer=trainer,
        requirement=updated_requirement,
        source="client_toc_details_reply",
    )
    return {
        "status": "toc_details_processed",
        "requirement_id": requirement_id,
        "updated_fields": details,
        "toc_result": toc_result,
    }


@router.post("/emails/check-replies")
async def manual_reply_check(request: Request):
    db = get_db()
    sent_recipients = await db["email_logs"].distinct(
        "to_email",
        {
            "status": "sent",
            "$or": [
                {"reply_received": {"$ne": True}},
                {"mail_type": "mail3", "client_slot_auto_result": {"$exists": False}},
            ],
        },
    )
    smtp_config = await get_admin_email_config(db)
    gmail_ok, replies, gmail_error = await asyncio.to_thread(
        _check_gmail_replies_fast,
        since_days=14,
        max_messages=100,
        from_emails=sent_recipients,
    )
    reply_source = "gmail_api" if gmail_ok else "imap"
    if not gmail_ok:
        replies = await asyncio.to_thread(
            check_email_replies,
            since_days=14,
            max_messages=100,
            from_emails=sent_recipients,
            gmail_user=smtp_config.get("smtpUser") or "",
            gmail_pass=smtp_config.get("smtpPass") or "",
            imap_host=smtp_config.get("imapHost") or ("imap.hostinger.com" if "hostinger" in str(smtp_config.get("smtpHost") or "").lower() else "imap.gmail.com"),
            imap_port=int(smtp_config.get("imapPort") or 993),
        )
    processed = 0
    skipped_duplicates = 0
    skipped_unmatched = 0
    client_slot_auto_sent = 0
    client_slot_auto_failed = 0
    client_slot_auto_results = []
    client_decision_results = []
    client_po_results = []
    extra_question_ai_replies_sent = 0
    extra_question_ai_replies_failed = 0
    extra_question_ai_reply_results = []
    commercial_negotiation_results = []
    client_toc_detail_results = []
    next_trainer_followups = []

    async def process_client_decision_reply(reply: dict, from_email: str, replied_at):
        body = reply.get("body") or ""
        subject = reply.get("subject") or ""
        if not _detect_client_interview_decision(subject, body).get("decision"):
            return None
        slot_meta = {
            "from_email": from_email,
            "subject": subject,
            "snippet": body[:500],
            "clean_body": body,
            "received_at": replied_at,
        }
        if await _matching_client_slot_email(db, slot_meta, body):
            return None
        client_match = await db["requirements"].find_one(
            {"client_email": {"$regex": f"^{_re.escape(from_email)}$", "$options": "i"}},
            {"_id": 0, "requirement_id": 1},
        )
        slot_mail_match = await db["email_logs"].find_one(
            {
                "to_email": {"$regex": f"^{_re.escape(from_email)}$", "$options": "i"},
                "mail_type": "client_slot_options",
                "status": "sent",
            },
            {"_id": 0, "email_id": 1},
        )
        if not client_match and not slot_mail_match:
            return None
        meta = {
            "email_id": reply.get("msg_id") or reply.get("message_id_header") or f"reply-{hashlib.sha256((subject + body).encode('utf-8')).hexdigest()[:16]}",
            "gmail_message_id": reply.get("msg_id") or reply.get("message_id_header") or "",
            "thread_id": reply.get("thread_id") or "",
            "from_email": from_email,
            "from_name": reply.get("from_name") or "",
            "subject": subject,
            "clean_body": body,
            "raw_body": body,
            "snippet": body[:500],
            "received_at": replied_at,
        }
        result = await _process_client_interview_decision(db, meta, request)
        if result:
            await _save_post_interview_decision_email(db, meta, result)
        return result

    async def process_client_po_reply(reply: dict, from_email: str, replied_at):
        body = reply.get("body") or ""
        subject = reply.get("subject") or ""
        if not _extract_client_po_details(subject, body):
            return None
        meta = {
            "email_id": reply.get("msg_id") or reply.get("message_id_header") or f"client-po-{hashlib.sha256((subject + body).encode('utf-8')).hexdigest()[:16]}",
            "gmail_message_id": reply.get("msg_id") or reply.get("message_id_header") or "",
            "thread_id": reply.get("thread_id") or "",
            "from_email": from_email,
            "from_name": reply.get("from_name") or "",
            "subject": subject,
            "clean_body": body,
            "raw_body": body,
            "snippet": body[:500],
            "received_at": replied_at,
            "message_id_header": reply.get("message_id_header", ""),
        }
        return await _process_client_purchase_order_email(db, meta, request)

    for reply in replies:
        from_raw = reply["from_email"]
        m = _re.search(r'<([^>]+)>', from_raw)
        from_email_clean = m.group(1) if m else from_raw.strip()
        message_id_header = reply.get("message_id_header", "")

        duplicate_or = [{"subject": reply["subject"], "body": reply["body"]}]
        if message_id_header:
            duplicate_or.insert(0, {"message_id_header": message_id_header})
        existing_reply = await db["conversations"].find_one(
            {
                "direction": "received",
                "to_email": {"$regex": f"^{_re.escape(from_email_clean)}$", "$options": "i"},
                "$or": duplicate_or,
            },
            {"_id": 0, "trainer_id": 1, "trainer_name": 1, "requirement_id": 1, "sent_at": 1},
        )
        if existing_reply:
            if existing_reply.get("requirement_id"):
                toc_log = await db["email_logs"].find_one(
                    {
                        "requirement_id": existing_reply.get("requirement_id"),
                        "to_email": {"$regex": f"^{_re.escape(from_email_clean)}$", "$options": "i"},
                        "mail_type": "client_toc_details_request",
                        "status": "sent",
                    },
                    {"_id": 0},
                    sort=[("created_at", -1), ("sent_at", -1)],
                )
                if toc_log:
                    toc_detail_result = await _process_client_toc_details_reply(
                        db,
                        request,
                        log=toc_log,
                        reply=reply,
                        from_email=from_email_clean,
                        replied_at=existing_reply.get("sent_at") or utc_now(),
                    )
                    if toc_detail_result:
                        client_toc_detail_results.append(toc_detail_result)
                        skipped_duplicates += 1
                        continue
            po_result = await process_client_po_reply(reply, from_email_clean, existing_reply.get("sent_at") or utc_now())
            if po_result:
                client_po_results.append(po_result)
                skipped_duplicates += 1
                continue
            decision_result = await process_client_decision_reply(reply, from_email_clean, existing_reply.get("sent_at") or utc_now())
            if decision_result:
                client_decision_results.append(decision_result)
                skipped_duplicates += 1
                continue
            if existing_reply.get("trainer_id") and existing_reply.get("requirement_id"):
                slot_log = await db["email_logs"].find_one(
                    {
                        "trainer_id": existing_reply.get("trainer_id"),
                        "requirement_id": existing_reply.get("requirement_id"),
                        "to_email": {"$regex": f"^{_re.escape(from_email_clean)}$", "$options": "i"},
                        "mail_type": "mail3",
                        "status": "sent",
                    },
                    {"_id": 0},
                    sort=[("sent_at", -1), ("created_at", -1)],
                )
                if slot_log:
                    slot_result = await _auto_send_client_slots_from_trainer_reply(db, request, slot_log, reply)
                    if slot_result and not slot_result.get("skipped"):
                        client_slot_auto_results.append(slot_result)
                        if slot_result.get("success"):
                            client_slot_auto_sent += 1
                        else:
                            client_slot_auto_failed += 1
            skipped_duplicates += 1
            continue

        replied_at = utc_now()
        try:
            if reply.get("received_at"):
                replied_at = datetime.fromisoformat(str(reply["received_at"]).replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            replied_at = utc_now()

        po_result = await process_client_po_reply(reply, from_email_clean, replied_at)
        if po_result:
            client_po_results.append(po_result)
            processed += 1
            continue

        decision_result = await process_client_decision_reply(reply, from_email_clean, replied_at)
        if decision_result:
            client_decision_results.append(decision_result)
            processed += 1
            continue

        reply_subject_norm = _norm_subject(reply.get("subject", ""))
        candidate_logs = await db["email_logs"].find(
            {
                "to_email": {"$regex": f"^{_re.escape(from_email_clean)}$", "$options": "i"},
                "status": "sent",
                "sent_at": {"$lte": replied_at},
            },
            {"_id": 0},
        ).sort("sent_at", -1).limit(25).to_list(25)

        def candidate_score(item):
            subject_norm = _norm_subject(item.get("subject", ""))
            reply_body_norm = str(reply.get("body", "")).lower()
            trainer_name_norm = str(item.get("trainer_name", "")).strip().lower()
            score = 0
            if subject_norm and (subject_norm in reply_subject_norm or reply_subject_norm in subject_norm):
                score += 100
            if trainer_name_norm and trainer_name_norm in reply_body_norm:
                score += 200
            if item.get("mail_type") == "mail2" and "additional details required" in reply_subject_norm:
                score += 80
            if item.get("mail_type") == "mail2_followup" and "details required" in reply_subject_norm:
                score += 70
            if item.get("mail_type") == "mail3" and "interview slot booking" in reply_subject_norm:
                score += 150
            if item.get("mail_type") == "mail4" and "interview schedule" in reply_subject_norm:
                score += 120
            if item.get("mail_type") == "mail1_reminder" and "reminder" in reply_subject_norm:
                score += 30
            if item.get("mail_type") == "trainer_commercial_negotiation" and "commercial" in reply_subject_norm:
                score += 180
            if item.get("reply_received"):
                score -= 40
            return score

        log = sorted(candidate_logs, key=candidate_score, reverse=True)[0] if candidate_logs else None
        if not log:
            log = await db["conversations"].find_one(
                {"to_email": {"$regex": f"^{_re.escape(from_email_clean)}$", "$options": "i"}, "direction": "sent", "sent_at": {"$lte": replied_at}},
                sort=[("sent_at", -1)]
            )
        if log:
            trainer_id_matched     = log.get("trainer_id")
            requirement_id_matched = log.get("requirement_id")
            status_map = {"mark_interested": "interested", "mark_declined": "declined", "requires_review": "pending_review"}

            await db["email_logs"].update_one(
                {"email_id": log.get("email_id")},
                {"$set": {"reply_received": True, "reply_sentiment": reply["sentiment"],
                           "reply_text": reply["body"], "replied_at": replied_at,
                           "reply_message_id": message_id_header}}
            )

            if log.get("mail_type") == "client_slot_options":
                duplicate_query = {
                    "to_email": from_email_clean,
                    "requirement_id": requirement_id_matched,
                    "direction": "received",
                    "$or": [
                        {"message_id_header": message_id_header} if message_id_header else {"subject": reply["subject"], "body": reply["body"]},
                        {"subject": reply["subject"], "body": reply["body"]},
                    ],
                }
                already_stored = await db["conversations"].find_one(duplicate_query)
                if not already_stored:
                    await db["conversations"].insert_one({
                        "trainer_id": trainer_id_matched,
                        "trainer_name": log.get("trainer_name"),
                        "to_email": from_email_clean,
                        "requirement_id": requirement_id_matched,
                        "subject": reply["subject"],
                        "body": reply["body"],
                        "direction": "received",
                        "mail_type": "client_slot_confirmation",
                        "status": "received",
                        "sent_at": replied_at,
                        "message_id_header": message_id_header,
                        "in_reply_to": reply.get("in_reply_to", ""),
                        "references": reply.get("references", ""),
                    })
                confirmation_result = await _handle_client_slot_confirmation_reply(
                    db,
                    request,
                    log=log,
                    reply=reply,
                    from_email=from_email_clean,
                    replied_at=replied_at,
                )
                client_slot_auto_results.append(confirmation_result)
                processed += 1
                continue

            if log.get("mail_type") == "client_toc_details_request":
                toc_detail_result = await _process_client_toc_details_reply(
                    db,
                    request,
                    log=log,
                    reply=reply,
                    from_email=from_email_clean,
                    replied_at=replied_at,
                )
                if toc_detail_result:
                    client_toc_detail_results.append(toc_detail_result)
                    processed += 1
                    continue

            duplicate_query = {
                "to_email": from_email_clean,
                "requirement_id": requirement_id_matched,
                "direction": "received",
                "$or": [
                    {"message_id_header": message_id_header} if message_id_header else {"subject": reply["subject"], "body": reply["body"]},
                    {"subject": reply["subject"], "body": reply["body"]},
                ],
            }
            already_stored = await db["conversations"].find_one(duplicate_query)
            if not already_stored:
                await db["conversations"].insert_one({
                    "trainer_id": trainer_id_matched, "trainer_name": log.get("trainer_name"),
                    "to_email": from_email_clean, "requirement_id": requirement_id_matched,
                    "subject": reply["subject"], "body": reply["body"],
                    "direction": "received", "mail_type": "reply",
                    "status": "received", "sent_at": replied_at,
                    "message_id_header": message_id_header,
                    "in_reply_to": reply.get("in_reply_to", ""),
                    "references": reply.get("references", ""),
                })
                await send_vendor_reply_notification(
                    db,
                    trainer_name=log.get("trainer_name", ""),
                    trainer_id=trainer_id_matched,
                    requirement_id=requirement_id_matched,
                    mail_type=log.get("mail_type", ""),
                    reply_subject=reply.get("subject", ""),
                    reply_body=reply.get("body", ""),
                    sentiment=reply.get("sentiment", ""),
                    request_base_url="",
                )
                requirement = await db["requirements"].find_one({"requirement_id": requirement_id_matched}, {"_id": 0})
                await send_teams_stage_notification(
                    db,
                    stage="trainer_replied",
                    trainer_name=log.get("trainer_name", ""),
                    requirement=requirement or {"requirement_id": requirement_id_matched},
                    request_base_url=_request_base_url(request),
                    context={
                        "source": "manual_reply_check",
                        "trainer_id": trainer_id_matched,
                        "sentiment": reply.get("sentiment", ""),
                        "subject": reply.get("subject", ""),
                    },
                )

            commercial_result = await _handle_trainer_commercial_negotiation_reply(
                db,
                request,
                log=log,
                reply=reply,
            )
            if commercial_result:
                commercial_negotiation_results.append(commercial_result)
                slot_followup = commercial_result.get("client_slot_result") or {}
                if slot_followup:
                    client_slot_auto_results.append(slot_followup)
                    if slot_followup.get("success"):
                        client_slot_auto_sent += 1
                    else:
                        client_slot_auto_failed += 1
                next_followup = commercial_result.get("next_trainer")
                if next_followup:
                    next_trainer_followups.append(next_followup)
                processed += 1
                continue

            extra_reply_result = await _auto_reply_extra_training_question(
                db,
                request,
                log=log,
                reply=reply,
                from_email=from_email_clean,
                replied_at=replied_at,
                message_id_header=message_id_header,
            )
            if extra_reply_result and not extra_reply_result.get("skipped"):
                extra_question_ai_reply_results.append(extra_reply_result)
                if extra_reply_result.get("success"):
                    extra_question_ai_replies_sent += 1
                else:
                    extra_question_ai_replies_failed += 1

            await db["trainers"].update_one(
                {"trainer_id": trainer_id_matched},
                {"$set": {"status": status_map.get(reply["action"], "pending_review")}}
            )
            if reply.get("action") == "mark_declined":
                followup_result = await _send_next_trainer_after_decline(
                    db,
                    request,
                    declined_log=log,
                    reply=reply,
                )
                next_trainer_followups.append(followup_result)
            slot_result = await _auto_send_client_slots_from_trainer_reply(db, request, log, reply)
            if slot_result and not slot_result.get("skipped"):
                client_slot_auto_results.append(slot_result)
                if slot_result.get("success"):
                    client_slot_auto_sent += 1
                else:
                    client_slot_auto_failed += 1
            processed += 1
        else:
            skipped_unmatched += 1

    pending_slot_scan = {"checked": 0, "sent": 0, "failed": 0, "results": [], "manual_only": True}
    client_slot_auto_sent += pending_slot_scan.get("sent", 0)
    client_slot_auto_failed += pending_slot_scan.get("failed", 0)
    client_slot_auto_results.extend(pending_slot_scan.get("results") or [])
    client_confirmation_scan = await _process_pending_client_slot_confirmations_from_logs(
        db,
        request,
        limit=25,
    )
    client_slot_auto_results.extend(client_confirmation_scan.get("processed") or [])
    if processed > 0 and reply_source == "imap":
        from agents.email_agent import mark_emails_seen
        msg_ids = [r["msg_id"] for r in replies if r.get("msg_id")]
        if msg_ids:
            await asyncio.to_thread(mark_emails_seen, msg_ids)

    return {
        "reply_source": reply_source,
        "gmail_fast_error": "" if gmail_ok else gmail_error,
        "replies_found": len(replies),
        "processed": processed,
        "skipped_duplicates": skipped_duplicates,
        "skipped_unmatched": skipped_unmatched,
        "client_slot_auto_sent": client_slot_auto_sent,
        "client_slot_auto_failed": client_slot_auto_failed,
        "client_slot_pending_checked": pending_slot_scan.get("checked", 0),
        "client_slot_confirmations_checked": client_confirmation_scan.get("checked", 0),
        "client_slot_confirmations_failed": client_confirmation_scan.get("failed", 0),
        "client_slot_auto_results": client_slot_auto_results,
        "client_decision_processed": len(client_decision_results),
        "client_decision_results": client_decision_results,
        "client_po_processed": len(client_po_results),
        "client_po_results": client_po_results,
        "client_toc_details_processed": len(client_toc_detail_results),
        "client_toc_detail_results": client_toc_detail_results,
        "extra_question_ai_replies_sent": extra_question_ai_replies_sent,
        "extra_question_ai_replies_failed": extra_question_ai_replies_failed,
        "extra_question_ai_reply_results": extra_question_ai_reply_results,
        "commercial_negotiation_results": commercial_negotiation_results,
        "next_trainer_followups": next_trainer_followups,
        "client_decision_error": "",
    }


# ─── Scheduler Config ─────────────────────────────────────────────────────────

@router.get("/scheduler/config")
async def get_scheduler_config_route():
    return await load_scheduler_config_from_db()


@router.post("/scheduler/config")
async def update_scheduler_config_route(payload: dict):
    allowed = {
        "retry_interval_unit", "retry_interval_value", "reply_check_interval",
        "gmail_fallback_interval", "excel_sync_interval", "max_retries",
        "auto_retry_enabled", "linkedin_client_lead_interval",
        "linkedin_client_lead_enabled",
    }
    clean = {k: v for k, v in payload.items() if k in allowed}
    if not clean:
        raise HTTPException(400, "No valid config keys provided")
    if "retry_interval_unit" in clean and clean["retry_interval_unit"] not in ("minutes", "hours", "days"):
        raise HTTPException(400, "retry_interval_unit must be 'minutes', 'hours', or 'days'")
    config = await save_scheduler_config_to_db(clean)
    return {"message": "Scheduler config updated", "config": config}


# ─── Dashboard Stats ──────────────────────────────────────────────────────────

@router.get("/business-excel/status")
async def business_excel_status():
    path = workbook_path()
    return {
        "path": str(path),
        "exists": path.exists(),
        "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat() if path.exists() else "",
        "filename": path.name,
    }


@router.post("/business-excel/sync")
async def sync_business_excel_route():
    return await sync_business_excel(get_db())


@router.post("/business-excel/send-email")
async def send_business_excel_email(payload: dict = {}):
    db = get_db()
    sync_result = await sync_business_excel(db)
    path = workbook_path()
    if not path.exists():
        raise HTTPException(404, "Business Excel workbook was not found after sync")

    to_email = str(payload.get("to_email") or "sujithamuttarasu@gmail.com").strip()
    if not to_email or "@" not in to_email:
        raise HTTPException(400, "Valid to_email is required")

    subject = str(payload.get("subject") or "TrainerSync Business Excel Register").strip()
    body = str(payload.get("body") or (
        "Dear Team,\n\n"
        "Please find attached the latest TrainerSync business Excel register.\n\n"
        "This workbook includes trainer data, requirements, selected/rejected details, "
        "client PO details, invoices, and monthly summary.\n\n"
        "Regards,\n"
        "Clahan Technologies"
    )).strip()

    smtp_config = await get_admin_email_config(db)
    file_bytes = path.read_bytes()
    success, error = _send_email_with_file_attachment(
        to_email,
        subject,
        body,
        path.name,
        file_bytes,
        smtp_config,
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    email_id = f"EMAIL-{uuid.uuid4().hex[:8].upper()}"
    await db["email_logs"].insert_one({
        "email_id": email_id,
        "mail_type": "business_excel_report",
        "from_email": smtp_config.get("fromEmail") or smtp_config.get("smtpUser") or "",
        "to_email": to_email,
        "subject": subject,
        "body": body,
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "attachment_filename": path.name,
        "attachment_path": str(path),
        "sync_result": sync_result,
        "created_at": utc_now(),
        "sent_at": utc_now() if success else None,
    })

    if not success:
        raise HTTPException(500, error or "Business Excel email failed")

    return {
        "success": True,
        "message": "Business Excel workbook sent successfully",
        "email_id": email_id,
        "to_email": to_email,
        "filename": path.name,
        "path": str(path),
        "sync_result": sync_result,
    }


@router.post("/business-excel/upload-drive")
async def upload_business_excel_to_drive(payload: dict = {}):
    db = get_db()
    sync_result = await sync_business_excel(db)
    path = workbook_path()
    if not path.exists():
        raise HTTPException(404, "Business Excel workbook was not found after sync")

    folder_name = str(payload.get("folder_name") or "TrainerSync Business Reports").strip()
    file_name = str(payload.get("file_name") or path.name).strip()
    try:
        upload_result = upload_file_to_drive(
            str(path),
            name=file_name,
            folder_name=folder_name,
        )
    except Exception as exc:
        raise HTTPException(
            400,
            {
                "message": "Google Drive upload failed. Reconnect Google OAuth and approve Drive permission.",
                "error": str(exc),
                "required_action": "Open /api/gmail/oauth-url and reconnect the Google account with Gmail, Calendar, and Drive permissions.",
            },
        )

    await db["excel_drive_uploads"].insert_one({
        "upload_id": f"DRIVE-{uuid.uuid4().hex[:8].upper()}",
        "filename": file_name,
        "local_path": str(path),
        "folder_name": folder_name,
        "drive_file_id": upload_result.get("file_id"),
        "drive_file_link": upload_result.get("web_view_link"),
        "sync_result": sync_result,
        "created_at": utc_now(),
    })
    return {
        "success": True,
        "message": "Business Excel workbook uploaded to Google Drive",
        "filename": file_name,
        "path": str(path),
        "drive": upload_result,
        "sync_result": sync_result,
    }


@router.get("/dashboard/stats")
async def get_dashboard_stats():
    db = get_db()
    total_trainers     = await db["trainers"].count_documents({})
    total_requirements = await db["requirements"].count_documents({})
    total_emails       = await db["email_logs"].count_documents({"status": "sent"})
    total_failed       = await db["email_logs"].count_documents({"status": "failed"})
    total_opened       = await db["email_logs"].count_documents({"opened": True})
    total_replies_logs = await db["email_logs"].count_documents({"reply_received": True})
    total_replies      = total_replies_logs
    interested         = await db["trainers"].count_documents({"status": "interested"})
    declined           = await db["trainers"].count_documents({"status": "declined"})
    pending_review     = await db["trainers"].count_documents({"status": "pending_review"})
    contacted          = await db["trainers"].count_documents({"status": "contacted"})
    confirmed          = await db["trainers"].count_documents({"status": "confirmed"})

    reply_rate    = round((total_replies / total_emails * 100) if total_emails > 0 else 0, 1)
    open_rate     = round((total_opened / total_emails * 100) if total_emails > 0 else 0, 1)
    interest_rate = round((interested / total_replies * 100) if total_replies > 0 else 0, 1)

    recent_emails = await db["email_logs"].find({}, {"_id": 0}).sort("created_at", -1).limit(5).to_list(5)
    recent_whatsapp = await db["whatsapp_logs"].find({}, {"_id": 0}).sort("created_at", -1).limit(8).to_list(8)
    whatsapp_total = await db["whatsapp_logs"].count_documents({})
    whatsapp_sent = await db["whatsapp_logs"].count_documents({"status": {"$in": ["queued", "sent", "delivered", "read"]}})
    whatsapp_delivered = await db["whatsapp_logs"].count_documents({"status": {"$in": ["delivered", "read"]}})
    whatsapp_failed = await db["whatsapp_logs"].count_documents({"status": {"$in": ["failed", "undelivered", "skipped"]}})
    whatsapp_replies = await db["whatsapp_logs"].count_documents({"direction": "inbound"})

    today = utc_now().date()
    activity = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        start = datetime.combine(day, datetime.min.time())
        end = start + timedelta(days=1)
        activity.append({
            "day": day.strftime("%a"),
            "date": day.isoformat(),
            "emails": await db["email_logs"].count_documents({
                "status": "sent",
                "sent_at": {"$gte": start, "$lt": end},
            }),
            "opens": await db["email_logs"].count_documents({
                "opened": True,
                "opened_at": {"$gte": start, "$lt": end},
            }),
            "replies": await db["email_logs"].count_documents({
                "reply_received": True,
                "replied_at": {"$gte": start, "$lt": end},
            }),
        })

    try:
        score_dist = await db["trainers"].aggregate([
            {"$match": {"match_score": {"$ne": None}}},
            {"$bucket": {"groupBy": "$match_score", "boundaries": [0, 20, 40, 60, 80, 101],
                          "default": "Other", "output": {"count": {"$sum": 1}}}}
        ]).to_list(10)
    except:
        score_dist = []

    return {
        "total_trainers": total_trainers, "total_requirements": total_requirements,
        "total_emails_sent": total_emails, "total_emails_failed": total_failed,
        "total_emails_opened": total_opened, "open_rate": open_rate,
        "total_replies": total_replies, "interested_count": interested,
        "declined_count": declined, "pending_review": pending_review,
        "contacted_count": contacted, "confirmed_count": confirmed,
        "reply_rate": reply_rate, "interest_rate": interest_rate,
        "recent_emails": recent_emails, "score_distribution": score_dist,
        "email_activity": activity,
        "whatsapp": {
            "total": whatsapp_total,
            "sent": whatsapp_sent,
            "delivered": whatsapp_delivered,
            "failed": whatsapp_failed,
            "replies": whatsapp_replies,
            "delivery_rate": round((whatsapp_delivered / whatsapp_total * 100) if whatsapp_total else 0, 1),
        },
        "recent_whatsapp": recent_whatsapp,
    }


# ─── Delete Single Trainer ────────────────────────────────────────────────────

def _parse_dashboard_date(value: Optional[str], fallback: datetime, *, end_of_day: bool = False) -> datetime:
    if not value:
        return fallback
    try:
        text = value.strip()
        if len(text) == 10:
            parsed = datetime.fromisoformat(text)
            return parsed + timedelta(days=1) if end_of_day else parsed
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except Exception:
        return fallback


def _dashboard_date_range(
    preset: str = "month",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> tuple[datetime, datetime, str]:
    now = utc_now()
    today_start = datetime.combine(now.date(), datetime.min.time())
    preset = (preset or "month").lower()
    if preset == "today":
        start = today_start
        end = start + timedelta(days=1)
    elif preset == "week":
        start = today_start - timedelta(days=today_start.weekday())
        end = start + timedelta(days=7)
    elif preset == "custom":
        start = _parse_dashboard_date(start_date, today_start - timedelta(days=30))
        end = _parse_dashboard_date(end_date, today_start + timedelta(days=1), end_of_day=True)
        if end <= start:
            end = start + timedelta(days=1)
    else:
        start = today_start.replace(day=1)
        end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
        preset = "month"
    return start, end, preset


def _range_match(field: str, start: datetime, end: datetime) -> dict:
    return {field: {"$gte": start, "$lt": end}}


def _week_key(year: int, week: int) -> str:
    return f"{int(year)}-W{int(week):02d}"


def _week_start(dt: datetime) -> datetime:
    start = datetime.combine(dt.date(), datetime.min.time())
    return start - timedelta(days=start.weekday())


def _week_axis(start: datetime, end: datetime) -> list[dict]:
    current = _week_start(start)
    last = _week_start(end - timedelta(seconds=1))
    weeks = []
    guard = 0
    while current <= last and guard < 80:
        iso = current.isocalendar()
        weeks.append({
            "key": _week_key(iso.year, iso.week),
            "week": current.strftime("%d %b"),
            "opened": 0,
            "closed": 0,
        })
        current += timedelta(days=7)
        guard += 1
    return weeks


def _category_label(value: str) -> str:
    raw = (value or "").strip()
    low = raw.lower()
    if not raw:
        return "Uncategorised"
    mappings = [
        ("DevOps", ["devops", "docker", "kubernetes", "terraform", "jenkins", "ci/cd", "cicd"]),
        ("Gen AI", ["gen ai", "genai", "generative ai", "llm", "rag", "prompt"]),
        ("Python", ["python", "django", "flask", "pandas"]),
        ("Cloud", ["aws", "azure", "gcp", "cloud"]),
        ("Full Stack", ["react", "angular", "vue", "node", "full stack", "javascript", "typescript"]),
        ("Data Engineering", ["data engineering", "spark", "hadoop", "etl", "data pipeline"]),
        ("Cybersecurity", ["cyber", "security", "soc", "siem"]),
        ("MLOps", ["mlops", "machine learning operations"]),
        ("SRE", ["sre", "site reliability"]),
    ]
    for label, needles in mappings:
        if any(item in low for item in needles):
            return label
    if raw in {"Agentic AI", "AIOps", "LLMOps", "Multi-Skillset"}:
        return raw
    return raw[:32]


async def _distinct_count(db, collection: str, field: str, match: dict) -> int:
    docs = await db[collection].aggregate([
        {"$match": match},
        {"$group": {"_id": f"${field}"}},
        {"$match": {"_id": {"$nin": [None, ""]}}},
        {"$count": "count"},
    ]).to_list(1)
    return int(docs[0]["count"]) if docs else 0


async def _distinct_values(db, collection: str, field: str, match: dict) -> set:
    docs = await db[collection].aggregate([
        {"$match": match},
        {"$group": {"_id": f"${field}"}},
        {"$match": {"_id": {"$nin": [None, ""]}}},
    ]).to_list(10000)
    return {doc["_id"] for doc in docs if doc.get("_id")}


DEFAULT_COST_RATES_INR = {
    # Real-only defaults. Do not invent billing when provider cost is not logged.
    "whatsapp_outbound_message": 0.0,
    "whatsapp_inbound_message": 0.0,
    "teams_notification": 0.0,
    "gemini_input_1k_tokens": 0.0,
    "gemini_output_1k_tokens": 0.0,
    "gemini_input_tokens_per_call": 0,
    "gemini_output_tokens_per_call": 0,
    "client_inbox_storage_gb_month": 0.0,
}


def _money(value: float) -> float:
    return round(float(value or 0), 2)


def _cost_number(value, default: float) -> float:
    try:
        if value in (None, ""):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


async def _dashboard_cost_rates(db) -> dict:
    settings_doc = await db["admin_settings"].find_one(
        {"settings_id": "default"},
        {"_id": 0, "costCfg": 1},
    )
    cfg = (settings_doc or {}).get("costCfg") or {}
    return {
        key: _cost_number(cfg.get(key), default)
        for key, default in DEFAULT_COST_RATES_INR.items()
    }


async def _estimated_collection_bytes(db, collection: str, match: dict, limit: int = 5000) -> tuple[int, int]:
    total_bytes = 0
    count = 0
    async for doc in db[collection].find(match, {"_id": 0}).limit(limit):
        count += 1
        try:
            total_bytes += len(_json.dumps(doc, default=str).encode("utf-8"))
        except Exception:
            total_bytes += len(str(doc).encode("utf-8"))
    return total_bytes, count


async def _actual_cost_inr(db, collection: str, match: dict) -> float:
    docs = await db[collection].aggregate([
        {"$match": match},
        {"$group": {"_id": None, "cost": {"$sum": {"$ifNull": ["$cost_inr", 0]}}}},
    ]).to_list(1)
    return float(docs[0]["cost"]) if docs else 0.0


async def _estimate_dashboard_expenses(db, start: datetime, end: datetime, weeks: list[dict]) -> dict:
    whatsapp_match = _range_match("created_at", start, end)
    whatsapp_outbound = await db["whatsapp_logs"].count_documents({
        **whatsapp_match,
        "direction": "outbound",
        "status": {"$in": ["queued", "sent", "delivered", "read"]},
    })
    whatsapp_inbound = await db["whatsapp_logs"].count_documents({
        **whatsapp_match,
        "direction": "inbound",
    })
    whatsapp_failed = await db["whatsapp_logs"].count_documents({
        **whatsapp_match,
        "status": {"$in": ["failed", "undelivered", "skipped"]},
    })

    teams_sent = await db["teams_logs"].count_documents({
        **_range_match("created_at", start, end),
        "status": "sent",
    })
    teams_failed = await db["teams_logs"].count_documents({
        **_range_match("created_at", start, end),
        "status": "failed",
    })

    client_processed = await db["client_emails"].count_documents(_range_match("received_at", start, end))
    client_auto_sent = await db["client_emails"].count_documents({
        **_range_match("received_at", start, end),
        "status": "auto_sent",
    })
    resume_gemini = await db["trainers"].count_documents({
        **_range_match("created_at", start, end),
        "extraction_source": "gemini",
    })

    usage_docs = await db["ai_usage_logs"].aggregate([
        {"$match": _range_match("created_at", start, end)},
        {"$group": {
            "_id": None,
            "calls": {"$sum": 1},
            "input_tokens": {"$sum": {"$ifNull": ["$input_tokens", 0]}},
            "output_tokens": {"$sum": {"$ifNull": ["$output_tokens", 0]}},
            "cost_inr": {"$sum": {"$ifNull": ["$cost_inr", 0]}},
        }},
    ]).to_list(1)
    actual_ai = usage_docs[0] if usage_docs else {}
    logged_input_tokens = int(actual_ai.get("input_tokens") or 0)
    logged_output_tokens = int(actual_ai.get("output_tokens") or 0)
    logged_cost = await _actual_cost_inr(db, "ai_usage_logs", _range_match("created_at", start, end))
    gemini_cost = logged_cost

    client_storage_bytes, client_storage_docs = await _estimated_collection_bytes(
        db,
        "client_emails",
        _range_match("received_at", start, end),
    )
    storage_cost = await _actual_cost_inr(db, "client_emails", _range_match("received_at", start, end))
    whatsapp_cost = await _actual_cost_inr(db, "whatsapp_logs", whatsapp_match)
    teams_cost = await _actual_cost_inr(db, "teams_logs", _range_match("created_at", start, end))
    communication_total = whatsapp_cost + teams_cost
    ai_total = gemini_cost
    storage_total = storage_cost
    total = communication_total + ai_total + storage_total

    weekly_expenses = []
    current = _week_start(start)
    guard = 0
    week_lookup = {item["key"]: item for item in weeks}
    while current < end and guard < 80:
        week_end = min(current + timedelta(days=7), end)
        if week_end > start:
            w_start = max(current, start)
            iso = current.isocalendar()
            key = _week_key(iso.year, iso.week)

            w_whatsapp_outbound = await db["whatsapp_logs"].count_documents({
                **_range_match("created_at", w_start, week_end),
                "direction": "outbound",
                "status": {"$in": ["queued", "sent", "delivered", "read"]},
            })
            w_whatsapp_inbound = await db["whatsapp_logs"].count_documents({
                **_range_match("created_at", w_start, week_end),
                "direction": "inbound",
            })
            w_teams_sent = await db["teams_logs"].count_documents({
                **_range_match("created_at", w_start, week_end),
                "status": "sent",
            })
            w_gemini = await _actual_cost_inr(db, "ai_usage_logs", _range_match("created_at", w_start, week_end))
            w_storage = await _actual_cost_inr(db, "client_emails", _range_match("received_at", w_start, week_end))
            w_whatsapp = await _actual_cost_inr(db, "whatsapp_logs", _range_match("created_at", w_start, week_end))
            w_teams = await _actual_cost_inr(db, "teams_logs", _range_match("created_at", w_start, week_end))
            weekly_expenses.append({
                "key": key,
                "week": (week_lookup.get(key) or {}).get("week") or current.strftime("%d %b"),
                "whatsapp": _money(w_whatsapp),
                "teams": _money(w_teams),
                "gemini": _money(w_gemini),
                "storage": _money(w_storage),
                "total": _money(w_whatsapp + w_teams + w_gemini + w_storage),
            })
        current += timedelta(days=7)
        guard += 1

    return {
        "currency": "INR",
        "estimated": False,
        "real_only": True,
        "total": _money(total),
        "communication_total": _money(communication_total),
        "ai_total": _money(ai_total),
        "storage_total": _money(storage_total),
        "items": [
            {
                "key": "whatsapp",
                "label": "WhatsApp Communication",
                "cost": _money(whatsapp_cost),
                "count": whatsapp_outbound + whatsapp_inbound,
                "unit": "messages",
                "note": f"{whatsapp_outbound} outbound, {whatsapp_inbound} inbound, {whatsapp_failed} failed/skipped. Cost uses only real logged cost_inr.",
            },
            {
                "key": "teams",
                "label": "Teams Communication",
                "cost": _money(teams_cost),
                "count": teams_sent,
                "unit": "notifications",
                "note": f"{teams_failed} failed webhook posts. Cost uses only real logged cost_inr.",
            },
            {
                "key": "gemini",
                "label": "Gemini Text Generation",
                "cost": _money(gemini_cost),
                "count": int(actual_ai.get("calls") or 0),
                "unit": "AI calls",
                "note": f"{int(actual_ai.get('calls') or 0)} logged calls with real cost_inr, {client_processed} client emails, {client_auto_sent} auto-sent replies, {resume_gemini} resume AI parses",
            },
            {
                "key": "client_storage",
                "label": "Client Inbox Cloud Storage",
                "cost": _money(storage_cost),
                "count": client_storage_docs,
                "unit": "stored emails",
                "note": f"{round(client_storage_bytes / 1024, 1)} KB stored. Cost uses only real logged cost_inr.",
            },
        ],
        "usage": {
            "whatsapp_outbound": whatsapp_outbound,
            "whatsapp_inbound": whatsapp_inbound,
            "whatsapp_failed": whatsapp_failed,
            "teams_sent": teams_sent,
            "teams_failed": teams_failed,
            "client_processed": client_processed,
            "client_auto_sent": client_auto_sent,
            "estimated_gemini_calls": 0,
            "logged_gemini_calls": int(actual_ai.get("calls") or 0),
            "logged_input_tokens": logged_input_tokens,
            "logged_output_tokens": logged_output_tokens,
            "estimated_input_tokens": 0,
            "estimated_output_tokens": 0,
            "client_storage_bytes": client_storage_bytes,
        },
        "rates": {},
        "weekly": weekly_expenses,
    }


@router.get("/dashboard/analytics")
async def get_dashboard_analytics(
    preset: str = "month",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    db = get_db()
    start, end, preset = _dashboard_date_range(preset, start_date, end_date)
    closed_statuses = ["closed", "completed", "fulfilled", "inactive", "cancelled", "archived"]
    req_range = _range_match("created_at", start, end)

    total_requirements = await db["requirements"].count_documents(req_range)
    po_req_ids_all = await _distinct_values(db, "purchase_orders", "requirement.requirement_id", {})
    closed_req_ids_all = await _distinct_values(db, "requirements", "requirement_id", {"status": {"$in": closed_statuses}})
    closed_ids_all = po_req_ids_all | closed_req_ids_all

    open_requirements = await db["requirements"].count_documents({
        **req_range,
        "status": {"$nin": closed_statuses},
        "requirement_id": {"$nin": list(closed_ids_all)},
    })
    closed_requirements = await db["requirements"].count_documents({
        **req_range,
        "$or": [
            {"status": {"$in": closed_statuses}},
            {"requirement_id": {"$in": list(po_req_ids_all)}},
        ],
    })

    shortlisted_ids = await _distinct_values(db, "shortlists", "requirement_id", {})
    emailed_ids = await _distinct_values(db, "email_logs", "requirement_id", {})
    in_pipeline_ids = (shortlisted_ids | emailed_ids) - closed_ids_all
    in_pipeline_requirements = await db["requirements"].count_documents({
        **req_range,
        "requirement_id": {"$in": list(in_pipeline_ids)},
    })

    avg_close_docs = await db["purchase_orders"].aggregate([
        {"$addFields": {"close_date": {"$ifNull": ["$acknowledged_at", {"$ifNull": ["$sent_at", "$created_at"]}]}}},
        {"$match": {"close_date": {"$gte": start, "$lt": end}}},
        {"$lookup": {
            "from": "requirements",
            "localField": "requirement.requirement_id",
            "foreignField": "requirement_id",
            "as": "req",
        }},
        {"$unwind": "$req"},
        {"$project": {"days": {"$divide": [{"$subtract": ["$close_date", "$req.created_at"]}, 86400000]}}},
        {"$group": {"_id": None, "avg": {"$avg": "$days"}}},
    ]).to_list(1)
    avg_days_to_close = round(float(avg_close_docs[0]["avg"]), 1) if avg_close_docs else 0

    weeks = _week_axis(start, end)
    week_index = {item["key"]: item for item in weeks}
    opened_docs = await db["requirements"].aggregate([
        {"$match": req_range},
        {"$group": {
            "_id": {"year": {"$isoWeekYear": "$created_at"}, "week": {"$isoWeek": "$created_at"}},
            "count": {"$sum": 1},
        }},
    ]).to_list(100)
    for doc in opened_docs:
        key = _week_key(doc["_id"]["year"], doc["_id"]["week"])
        if key in week_index:
            week_index[key]["opened"] = doc["count"]

    closed_week_docs = await db["purchase_orders"].aggregate([
        {"$match": _range_match("created_at", start, end)},
        {"$group": {
            "_id": {"year": {"$isoWeekYear": "$created_at"}, "week": {"$isoWeek": "$created_at"}},
            "ids": {"$addToSet": "$requirement.requirement_id"},
        }},
    ]).to_list(100)
    status_closed_week_docs = await db["requirements"].aggregate([
        {"$addFields": {"close_date": {"$ifNull": ["$closed_at", {"$ifNull": ["$updated_at", "$created_at"]}]}}},
        {"$match": {"status": {"$in": closed_statuses}, "close_date": {"$gte": start, "$lt": end}}},
        {"$group": {
            "_id": {"year": {"$isoWeekYear": "$close_date"}, "week": {"$isoWeek": "$close_date"}},
            "ids": {"$addToSet": "$requirement_id"},
        }},
    ]).to_list(100)
    closed_by_week = {}
    for doc in [*closed_week_docs, *status_closed_week_docs]:
        key = _week_key(doc["_id"]["year"], doc["_id"]["week"])
        closed_by_week.setdefault(key, set()).update(i for i in doc.get("ids", []) if i)
    for key, ids in closed_by_week.items():
        if key in week_index:
            week_index[key]["closed"] = len(ids)

    now = utc_now()
    month_start = datetime.combine(now.date(), datetime.min.time()).replace(day=1)
    month_end = month_start.replace(year=month_start.year + 1, month=1) if month_start.month == 12 else month_start.replace(month=month_start.month + 1)
    po_value_docs = await db["purchase_orders"].aggregate([
        {"$match": _range_match("created_at", month_start, month_end)},
        {"$group": {
            "_id": None,
            "value": {"$sum": {"$ifNull": ["$commercials.grand_total", 0]}},
            "count": {"$sum": 1},
        }},
    ]).to_list(1)
    po_month_value = round(float(po_value_docs[0]["value"]), 2) if po_value_docs else 0
    po_month_count = int(po_value_docs[0]["count"]) if po_value_docs else 0

    funnel = [
        {"stage": "New", "value": total_requirements},
        {"stage": "Shortlisted", "value": await _distinct_count(db, "shortlists", "requirement_id", _range_match("created_at", start, end))},
        {"stage": "Contacted", "value": await _distinct_count(db, "email_logs", "requirement_id", {"status": "sent", "sent_at": {"$gte": start, "$lt": end}})},
        {"stage": "Replied", "value": await _distinct_count(db, "email_logs", "requirement_id", {
            "reply_received": True,
            "$or": [{"replied_at": {"$gte": start, "$lt": end}}, {"created_at": {"$gte": start, "$lt": end}}],
        })},
        {"stage": "Interview", "value": await _distinct_count(db, "email_logs", "requirement_id", {
            "interview_scheduled": True,
            "$or": [{"interview_email_sent_at": {"$gte": start, "$lt": end}}, {"sent_at": {"$gte": start, "$lt": end}}],
        })},
        {"stage": "Selected", "value": await _distinct_count(db, "email_logs", "requirement_id", {
            "mail_type": "mail5_ok",
            "status": "sent",
            "sent_at": {"$gte": start, "$lt": end},
        })},
        {"stage": "PO", "value": await _distinct_count(db, "purchase_orders", "requirement.requirement_id", _range_match("created_at", start, end))},
    ]

    raw_categories = await db["requirements"].aggregate([
        {"$match": req_range},
        {"$project": {"category": {"$ifNull": ["$technology_category", "$technology_needed"]}}},
        {"$group": {"_id": "$category", "value": {"$sum": 1}}},
        {"$sort": {"value": -1}},
    ]).to_list(100)
    category_totals = {}
    for item in raw_categories:
        label = _category_label(item.get("_id", ""))
        category_totals[label] = category_totals.get(label, 0) + int(item.get("value", 0))
    if not category_totals:
        trainer_categories = await db["trainers"].aggregate([
            {"$project": {"category": {"$ifNull": ["$primary_category", {"$ifNull": ["$technology_category", "$category"]}]}}},
            {"$group": {"_id": "$category", "value": {"$sum": 1}}},
            {"$sort": {"value": -1}},
            {"$limit": 8},
        ]).to_list(20)
        for item in trainer_categories:
            label = _category_label(item.get("_id", ""))
            category_totals[label] = category_totals.get(label, 0) + int(item.get("value", 0))
    category_breakdown = [
        {"name": name, "value": value}
        for name, value in sorted(category_totals.items(), key=lambda kv: kv[1], reverse=True)[:8]
    ]

    trend_start = _week_start(now - timedelta(weeks=3))
    trend_weeks = _week_axis(trend_start, now + timedelta(days=1))[-4:]
    trend_index = {item["key"]: {**item, "sent": 0, "replies": 0, "reply_rate": 0} for item in trend_weeks}
    reply_trend_docs = await db["email_logs"].aggregate([
        {"$match": {"sent_at": {"$gte": trend_start, "$lt": now + timedelta(days=1)}, "status": "sent"}},
        {"$group": {
            "_id": {"year": {"$isoWeekYear": "$sent_at"}, "week": {"$isoWeek": "$sent_at"}},
            "sent": {"$sum": 1},
            "replies": {"$sum": {"$cond": ["$reply_received", 1, 0]}},
        }},
    ]).to_list(20)
    for doc in reply_trend_docs:
        key = _week_key(doc["_id"]["year"], doc["_id"]["week"])
        if key in trend_index:
            sent = int(doc.get("sent", 0))
            replies = int(doc.get("replies", 0))
            trend_index[key].update({
                "sent": sent,
                "replies": replies,
                "reply_rate": round((replies / sent * 100) if sent else 0, 1),
            })
    reply_rate_trend = list(trend_index.values())

    whatsapp_docs = await db["whatsapp_logs"].aggregate([
        {"$match": _range_match("created_at", start, end)},
        {"$group": {
            "_id": None,
            "total": {"$sum": 1},
            "delivered": {"$sum": {"$cond": [{"$in": ["$status", ["delivered", "read"]]}, 1, 0]}},
            "sent": {"$sum": {"$cond": [{"$in": ["$status", ["sent", "queued", "delivered", "read"]]}, 1, 0]}},
            "failed": {"$sum": {"$cond": [{"$in": ["$status", ["failed", "undelivered"]]}, 1, 0]}},
        }},
    ]).to_list(1)
    whatsapp = whatsapp_docs[0] if whatsapp_docs else {"total": 0, "delivered": 0, "sent": 0, "failed": 0}
    whatsapp_total = int(whatsapp.get("total", 0))
    whatsapp_delivered = int(whatsapp.get("delivered", 0))
    whatsapp_delivery_rate = round((whatsapp_delivered / whatsapp_total * 100) if whatsapp_total else 0, 1)
    expenses = await _estimate_dashboard_expenses(db, start, end, weeks)

    return {
        "range": {"preset": preset, "start": start.isoformat(), "end": end.isoformat()},
        "status_cards": {
            "total_open": open_requirements,
            "total_closed": closed_requirements,
            "total_in_pipeline": in_pipeline_requirements,
            "average_days_to_close": avg_days_to_close,
        },
        "requirements_weekly": weeks,
        "pipeline_funnel": funnel,
        "category_breakdown": category_breakdown,
        "po_month": {"value": po_month_value, "count": po_month_count, "currency": "INR"},
        "reply_rate_trend": reply_rate_trend,
        "whatsapp": {
            "total": whatsapp_total,
            "sent": int(whatsapp.get("sent", 0)),
            "delivered": whatsapp_delivered,
            "failed": int(whatsapp.get("failed", 0)),
            "delivery_rate": whatsapp_delivery_rate,
        },
        "expenses": expenses,
    }


@router.patch("/trainers/{trainer_id}")
async def update_trainer(trainer_id: str, payload: dict):
    db = get_db()
    allowed_fields = {
        "teams_email",
        "microsoft_teams_email",
        "teams_upn",
        "email",
        "phone",
        "location",
        "linkedin",
    }
    updates = {
        key: (str(value).strip() if value is not None else "")
        for key, value in payload.items()
        if key in allowed_fields
    }
    if not updates:
        raise HTTPException(400, "No supported trainer fields provided")
    updates["updated_at"] = utc_now()
    result = await db["trainers"].find_one_and_update(
        {"trainer_id": trainer_id},
        {"$set": updates},
        projection={"_id": 0},
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise HTTPException(404, "Trainer not found")
    return {"success": True, "trainer": result}


@router.delete("/trainers/{trainer_id}")
async def delete_trainer(trainer_id: str):
    db = get_db()
    result = await db["trainers"].delete_one({"trainer_id": trainer_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Trainer not found")
    return {"message": f"Trainer {trainer_id} deleted", "deleted": True}


# ─── Send Email to Single Shortlisted Trainer ────────────────────────────────

@router.post("/emails/{email_id}/send-one")
async def send_email_to_one(email_id: str, request: Request, body: dict = {}):
    db = get_db()
    log = await db["email_logs"].find_one({"email_id": email_id})
    if not log:
        raise HTTPException(404, "Email log not found")

    email_body = log["body"]
    custom_msg = body.get("message", "")
    if custom_msg:
        email_body = f"{custom_msg}\n\n---\n{email_body}"

    smtp_config = await get_admin_email_config(db)
    trainer_phone = await _trainer_phone(db, log.get("trainer_id", ""), log.get("trainer_phone", ""))
    trainer_for_teams = await _trainer_for_direct_teams(
        db,
        log.get("trainer_id", ""),
        {
            "trainer_id": log.get("trainer_id", ""),
            "name": log.get("trainer_name", ""),
            "email": log.get("to_email", ""),
            "phone": trainer_phone,
        },
    )
    email_result, whatsapp_result, teams_direct_result = await asyncio.gather(
        send_email_async(
            log["to_email"],
            log["subject"],
            email_body,
            smtp_config,
            build_tracking_url(request, email_id),
        ),
        send_shortlist_whatsapp(
            db,
            trainer_phone=trainer_phone,
            trainer_name=log.get("trainer_name", ""),
            subject=log.get("subject", ""),
            body=email_body,
            mail_type=log.get("mail_type", ""),
            requirement_id=log.get("requirement_id", ""),
            email_id=email_id,
            request_base_url=_request_base_url(request),
        ),
        send_trainer_teams_direct_message(
            db,
            trainer=trainer_for_teams,
            subject=log.get("subject", ""),
            body=email_body,
            requirement_id=log.get("requirement_id", ""),
            mail_type=log.get("mail_type", ""),
            email_id=email_id,
        ),
    )
    success, error = email_result
    teams_result = {"status": "not_sent", "error": "email_failed"}
    if success:
        await db["email_logs"].update_one(
            {"email_id": email_id},
            {"$set": {"status": "sent", "sent_at": utc_now(), "error_message": ""},
             "$inc": {"retry_count": 1}}
        )
        requirement = await db["requirements"].find_one(
            {"requirement_id": log.get("requirement_id", "")},
            {"_id": 0},
        )
        teams_result = await send_teams_stage_notification(
            db,
            stage="pipeline_message_sent",
            trainer_name=log.get("trainer_name", ""),
            requirement=requirement or {"requirement_id": log.get("requirement_id", "")},
            request_base_url=_request_base_url(request),
            context={
                "source": "email_send_one",
                "email_id": email_id,
                "mail_type": log.get("mail_type", ""),
                "trainer_id": log.get("trainer_id", ""),
                "recipient_type": "trainer",
                "to_email": log.get("to_email", ""),
                "to_phone": trainer_phone,
                "subject": log.get("subject", ""),
                "body": email_body,
                "email_status": "sent",
                "whatsapp_status": whatsapp_result.get("status", ""),
                "teams_direct_status": teams_direct_result.get("status", ""),
            },
        )
        await db["email_logs"].update_one(
            {"email_id": email_id},
            {"$set": {"whatsapp_summary": whatsapp_result, "teams_direct_summary": teams_direct_result, "teams_summary": teams_result}},
        )
    return {"success": success, "error": error, "whatsapp": whatsapp_result, "teams_direct": teams_direct_result, "teams": teams_result}


# ─── Delete Requirement ───────────────────────────────────────────────────────

@router.delete("/requirements/{requirement_id}")
async def delete_requirement(requirement_id: str):
    db = get_db()
    r = await db["requirements"].delete_one({"requirement_id": requirement_id})
    if r.deleted_count == 0:
        raise HTTPException(404, "Requirement not found")
    await db["shortlists"].delete_many({"requirement_id": requirement_id})
    return {"message": f"Requirement {requirement_id} deleted", "deleted": True}


# ─── AI Reply Intent Analyzer ─────────────────────────────────────────────────
#
# Uses Gemini gemini-1.5-flash to accurately classify trainer reply intent.
# CRITICAL: negative phrases are matched FIRST before positive to avoid
# "not interested" being classified as positive due to "interested" substring.
#
def _keyword_intent(body: str) -> dict:
    t = body.lower().strip()
    # Negative checked FIRST — whole phrases only
    neg_phrases = [
        "not interested", "not available", "not able", "not in a position",
        "i am not", "i'm not", "i will not", "i wont", "i won't",
        "cannot", "cant", "can not", "unable", "no thanks", "no thank you",
        "decline", "declining", "unfortunately", "regret to",
        "busy", "unavailable", "withdraw", "not suitable",
        "not convenient", "pass on this", "not looking",
        "not considering", "no longer", "sorry, i",
    ]
    for phrase in neg_phrases:
        if phrase in t:
            return {"intent": "negative", "reason": f'Matched negative phrase: "{phrase}"',
                    "confidence": 0.92, "ai_used": False}

    if _question_without_commitment(t):
        return {
            "intent": "neutral",
            "reason": "Question without clear commitment",
            "confidence": 0.7,
            "ai_used": False,
        }

    # Positive only if no negative found
    pos_phrases = [
        "i am interested", "i'm interested", "i am available", "i'm available",
        "happy to", "glad to", "looking forward", "sounds good",
        "absolutely", "definitely", "please share", "will do",
        "let us proceed", "i can ", "yes, ", "sure, ",
        "confirm", "proceed", "accept", "agree to", "great opportunity",
    ]
    for phrase in pos_phrases:
        if phrase in t:
            return {"intent": "positive", "reason": f'Matched positive phrase: "{phrase}"',
                    "confidence": 0.85, "ai_used": False}

    return {"intent": "neutral", "reason": "No clear signal found", "confidence": 0.5, "ai_used": False}


@router.post("/ai/analyze-reply")
async def analyze_reply_intent(payload: dict):
    """
    Uses Gemini AI to analyze trainer reply intent accurately.
    Returns: { intent, reason, confidence, ai_used }
    """
    reply_body   = (payload.get("reply_body") or "").strip()
    trainer_name = payload.get("trainer_name", "the trainer")
    stage        = payload.get("stage", "")
    requirement  = payload.get("requirement", "")

    if not reply_body:
        return {"intent": "neutral", "reason": "Empty reply body", "confidence": 0.5, "ai_used": False}

    # Strip quoted lines (lines starting with ">") — only analyze the trainer's own words
    clean_lines = [l for l in reply_body.splitlines() if not l.strip().startswith(">")]
    clean_body  = "\n".join(clean_lines).strip() or reply_body

    # Try Gemini AI first
    try:
        import httpx as _httpx
        from config import get_settings as _get_settings
        _settings = _get_settings()
        _api_key = os.getenv("GEMINI_API_KEY", "") or getattr(_settings, "gemini_api_key", "")
        if not _api_key:
            raise ValueError("GEMINI_API_KEY not set")
        prompt = f"""You are an expert email intent classifier for a trainer recruitment platform.

Trainer "{trainer_name}" replied to our email at pipeline stage: "{stage}".
Training requirement: "{requirement}".

Their reply:
---
{clean_body[:1500]}
---

Classify intent as exactly one of:
- "positive"  : interested, available, agreeable, willing to proceed, sharing details
- "negative"  : NOT interested, NOT available, declining, withdrawing, saying no
- "neutral"   : unclear, asking question without committing, out-of-office auto-reply

CRITICAL RULES:
1. "I am not interested" = NEGATIVE always.
2. "Not available" = NEGATIVE always.
3. Polite thank-you + decline = NEGATIVE.
4. Sharing experience/details/CV = POSITIVE.
5. Confirming slot/meeting = POSITIVE.
6. Question without declining = NEUTRAL.
7. Out-of-office / auto-reply = NEUTRAL.

Respond ONLY as valid JSON:
{{"intent": "positive or negative or neutral", "reason": "one sentence", "confidence": 0.0}}"""
        _url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={_api_key}"
        import asyncio as _asyncio
        async def _call():
            async with _httpx.AsyncClient(timeout=20) as _c:
                _r = await _c.post(_url, json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0, "maxOutputTokens": 150}})
                return _r.json()
        data = _asyncio.get_event_loop().run_until_complete(_call())
        raw = (data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")).strip()
        json_match = _re.search(r'\{.*\}', raw, _re.DOTALL)
        if json_match:
            result = _json.loads(json_match.group())
            intent = result.get("intent", "neutral").lower()
            if intent not in ("positive", "negative", "neutral"):
                intent = "neutral"
            return {
                "intent":     intent,
                "reason":     result.get("reason", ""),
                "confidence": float(result.get("confidence", 0.85)),
                "ai_used":    True,
            }
    except Exception as exc:
        logger.warning("AI analyze-reply Gemini API error; falling back to keyword matching: %s", exc)

    # Fallback — deterministic keyword classifier
    return _keyword_intent(clean_body)


@router.post("/ai/log-usage")
async def log_ai_usage(payload: dict):
    db = get_db()
    rates = await _dashboard_cost_rates(db)

    input_tokens = int(_cost_number(payload.get("input_tokens"), 0))
    output_tokens = int(_cost_number(payload.get("output_tokens"), 0))
    if not input_tokens:
        input_tokens = max(1, int(len(str(payload.get("prompt") or "")) / 4))
    if not output_tokens:
        output_tokens = max(1, int(len(str(payload.get("output") or "")) / 4))

    cost_inr = (
        (input_tokens / 1000) * rates["gemini_input_1k_tokens"]
        + (output_tokens / 1000) * rates["gemini_output_1k_tokens"]
    )
    doc = {
        "usage_id": f"AI-{uuid.uuid4().hex[:10].upper()}",
        "provider": payload.get("provider") or "gemini",
        "model": payload.get("model") or get_settings().gemini_model or "gemini-1.5-flash",
        "feature": payload.get("feature") or "text_generation",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_inr": _money(cost_inr),
        "metadata": payload.get("metadata") or {},
        "created_at": utc_now(),
    }
    await db["ai_usage_logs"].insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}


@router.get("/trainers/resume-status/{upload_id}")
async def get_resume_status(upload_id: str):
    """Get the status of a resume upload."""
    db = get_db()
    upload = await db["resume_uploads"].find_one(
        {"upload_id": upload_id},
        {"_id": 0}
    )

    if not upload:
        raise HTTPException(404, "Resume upload not found")

    # Convert datetime objects to ISO strings for JSON serialization
    if isinstance(upload.get("created_at"), datetime):
        upload["created_at"] = upload["created_at"].isoformat()
    if isinstance(upload.get("processed_at"), datetime):
        upload["processed_at"] = upload["processed_at"].isoformat()

    return upload


@router.get("/trainers/by-upload/{upload_id}")
async def get_trainer_by_upload(upload_id: str):
    """Get the trainer record created from a resume upload."""
    db = get_db()
    upload = await db["resume_uploads"].find_one({"upload_id": upload_id}, {"_id": 0})
    if not upload:
        raise HTTPException(404, "Resume upload not found")

    trainer = await db["trainers"].find_one(
        {"trainer_id": upload["trainer_id"]},
        {"_id": 0}
    )

    if not trainer:
        raise HTTPException(404, "Trainer not found")

    return {
        "upload_id": upload_id,
        "trainer": trainer,
        "extraction_status": upload.get("processing_status"),
    }


@router.post("/trainers/confirm-resume/{upload_id}")
async def confirm_resume_data(upload_id: str, background_tasks: BackgroundTasks, corrections: dict = {}):
    """
    Confirm extracted resume data and optionally apply corrections.
    Updates trainer record with confirmed data.
    """
    db = get_db()
    upload = await db["resume_uploads"].find_one({"upload_id": upload_id})
    if not upload:
        raise HTTPException(404, "Resume upload not found")

    profile = _profile_from_resume_upload(upload, corrections)
    save_result = await save_trainer_from_resume(profile, db, use_ai_tags=False)
    trainer_id = save_result.get("trainer_id")
    if trainer_id:
        background_tasks.add_task(_categorise_trainers_background, [trainer_id])

    return {
        "message": "Resume data confirmed and trainer updated",
        "upload_id": upload_id,
        "trainer_id": trainer_id,
        "extracted_data": profile,
        "background_categorisation": bool(trainer_id),
        **save_result,
    }

@router.get("/resume-uploads")
async def list_resume_uploads(status: Optional[str] = None, page: int = 1, limit: int = 20):
    """List all resume uploads with pagination."""
    db = get_db()
    query = {}
    if status:
        query["processing_status"] = status

    total = await db["resume_uploads"].count_documents(query)
    skip = (page - 1) * limit

    uploads = await db["resume_uploads"].find(query, {"_id": 0, "extracted_text": 0}).sort(
        "created_at", -1
    ).skip(skip).limit(limit).to_list(limit)

    # Convert datetime objects for JSON serialization
    for upload in uploads:
        if isinstance(upload.get("created_at"), datetime):
            upload["created_at"] = upload["created_at"].isoformat()
        if isinstance(upload.get("processed_at"), datetime):
            upload["processed_at"] = upload["processed_at"].isoformat()

    return {
        "uploads": uploads,
        "total": total,
        "page": page,
        "pages": -(-total // limit),
    }


@router.delete("/resume-uploads/{upload_id}")
async def delete_resume_upload(upload_id: str):
    """Delete a resume upload and its associated trainer record if it was only created from resume."""
    db = get_db()
    upload = await db["resume_uploads"].find_one({"upload_id": upload_id})
    if not upload:
        raise HTTPException(404, "Resume upload not found")

    trainer_id = upload["trainer_id"]

    # Delete upload
    await db["resume_uploads"].delete_one({"upload_id": upload_id})

    # Delete trainer if it was only created from this resume upload
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id})
    if trainer and trainer.get("source_sheet") == "resume_upload":
        await db["trainers"].delete_one({"trainer_id": trainer_id})

    return {
        "message": f"✅ Resume upload {upload_id} deleted",
        "trainer_deleted": trainer and trainer.get("source_sheet") == "resume_upload",
    }


def _exact_email_query(email: str) -> dict:
    clean = _email_key(email)
    if not clean or "@" not in clean:
        raise HTTPException(400, "Enter a valid email address")
    return {"$regex": f"^{_re.escape(clean)}$", "$options": "i"}


async def _resume_email_matches(db, email: str) -> dict:
    email_query = _exact_email_query(email)
    trainers = await db["trainers"].find(
        {"email": email_query},
        {
            "_id": 0,
            "trainer_id": 1,
            "name": 1,
            "email": 1,
            "phone": 1,
            "technology_category": 1,
            "domain": 1,
            "created_at": 1,
        },
    ).sort("created_at", -1).to_list(50)
    trainer_ids = [item.get("trainer_id") for item in trainers if item.get("trainer_id")]
    trainer_id_query = {"$in": trainer_ids or ["__none__"]}

    upload_query = {
        "$or": [
            {"extracted_data.email": email_query},
            {"extracted_data.trainer_id": trainer_id_query},
            {"trainer_id": trainer_id_query},
        ]
    }
    uploads = await db["resume_uploads"].find(
        upload_query,
        {
            "_id": 0,
            "upload_id": 1,
            "trainer_id": 1,
            "filename": 1,
            "processing_status": 1,
            "extracted_data.email": 1,
            "extracted_data.name": 1,
            "created_at": 1,
            "processed_at": 1,
        },
    ).sort("created_at", -1).to_list(100)

    shortlist_count = await db["shortlists"].count_documents({"top_trainers.trainer_id": trainer_id_query})
    email_log_count = await db["email_logs"].count_documents({
        "$or": [
            {"trainer_id": trainer_id_query},
            {"to_email": email_query},
        ]
    })
    conversation_count = await db["conversations"].count_documents({
        "$or": [
            {"trainer_id": trainer_id_query},
            {"to_email": email_query},
        ]
    })
    return {
        "email": _email_key(email),
        "trainers": trainers,
        "uploads": uploads,
        "counts": {
            "trainers": len(trainers),
            "resume_uploads": len(uploads),
            "shortlists_with_trainer": shortlist_count,
            "email_logs": email_log_count,
            "conversations": conversation_count,
        },
        "trainer_ids": trainer_ids,
    }


@router.get("/resume-data/by-email")
async def preview_resume_data_by_email(email: str):
    db = get_db()
    return await _resume_email_matches(db, email)


@router.delete("/resume-data/by-email")
async def delete_resume_data_by_email(email: str, include_logs: bool = False):
    db = get_db()
    matches = await _resume_email_matches(db, email)
    trainer_ids = matches.get("trainer_ids") or []
    email_query = _exact_email_query(email)
    trainer_id_query = {"$in": trainer_ids or ["__none__"]}
    upload_ids = [item.get("upload_id") for item in matches.get("uploads", []) if item.get("upload_id")]

    deleted = {
        "trainers": 0,
        "resume_uploads": 0,
        "shortlist_entries_removed": 0,
        "email_logs": 0,
        "conversations": 0,
    }
    if trainer_ids:
        deleted["trainers"] = (await db["trainers"].delete_many({"trainer_id": trainer_id_query})).deleted_count
        pull_result = await db["shortlists"].update_many(
            {"top_trainers.trainer_id": trainer_id_query},
            {"$pull": {"top_trainers": {"trainer_id": trainer_id_query}}},
        )
        deleted["shortlist_entries_removed"] = pull_result.modified_count
    if upload_ids:
        deleted["resume_uploads"] = (await db["resume_uploads"].delete_many({"upload_id": {"$in": upload_ids}})).deleted_count
    else:
        deleted["resume_uploads"] = (await db["resume_uploads"].delete_many({"extracted_data.email": email_query})).deleted_count

    if include_logs:
        log_query = {
            "$or": [
                {"trainer_id": trainer_id_query},
                {"to_email": email_query},
            ]
        }
        deleted["email_logs"] = (await db["email_logs"].delete_many(log_query)).deleted_count
        deleted["conversations"] = (await db["conversations"].delete_many(log_query)).deleted_count

    return {
        "success": True,
        "email": matches["email"],
        "deleted": deleted,
        "matched": matches["counts"],
    }


def _domain_search_regex(domain: str) -> dict:
    clean = str(domain or "").strip()
    compact = _re.sub(r"[^A-Za-z0-9]+", "", clean)
    if len(compact) < 2:
        raise HTTPException(400, "Enter a domain or technology, for example Data Science or Python")
    if len(compact) <= 40:
        pattern = r"[\s_\-./]*".join(_re.escape(char) for char in compact)
    else:
        pattern = _re.escape(clean)
    return {"$regex": pattern, "$options": "i"}


def _domain_search_terms(domain: str) -> list:
    clean = str(domain or "").strip()
    compact = _re.sub(r"[^A-Za-z0-9]+", "", clean).lower()
    aliases = {
        "datascience": [
            "Data Science",
            "DataScience",
            "Machine Learning",
            "ML",
            "Deep Learning",
            "Python",
            "Pandas",
            "NumPy",
            "Scikit",
            "Statistics",
            "Predictive Analytics",
        ],
        "dataanalytics": ["Data Analytics", "Data Analyst", "Python", "SQL", "Power BI", "Tableau", "Excel"],
        "ai": ["AI", "Artificial Intelligence", "Machine Learning", "Deep Learning"],
        "genai": ["Gen AI", "Generative AI", "LLM", "RAG", "LangChain", "OpenAI"],
        "aws": ["AWS", "Amazon Web Services"],
        "azure": ["Azure", "Microsoft Azure"],
        "devops": ["DevOps", "Docker", "Kubernetes", "Jenkins", "Terraform", "CI/CD"],
    }
    terms = [clean]
    if compact and compact.lower() != clean.lower():
        terms.append(compact)
    terms.extend(aliases.get(compact, []))
    seen = set()
    return [term for term in terms if term and not (term.lower() in seen or seen.add(term.lower()))]


def _domain_search_regexes(domain: str) -> list:
    return [_domain_search_regex(term) for term in _domain_search_terms(domain)]


def _field_regex_clauses(fields: list, regexes: list) -> list:
    return [{field: regex} for field in fields for regex in regexes]


def _resume_domain_trainer_query(domain: str) -> dict:
    regexes = _domain_search_regexes(domain)
    searchable_fields = [
        "technology_category",
        "primary_category",
        "category",
        "domain",
        "technologies",
        "summary",
        "role_designation",
        "resume",
        "combined_text",
        "skills",
        "secondary_categories",
        "specialty_tags",
        "specialisation_tags",
    ]
    return {"$or": _field_regex_clauses(searchable_fields, regexes)}


def _resume_domain_upload_query(domain: str) -> dict:
    regexes = _domain_search_regexes(domain)
    searchable_fields = [
        "filename",
        "source_archive",
        "archive_path",
        "extracted_text",
        "raw_text",
        "extracted_data.technology_category",
        "extracted_data.primary_category",
        "extracted_data.category",
        "extracted_data.domain",
        "extracted_data.technologies",
        "extracted_data.summary",
        "extracted_data.role_designation",
        "extracted_data.resume",
        "extracted_data.combined_text",
        "extracted_data.skills",
        "extracted_data.secondary_categories",
        "extracted_data.specialty_tags",
        "extracted_data.specialisation_tags",
    ]
    return {"$or": _field_regex_clauses(searchable_fields, regexes)}


async def _resume_domain_matches(db, domain: str) -> dict:
    search = str(domain or "").strip()
    _domain_search_regex(search)
    exact_matches = await _resume_domain_exact_matches(db, search)
    exact_counts = exact_matches.get("counts") or {}
    if (exact_counts.get("trainers") or 0) + (exact_counts.get("resume_uploads") or 0):
        return exact_matches

    initial_uploads = await db["resume_uploads"].find(
        _resume_domain_upload_query(search),
        {"_id": 0, "upload_id": 1, "trainer_id": 1, "extracted_data.trainer_id": 1},
    ).limit(200).to_list(200)
    upload_trainer_ids = sorted({
        item.get("trainer_id") or ((item.get("extracted_data") or {}).get("trainer_id"))
        for item in initial_uploads
        if item.get("trainer_id") or ((item.get("extracted_data") or {}).get("trainer_id"))
    })

    trainer_query = {
        "$or": [
            _resume_domain_trainer_query(search),
            {"trainer_id": {"$in": upload_trainer_ids or ["__none__"]}},
        ]
    }
    trainers = await db["trainers"].find(
        trainer_query,
        {
            "_id": 0,
            "trainer_id": 1,
            "name": 1,
            "email": 1,
            "phone": 1,
            "technology_category": 1,
            "domain": 1,
            "technologies": 1,
            "skills": 1,
            "created_at": 1,
        },
    ).sort("created_at", -1).to_list(200)
    trainer_ids = sorted({item.get("trainer_id") for item in trainers if item.get("trainer_id")})
    trainer_id_query = {"$in": trainer_ids or ["__none__"]}

    uploads = await db["resume_uploads"].find(
        {
            "$or": [
                _resume_domain_upload_query(search),
                {"trainer_id": trainer_id_query},
                {"extracted_data.trainer_id": trainer_id_query},
            ]
        },
        {
            "_id": 0,
            "upload_id": 1,
            "trainer_id": 1,
            "filename": 1,
            "processing_status": 1,
            "extracted_data.email": 1,
            "extracted_data.name": 1,
            "extracted_data.technology_category": 1,
            "extracted_data.skills": 1,
            "created_at": 1,
            "processed_at": 1,
        },
    ).sort("created_at", -1).to_list(300)

    upload_ids = sorted({item.get("upload_id") for item in uploads if item.get("upload_id")})
    shortlist_count = await db["shortlists"].count_documents({"top_trainers.trainer_id": trainer_id_query})
    email_log_count = await db["email_logs"].count_documents({"trainer_id": trainer_id_query})
    conversation_count = await db["conversations"].count_documents({"trainer_id": trainer_id_query})

    return {
        "domain": search,
        "trainers": trainers,
        "uploads": uploads,
        "counts": {
            "trainers": len(trainers),
            "resume_uploads": len(uploads),
            "shortlists_with_trainer": shortlist_count,
            "email_logs": email_log_count,
            "conversations": conversation_count,
        },
        "trainer_ids": trainer_ids,
        "upload_ids": upload_ids,
    }


@router.get("/resume-data/by-domain")
async def preview_resume_data_by_domain(domain: str):
    db = get_db()
    return await _resume_domain_matches(db, domain)


@router.delete("/resume-data/by-domain")
async def delete_resume_data_by_domain(domain: str, include_logs: bool = False):
    db = get_db()
    matches = await _resume_domain_matches(db, domain)
    trainer_ids = matches.get("trainer_ids") or []
    upload_ids = matches.get("upload_ids") or []
    trainer_id_query = {"$in": trainer_ids or ["__none__"]}

    deleted = {
        "trainers": 0,
        "resume_uploads": 0,
        "shortlist_entries_removed": 0,
        "email_logs": 0,
        "conversations": 0,
    }
    if trainer_ids:
        deleted["trainers"] = (await db["trainers"].delete_many({"trainer_id": trainer_id_query})).deleted_count
        pull_result = await db["shortlists"].update_many(
            {"top_trainers.trainer_id": trainer_id_query},
            {"$pull": {"top_trainers": {"trainer_id": trainer_id_query}}},
        )
        deleted["shortlist_entries_removed"] = pull_result.modified_count
    if upload_ids:
        deleted["resume_uploads"] = (await db["resume_uploads"].delete_many({"upload_id": {"$in": upload_ids}})).deleted_count

    if include_logs and trainer_ids:
        deleted["email_logs"] = (await db["email_logs"].delete_many({"trainer_id": trainer_id_query})).deleted_count
        deleted["conversations"] = (await db["conversations"].delete_many({"trainer_id": trainer_id_query})).deleted_count

    return {
        "success": True,
        "domain": matches["domain"],
        "deleted": deleted,
        "matched": matches["counts"],
    }


def _clean_resume_domain_label(value: str) -> str:
    clean = str(value or "").strip()
    clean = _re.sub(r"^[^\w+#.]+", "", clean).strip()
    clean = _re.sub(r"\s+", " ", clean)
    return clean


def _normalise_resume_domain_label(value: str) -> str:
    clean = _clean_resume_domain_label(value)
    compact = _re.sub(r"[^a-z0-9+#.]+", "", clean.lower())
    data_science_terms = {
        "datascience",
        "machinelearning",
        "ml",
        "deeplearning",
        "python",
        "pandas",
        "numpy",
        "scikit",
        "scikitlearn",
        "sklearn",
        "statistics",
        "statisticalmodeling",
        "pytorch",
        "tensorflow",
        "r",
        "sql",
        "tableau",
        "powerbi",
    }
    if compact in data_science_terms:
        return "Data Science"
    gen_ai_terms = {"genai", "generativeai", "llm", "llmops", "rag", "langchain", "openai"}
    if compact in gen_ai_terms:
        return "Gen AI"
    return clean or "Uncategorised"


def _resume_domain_label(doc: dict) -> str:
    source = doc or {}
    for key in ("technology_category", "primary_category", "category", "domain"):
        value = _normalise_resume_domain_label(source.get(key))
        if value and value.lower() not in {"multi-skillset", "multiskillset", "uncategorised", "uncategorized", "unknown"}:
            return value
    technologies = str(source.get("technologies") or "").strip()
    if technologies:
        first = technologies.split(",")[0].strip()
        if first:
            return _normalise_resume_domain_label(first)
    skills = source.get("skills") or []
    if isinstance(skills, str):
        skills = [item.strip() for item in skills.split(",")]
    if isinstance(skills, list):
        for skill in skills:
            clean = _normalise_resume_domain_label(skill)
            if clean:
                return clean
    return "Uncategorised"


def _public_resume_domain_item(doc: dict, item_type: str) -> dict:
    extracted = doc.get("extracted_data") or {}
    def text(value) -> str:
        return "" if value is None else str(value)

    skills = doc.get("skills") or extracted.get("skills") or []
    if not isinstance(skills, list):
        skills = []

    return {
        "type": item_type,
        "trainer_id": text(doc.get("trainer_id") or extracted.get("trainer_id")),
        "upload_id": text(doc.get("upload_id")),
        "name": text(doc.get("name") or extracted.get("name")),
        "email": text(doc.get("email") or extracted.get("email")),
        "phone": text(doc.get("phone") or extracted.get("phone")),
        "filename": text(doc.get("filename")),
        "domain": _resume_domain_label(extracted or doc),
        "skills": [text(skill) for skill in skills[:6]],
        "status": text(doc.get("processing_status") or doc.get("status")),
    }


async def _resume_domain_exact_matches(db, domain: str) -> dict:
    target = _normalise_resume_domain_label(domain).lower()
    upload_docs = await db["resume_uploads"].find(
        {},
        {
            "_id": 0,
            "upload_id": 1,
            "trainer_id": 1,
            "filename": 1,
            "processing_status": 1,
            "extracted_data": 1,
            "created_at": 1,
            "processed_at": 1,
        },
    ).sort("created_at", -1).to_list(5000)
    uploads = [
        upload for upload in upload_docs
        if _resume_domain_label(upload.get("extracted_data") or {}).lower() == target
    ]
    upload_trainer_ids = {
        str(upload.get("trainer_id") or ((upload.get("extracted_data") or {}).get("trainer_id")))
        for upload in uploads
        if upload.get("trainer_id") or ((upload.get("extracted_data") or {}).get("trainer_id"))
    }
    trainer_query = {
        "$or": [
            {"source_sheet": "resume_upload"},
            {"source": "resume_upload"},
            {"trainer_id": {"$in": list(upload_trainer_ids) or ["__none__"]}},
        ]
    }
    trainer_docs = await db["trainers"].find(
        trainer_query,
        {
            "_id": 0,
            "trainer_id": 1,
            "name": 1,
            "email": 1,
            "phone": 1,
            "technology_category": 1,
            "primary_category": 1,
            "category": 1,
            "domain": 1,
            "technologies": 1,
            "skills": 1,
            "status": 1,
            "created_at": 1,
        },
    ).sort("created_at", -1).to_list(5000)
    trainers = [trainer for trainer in trainer_docs if _resume_domain_label(trainer).lower() == target]
    trainer_ids = sorted({str(item.get("trainer_id")) for item in trainers if item.get("trainer_id")})
    upload_ids = sorted({str(item.get("upload_id")) for item in uploads if item.get("upload_id")})
    trainer_id_query = {"$in": trainer_ids or ["__none__"]}
    shortlist_count = await db["shortlists"].count_documents({"top_trainers.trainer_id": trainer_id_query})
    email_log_count = await db["email_logs"].count_documents({"trainer_id": trainer_id_query})
    conversation_count = await db["conversations"].count_documents({"trainer_id": trainer_id_query})

    return {
        "domain": _normalise_resume_domain_label(domain),
        "trainers": [_public_resume_domain_item(trainer, "trainer") for trainer in trainers[:200]],
        "uploads": [_public_resume_domain_item(upload, "upload") for upload in uploads[:300]],
        "counts": {
            "trainers": len(trainers),
            "resume_uploads": len(uploads),
            "shortlists_with_trainer": shortlist_count,
            "email_logs": email_log_count,
            "conversations": conversation_count,
        },
        "trainer_ids": trainer_ids,
        "upload_ids": upload_ids,
    }


@router.get("/resume-data/domain-summary")
async def resume_data_domain_summary(limit_per_domain: int = 8):
    db = get_db()
    limit_per_domain = max(1, min(20, int(limit_per_domain or 8)))
    groups = {}

    def group_for(label: str) -> dict:
        key = label or "Uncategorised"
        if key not in groups:
            groups[key] = {
                "domain": key,
                "trainers_count": 0,
                "uploads_count": 0,
                "trainer_ids": set(),
                "upload_ids": set(),
                "trainers": [],
                "uploads": [],
            }
        return groups[key]

    upload_docs = await db["resume_uploads"].find(
        {},
        {
            "_id": 0,
            "upload_id": 1,
            "trainer_id": 1,
            "filename": 1,
            "processing_status": 1,
            "extracted_data": 1,
            "created_at": 1,
        },
    ).sort("created_at", -1).to_list(1000)
    for upload in upload_docs:
        extracted = upload.get("extracted_data") or {}
        group = group_for(_resume_domain_label(extracted))
        upload_id = upload.get("upload_id")
        if upload_id and upload_id not in group["upload_ids"]:
            group["upload_ids"].add(upload_id)
            group["uploads_count"] += 1
            if len(group["uploads"]) < limit_per_domain:
                group["uploads"].append(_public_resume_domain_item(upload, "upload"))

    trainer_ids_from_uploads = {
        upload.get("trainer_id") or ((upload.get("extracted_data") or {}).get("trainer_id"))
        for upload in upload_docs
        if upload.get("trainer_id") or ((upload.get("extracted_data") or {}).get("trainer_id"))
    }
    trainer_query = {
        "$or": [
            {"source_sheet": "resume_upload"},
            {"source": "resume_upload"},
            {"trainer_id": {"$in": list(trainer_ids_from_uploads) or ["__none__"]}},
        ]
    }
    trainer_docs = await db["trainers"].find(
        trainer_query,
        {
            "_id": 0,
            "trainer_id": 1,
            "name": 1,
            "email": 1,
            "phone": 1,
            "technology_category": 1,
            "primary_category": 1,
            "category": 1,
            "domain": 1,
            "technologies": 1,
            "skills": 1,
            "status": 1,
            "created_at": 1,
        },
    ).sort("created_at", -1).to_list(1000)
    for trainer in trainer_docs:
        group = group_for(_resume_domain_label(trainer))
        trainer_id = trainer.get("trainer_id")
        if trainer_id and trainer_id not in group["trainer_ids"]:
            group["trainer_ids"].add(trainer_id)
            group["trainers_count"] += 1
            if len(group["trainers"]) < limit_per_domain:
                group["trainers"].append(_public_resume_domain_item(trainer, "trainer"))

    domains = []
    for group in groups.values():
        group["trainer_ids"] = sorted(group["trainer_ids"])
        group["upload_ids"] = sorted(group["upload_ids"])
        group["total"] = group["trainers_count"] + group["uploads_count"]
        domains.append(group)
    domains.sort(key=lambda item: (-item["total"], item["domain"].lower()))

    return {
        "domains": domains,
        "total_domains": len(domains),
        "total_trainers": sum(item["trainers_count"] for item in domains),
        "total_uploads": sum(item["uploads_count"] for item in domains),
    }


# --- Client Inbox / Gmail Automation ---------------------------------------

@router.post("/gmail/webhook")
async def gmail_webhook(request: Request):
    db = get_db()
    try:
        payload = await request.json()
        decoded = _decode_pubsub_payload(payload)
        email_address = decoded.get("emailAddress")
        incoming_history_id = decoded.get("historyId")
        now = utc_now()

        await db["gmail_sync"].update_one(
            {"sync_id": "default"},
            {"$set": {
                "last_webhook_received_at": now,
                "last_pubsub_payload": decoded,
                "gmail_user": email_address,
            }},
            upsert=True,
        )

        if not incoming_history_id:
            return {"status": "ok", "message": "No historyId in Pub/Sub payload"}

        service = get_gmail_service()
        sync = await db["gmail_sync"].find_one({"sync_id": "default"}, {"_id": 0})
        last_history_id = (sync or {}).get("last_history_id")
        if not last_history_id:
            await db["gmail_sync"].update_one(
                {"sync_id": "default"},
                {"$set": {"last_history_id": incoming_history_id}},
                upsert=True,
            )
            return {"status": "ok", "message": "Initialized Gmail history cursor"}

        try:
            message_ids, latest_history_id = get_history_message_ids(service, last_history_id)
        except Exception as exc:
            await db["gmail_sync"].update_one(
                {"sync_id": "default"},
                {"$set": {"last_history_id": incoming_history_id, "last_error": str(exc)}},
                upsert=True,
            )
            return {"status": "ok", "message": "History cursor reset", "error": str(exc)}

        settings = await _client_inbox_settings(db)
        whitelist = _parse_domain_csv(settings.get("clientDomainsWhitelist", ""))
        processed = []
        skipped = 0

        for message_id in message_ids:
            try:
                meta = _gmail_metadata(service, message_id)
                slot_doc = await _matching_client_slot_email(db, meta)
                if slot_doc:
                    slot_result = await _process_client_slot_reply(
                        db,
                        message_id,
                        service,
                        request,
                        meta_hint=meta,
                        slot_doc=slot_doc,
                    )
                    if slot_result:
                        processed.append(slot_result)
                        continue
                decision_result = await _process_and_store_client_decision_message(
                    db,
                    message_id,
                    service,
                    request,
                    meta_hint=meta,
                )
                if decision_result:
                    processed.append(decision_result)
                    continue
                known_domain = await _known_client_domain(db, meta.get("from_email", ""))
                likely_training = known_domain or is_likely_training_email(
                    meta.get("subject", ""),
                    meta.get("from_email", ""),
                    whitelist,
                    meta.get("snippet", ""),
                )
                if not likely_training:
                    await db["client_emails"].update_one(
                        {"email_id": message_id},
                        {"$setOnInsert": {
                            **meta,
                            "received_at": now,
                            "raw_body": "",
                            "clean_body": "",
                            "extracted": {"is_training_request": False, "confidence": 0},
                            "generated_reply": {},
                            "requirement_id": None,
                            "status": "spam",
                            "confidence": 0,
                            "auto_send_eligible": False,
                            "sent_at": None,
                            "sent_by": None,
                            "whatsapp_notified": False,
                            "created_at": now,
                        }},
                        upsert=True,
                    )
                    skipped += 1
                    continue
                processed.append(await _process_and_store_client_message(db, message_id, service, request))
            except Exception as exc:
                await db["webhook_logs"].insert_one({
                    "webhook_type": "gmail_client_inbox",
                    "gmail_message_id": message_id,
                    "status": "error",
                    "error": str(exc),
                    "created_at": utc_now(),
                })

        await db["gmail_sync"].update_one(
            {"sync_id": "default"},
            {"$set": {
                "last_history_id": latest_history_id or incoming_history_id,
                "last_processed_at": utc_now(),
                "last_processed_count": len(processed),
            }},
            upsert=True,
        )
        return {"status": "ok", "processed": processed, "skipped": skipped}
    except Exception as exc:
        logger.warning("Gmail webhook error: %s", exc)
        return {"status": "ok", "error": str(exc)}


@router.post("/gmail/sync-now")
async def gmail_sync_now(request: Request, limit: int = 25):
    db = get_db()
    try:
        return await _sync_recent_client_inbox(db, request, limit)
    except Exception as exc:
        raise HTTPException(500, f"Gmail sync failed: {exc}") from exc


@router.get("/inbox")
async def get_client_inbox(status: Optional[str] = None, page: int = 1, limit: int = 20):
    db = get_db()
    query = {}
    if status and status != "all":
        query["status"] = status
    total = await db["client_emails"].count_documents(query)
    skip = (max(page, 1) - 1) * limit
    docs = await db["client_emails"].find(query, {"_id": 0}).sort("received_at", -1).skip(skip).limit(limit).to_list(limit)
    today = utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
    stats = {
        "today": await db["client_emails"].count_documents({"received_at": {"$gte": today}}),
        "pending_approval": await db["client_emails"].count_documents({"status": "pending_approval"}),
        "auto_sent": await db["client_emails"].count_documents({"status": "auto_sent"}),
        "sent": await db["client_emails"].count_documents({"status": "sent"}),
        "office_replies": await db["client_emails"].count_documents({"office_mail_category": {"$nin": [None, ""]}}),
        "requirements_created": await db["client_emails"].count_documents({"requirement_id": {"$nin": [None, ""]}}),
    }
    whatsapp_logs = await db["whatsapp_logs"].find(
        {"event_type": "client_requirement_inbox"},
        {"_id": 0},
    ).sort("created_at", -1).limit(5).to_list(5)
    return {
        "emails": [_public_doc(doc) for doc in docs],
        "total": total,
        "page": page,
        "pages": -(-total // limit) if limit else 1,
        "stats": stats,
        "whatsapp_logs": whatsapp_logs,
    }


# --- Client Lead Finder -----------------------------------------------------

LEAD_KEYWORDS = [
    "need trainer", "trainer required", "require trainer", "looking for trainer",
    "corporate trainer", "training requirement", "need corporate training",
    "freelance trainer", "technical trainer", "instructor required",
]

LEAD_DOMAINS = [
    "devops", "full stack", "aws", "azure", "python", "java", "react", "node",
    "power bi", "tableau", "data science", "machine learning", "genai",
    "kubernetes", "docker", "jenkins", "terraform", "salesforce", "sap",
    "cybersecurity", "cloud", "sql", "excel", "agile", "scrum",
]


def _lead_text(payload: dict) -> str:
    return "\n".join(str(payload.get(key) or "") for key in [
        "post_text", "description", "notes", "title", "source_url", "company_name", "contact_name",
    ])


def _analyse_client_lead(payload: dict) -> dict:
    text = _lead_text(payload)
    haystack = text.lower()
    matched = [kw for kw in LEAD_KEYWORDS if kw in haystack]
    domains = [domain for domain in LEAD_DOMAINS if domain in haystack]
    extracted_email = _extract_public_email(text)
    phone_match = _re.search(r"(?:\+?91[-\s]?)?[6-9]\d{9}", text)
    confidence = 0.25 + (0.4 if matched else 0) + (0.2 if domains else 0)
    if payload.get("contact_email") or extracted_email:
        confidence += 0.1
    if payload.get("source_url"):
        confidence += 0.05
    primary_domain = payload.get("domain") or (domains[0].title() if domains else "")
    return {
        "is_trainer_requirement_lead": bool(matched),
        "matched_keywords": matched,
        "domain": primary_domain,
        "domains_found": domains,
        "contact_email": payload.get("contact_email") or extracted_email,
        "contact_phone": payload.get("contact_phone") or (phone_match.group(0) if phone_match else ""),
        "confidence": round(min(confidence, 0.95), 2),
    }


def _client_lead_draft(lead: dict) -> dict:
    domain = lead.get("domain") or "corporate training"
    contact_name = lead.get("contact_name") or "Team"
    signature = "Best Regards,\nRecruitment Team\nClahan Technologies"
    return {
        "subject": f"Trainer Support for {domain} Requirement",
        "body": (
            f"Dear {contact_name},\n\n"
            f"We noticed your requirement related to {domain} training.\n\n"
            "Clahan Technologies can help you with suitable corporate trainers based on your duration, "
            "audience level, delivery mode, dates, and budget.\n\n"
            "Kindly let us know if the requirement is still open. Once confirmed, we can share relevant trainer profiles for your review.\n\n"
            f"{signature}"
        ),
    }


TRAINER_PROFILE_KEYWORDS = [
    "trainer", "corporate trainer", "technical trainer", "instructor", "faculty",
    "mentor", "coach", "freelance trainer", "training delivery", "conduct trainings",
    "workshop facilitator", "guest faculty", "resource person", "subject matter expert",
    "learning facilitator", "training specialist", "training consultant",
    "visiting faculty", "bootcamp instructor", "certification trainer",
    "L&D trainer", "professional trainer", "industry trainer",
]

TRAINER_PROVIDER_SIGNALS = [
    # Role titles
    "freelance trainer", "corporate trainer", "technical trainer", "trainer profile",
    "training delivery", "conduct trainings", "conducted trainings", "delivered training",
    "delivers training", "instructor", "faculty", "mentor", "coach",
    "online training", "classroom training", "corporate training experience",
    "training assignment", "training sessions",
    # Experience indicators
    "trainings conducted", "batches conducted", "batches delivered",
    "training experience", "years of training", "training engagements",
    "corporate clients", "trained professionals", "trained employees",
    "trained participants", "training hours", "hours of training",
    "sessions delivered", "workshops conducted", "workshops delivered",
    # Availability/offering signals
    "available for training", "open for training", "available for corporate",
    "accepting training", "offering training", "providing training",
    "training services", "freelance available", "available as trainer",
    "open to training opportunities", "open to freelance",
    # Certification signals (trainer-specific)
    "certified trainer", "certified instructor", "authorized trainer",
    "accredited trainer", "certified professional trainer",
    "train the trainer", "tttt certified",
    # Domain expertise with training
    "devops trainer", "python trainer", "aws trainer", "azure trainer",
    "java trainer", "sap trainer", "cloud trainer", "data science trainer",
    "full stack trainer", "react trainer", "kubernetes trainer",
    "power bi trainer", "tableau trainer", "salesforce trainer",
    "machine learning trainer", "ai trainer", "genai trainer",
    "cybersecurity trainer", "agile trainer", "scrum trainer",
    # Platform/delivery signals
    "online classes", "virtual training", "in-person training",
    "hybrid training", "self-paced", "instructor-led",
    "hands-on labs", "real-time projects", "case studies",
]

TRAINER_PROFILE_BLOCKERS = [
    # Job listing indicators
    "job vacancies", "job vacancy", "apply to", "job description",
    "required candidate profile", "hiring office", "we are hiring",
    "we are looking for", "salary", "lacs p.a", "job opening", "job role",
    # Job seeker indicators
    "current ctc", "expected ctc", "notice period", "immediate joiner",
    "last working day", "offer in hand", "open to opportunities",
    "actively exploring", "willing to relocate", "seeking opportunity",
    "looking for job", "looking for opportunities", "application for",
    "my resume", "work preference", "ready to work from office",
    # Recruitment/staffing (not trainer)
    "bench sales", "bench consultant", "hotlist", "available consultant",
    "h1b", "visa status", "work authorization", "staffing",
    "placement agency", "manpower", "temp staffing",
    # Product/company pages (not person profiles)
    "add to cart", "buy now", "subscribe now", "pricing plans",
    "terms of service", "privacy policy", "cookie policy",
    "sign up free", "free trial", "download app",
]

TRAINER_PROFILE_SOFT_BLOCKERS = [
    "institute", "academy", "pvt ltd", "private limited", "solutions",
    "technologies", "consultant", "consulting",
    "consultant1 day ago", "consultant2 days ago", "consultant3 days ago",
    "recruiter", "location ", "experience ", "yrs · consultant",
    "yrs consultant", "talent acquisition", "recruitment specialist",
    "hr manager", "hr executive", "placement officer",
]

INDIA_LOCATION_TERMS = [
    "india", "indian", "bengaluru", "bangalore", "hyderabad", "chennai", "pune",
    "mumbai", "delhi", "new delhi", "noida", "gurgaon", "gurugram", "kolkata",
    "ahmedabad", "coimbatore", "kochi", "kerala", "telangana", "karnataka",
    "tamil nadu", "maharashtra", "andhra pradesh", "uttar pradesh", "gujarat",
    "rajasthan", "madhya pradesh", "bhopal", "indore", "jaipur", "lucknow",
    "chandigarh", "bhubaneswar", "odisha", "nagpur", "mysore", "mysuru",
]


def _looks_indian_profile_text(text: str = "", source_url: str = "") -> bool:
    haystack = f"{text or ''} {source_url or ''}".lower()
    is_public_profile = (
        "linkedin.com/in/" in haystack
        or "linkedin.com/pub/" in haystack
        or "naukri.com" in haystack
    )
    return (
        is_public_profile and (
            any(term in haystack for term in INDIA_LOCATION_TERMS)
            or " in.linkedin.com/" in haystack
            or "/in/" in haystack and any(term in haystack for term in ["greater delhi", "greater bengaluru", "greater hyderabad"])
            or "naukri.com" in haystack
        )
    )


def _extract_public_email(text: str = "") -> str:
    """Extract a personal/trainer email from public text with advanced obfuscation handling.

    Handles patterns like:
      - name [at] domain [dot] com
      - name (at) domain (dot) com
      - name{at}domain{dot}com
      - name AT domain DOT com
      - name @ domain . com (spaces around @ and .)
      - Unicode fullwidth @: ＠ ﹫
      - 'email me at name at gmail dot com'
      - Parenthetical: name(at)domain(dot)com
      - Spaced: n a m e @ g m a i l . c o m
      - Reversed: moc.liamg@eman (rare but handled)
    """
    value = str(text or "")
    if not value:
        return ""

    # --- Blocklist: skip generic/system emails ---
    _EMAIL_BLOCKLIST_PATTERNS = [
        "example.com", "email.com", "domain.com", "test.com", "sample.com",
        "your-email", "yourmail", "youremail", "user@", "username@",
        "noreply", "no-reply", "no_reply", "donotreply", "do-not-reply",
        "news@", "newsletter@", "info@", "admin@", "support@", "help@",
        "sales@", "marketing@", "contact@", "feedback@", "abuse@",
        "postmaster@", "webmaster@", "root@", "system@", "mailer-daemon",
        "notifications@", "notify@", "alerts@", "bot@", "auto@",
        "linkedin.com", "facebook.com", "twitter.com", "instagram.com",
        "naukri.com", "monster.com", "indeed.com", "glassdoor.com",
        "placeholder", "dummy", "fake", "temp@", "temporary@",
    ]

    # --- Normalisation passes ---
    candidates = []

    # Pass 1: original text
    candidates.append(value)

    # Pass 2: de-obfuscate common patterns
    normalised = value
    # Handle [at] (at) {at} <at> " at " variations
    normalised = _re.sub(
        r"\s*(?:\[at\]|\(at\)|\{at\}|<at>|«at»|\bat\b)\s*",
        "@", normalised, flags=_re.I
    )
    # Handle [dot] (dot) {dot} <dot> " dot " variations
    normalised = _re.sub(
        r"\s*(?:\[dot\]|\(dot\)|\{dot\}|<dot>|«dot»|\bdot\b)\s*",
        ".", normalised, flags=_re.I
    )
    # Unicode fullwidth characters
    normalised = normalised.replace("＠", "@").replace("﹫", "@")
    normalised = normalised.replace("．", ".").replace("。", ".")
    # Handle spaces around @ and .
    normalised = _re.sub(r"\s*@\s*", "@", normalised)
    normalised = _re.sub(r"\s*\.\s*", ".", normalised)
    candidates.append(normalised)

    # Pass 3: collapse all whitespace (catches s p a c e d emails)
    compact = _re.sub(r"\s+", "", normalised)
    candidates.append(compact)

    # Pass 4: handle 'email: name at gmail dot com' spoken style
    spoken_match = _re.search(
        r"(?:email|e-mail|mail|contact)\s*[:\-]?\s*([\w.+-]+)\s+at\s+([\w.-]+)\s+dot\s+(\w{2,6})",
        value, flags=_re.I
    )
    if spoken_match:
        spoken_email = f"{spoken_match.group(1)}@{spoken_match.group(2)}.{spoken_match.group(3)}"
        candidates.append(spoken_email)

    # Pass 5: HTML entity decode and handle href mailto
    decoded = _html.unescape(value)
    mailto_match = _re.search(r"mailto:\s*([\w.+-]+@[\w.-]+\.\w{2,})", decoded, flags=_re.I)
    if mailto_match:
        candidates.insert(0, mailto_match.group(1))  # high priority
    if decoded != value:
        candidates.append(decoded)

    # --- Email regex with comprehensive TLDs ---
    tlds = (
        "com|org|net|in|co|co\\.in|edu|io|ai|dev|info|biz|me|us|uk|ca|au|sg|ae|"
        "tech|cloud|solutions|consulting|training|pro|xyz|online|site|live|"
        "outlook|hotmail|gmail|yahoo|rediffmail|"
        "gov|mil|int|museum|jobs|travel|coop|asia|eu|de|fr|jp|br|ru|cn|kr|"
        "academy|agency|company|digital|engineering|software|systems|services"
    )
    email_pattern = (
        rf"(?<![\w.+-])"
        rf"[\w.+-]{{2,80}}"
        rf"@"
        rf"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{{0,61}}[A-Za-z0-9])?\.)+(?:{tlds})"
        rf"(?=$|[^A-Za-z0-9]|\.[A-Z])"
    )

    # --- Score candidates and pick the best personal email ---
    found_emails = []
    seen_lower = set()

    for candidate in candidates:
        for match in _re.finditer(email_pattern, candidate, flags=_re.I):
            email = match.group(0).strip(".,;:()[]{}<>\"'")
            lower = email.lower()

            # Skip blocklisted
            if any(bad in lower for bad in _EMAIL_BLOCKLIST_PATTERNS):
                continue
            # Skip if already seen
            if lower in seen_lower:
                continue
            seen_lower.add(lower)

            # Score the email for likelihood of being a personal/trainer email
            score = 0
            local_part = lower.split("@")[0]
            domain_part = lower.split("@")[1] if "@" in lower else ""

            # Personal email providers get a boost
            personal_providers = ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
                                  "rediffmail.com", "protonmail.com", "icloud.com", "live.com",
                                  "ymail.com", "zoho.com", "aol.com", "mail.com"]
            if domain_part in personal_providers:
                score += 30

            # Name-like local parts (not just numbers or generic words)
            if _re.match(r"^[a-z][a-z0-9._+-]{2,}", local_part):
                score += 20
            if _re.search(r"[a-z]{3,}", local_part):
                score += 10

            # Context: is it near contact/resume/trainer words?
            email_pos = candidate.lower().find(lower)
            if email_pos >= 0:
                context_window = candidate[max(0, email_pos - 200):email_pos + len(email) + 200].lower()
                contact_words = ["email", "e-mail", "mail", "contact", "reach", "resume",
                                 "cv", "phone", "mobile", "whatsapp", "trainer", "instructor"]
                if any(word in context_window for word in contact_words):
                    score += 25

            # Penalize generic prefixes
            generic_prefixes = ["info", "admin", "support", "sales", "hr", "contact",
                                "team", "office", "careers", "jobs", "recruitment"]
            if any(local_part.startswith(prefix) for prefix in generic_prefixes):
                score -= 40

            # Penalize very short local parts
            if len(local_part) < 4:
                score -= 15

            found_emails.append((email, score))

    if not found_emails:
        return ""

    # Return the highest scoring email
    found_emails.sort(key=lambda x: x[1], reverse=True)
    return found_emails[0][0]


def _extract_contact_context_email(text: str = "") -> str:
    """Extract a trainer's personal email from text using context analysis.

    This function goes beyond simple regex matching — it uses surrounding context
    to determine if an email belongs to the trainer/person themselves (not a company
    or third-party contact). Returns empty string if the email doesn't look like a
    personal trainer contact.
    """
    value = str(text or "")
    if not value:
        return ""

    email = _extract_public_email(value)
    if not email:
        return ""

    lower = value.lower()
    email_lower = email.lower()
    email_pos = lower.find(email_lower)
    if email_pos < 0:
        return ""

    # Get a wider context window around the email
    context_start = max(0, email_pos - 300)
    context_end = min(len(lower), email_pos + len(email) + 300)
    context = lower[context_start:context_end]

    # --- Strong negative signals: definitely NOT the trainer's personal email ---
    hard_reject_markers = [
        "privacy policy", "terms of service", "terms and conditions",
        "cookie policy", "unsubscribe", "opt out", "opt-out",
        "powered by", "built with", "developed by",
        "copyright ©", "all rights reserved",
        "customer support", "customer service", "helpdesk",
        "report abuse", "spam", "phishing",
    ]
    if any(marker in context for marker in hard_reject_markers):
        return ""

    # --- Soft negative signals: likely not personal email ---
    soft_reject_markers = [
        "support@", "info@", "admin@", "sales@", "hr@", "careers@",
        "noreply", "no-reply", "do-not-reply", "donotreply",
        "team@", "contact@", "office@", "enquiry@", "enquiries@",
        "recruitment@", "jobs@", "marketing@", "billing@",
        "linkedin.com", "facebook.com", "naukri.com", "indeed.com",
    ]
    if any(marker in context for marker in soft_reject_markers):
        # But if there's also a strong positive signal, allow it
        strong_personal_signals = [
            "my email", "my mail", "reach me", "contact me", "mail me",
            "write to me", "drop me", "email me", "ping me",
        ]
        if not any(signal in context for signal in strong_personal_signals):
            return ""

    # --- Positive signals: this IS a personal/trainer contact email ---
    strong_positive_markers = [
        # Direct personal indicators
        "my email", "my mail", "my id", "my contact",
        "reach me", "contact me", "mail me", "email me",
        "write to me", "drop me a mail", "ping me",
        "get in touch", "feel free to reach",
        # Resume/CV/profile context
        "resume", "curriculum vitae", "cv", "biodata", "bio-data",
        "profile", "about me", "personal details", "personal info",
        # Trainer/professional context
        "trainer", "instructor", "faculty", "mentor", "coach",
        "freelance", "corporate trainer", "training consultant",
        "subject matter expert", "sme",
        # Contact section markers
        "contact details", "contact information", "personal details",
        "email:", "e-mail:", "mail:", "email id:", "email address:",
        "contact:", "reach:", "connect:",
        # Social/portfolio context (personal page)
        "portfolio", "personal website", "my website", "my blog",
    ]

    moderate_positive_markers = [
        # General contact words
        "email", "e-mail", "mail", "contact", "reach",
        "phone", "mobile", "whatsapp", "call",
        # Professional context
        "experience", "years", "certified", "certification",
        "skills", "expertise", "specialization",
        "training delivery", "conducted", "delivered",
        "available", "availability", "open to",
    ]

    # Score the context
    score = 0
    for marker in strong_positive_markers:
        if marker in context:
            score += 30
            break  # One strong signal is enough

    for marker in moderate_positive_markers:
        if marker in context:
            score += 10

    # Check if email local part looks like a person's name
    local_part = email_lower.split("@")[0]
    domain_part = email_lower.split("@")[1] if "@" in email_lower else ""

    # Personal email providers are a strong signal
    personal_providers = [
        "gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
        "rediffmail.com", "protonmail.com", "icloud.com", "live.com",
        "ymail.com", "zoho.com", "aol.com", "mail.com",
    ]
    if domain_part in personal_providers:
        score += 25

    # Name-like local part (letters with dots/underscores, not just numbers)
    if _re.match(r"^[a-z][a-z._-]{2,}", local_part) and _re.search(r"[a-z]{3,}", local_part):
        score += 15

    # Penalize very generic local parts
    generic_locals = ["info", "admin", "support", "contact", "office",
                      "team", "hr", "sales", "help", "service"]
    if local_part in generic_locals:
        score -= 50

    # If score is high enough, return the email
    # Threshold: at least one moderate signal or personal provider match
    if score >= 20:
        return email

    return ""


def _extract_public_phone(text: str = "") -> str:
    """Extract an Indian mobile/WhatsApp number from public profile text with high accuracy.

    Handles patterns like:
      - +91 98765 43210, +91-9876543210, 91 9876543210
      - 09876543210 (leading zero)
      - 9876543210 (bare 10-digit)
      - (+91) 98765-43210
      - WhatsApp: 9876543210
      - Call/SMS: +91 98765 43210
      - Obfuscated: 98765-432-10, 9876 543 210
      - With country code variations: 0091, +91, 91-
      - Landline Indian numbers: 040-12345678, 080 1234 5678
    """
    value = str(text or "")
    if not value:
        return ""

    # --- Blocklist patterns: skip phone numbers in wrong context ---
    _PHONE_BLOCK_CONTEXT = [
        "fax", "toll free", "1800", "1-800", "helpline", "grievance",
        "customer care", "ivr", "press 1", "ext.", "extension",
    ]

    # --- Phone number patterns (most specific to least specific) ---
    phone_patterns = [
        # +91 / 91 / 0091 followed by 10-digit mobile (starts with 6-9)
        r"(?:\+91|0091|91)[\s.\-/()]*([6-9]\d[\s.\-/()]*\d[\s.\-/()]*\d[\s.\-/()]*\d[\s.\-/()]*\d[\s.\-/()]*\d[\s.\-/()]*\d[\s.\-/()]*\d[\s.\-/()]*\d)",
        # Leading 0 + 10-digit mobile
        r"(?<!\d)0([6-9]\d{9})(?!\d)",
        # Bare 10-digit Indian mobile with separators
        r"(?<!\d)([6-9]\d[\s.\-/]*\d[\s.\-/]*\d[\s.\-/]*\d[\s.\-/]*\d[\s.\-/]*\d[\s.\-/]*\d[\s.\-/]*\d[\s.\-/]*\d)(?!\d)",
        # WhatsApp/Call/Mobile/Phone label followed by number
        r"(?:whatsapp|wa|call|mobile|mob|phone|ph|cell|contact|reach\s*(?:me|us)?)\s*[:\-#.]*\s*(?:\+?91[\s.\-/()]*)?([6-9]\d[\s.\-/()]*\d[\s.\-/()]*\d[\s.\-/()]*\d[\s.\-/()]*\d[\s.\-/()]*\d[\s.\-/()]*\d[\s.\-/()]*\d[\s.\-/()]*\d)",
    ]

    found_phones = []
    seen_numbers = set()

    for pattern in phone_patterns:
        for match in _re.finditer(pattern, value, flags=_re.I):
            # Extract the captured group (the 10-digit part)
            raw = match.group(1) if match.lastindex else match.group(0)
            # Strip all non-digit characters
            digits = _re.sub(r"\D", "", raw)

            # Ensure we have exactly 10 digits starting with 6-9
            if len(digits) == 10 and digits[0] in "6789":
                if digits in seen_numbers:
                    continue
                seen_numbers.add(digits)

                # Check context for blocklisted patterns
                start = max(0, match.start() - 80)
                end = min(len(value), match.end() + 80)
                context = value[start:end].lower()
                if any(block in context for block in _PHONE_BLOCK_CONTEXT):
                    continue

                # Score: prefer numbers near contact/trainer context
                score = 0
                contact_words = ["whatsapp", "wa", "mobile", "mob", "phone", "ph",
                                 "cell", "call", "contact", "reach", "trainer",
                                 "resume", "cv", "profile", "personal"]
                if any(word in context for word in contact_words):
                    score += 30

                # Prefer numbers with country code prefix
                full_match_text = match.group(0).lower()
                if "+91" in full_match_text or "0091" in full_match_text or full_match_text.startswith("91"):
                    score += 20

                # Penalize numbers that look like IDs or years
                preceding = value[max(0, match.start() - 10):match.start()].lower()
                if any(word in preceding for word in ["id", "reg", "ref", "order", "pin", "zip", "code", "otp", "aadhaar", "pan"]):
                    score -= 50

                found_phones.append((digits, score))

            elif len(digits) == 11 and digits[0] == "0" and digits[1] in "6789":
                # Leading zero variant
                clean = digits[1:]
                if clean in seen_numbers:
                    continue
                seen_numbers.add(clean)
                found_phones.append((clean, 5))

            elif len(digits) == 12 and digits[:2] == "91" and digits[2] in "6789":
                # 91 prefix without +
                clean = digits[2:]
                if clean in seen_numbers:
                    continue
                seen_numbers.add(clean)
                found_phones.append((clean, 15))

    if not found_phones:
        return ""

    # Return the highest-scored phone number
    found_phones.sort(key=lambda x: x[1], reverse=True)
    return found_phones[0][0]


def _public_resume_urls(text: str = "", base_url: str = "") -> list[str]:
    value = _html.unescape(str(text or ""))
    urls = set()
    for match in _re.finditer(r"https?://[^\s\"'<>)]+", value, flags=_re.I):
        urls.add(match.group(0).rstrip(".,;:)]}"))
    for match in _re.finditer(r"href=[\"']([^\"']+)[\"']", value, flags=_re.I):
        href = match.group(1).strip()
        if href:
            urls.add(_urljoin(base_url or "", href))
    wanted = []
    for url in urls:
        lower = url.lower()
        if not lower.startswith(("http://", "https://")):
            continue
        if any(skip in lower for skip in ["linkedin.com/login", "linkedin.com/signup", "linkedin.com/company", "mailto:", "tel:"]):
            continue
        if (
            any(lower.split("?")[0].endswith(ext) for ext in [".pdf", ".docx", ".doc"])
            or any(word in lower for word in ["resume", "curriculum-vitae", "/cv", "cv."])
        ):
            wanted.append(url)
    return wanted[:3]


def _text_from_public_document_bytes(data: bytes, content_type: str = "", url: str = "") -> str:
    lower_url = str(url or "").lower()
    lower_type = str(content_type or "").lower()
    try:
        if ".pdf" in lower_url or "pdf" in lower_type:
            doc = fitz.open(stream=data, filetype="pdf")
            return "\n".join(page.get_text("text") for page in doc[:6])[:25000]
        if ".docx" in lower_url or "wordprocessingml" in lower_type:
            document = _DocxDocument(io.BytesIO(data))
            return "\n".join(paragraph.text for paragraph in document.paragraphs)[:25000]
        if any(kind in lower_type for kind in ["text/plain", "text/html"]) or lower_url.endswith((".txt", ".html", ".htm")):
            text = data[:500000].decode("utf-8", errors="ignore")
            return _re.sub(r"<[^>]+>", " ", text)[:25000]
    except Exception:
        return ""
    return ""


async def _extract_public_resume_contact(client, public_text: str = "", source_url: str = "", timeout: int = 25) -> dict:
    for resume_url in _public_resume_urls(public_text, source_url):
        try:
            response = await client.get(resume_url, follow_redirects=True, timeout=timeout)
            response.raise_for_status()
            content = response.content[:6_000_000]
            extracted_text = _text_from_public_document_bytes(
                content,
                response.headers.get("content-type", ""),
                str(response.url or resume_url),
            )
            email = _extract_public_email(extracted_text)
            phone_match = _re.search(r"(?:\+?91[-\s]?)?[6-9]\d{9}", extracted_text or "")
            if email or phone_match:
                return {
                    "url": str(response.url or resume_url),
                    "text": extracted_text,
                    "email": email,
                    "phone": phone_match.group(0) if phone_match else "",
                }
        except Exception:
            continue
    return {}


def _public_contact_urls(text: str = "", base_url: str = "") -> list[str]:
    value = _html.unescape(str(text or ""))
    urls = set()
    for match in _re.finditer(r"https?://[^\s\"'<>)]+", value, flags=_re.I):
        urls.add(match.group(0).rstrip(".,;:)]}"))
    for match in _re.finditer(r"href=[\"']([^\"']+)[\"']", value, flags=_re.I):
        href = match.group(1).strip()
        if href:
            urls.add(_urljoin(base_url or "", href))
    blocked = [
        "linkedin.com", "licdn.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
        "youtube.com", "google.com", "github.com", "static.", "media.", "mailto:", "tel:",
    ]
    wanted = []
    for url in urls:
        lower = url.lower()
        if not lower.startswith(("http://", "https://")):
            continue
        if any(item in lower for item in blocked):
            continue
        if any(token in lower for token in ["portfolio", "resume", "curriculum-vitae", "/cv", "cv.", "contact", "about"]):
            wanted.append(url)
    return wanted[:4]


async def _extract_public_website_contact(client, public_text: str = "", source_url: str = "", timeout: int = 25) -> dict:
    for website_url in _public_contact_urls(public_text, source_url):
        try:
            response = await client.get(website_url, follow_redirects=True, timeout=timeout)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            text = _text_from_public_document_bytes(response.content[:1_000_000], content_type, str(response.url or website_url))
            if not text:
                text = response.text[:500000]
            email = _extract_contact_context_email(text)
            phone = _extract_public_phone(text)
            if email or phone:
                return {
                    "url": str(response.url or website_url),
                    "text": text[:25000],
                    "email": email,
                    "phone": phone,
                }
        except Exception:
            continue
    return {}


def _analyse_trainer_profile_lead(payload: dict) -> dict:
    """Analyse a public LinkedIn/Naukri profile to determine if it's a trainer.

    Uses multi-signal scoring with:
    - Provider signals (explicit trainer role/experience mentions)
    - Domain expertise signals
    - India location detection
    - Contact information availability
    - Blocker detection (job seekers, recruiters, companies)
    - Contextual confidence calibration
    """
    text = _lead_text(payload)
    haystack = text.lower()

    # --- Signal detection ---
    matched = [kw for kw in TRAINER_PROFILE_KEYWORDS if kw in haystack]
    provider_signals = [kw for kw in TRAINER_PROVIDER_SIGNALS if kw in haystack]
    blockers = [kw for kw in TRAINER_PROFILE_BLOCKERS if kw in haystack]
    soft_blockers = [kw for kw in TRAINER_PROFILE_SOFT_BLOCKERS if kw in haystack]
    domains = [domain for domain in LEAD_DOMAINS if domain in haystack]
    extracted_email = _extract_public_email(text)
    extracted_phone = _extract_public_phone(text)
    indian_profile = _looks_indian_profile_text(text, payload.get("source_url") or "")
    source_url = str(payload.get("source_url") or "").lower()
    is_public_linkedin_profile = "linkedin.com/in" in source_url or "linkedin.com/pub" in source_url
    is_naukri_profile = "naukri.com" in source_url

    # --- Advanced trainer detection logic ---

    # Check for years of experience mentions
    experience_match = _re.search(
        r"(\d{1,2})\+?\s*(?:years?|yrs?)[\s.]*(?:of\s+)?(?:training|teaching|instructing|coaching)",
        haystack
    )
    has_training_experience = bool(experience_match)
    experience_years = int(experience_match.group(1)) if experience_match else 0

    # Check for number of trainings/batches conducted
    batches_match = _re.search(
        r"(\d+)\+?\s*(?:trainings?|batches?|sessions?|workshops?)\s*(?:conducted|delivered|completed)",
        haystack
    )
    has_batch_count = bool(batches_match)

    # Check for client names (indicates active trainer)
    client_indicators = _re.findall(
        r"(?:trained\s+(?:at|for)|clients?\s*(?:include|:)|worked\s+with)\s*[:\-]?\s*([A-Z][A-Za-z\s,&]+)",
        text
    )
    has_client_mentions = bool(client_indicators)

    # Check for certification count
    cert_patterns = _re.findall(
        r"(?:certified|certification|certificate)\s+(?:in\s+)?[\w\s]+",
        haystack
    )
    cert_count = len(cert_patterns)

    # --- Confidence scoring (multi-factor) ---
    confidence = 0.30  # Base

    # Provider signals: strongest indicator
    signal_count = len(provider_signals)
    if signal_count >= 5:
        confidence += 0.25
    elif signal_count >= 3:
        confidence += 0.18
    elif signal_count >= 1:
        confidence += 0.10

    # Domain expertise
    domain_count = len(domains)
    if domain_count >= 3:
        confidence += 0.12
    elif domain_count >= 1:
        confidence += 0.07

    # India location
    if indian_profile:
        confidence += 0.08

    # LinkedIn/Naukri profile URL
    if is_public_linkedin_profile:
        confidence += 0.07
    elif is_naukri_profile:
        confidence += 0.05

    # Keyword matches
    if len(matched) >= 3:
        confidence += 0.08
    elif matched:
        confidence += 0.04

    # Contact information (shows transparency/accessibility)
    if payload.get("contact_email") or extracted_email:
        confidence += 0.08
    if payload.get("contact_phone") or extracted_phone:
        confidence += 0.05

    # Training experience years (strong signal)
    if experience_years >= 10:
        confidence += 0.12
    elif experience_years >= 5:
        confidence += 0.08
    elif has_training_experience:
        confidence += 0.05

    # Batch/training count
    if has_batch_count:
        confidence += 0.06

    # Client mentions
    if has_client_mentions:
        confidence += 0.06

    # Certifications
    if cert_count >= 3:
        confidence += 0.06
    elif cert_count >= 1:
        confidence += 0.03

    # --- Negative adjustments ---
    if blockers:
        # Hard blockers significantly reduce confidence
        blocker_penalty = min(len(blockers), 4) * 0.12
        confidence -= blocker_penalty
    elif soft_blockers:
        # Soft blockers only penalize if there's not strong trainer evidence
        if not is_public_linkedin_profile and signal_count < 2:
            confidence -= min(len(soft_blockers), 3) * 0.06
        elif signal_count < 4:
            confidence -= min(len(soft_blockers), 2) * 0.03

    # --- Determine if this is a trainer profile lead ---
    # More nuanced decision: not just "has provider signals and no blockers"
    is_trainer_lead = False

    if blockers:
        # Even with blockers, if overwhelming positive evidence exists, consider it
        if signal_count >= 5 and has_training_experience and confidence > 0.55:
            is_trainer_lead = True
    elif signal_count >= 1:
        is_trainer_lead = True
    elif has_training_experience and (matched or domains):
        is_trainer_lead = True
    elif is_public_linkedin_profile and len(matched) >= 2 and domains:
        # LinkedIn profile with multiple trainer keywords + domain match
        is_trainer_lead = True

    # Build candidate reason
    reasons = []
    if provider_signals:
        reasons.append(f"trainer signals: {', '.join(provider_signals[:3])}")
    if has_training_experience:
        reasons.append(f"{experience_years}+ years training experience")
    if has_batch_count:
        reasons.append("quantified training delivery")
    if has_client_mentions:
        reasons.append("corporate client mentions")
    if domains:
        reasons.append(f"domain expertise: {', '.join(domains[:3])}")
    candidate_reason = "; ".join(reasons) if reasons else ""

    primary_domain = payload.get("domain") or (domains[0].title() if domains else "")

    return {
        "is_trainer_profile_lead": is_trainer_lead,
        "matched_keywords": matched,
        "provider_signals": provider_signals,
        "blocked_keywords": blockers,
        "soft_blocked_keywords": soft_blockers,
        "domain": primary_domain,
        "domains_found": domains,
        "contact_email": payload.get("contact_email") or extracted_email,
        "contact_phone": payload.get("contact_phone") or extracted_phone,
        "indian_profile": indian_profile,
        "confidence": round(max(0.0, min(confidence, 0.98)), 2),
        "candidate_reason": candidate_reason,
        "training_experience_years": experience_years,
        "has_batch_count": has_batch_count,
        "has_client_mentions": has_client_mentions,
        "certification_count": cert_count,
    }


def _searched_domain_from_query(query: str = "") -> str:
    quoted = _re.findall(r'"([^"]+)"', str(query or ""))
    for item in quoted:
        text = str(item or "").strip()
        if text and text.lower() not in {
            "trainer", "corporate trainer", "certified", "consultant", "training",
            "india", "need trainer", "seeking trainer", "looking for trainer",
            "trainer required", "certified trainer required", "corporate trainer required",
            "trainer requirement", "corporate training",
        }:
            return text
    return ""


def _trainer_intent_query(query: str = "") -> bool:
    text = str(query or "").lower()
    return any(term in text for term in [
        "trainer", "instructor", "mentor", "coach", "faculty", "sme trainer",
        "training consultant", "corporate facilitator", "workshop facilitator",
        "subject matter expert",
    ])


def _public_search_domain_aliases(domain: str = "") -> list[str]:
    clean = _re.sub(
        r"\b(trainer|training|jobs?|job|online|corporate|technical|faculty|instructor)\b",
        " ",
        str(domain or "").lower(),
    )
    compact = _re.sub(r"[^a-z0-9]", "", clean)
    aliases = {clean.strip(), compact}
    if "devops" in compact:
        aliases.add("devops")
    if "python" in compact:
        aliases.add("python")
    if "aws" in compact:
        aliases.add("aws")
    if "fullstack" in compact:
        aliases.add("fullstack")
    if "s4hana" in compact or "sap" in compact:
        aliases.update({"sap", "s4hana", "saps4hana"})
    if "apisix" in compact or "apacheapisix" in compact:
        aliases.update({"apisix", "apacheapisix"})
    return [item for item in aliases if item]


def _public_search_text_matches_domain(title: str = "", source_url: str = "", domain: str = "", content: str = "") -> bool:
    if not domain:
        return True
    haystack = f"{title or ''} {source_url or ''} {content or ''}".lower()
    compact_haystack = _re.sub(r"[^a-z0-9]", "", haystack)
    for alias in _public_search_domain_aliases(domain):
        alias_compact = _re.sub(r"[^a-z0-9]", "", alias)
        if alias_compact and (alias_compact in compact_haystack or alias in haystack):
            return True
    return False


def _is_public_naukri_trainer_profile_result(title: str = "", source_url: str = "", content: str = "") -> bool:
    text = f"{title or ''} {source_url or ''} {content or ''}".lower()
    url = str(source_url or "").lower()
    has_email = bool(_extract_public_email(text))
    has_phone = bool(_re.search(r"(?:\+91[\s-]?)?[6-9]\d{9}\b", text))

    employer_url_tokens = [
        "job-listings", "jobs-in", "job-vacancies", "vacancies", "apply-to",
        "jobs-careers", "jobs?", "/jobs", "-jobs-", "-job-", "page-", "trainer-jobs",
        "jobdetail", "job-detail", "jobsearch", "job-search",
    ]
    employer_text_tokens = [
        " job ", " jobs ", "job vacancies", "job vacancy", "apply to", "job description", "required candidate profile",
        "hiring office", "we are hiring", "we are looking for", "salary", "lacs p.a",
        "vacancies", "candidate profile", "job opening", "job role", "current ctc",
        "expected ctc", "notice period", "immediate joiner", "last working day",
        "offer in hand", "actively exploring", "open to opportunities", "willing to relocate",
        "application for", "my resume", "ready to work from office", "work preference",
        "institute", "academy", "pvt ltd", "private limited", "solutions", "technologies",
        "consultant", "consulting", "consultant1 day ago", "consultant2 days ago", "consultant3 days ago", "recruiter",
        "location ", "experience ", "yrs · consultant", "yrs consultant",
    ]
    trainer_profile_tokens = [
        "trainer profile", "freelance trainer", "corporate trainer", "technical trainer",
        "training delivery", "conduct trainings", "conducted trainings", "delivered training",
        "curriculum vitae", " cv ", "contact no",
        "contact:", "email id", "email:",
    ]

    if any(token in url for token in employer_url_tokens):
        return False
    if any(token in text for token in employer_text_tokens):
        return False
    return any(token in f" {text} " for token in trainer_profile_tokens) and (has_email or has_phone or "linkedin.com/in" in text)


@router.get("/client-leads")
async def list_client_leads(status: Optional[str] = None, q: Optional[str] = None, limit: int = 100):
    db = get_db()
    query = {}
    if status and status != "all":
        query["status"] = status
    if q:
        pattern = {"$regex": _re.escape(q.strip()), "$options": "i"}
        query["$or"] = [
            {"company_name": pattern}, {"contact_name": pattern}, {"domain": pattern},
            {"source": pattern}, {"post_text": pattern}, {"source_url": pattern},
        ]
    limit = max(10, min(int(limit or 100), 300))
    leads = await db["client_leads"].find(query, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    stats = {
        "total": await db["client_leads"].count_documents({}),
        "new": await db["client_leads"].count_documents({"status": "new"}),
        "reviewed": await db["client_leads"].count_documents({"status": "reviewed"}),
        "contacted": await db["client_leads"].count_documents({"status": "contacted"}),
        "converted": await db["client_leads"].count_documents({"status": "converted"}),
        "rejected": await db["client_leads"].count_documents({"status": "rejected"}),
    }
    card_docs = []
    for doc in leads:
        item = _public_doc(doc)
        if item.get("post_text"):
            item["post_text"] = str(item.get("post_text") or "")[:2500]
        draft = item.get("draft")
        if isinstance(draft, dict) and draft.get("body"):
            item["draft"] = {**draft, "body": str(draft.get("body") or "")[:2500]}
        card_docs.append(item)
    return {"success": True, "leads": card_docs, "stats": stats}


@router.post("/client-leads/analyze")
async def analyze_client_lead(payload: dict):
    analysis = _analyse_client_lead(payload)
    return {"success": True, "analysis": analysis, "draft": _client_lead_draft({**payload, **analysis})}


@router.post("/client-leads")
async def create_client_lead(payload: dict):
    db = get_db()
    analysis = _analyse_client_lead(payload)
    now = utc_now()
    lead_id = payload.get("lead_id") or f"LEAD-{uuid.uuid4().hex[:8].upper()}"
    source_url = str(payload.get("source_url") or "").strip()
    if source_url:
        existing = await db["client_leads"].find_one({"source_url": source_url}, {"_id": 0, "lead_id": 1})
        if existing:
            raise HTTPException(409, {"message": "Lead already exists for this source URL", "lead_id": existing.get("lead_id")})
    lead = {
        "lead_id": lead_id,
        "source": payload.get("source") or "Manual",
        "source_url": source_url,
        "company_name": payload.get("company_name") or "",
        "contact_name": payload.get("contact_name") or "",
        "contact_email": analysis.get("contact_email") or "",
        "contact_phone": analysis.get("contact_phone") or "",
        "domain": analysis.get("domain") or "",
        "post_text": payload.get("post_text") or payload.get("description") or "",
        "notes": payload.get("notes") or "",
        "status": payload.get("status") or "new",
        "confidence": analysis.get("confidence"),
        "is_trainer_requirement_lead": analysis.get("is_trainer_requirement_lead"),
        "matched_keywords": analysis.get("matched_keywords"),
        "domains_found": analysis.get("domains_found"),
        "draft": _client_lead_draft({**payload, **analysis}),
        "created_at": now,
        "updated_at": now,
    }
    await db["client_leads"].insert_one(lead)
    return {"success": True, "lead": _public_doc(lead)}


@router.post("/client-leads/search-public")
async def search_public_client_leads(payload: dict = {}):
    import httpx as _httpx

    api_key = (
        os.getenv("TAVILY_API_KEY", "")
        or getattr(get_settings(), "tavily_api_key", "")
    ).strip()
    if not api_key:
        raise HTTPException(
            400,
            {
                "message": "TAVILY_API_KEY is not set. Public lead search requires a Tavily API key.",
                "required_env": "TAVILY_API_KEY",
                "how_to_fix": [
                    "1. Go to https://app.tavily.com and sign up (free)",
                    "2. Copy your API key from the dashboard",
                    "3. Add TAVILY_API_KEY=tvly-your-key to backend/.env",
                    "4. Restart the backend server",
                ],
                "free_plan": "1000 searches/month — enough for daily lead searches",
            },
        )

    db = get_db()
    auto_discover = bool(payload.get("auto_discover"))

    # ── CREDIT-SAFE domain list ───────────────────────────────────────────────
    # Only IT/Technical domains that Clahan actually places trainers for.
    # Non-IT domains (Excel, Soft Skills, Communication) are excluded by default
    # because they waste credits and return low-quality leads.
    # Pass "domains" in payload to override this list.
    DEFAULT_IT_DOMAINS = [
        "DevOps", "AWS", "Azure", "Python", "Java", "SAP",
        "Data Science", "Machine Learning", "AI", "GenAI",
        "Full Stack", "React", "Data Engineering", "Cloud",
        "Cyber Security", "Power BI",
    ]

    # Non-IT domains — only included if caller explicitly requests them
    NON_IT_DOMAINS = [
        "Excel", "Soft Skills", "Leadership", "Communication",
        "Behavioural", "Sales Training",
    ]

    if payload.get("domains"):
        # Caller specified domains — use those
        domains = [str(d).strip() for d in payload["domains"] if str(d).strip()]
    elif payload.get("include_non_it"):
        # Explicitly requested non-IT too
        domains = DEFAULT_IT_DOMAINS + NON_IT_DOMAINS
    else:
        # Default: IT only — saves credits
        domains = DEFAULT_IT_DOMAINS

    # Hard cap: max 6 domains per run to stay within free credit limit
    max_domains = min(int(payload.get("max_domains") or 4), 6)
    domains = domains[:max_domains]

    max_results = max(1, min(int(payload.get("max_results") or 3), 5))

    saved = []
    skipped = []
    queries = []

    # ── CREDIT-SAFE phrase list ───────────────────────────────────────────────
    # Use only the most effective high-signal phrases.
    # Fewer phrases × fewer domains = fewer credits used.
    HIGH_SIGNAL_PHRASES = [
        "Corporate Trainer Required",
        "Technical Training Requirement",
        "Need Technical Trainer",
        "Trainer Required",
        "Subject Matter Expert Trainer Required",
        "Looking for Corporate Trainer",
    ]

    # Full phrase list — only used when caller requests deep search
    ALL_PHRASES = [
        "Need Trainer",
        "Seeking Trainer",
        "Looking for Trainer",
        "Trainer Required",
        "Corporate Trainer Required",
        "Hiring Trainer",
        "Hiring Corporate Trainer",
        "Immediate Requirement for Trainer",
        "Trainer Vacancy",
        "Trainer Opening",
        "Trainer Position Available",
        "Corporate Training Requirement",
        "Looking for Corporate Trainer",
        "Need Technical Trainer",
        "Need Soft Skills Trainer",
        "Need Python Trainer",
        "Need AI Trainer",
        "Need Data Analytics Trainer",
        "Need Power BI Trainer",
        "Need Excel Trainer",
        "Need Communication Skills Trainer",
        "Freelance Trainer Required",
        "Contract Trainer Required",
        "Part-Time Trainer Required",
        "Online Trainer Required",
        "Offline Trainer Required",
        "Guest Faculty Required",
        "Resource Person Required",
        "Workshop Trainer Required",
        "Faculty Required for Training",
        "Learning and Development Trainer Required",
        "L&D Trainer Hiring",
        "Training Consultant Required",
        "Training Specialist Required",
        "Corporate Learning Trainer",
        "Employee Training Facilitator Required",
        "Technical Training Requirement",
        "Corporate Workshop Facilitator Required",
        "Instructor Required",
        "Subject Matter Expert Trainer Required",
        "Training Program Facilitator Required",
        "Campus Trainer Required",
        "College Trainer Required",
        "Industrial Trainer Required",
        "Professional Trainer Required",
        "Leadership Trainer Required",
        "Behavioral Skills Trainer Required",
        "Corporate Coach Required",
        "Business Trainer Required",
    ]

    # Use high-signal phrases by default (saves credits)
    # Use all phrases only if deep_search=true in payload
    client_requirement_phrases = (
        ALL_PHRASES if payload.get("deep_search") else HIGH_SIGNAL_PHRASES
    )

    if auto_discover:
        for phrase in client_requirement_phrases[:3]:   # limit auto-discover too
            queries.append(f'site:linkedin.com/posts "{phrase}"')

    for domain in domains:
        for phrase in client_requirement_phrases[:3]:   # max 3 phrases per domain
            queries.append(f'site:linkedin.com/posts "{phrase}" "{domain}"')
        queries.append(f'site:linkedin.com/company "{domain}" "trainer required"')

    queries = list(dict.fromkeys(queries))

    # ── HARD CAP on queries to protect credits ────────────────────────────────
    # Default: max 8 queries per run = max 8 × 3 = 24 Tavily calls
    # deep_search: max 18 queries
    max_queries_default = 18 if payload.get("deep_search") else 8
    max_queries = min(int(payload.get("max_queries") or max_queries_default), 18)
    queries = queries[:max_queries]

    search_timeout = 45
    # Reduce concurrency — fewer parallel calls = more controlled credit usage
    search_concurrency = max(1, min(int(payload.get("concurrency") or 3), 6))
    async with _httpx.AsyncClient(timeout=search_timeout) as client:
        semaphore = asyncio.Semaphore(search_concurrency)

        async def _run_public_trainer_query(query: str):
            async with semaphore:
                try:
                    response = await client.post(
                        "https://api.tavily.com/search",
                        json={
                            "api_key": api_key,
                            "query": query,
                            "search_depth": "basic",
                            "max_results": max_results,
                            "include_answer": False,
                            "include_raw_content": True,
                        },
                    )
                    response.raise_for_status()
                    return query, response.json(), None
                except _httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code if exc.response is not None else "unknown"
                    detail = (exc.response.text or exc.response.reason_phrase or "").strip() if exc.response is not None else ""
                    return query, None, f"Tavily search failed ({status_code}): {detail[:300]}"
                except Exception as exc:
                    return query, None, str(exc)

        query_results = await asyncio.gather(*[_run_public_trainer_query(query) for query in queries])
        failed_query_count = 0

        for query, data, error in query_results:
            if error:
                failed_query_count += 1
                skipped.append({"query": query, "reason": error})
                continue
            try:
                results = data.get("results") or []
            except Exception as exc:
                skipped.append({"query": query, "reason": str(exc)})
                continue

            for result in results:
                searched_domain = _searched_domain_from_query(query)
                source_url = str(result.get("url") or "").strip()
                if not source_url:
                    continue
                existing = await db["client_leads"].find_one({"source_url": source_url}, {"_id": 0, "lead_id": 1})
                if existing:
                    skipped.append({"url": source_url, "reason": "duplicate", "lead_id": existing.get("lead_id")})
                    continue
                title = str(result.get("title") or "")
                content = str(result.get("content") or result.get("snippet") or "")
                raw_content = str(result.get("raw_content") or "")
                image_url = str(result.get("image") or result.get("favicon") or "").strip()
                public_text = f"{title}\n\n{content}\n\n{raw_content}".strip()
                resume_contact = await _extract_public_resume_contact(client, public_text, source_url)
                if resume_contact.get("text"):
                    public_text = f"{public_text}\n\nPublic linked resume/document:\n{resume_contact['text']}".strip()
                website_contact = await _extract_public_website_contact(client, public_text, source_url)
                if website_contact.get("text"):
                    public_text = f"{public_text}\n\nPublic linked website/portfolio:\n{website_contact['text']}".strip()
                lead_payload = {
                    "source": "Public Web Search",
                    "source_url": source_url,
                    "company_name": "",
                    "contact_name": title[:120],
                    "post_text": public_text,
                    "notes": f"Found by public lead search query: {query}",
                }
                analysis = _analyse_client_lead(lead_payload)
                if resume_contact.get("email"):
                    analysis["contact_email"] = resume_contact["email"]
                if website_contact.get("email"):
                    analysis["contact_email"] = website_contact["email"]
                if resume_contact.get("phone") and not analysis.get("contact_phone"):
                    analysis["contact_phone"] = resume_contact["phone"]
                if website_contact.get("phone") and not analysis.get("contact_phone"):
                    analysis["contact_phone"] = website_contact["phone"]
                if not analysis.get("is_trainer_requirement_lead") and analysis.get("confidence", 0) < 0.65:
                    skipped.append({"url": source_url, "reason": "low confidence", "confidence": analysis.get("confidence")})
                    continue
                now = utc_now()
                lead = {
                    "lead_id": f"LEAD-{uuid.uuid4().hex[:8].upper()}",
                    "source": lead_payload["source"],
                    "source_url": source_url,
                    "company_name": "",
                    "contact_name": lead_payload["contact_name"],
                    "contact_email": analysis.get("contact_email") or "",
                    "contact_phone": analysis.get("contact_phone") or "",
                    "domain": searched_domain or analysis.get("domain") or "",
                    "searched_domain": searched_domain,
                    "post_text": lead_payload["post_text"],
                    "notes": lead_payload["notes"],
                    "public_resume_url": resume_contact.get("url", ""),
                    "public_website_url": website_contact.get("url", ""),
                    "status": "new",
                    "confidence": analysis.get("confidence"),
                    "is_trainer_requirement_lead": analysis.get("is_trainer_requirement_lead"),
                    "matched_keywords": analysis.get("matched_keywords"),
                    "domains_found": analysis.get("domains_found"),
                    "draft": _client_lead_draft({**lead_payload, **analysis}),
                    "created_at": now,
                    "updated_at": now,
                }
                await db["client_leads"].insert_one(lead)
                saved.append(_public_doc(lead))

    return {
        "success": True,
        "saved_count": len(saved),
        "skipped_count": len(skipped),
        "failed_query_count": failed_query_count,
        "search_error": (
            skipped[0].get("reason")
            if failed_query_count == len(queries) and not saved and skipped
            else ""
        ),
        "queries": queries,
        "saved": saved,
        "skipped": skipped[:50],
    }


@router.post("/client-leads/auto-discover-now")
async def auto_discover_client_leads_now():
    return await search_public_client_leads({
        "auto_discover": True,
        "max_results": 8,
        "max_queries": 180,
        "concurrency": 4,
    })


@router.get("/trainer-profile-leads")
async def list_trainer_profile_leads(
    status: Optional[str] = None,
    q: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 100,
    compact: bool = False,
    include_stats: bool = True,
):
    db = get_db()
    query = {}
    if status and status != "all":
        query["status"] = status
    source_filter = str(source or "").strip().lower()
    if source_filter == "naukri":
        query["source"] = "Naukri Public Search"
    elif source_filter == "linkedin":
        query["source"] = {"$regex": "linkedin", "$options": "i"}
    if q:
        pattern = {"$regex": _re.escape(q.strip()), "$options": "i"}
        query["$or"] = [
            {"trainer_name": pattern}, {"domain": pattern}, {"source": pattern},
            {"headline": pattern}, {"profile_text": pattern}, {"source_url": pattern},
        ]
    limit = max(10, min(int(limit or 100), 300))
    projection = {"_id": 0}
    if compact:
        projection = {
            "_id": 0,
            "lead_id": 1,
            "source": 1,
            "source_url": 1,
            "trainer_name": 1,
            "contact_email": 1,
            "contact_phone": 1,
            "domain": 1,
            "searched_domain": 1,
            "headline": 1,
            "profile_text": 1,
            "notes": 1,
            "public_resume_url": 1,
            "public_website_url": 1,
            "status": 1,
            "confidence": 1,
            "contact_trust": 1,
            "verification_tier": 1,
            "verification_status": 1,
            "verified_trainer_id": 1,
            "linkedin_lead_verified": 1,
            "created_at": 1,
        }
    leads = await db["trainer_profile_leads"].find(query, projection).sort("created_at", -1).limit(limit).to_list(limit)
    if compact:
        for lead in leads:
            text = str(lead.get("profile_text") or "")
            if len(text) > 3000:
                lead["profile_text"] = text[:3000] + "..."
    stats = {}
    if include_stats:
        stats_query = {"source": query["source"]} if query.get("source") else {}
        stats = {
            "total": await db["trainer_profile_leads"].count_documents(stats_query),
            "new": await db["trainer_profile_leads"].count_documents({**stats_query, "status": "new"}),
            "reviewed": await db["trainer_profile_leads"].count_documents({**stats_query, "status": "reviewed"}),
            "contacted": await db["trainer_profile_leads"].count_documents({**stats_query, "status": "contacted"}),
            "converted": await db["trainer_profile_leads"].count_documents({**stats_query, "status": "converted"}),
            "rejected": await db["trainer_profile_leads"].count_documents({**stats_query, "status": "rejected"}),
        }
    return {"success": True, "leads": [_enrich_lead_response(doc) for doc in leads], "stats": stats}


@router.post("/trainer-profile-leads/search-public")
async def search_public_trainer_profile_leads(payload: dict = {}):
    import httpx as _httpx

    api_key = (
        os.getenv("TAVILY_API_KEY", "")
        or getattr(get_settings(), "tavily_api_key", "")
    ).strip()
    if not api_key:
        raise HTTPException(
            400,
            {
                "message": "TAVILY_API_KEY is required for automatic public trainer profile search.",
                "required_env": "TAVILY_API_KEY",
                "setup": "Create a Tavily API key and add it to backend/.env, then restart backend.",
            },
        )

    db = get_db()
    domains = payload.get("domains") or ["SAP S/4HANA", "Apache APISIX", "DevOps", "AWS", "Python"]
    domains = [str(item).strip() for item in domains if str(item).strip()][:12]
    source_mode = str(payload.get("source") or payload.get("source_mode") or "linkedin").strip().lower()
    deep_enrich = bool(payload.get("deep_enrich", source_mode not in {"naukri"}))
    max_results = max(1, min(int(payload.get("max_results") or 5), 10))
    saved = []
    skipped = []
    queries = []
    LOCATIONS = [
        "Hyderabad", "Warangal", "Karimnagar", "Nizamabad",
        "Visakhapatnam", "Vijayawada", "Guntur", "Tirupati", "Amaravati",
        "Bangalore", "Mumbai", "Pune", "Delhi", "Chennai", "Noida",
        "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
        "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand",
        "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
        "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab",
        "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
        "Uttar Pradesh", "Uttarakhand", "West Bengal",
    ]
    TRAINER_SEARCH_ROLES = [
        "trainer",
        "corporate trainer",
        "freelance trainer",
        "certified trainer",
        "instructor",
        "training consultant",
        "SME trainer",
        "mentor",
        "trainer India",
        "technical trainer",
        "soft skills trainer",
        "professional trainer",
        "guest faculty",
        "resource person",
        "workshop facilitator",
        "learning facilitator",
        "corporate facilitator",
        "training specialist",
        "training manager",
        "training lead",
        "subject matter expert",
        "coach",
        "industry trainer",
        "visiting faculty",
        "online trainer",
        "offline trainer",
        "virtual trainer",
        "contract trainer",
        "part-time trainer",
        "L&D trainer",
        "learning and development specialist",
        "curriculum trainer",
        "education consultant",
        "instructional trainer",
        "corporate coach",
        "professional coach",
        "skills trainer",
        "technical instructor",
        "faculty trainer",
        "bootcamp instructor",
        "workshop trainer",
        "seminar speaker",
        "keynote trainer",
        "training provider",
        "training partner",
        "industry expert",
        "practitioner trainer",
        "certification trainer",
        "apprenticeship trainer",
        "academic trainer",
        "college trainer",
    ]
    for domain in domains:
        if source_mode in {"linkedin", "both", "all"}:
            for role in TRAINER_SEARCH_ROLES:
                queries.append(f'site:linkedin.com/in "{domain}" "{role}"')
            queries.extend([
                f'site:linkedin.com/in "{domain}" "certified" "trainer" India',
                f'site:linkedin.com/in "{domain}" "experienced" "trainer" India',
                f'site:linkedin.com/in "{domain}" "years experience" "trainer" India',
            ])
            for location in LOCATIONS:
                queries.append(f'site:linkedin.com/in "{domain}" trainer "{location}"')
        if source_mode in {"naukri", "both", "all"}:
            queries.extend([
                f'site:naukri.com "{domain}" "trainer profile" "India" -jobs -vacancies',
                f'site:naukri.com "{domain}" "freelance trainer" "resume" -jobs -vacancies',
                f'site:naukri.com "{domain}" "corporate trainer" "resume" -jobs -vacancies',
                f'site:naukri.com "{domain}" "trainer" "email" "India" -jobs -vacancies',
                f'site:naukri.com "{domain}" "trainer" "contact" "India" -jobs -vacancies',
            ])
    queries = list(dict.fromkeys(queries))
    queries = queries[: int(payload.get("max_queries") or 60)]

    search_timeout = 30 if source_mode == "naukri" else 45
    search_concurrency = max(1, min(int(payload.get("concurrency") or 6), 10))
    async with _httpx.AsyncClient(timeout=search_timeout) as client:
        semaphore = asyncio.Semaphore(search_concurrency)

        async def _run_public_trainer_query(query: str):
            async with semaphore:
                try:
                    response = await client.post(
                        "https://api.tavily.com/search",
                        json={
                            "api_key": api_key,
                            "query": query,
                            "search_depth": "basic",
                            "max_results": max_results,
                            "include_answer": False,
                            "include_raw_content": True,
                        },
                    )
                    response.raise_for_status()
                    return query, response.json(), None
                except _httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code if exc.response is not None else "unknown"
                    detail = (exc.response.text or exc.response.reason_phrase or "").strip() if exc.response is not None else ""
                    return query, None, f"Tavily search failed ({status_code}): {detail[:300]}"
                except Exception as exc:
                    return query, None, str(exc)

        query_results = await asyncio.gather(*[_run_public_trainer_query(query) for query in queries])
        failed_query_count = 0

        for query, data, error in query_results:
            if error:
                failed_query_count += 1
                skipped.append({"query": query, "reason": error})
                continue
            try:
                results = data.get("results") or []
            except Exception as exc:
                skipped.append({"query": query, "reason": str(exc)})
                continue

            for result in results:
                searched_domain = _searched_domain_from_query(query)
                source_url = str(result.get("url") or "").strip()
                if not source_url:
                    continue
                source_lower = source_url.lower()
                is_linkedin_result = "linkedin.com/in" in source_lower or "linkedin.com/pub" in source_lower
                is_naukri_result = "naukri.com" in source_lower
                if source_mode == "naukri" and not is_naukri_result:
                    skipped.append({"url": source_url, "reason": "not a public Naukri result"})
                    continue
                if source_mode not in {"naukri"} and not (is_linkedin_result or (source_mode in {"both", "all"} and is_naukri_result)):
                    skipped.append({"url": source_url, "reason": "not a supported public trainer result"})
                    continue
                title = str(result.get("title") or "")
                content = str(result.get("content") or result.get("snippet") or "")
                raw_content = str(result.get("raw_content") or "")
                full_result_text = f"{content}\n{raw_content}"
                if is_naukri_result and not _is_public_naukri_trainer_profile_result(title, source_url, full_result_text):
                    skipped.append({
                        "url": source_url,
                        "reason": "Naukri employer/job listing skipped",
                        "title": title[:120],
                    })
                    continue
                if not _public_search_text_matches_domain(title, source_url, searched_domain, f"{content}\n{raw_content}"):
                    skipped.append({
                        "url": source_url,
                        "reason": "result does not match searched domain skill",
                        "searched_domain": searched_domain,
                        "title": title[:120],
                    })
                    continue
                image_url = str(result.get("image") or result.get("favicon") or "").strip()
                public_text = f"{title}\n\n{content}\n\n{raw_content}".strip()
                resume_contact = await _extract_public_resume_contact(client, public_text, source_url) if deep_enrich else {}
                if resume_contact.get("text"):
                    public_text = f"{public_text}\n\nPublic linked resume/document:\n{resume_contact['text']}".strip()
                website_contact = await _extract_public_website_contact(client, public_text, source_url) if deep_enrich else {}
                if website_contact.get("text"):
                    public_text = f"{public_text}\n\nPublic linked website/portfolio:\n{website_contact['text']}".strip()
                phone_from_text = _extract_public_phone(public_text)
                email_from_text = _extract_contact_context_email(public_text)
                lead_payload = {
                    "source": "Naukri Public Search" if is_naukri_result else "Public LinkedIn Search",
                    "source_url": source_url,
                    "trainer_name": title[:120],
                    "post_text": public_text,
                    "description": public_text,
                    "notes": f"Found by public trainer profile search query: {query}",
                }
                analysis = _analyse_trainer_profile_lead(lead_payload)
                if resume_contact.get("email"):
                    analysis["contact_email"] = resume_contact["email"]
                if website_contact.get("email"):
                    analysis["contact_email"] = website_contact["email"]
                if resume_contact.get("phone") and not analysis.get("contact_phone"):
                    analysis["contact_phone"] = resume_contact["phone"]
                if website_contact.get("phone") and not analysis.get("contact_phone"):
                    analysis["contact_phone"] = website_contact["phone"]
                if (
                    is_linkedin_result
                    and _trainer_intent_query(query)
                    and not analysis.get("blocked_keywords")
                    and not analysis.get("is_trainer_profile_lead")
                ):
                    analysis["is_trainer_profile_lead"] = True
                    analysis["provider_signals"] = [
                        *(analysis.get("provider_signals") or []),
                        "trainer search query",
                    ]
                    analysis["confidence"] = max(float(analysis.get("confidence") or 0), 0.62)
                    analysis["candidate_reason"] = "LinkedIn profile matched the searched skill and trainer-intent query."
                if is_linkedin_result and not analysis.get("indian_profile"):
                    analysis["indian_profile"] = True
                    analysis["india_inferred_from_query"] = True
                contact_email = analysis.get("contact_email") or email_from_text or ""
                contact_phone = analysis.get("contact_phone") or phone_from_text or ""
                dup_lead_id = await _is_duplicate_linkedin_lead(
                    db,
                    source_url=source_url,
                    contact_email=contact_email,
                    trainer_name=lead_payload["trainer_name"],
                )
                if dup_lead_id:
                    skipped.append({"url": source_url, "reason": "duplicate_email_or_url", "lead_id": dup_lead_id})
                    continue
                if not analysis.get("indian_profile"):
                    skipped.append({"url": source_url, "reason": "outside India or India location not visible"})
                    continue
                if not analysis.get("is_trainer_profile_lead"):
                    skipped.append({
                        "url": source_url,
                        "reason": "not a trainer provider profile",
                        "confidence": analysis.get("confidence"),
                        "blocked_keywords": analysis.get("blocked_keywords") or [],
                    })
                    continue
                now = utc_now()
                lead = {
                    "lead_id": f"TPL-{uuid.uuid4().hex[:8].upper()}",
                    "source": lead_payload["source"],
                    "source_url": source_url,
                    "trainer_name": lead_payload["trainer_name"],
                    "contact_email": contact_email,
                    "contact_phone": contact_phone,
                    "domain": searched_domain or analysis.get("domain") or "",
                    "searched_domain": searched_domain,
                    "headline": title,
                    "profile_image": image_url,
                    "profile_text": lead_payload["post_text"],
                    "notes": lead_payload["notes"],
                    "public_resume_url": resume_contact.get("url", ""),
                    "public_website_url": website_contact.get("url", ""),
                    "status": "new",
                    "confidence": analysis.get("confidence"),
                    "indian_profile": analysis.get("indian_profile"),
                    "india_inferred_from_query": bool(analysis.get("india_inferred_from_query")),
                    "is_trainer_profile_lead": analysis.get("is_trainer_profile_lead"),
                    "candidate_reason": analysis.get("candidate_reason", ""),
                    "provider_signals": analysis.get("provider_signals") or [],
                    "matched_keywords": analysis.get("matched_keywords"),
                    "domains_found": analysis.get("domains_found"),
                    "created_at": now,
                    "updated_at": now,
                }
                _stamp_linkedin_signal_on_enriched(
                    lead,
                    email=lead.get("contact_email", ""),
                    phone=lead.get("contact_phone", ""),
                    name=lead.get("trainer_name", ""),
                    linkedin=lead.get("source_url", ""),
                )
                await db["trainer_profile_leads"].insert_one(lead)
                try:
                    lead["trainer_save"] = await _save_linkedin_lead_as_trainer(db, lead)
                    lead["verified_trainer_id"] = lead["trainer_save"].get("trainer_id", "")
                    lead["verification_status"] = "placeholder_created" if lead["trainer_save"].get("action") == "inserted" else "linked_to_trainer"
                except Exception as exc:
                    lead["trainer_save"] = {"saved": False, "error": str(exc)}
                saved.append(_enrich_lead_response(lead))
                pav_urls = _re.findall(r"https?://in\.linkedin\.com/in/[a-zA-Z0-9_-]+", public_text or "")
                pav_urls += _re.findall(r"https?://www\.linkedin\.com/in/[a-zA-Z0-9_-]+", public_text or "")
                pav_urls = list(dict.fromkeys(pav_urls))[:8]

                for pav_url in pav_urls:
                    if pav_url == source_url:
                        continue
                    pav_dup_lead_id = await _is_duplicate_linkedin_lead(db, pav_url)
                    if pav_dup_lead_id:
                        continue
                    try:
                        pav_resp = await client.get(pav_url, follow_redirects=True, timeout=15)
                        pav_resp.raise_for_status()
                        pav_text = f"{pav_resp.text[:300000]}"
                        pav_phone = _extract_public_phone(pav_text)
                        pav_email = _extract_contact_context_email(pav_text)
                        pav_payload = {
                            "source_url": pav_url,
                            "post_text": pav_text[:8000],
                            "description": pav_text[:8000],
                        }
                        pav_analysis = _analyse_trainer_profile_lead(pav_payload)
                        if not pav_analysis.get("is_trainer_profile_lead"):
                            continue
                        pav_lead = {
                            "lead_id": f"TPL-{uuid.uuid4().hex[:8].upper()}",
                            "source": "Public LinkedIn Search (PAV)",
                            "source_url": pav_url,
                            "trainer_name": pav_url.split("/in/")[-1].replace("-", " ").title()[:80],
                            "contact_email": pav_email or "",
                            "contact_phone": pav_phone or "",
                            "domain": searched_domain or analysis.get("domain") or "",
                            "searched_domain": searched_domain,
                            "headline": "",
                            "profile_text": pav_text[:8000],
                            "notes": f"Found via People Also Viewed from {source_url}",
                            "status": "new",
                            "confidence": pav_analysis.get("confidence", 0.7),
                            "is_trainer_profile_lead": True,
                            "created_at": utc_now(),
                            "updated_at": utc_now(),
                        }
                        _stamp_linkedin_signal_on_enriched(
                            pav_lead,
                            email=pav_lead.get("contact_email", ""),
                            phone=pav_lead.get("contact_phone", ""),
                            name=pav_lead.get("trainer_name", ""),
                            linkedin=pav_lead.get("source_url", ""),
                        )
                        await db["trainer_profile_leads"].insert_one(pav_lead)
                        try:
                            pav_lead["trainer_save"] = await _save_linkedin_lead_as_trainer(db, pav_lead)
                            pav_lead["verified_trainer_id"] = pav_lead["trainer_save"].get("trainer_id", "")
                            pav_lead["verification_status"] = "placeholder_created" if pav_lead["trainer_save"].get("action") == "inserted" else "linked_to_trainer"
                        except Exception as exc:
                            pav_lead["trainer_save"] = {"saved": False, "error": str(exc)}
                        saved.append(_enrich_lead_response(pav_lead))
                    except Exception:
                        continue

    return {
        "success": True,
        "saved_count": len(saved),
        "skipped_count": len(skipped),
        "failed_query_count": failed_query_count,
        "search_error": (
            skipped[0].get("reason")
            if failed_query_count == len(queries) and not saved and skipped
            else ""
        ),
        "queries": queries,
        "saved": saved,
        "skipped": skipped[:50],
    }


@router.post("/trainer-profile-leads/expand-from-profiles")
async def expand_trainer_profile_leads_from_profiles(payload: dict = {}):
    import httpx as _httpx

    db = get_db()
    profile_urls = [
        str(url or "").strip()
        for url in (payload.get("profile_urls") or [])
        if str(url or "").strip()
    ]
    profile_urls = list(dict.fromkeys(profile_urls))[:30]
    if not profile_urls:
        raise HTTPException(400, "At least one LinkedIn profile URL is required")

    domain = str(payload.get("domain") or "").strip()
    limit_per_profile = max(1, min(int(payload.get("limit_per_profile") or 8), 12))
    saved = []
    skipped = []

    async with _httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for source_url in profile_urls:
            if "linkedin.com/in" not in source_url.lower():
                skipped.append({"url": source_url, "reason": "not a LinkedIn profile URL"})
                continue
            try:
                response = await client.get(source_url)
                response.raise_for_status()
                source_text = response.text[:300000]
            except Exception as exc:
                skipped.append({"url": source_url, "reason": str(exc)})
                continue

            pav_urls = _re.findall(r"https?://in\.linkedin\.com/in/[a-zA-Z0-9_-]+", source_text or "")
            pav_urls += _re.findall(r"https?://www\.linkedin\.com/in/[a-zA-Z0-9_-]+", source_text or "")
            pav_urls = [
                url for url in list(dict.fromkeys(pav_urls))
                if url.rstrip("/") != source_url.rstrip("/")
            ][:limit_per_profile]

            if not pav_urls:
                skipped.append({"url": source_url, "reason": "no related LinkedIn profiles found"})
                continue

            for pav_url in pav_urls:
                duplicate_id = await _is_duplicate_linkedin_lead(db, pav_url)
                if duplicate_id:
                    skipped.append({"url": pav_url, "reason": "duplicate", "lead_id": duplicate_id})
                    continue
                try:
                    pav_resp = await client.get(pav_url)
                    pav_resp.raise_for_status()
                    pav_text = pav_resp.text[:300000]
                except Exception as exc:
                    skipped.append({"url": pav_url, "reason": str(exc)})
                    continue

                pav_payload = {
                    "source_url": pav_url,
                    "post_text": pav_text[:8000],
                    "description": pav_text[:8000],
                    "domain": domain,
                }
                pav_analysis = _analyse_trainer_profile_lead(pav_payload)
                if domain and not _public_search_text_matches_domain("", pav_url, domain, pav_text):
                    skipped.append({"url": pav_url, "reason": "result does not match selected domain"})
                    continue
                if not pav_analysis.get("indian_profile"):
                    skipped.append({"url": pav_url, "reason": "outside India or India location not visible"})
                    continue
                if not pav_analysis.get("is_trainer_profile_lead"):
                    skipped.append({
                        "url": pav_url,
                        "reason": "not a trainer provider profile",
                        "confidence": pav_analysis.get("confidence"),
                    })
                    continue

                pav_lead = {
                    "lead_id": f"TPL-{uuid.uuid4().hex[:8].upper()}",
                    "source": "Public LinkedIn Search (Expanded)",
                    "source_url": pav_url,
                    "trainer_name": pav_url.split("/in/")[-1].replace("-", " ").title()[:80],
                    "contact_email": _extract_contact_context_email(pav_text) or "",
                    "contact_phone": _extract_public_phone(pav_text) or "",
                    "domain": domain or pav_analysis.get("domain") or "",
                    "searched_domain": domain,
                    "headline": "",
                    "profile_text": pav_text[:8000],
                    "notes": f"Found via People Also Viewed from {source_url}",
                    "status": "new",
                    "confidence": pav_analysis.get("confidence", 0.7),
                    "indian_profile": pav_analysis.get("indian_profile"),
                    "is_trainer_profile_lead": True,
                    "matched_keywords": pav_analysis.get("matched_keywords"),
                    "domains_found": pav_analysis.get("domains_found"),
                    "created_at": utc_now(),
                    "updated_at": utc_now(),
                }
                _stamp_linkedin_signal_on_enriched(
                    pav_lead,
                    email=pav_lead.get("contact_email", ""),
                    phone=pav_lead.get("contact_phone", ""),
                    name=pav_lead.get("trainer_name", ""),
                    linkedin=pav_lead.get("source_url", ""),
                )
                await db["trainer_profile_leads"].insert_one(pav_lead)
                try:
                    pav_lead["trainer_save"] = await _save_linkedin_lead_as_trainer(db, pav_lead)
                    pav_lead["verified_trainer_id"] = pav_lead["trainer_save"].get("trainer_id", "")
                    pav_lead["verification_status"] = "placeholder_created" if pav_lead["trainer_save"].get("action") == "inserted" else "linked_to_trainer"
                except Exception as exc:
                    pav_lead["trainer_save"] = {"saved": False, "error": str(exc)}
                saved.append(_enrich_lead_response(pav_lead))

    return {
        "success": True,
        "checked": len(profile_urls),
        "saved_count": len(saved),
        "skipped_count": len(skipped),
        "saved": saved,
        "skipped": skipped[:50],
    }


@router.post("/trainer-profile-leads/enrich-public-emails")
async def enrich_trainer_profile_public_emails(payload: dict = {}):
    import httpx as _httpx

    db = get_db()
    query = {
        "$or": [{"contact_email": {"$exists": False}}, {"contact_email": ""}, {"contact_email": None}],
        "status": {"$nin": ["rejected", "contacted"]},
    }
    domain = str(payload.get("domain") or "").strip()
    if domain:
        pattern = {"$regex": _re.escape(domain), "$options": "i"}
        query["$and"] = [{
            "$or": [{"domain": pattern}, {"searched_domain": pattern}, {"profile_text": pattern}, {"headline": pattern}]
        }]
    source_filter = str(payload.get("source") or payload.get("source_mode") or "").strip().lower()
    if source_filter == "naukri":
        query["source"] = {"$regex": "naukri", "$options": "i"}
    elif source_filter == "linkedin":
        query["source"] = {"$regex": "linkedin", "$options": "i"}
    limit = max(1, min(int(payload.get("limit") or (40 if source_filter == "naukri" else 75)), 200))
    docs = await db["trainer_profile_leads"].find(query, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    enriched = []
    skipped = []
    request_timeout = 4 if source_filter == "naukri" else 40
    linked_timeout = 4 if source_filter == "naukri" else 25
    deep_link_scan = bool(payload.get("deep_link_scan", source_filter != "naukri"))
    fetch_source_page = bool(payload.get("fetch_source_page", source_filter != "naukri"))
    async with _httpx.AsyncClient(timeout=request_timeout) as client:
        for lead in docs:
            lead_id = lead.get("lead_id")
            public_text = "\n".join(str(lead.get(key) or "") for key in ["headline", "profile_text", "notes", "source_url"])
            email = _extract_public_email(public_text)
            phone = lead.get("contact_phone") or ""
            resume_url = lead.get("public_resume_url") or ""
            website_url = lead.get("public_website_url") or ""
            source_page_text = ""
            if not email and fetch_source_page and source_filter == "naukri" and lead.get("source_url"):
                try:
                    response = await client.get(lead.get("source_url"), follow_redirects=True, timeout=request_timeout)
                    response.raise_for_status()
                    source_page_text = _re.sub(r"<[^>]+>", " ", response.text[:750000])
                    email = _extract_public_email(source_page_text)
                    phone_match = _re.search(r"(?:\+?91[-\s]?)?[6-9]\d{9}", source_page_text or "")
                    phone = phone or (phone_match.group(0) if phone_match else "")
                    public_text = f"{public_text}\n\n{source_page_text[:50000]}"
                except Exception:
                    pass
            if not email and deep_link_scan:
                resume_contact = await _extract_public_resume_contact(client, public_text, lead.get("source_url") or "", timeout=linked_timeout)
                email = resume_contact.get("email") or ""
                phone = phone or resume_contact.get("phone") or ""
                resume_url = resume_url or resume_contact.get("url") or ""
            if not email and deep_link_scan:
                website_contact = await _extract_public_website_contact(client, public_text, lead.get("source_url") or "", timeout=linked_timeout)
                email = website_contact.get("email") or ""
                phone = phone or website_contact.get("phone") or ""
                website_url = website_url or website_contact.get("url") or ""
            if not email:
                skipped.append({"lead_id": lead_id, "trainer_name": lead.get("trainer_name"), "reason": "no public email found"})
                continue
            update = {
                "contact_email": email,
                "contact_phone": phone,
                "public_resume_url": resume_url,
                "public_website_url": website_url,
                "email_source": "public_profile_or_linked_website",
                "updated_at": utc_now(),
            }
            update = _stamp_linkedin_signal_on_enriched(
                update,
                email=email,
                phone=phone,
                name=lead.get("trainer_name") or lead.get("headline") or "",
                linkedin=lead.get("source_url") or "",
            )
            await db["trainer_profile_leads"].update_one({"lead_id": lead_id}, {"$set": update})
            enriched.append({**lead, **update})
    return {"success": True, "checked": len(docs), "enriched_count": len(enriched), "enriched": [_enrich_lead_response(item) for item in enriched], "skipped": skipped[:50]}


_MAIL_MATCH_STOPWORDS = {
    "trainer", "training", "jobs", "job", "online", "corporate", "technical", "faculty",
    "instructor", "naukri", "linkedin", "public", "search", "profile", "india", "remote",
    "years", "experience", "opening", "vacancies", "vacancy", "june", "page", "apply",
    "devops", "python", "aws", "azure", "cloud", "sap", "full", "stack", "java",
    "bangalore", "bengaluru", "mumbai", "pune", "delhi", "noida", "hyderabad", "chennai",
    "kolkata", "gurgaon", "gurugram", "remote", "areas", "all", "technology", "software",
    "solutions", "institute", "school", "course", "courses",
}


def _lead_match_terms_for_mail_lookup(lead: dict) -> list[str]:
    text = " ".join(str(lead.get(key) or "") for key in ["trainer_name", "headline", "domain", "searched_domain"])
    terms = []
    for item in _re.findall(r"[a-zA-Z][a-zA-Z0-9+#./-]{2,}", text.lower()):
        clean = item.strip(" .,/+-_")
        if len(clean) < 4 or clean in _MAIL_MATCH_STOPWORDS:
            continue
        if clean not in terms:
            terms.append(clean)
    return terms[:12]


def _mail_lookup_text(doc: dict) -> str:
    extracted = doc.get("extracted") or doc.get("extracted_data") or {}
    return "\n".join([
        str(doc.get("from_name") or ""),
        str(doc.get("from_email") or ""),
        str(doc.get("subject") or ""),
        str(doc.get("snippet") or ""),
        str(doc.get("clean_body") or ""),
        str(doc.get("raw_body") or ""),
        str(doc.get("body") or ""),
        str(extracted),
    ])


def _mail_lookup_score(lead: dict, text: str, terms: list[str]) -> tuple[int, int]:
    haystack = str(text or "").lower()
    score = 0
    domain_aliases = _public_search_domain_aliases(lead.get("domain") or lead.get("searched_domain") or "")
    if any(alias and alias in haystack for alias in domain_aliases):
        score += 2
    matched_terms = [term for term in terms if term in haystack]
    score += min(len(matched_terms), 4)
    if any(word in haystack for word in ["resume", "cv", "profile", "trainer", "training", "availability", "commercial", "experience"]):
        score += 1
    return score, len(matched_terms)


def _verification_tokens(value: str = "") -> list[str]:
    tokens = []
    for item in _re.findall(r"[a-zA-Z][a-zA-Z0-9+#./-]{2,}", str(value or "").lower()):
        clean = item.strip(" .,/+-_")
        if len(clean) < 3 or clean in _MAIL_MATCH_STOPWORDS:
            continue
        if clean not in tokens:
            tokens.append(clean)
    return tokens[:16]


def _lead_identity_tokens(lead: dict) -> tuple[list[str], list[str]]:
    name_tokens = _verification_tokens(" ".join([
        str(lead.get("trainer_name") or ""),
        str(lead.get("headline") or ""),
    ]))
    domain_tokens = _verification_tokens(" ".join([
        str(lead.get("domain") or ""),
        str(lead.get("searched_domain") or ""),
        str(lead.get("profile_text") or "")[:1200],
    ]))
    return name_tokens[:6], domain_tokens[:10]


def _internal_verification_score(lead: dict, text: str) -> tuple[int, list[str]]:
    haystack = str(text or "").lower()
    name_tokens, domain_tokens = _lead_identity_tokens(lead)
    reasons = []
    score = 0
    name_hits = [token for token in name_tokens if token in haystack]
    domain_hits = [token for token in domain_tokens if token in haystack]
    if len(name_hits) >= 2:
        score += 55
        reasons.append(f"name match: {', '.join(name_hits[:3])}")
    elif len(name_hits) == 1 and len(name_tokens) == 1:
        score += 35
        reasons.append(f"name match: {name_hits[0]}")
    if domain_hits:
        score += min(len(domain_hits), 3) * 10
        reasons.append(f"skill/domain match: {', '.join(domain_hits[:3])}")
    source_url = str(lead.get("source_url") or "").lower().strip()
    if source_url and source_url in haystack:
        score += 35
        reasons.append("linkedin url match")
    if any(word in haystack for word in ["resume", "cv", "curriculum vitae"]):
        score += 10
        reasons.append("resume context")
    return score, reasons


def _verification_source_item(source: str, doc: dict, text: str, email: str = "", phone: str = "") -> dict:
    return {
        "source": source,
        "doc": doc,
        "text": text,
        "email": str(email or "").strip(),
        "phone": str(phone or "").strip(),
    }


@router.post("/trainer-profile-leads/{lead_id}/verify-internal")
async def verify_trainer_profile_lead_internal(lead_id: str):
    db = get_db()
    lead = await db["trainer_profile_leads"].find_one({"lead_id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(404, "Trainer profile lead not found")

    sources = []
    trainer_docs = await db["trainers"].find(
        {},
        {"_id": 0, "trainer_id": 1, "name": 1, "email": 1, "phone": 1, "linkedin": 1, "domain": 1, "technologies": 1, "skills": 1, "location": 1, "summary": 1, "source_sheet": 1, "created_at": 1},
    ).sort("created_at", -1).limit(1500).to_list(1500)
    for doc in trainer_docs:
        text = "\n".join(str(doc.get(key) or "") for key in doc.keys())
        sources.append(_verification_source_item("Verified from Trainer DB", doc, text, doc.get("email"), doc.get("phone")))

    resume_docs = await db["resume_uploads"].find(
        {},
        {"_id": 0, "upload_id": 1, "trainer_id": 1, "filename": 1, "extracted_data": 1, "extracted_text": 1, "created_at": 1},
    ).sort("created_at", -1).limit(1500).to_list(1500)
    for doc in resume_docs:
        extracted = doc.get("extracted_data") or {}
        text = "\n".join([str(doc.get("filename") or ""), str(extracted), str(doc.get("extracted_text") or "")[:30000]])
        email = extracted.get("email") or _extract_public_email(text)
        phone = extracted.get("phone") or _extract_public_phone(text)
        sources.append(_verification_source_item("Verified from Resume", doc, text, email, phone))

    mail_docs = await db["email_logs"].find(
        {},
        {"_id": 0, "email_id": 1, "trainer_id": 1, "trainer_name": 1, "to_email": 1, "subject": 1, "body": 1, "source": 1, "created_at": 1},
    ).sort("created_at", -1).limit(1000).to_list(1000)
    for doc in mail_docs:
        text = "\n".join(str(doc.get(key) or "") for key in ["trainer_name", "to_email", "subject", "body", "source"])
        sources.append(_verification_source_item("Verified from Email History", doc, text, doc.get("to_email"), ""))

    best = None
    for source in sources:
        score, reasons = _internal_verification_score(lead, source["text"])
        if not source["email"] and not source["phone"]:
            score -= 20
        if not best or score > best["score"]:
            best = {**source, "score": score, "reasons": reasons}

    if not best or best["score"] < 70 or not (best["email"] or best["phone"]):
        update = {
            "verification_status": "unverified",
            "verification_source": "No strong internal match",
            "verification_score": max(0, int((best or {}).get("score") or 0)),
            "verification_reasons": (best or {}).get("reasons") or [],
            "updated_at": utc_now(),
        }
        await db["trainer_profile_leads"].update_one({"lead_id": lead_id}, {"$set": update})
        return {"success": True, "verified": False, "lead": _enrich_lead_response({**lead, **update})}

    source_doc = best["doc"] or {}
    update = {
        "verification_status": "verified",
        "verification_source": best["source"],
        "verification_score": min(100, int(best["score"])),
        "verification_reasons": best["reasons"],
        "verification_reference": source_doc.get("trainer_id") or source_doc.get("upload_id") or source_doc.get("email_id") or source_doc.get("filename") or "",
        "contact_email": best["email"] or lead.get("contact_email") or "",
        "contact_phone": best["phone"] or lead.get("contact_phone") or "",
        "email_source": best["source"],
        "updated_at": utc_now(),
    }
    verified_tier = (
        ContactVerificationTier.RESUME_VERIFIED.value
        if "resume" in str(best["source"] or "").lower() or "trainer db" in str(best["source"] or "").lower()
        else ContactVerificationTier.AI_EXTRACTED.value
    )
    update["verification_tier"] = verified_tier
    contact_trust = dict(lead.get("contact_trust") or {})
    if update["contact_email"]:
        contact_trust["email"] = {
            "tier": verified_tier,
            "weight": TIER_WEIGHT[verified_tier],
            "value": update["contact_email"],
        }
    if update["contact_phone"]:
        contact_trust["phone"] = {
            "tier": verified_tier,
            "weight": TIER_WEIGHT[verified_tier],
            "value": update["contact_phone"],
        }
    if contact_trust:
        update["contact_trust"] = contact_trust
    await db["trainer_profile_leads"].update_one({"lead_id": lead_id}, {"$set": update})
    return {"success": True, "verified": True, "lead": _enrich_lead_response({**lead, **update})}


@router.post("/trainer-profile-leads/enrich-from-mails")
async def enrich_trainer_profile_emails_from_mails(payload: dict = {}):
    db = get_db()
    query = {
        "$or": [{"contact_email": {"$exists": False}}, {"contact_email": ""}, {"contact_email": None}],
        "status": {"$nin": ["rejected", "contacted"]},
    }
    source_filter = str(payload.get("source") or payload.get("source_mode") or "").strip().lower()
    if source_filter == "naukri":
        query["source"] = {"$regex": "naukri", "$options": "i"}
    elif source_filter == "linkedin":
        query["source"] = {"$regex": "linkedin", "$options": "i"}
    domain = str(payload.get("domain") or "").strip()
    if domain:
        pattern = {"$regex": _re.escape(domain), "$options": "i"}
        query["$and"] = [{
            "$or": [{"domain": pattern}, {"searched_domain": pattern}, {"profile_text": pattern}, {"headline": pattern}]
        }]

    limit = max(1, min(int(payload.get("limit") or 60), 150))
    leads = await db["trainer_profile_leads"].find(query, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    mail_docs = await db["client_emails"].find(
        {},
        {"_id": 0, "from_email": 1, "from_name": 1, "subject": 1, "snippet": 1, "clean_body": 1, "raw_body": 1, "extracted": 1, "received_at": 1},
    ).sort("received_at", -1).limit(1200).to_list(1200)
    resume_docs = await db["resume_uploads"].find(
        {},
        {"_id": 0, "filename": 1, "extracted_data": 1, "extracted_text": 1, "created_at": 1},
    ).sort("created_at", -1).limit(1200).to_list(1200)
    trainer_docs = await db["trainers"].find(
        {},
        {"_id": 0, "name": 1, "email": 1, "phone": 1, "domain": 1, "specialization": 1, "skills": 1, "experience": 1, "created_at": 1},
    ).sort("created_at", -1).limit(1200).to_list(1200)

    enriched = []
    skipped = []
    sources = []
    for doc in trainer_docs:
        email = str(doc.get("email") or "").strip()
        if email:
            sources.append(("trainer_database", doc, " ".join(str(doc.get(key) or "") for key in doc.keys()), email, str(doc.get("phone") or "")))
    for doc in resume_docs:
        extracted = doc.get("extracted_data") or {}
        text = "\n".join([str(doc.get("filename") or ""), str(extracted), str(doc.get("extracted_text") or "")[:20000]])
        email = _extract_public_email(text)
        phone_match = _re.search(r"(?:\+?91[-\s]?)?[6-9]\d{9}", text or "")
        if email:
            sources.append(("resume_mail_or_upload", doc, text, email, phone_match.group(0) if phone_match else ""))
    for doc in mail_docs:
        text = _mail_lookup_text(doc)
        email = str(doc.get("from_email") or "").strip() or _extract_public_email(text)
        phone_match = _re.search(r"(?:\+?91[-\s]?)?[6-9]\d{9}", text or "")
        if email:
            sources.append(("office_mail", doc, text, email, phone_match.group(0) if phone_match else ""))

    for lead in leads:
        lead_id = lead.get("lead_id")
        terms = _lead_match_terms_for_mail_lookup(lead)
        best = None
        best_score = 0
        best_term_hits = 0
        for source_name, source_doc, text, email, phone in sources:
            score, term_hits = _mail_lookup_score(lead, text, terms)
            if score > best_score:
                best = (source_name, source_doc, email, phone)
                best_score = score
                best_term_hits = term_hits
        if not best or best_score < 5 or best_term_hits < 2:
            skipped.append({"lead_id": lead_id, "trainer_name": lead.get("trainer_name"), "reason": "no matching stored mail/resume email found"})
            continue
        source_name, source_doc, email, phone = best
        update = {
            "contact_email": email,
            "contact_phone": lead.get("contact_phone") or phone,
            "email_source": source_name,
            "mail_match_score": best_score,
            "mail_match_reference": source_doc.get("email_id") or source_doc.get("filename") or source_doc.get("name") or source_doc.get("subject") or "",
            "updated_at": utc_now(),
        }
        verified_tier = (
            ContactVerificationTier.RESUME_VERIFIED.value
            if source_name in {"trainer_database", "resume_mail_or_upload"}
            else ContactVerificationTier.AI_EXTRACTED.value
        )
        contact_trust = dict(lead.get("contact_trust") or {})
        contact_trust["email"] = {
            "tier": verified_tier,
            "weight": TIER_WEIGHT[verified_tier],
            "value": email,
        }
        if update["contact_phone"]:
            contact_trust["phone"] = {
                "tier": verified_tier,
                "weight": TIER_WEIGHT[verified_tier],
                "value": update["contact_phone"],
            }
        update["contact_trust"] = contact_trust
        update["verification_tier"] = verified_tier
        await db["trainer_profile_leads"].update_one({"lead_id": lead_id}, {"$set": update})
        enriched.append({**lead, **update})

    return {
        "success": True,
        "checked": len(leads),
        "mail_sources_checked": len(sources),
        "enriched_count": len(enriched),
        "enriched": [_enrich_lead_response(item) for item in enriched],
        "skipped": skipped[:50],
    }


@router.post("/trainer-profile-leads/send-public-email-outreach")
async def send_public_email_trainer_outreach(payload: dict = {}):
    db = get_db()
    query = {
        "contact_email": {"$nin": [None, ""]},
        "status": {"$nin": ["rejected", "contacted"]},
    }
    domain = str(payload.get("domain") or "").strip()
    if domain:
        pattern = {"$regex": _re.escape(domain), "$options": "i"}
        query["$and"] = [{
            "$or": [{"domain": pattern}, {"searched_domain": pattern}, {"profile_text": pattern}, {"headline": pattern}]
        }]
    limit = max(1, min(int(payload.get("limit") or 25), 100))
    leads = await db["trainer_profile_leads"].find(query, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    smtp_config = await get_admin_email_config(db)
    sent = []
    failed = []
    skipped = []
    for lead in leads:
        to_email = str(lead.get("contact_email") or "").strip()
        if not _extract_public_email(to_email):
            skipped.append({"lead_id": lead.get("lead_id"), "to_email": to_email, "reason": "invalid email"})
            continue
        existing = await db["email_logs"].find_one({
            "lead_id": lead.get("lead_id"),
            "to_email": to_email,
            "mail_type": "linkedin_trainer_profile_outreach",
            "status": "sent",
        }, {"_id": 0, "email_id": 1})
        if existing:
            skipped.append({"lead_id": lead.get("lead_id"), "to_email": to_email, "reason": "already sent"})
            continue
        draft = _trainer_profile_lead_mail_draft(lead, {**payload, "domain": payload.get("domain") or lead.get("domain")})
        subject = str(draft.get("subject") or f"Training Requirement - {lead.get('domain') or 'Training'}").strip()
        body = str(draft.get("body") or "").strip()
        email_id = f"TPLMAIL-{uuid.uuid4().hex[:8].upper()}"
        now = utc_now()
        success, error = await send_email_async(to_email, subject, body, smtp_config, "")
        log_doc = {
            "email_id": email_id,
            "mail_type": "linkedin_trainer_profile_outreach",
            "source": "linkedin_shortlist_bulk_public_email",
            "lead_id": lead.get("lead_id"),
            "trainer_name": lead.get("trainer_name") or lead.get("headline") or "",
            "to_email": to_email,
            "subject": subject,
            "body": body,
            "status": "sent" if success else "failed",
            "error_message": error if not success else "",
            "sent_at": now if success else None,
            "created_at": now,
            "reply_received": False,
            "opened": False,
            "open_count": 0,
        }
        await db["email_logs"].insert_one(log_doc)
        await db["trainer_profile_leads"].update_one(
            {"lead_id": lead.get("lead_id")},
            {"$set": {
                "status": "contacted" if success else lead.get("status", "new"),
                "last_email_id": email_id,
                "last_contacted_at": now if success else None,
                "last_error": error if not success else "",
                "updated_at": utc_now(),
            }},
        )
        item = {"lead_id": lead.get("lead_id"), "trainer_name": lead.get("trainer_name"), "to_email": to_email, "email_id": email_id, "status": "sent" if success else "failed", "error": error}
        if success:
            sent.append(item)
        else:
            failed.append(item)
    return {"success": True, "checked": len(leads), "sent_count": len(sent), "failed_count": len(failed), "skipped_count": len(skipped), "sent": sent, "failed": failed, "skipped": skipped[:50]}


@router.patch("/trainer-profile-leads/{lead_id}")
async def update_trainer_profile_lead(lead_id: str, payload: dict):
    db = get_db()
    allowed = {"source", "source_url", "trainer_name", "contact_email", "contact_phone", "domain", "headline", "profile_text", "notes", "status", "public_resume_url", "public_website_url"}
    updates = {key: value for key, value in payload.items() if key in allowed}
    updates["updated_at"] = utc_now()
    doc = await db["trainer_profile_leads"].find_one_and_update(
        {"lead_id": lead_id},
        {"$set": updates},
        projection={"_id": 0},
        return_document=ReturnDocument.AFTER,
    )
    if not doc:
        raise HTTPException(404, "Trainer profile lead not found")
    return {"success": True, "lead": _public_doc(doc)}


def _trainer_profile_lead_mail_draft(lead: dict, payload: dict) -> dict:
    trainer_name = (
        payload.get("trainer_name")
        or lead.get("trainer_name")
        or lead.get("headline")
        or "Trainer"
    )
    domain = str(payload.get("domain") or lead.get("domain") or "Training").strip()
    duration = str(payload.get("duration") or "").strip()
    mode = str(payload.get("mode") or "Online").strip()
    participants = str(payload.get("participants") or "").strip()
    requirement_note = str(payload.get("requirement_note") or "").strip()
    details = [f"* Domain/Technology: {domain}"]
    if duration:
        details.append(f"* Duration: {duration}")
    if mode:
        details.append(f"* Mode: {mode}")
    if participants:
        details.append(f"* Participants: {participants}")
    if requirement_note:
        details.append(f"* Requirement note: {requirement_note}")

    return {
        "subject": f"Training Requirement - {domain}",
        "body": (
            f"Dear {trainer_name},\n\n"
            f"We came across your public trainer profile related to {domain} and would like to check your interest for a relevant corporate training requirement.\n\n"
            "Training Details:\n\n"
            f"{chr(10).join(details)}\n\n"
            "At this stage, we are checking your interest and availability first. Once you confirm, we will share the confirmed schedule, participant details, and next steps.\n\n"
            "Kindly confirm your interest and share your updated trainer profile/resume along with your experience, availability, and commercial expectation.\n\n"
            "Best Regards,\n"
            "Recruitment Team\n"
            "Clahan Technologies"
        ),
    }


@router.post("/trainer-profile-leads/{lead_id}/send-email")
async def send_trainer_profile_lead_email(lead_id: str, payload: dict = {}):
    db = get_db()
    lead = await db["trainer_profile_leads"].find_one({"lead_id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(404, "Trainer profile lead not found")
    to_email = str(payload.get("to_email") or lead.get("contact_email") or "").strip()
    if not to_email:
        raise HTTPException(400, "Trainer email is required before sending")
    draft = payload.get("draft") or _trainer_profile_lead_mail_draft(lead, payload)
    subject = str(draft.get("subject") or f"Training Requirement - {lead.get('domain') or 'Training'}").strip()
    body = str(draft.get("body") or "").strip()
    smtp_config = await get_admin_email_config(db)
    email_id = f"TPLMAIL-{uuid.uuid4().hex[:8].upper()}"
    sent_at = utc_now()
    success, error = await send_email_async(to_email, subject, body, smtp_config, "")
    status_value = "sent" if success else "failed"
    await db["email_logs"].insert_one({
        "email_id": email_id,
        "mail_type": "linkedin_trainer_profile_outreach",
        "source": "linkedin_shortlist",
        "lead_id": lead_id,
        "trainer_name": lead.get("trainer_name") or lead.get("headline") or "",
        "to_email": to_email,
        "subject": subject,
        "body": body,
        "status": status_value,
        "error_message": error if not success else "",
        "sent_at": sent_at if success else None,
        "created_at": sent_at,
        "reply_received": False,
        "opened": False,
        "open_count": 0,
    })
    await db["trainer_profile_leads"].update_one(
        {"lead_id": lead_id},
        {"$set": {
            "contact_email": to_email,
            "status": "contacted" if success else lead.get("status", "reviewed"),
            "last_email_id": email_id,
            "last_contacted_at": sent_at if success else None,
            "last_error": error if not success else "",
            "updated_at": utc_now(),
        }},
    )
    return {"success": success, "status": status_value, "error": error, "email_id": email_id, "draft": draft}


@router.delete("/trainer-profile-leads/by-domain")
async def delete_trainer_profile_leads_by_domain(domain: str):
    clean = str(domain or "").strip()
    if not clean:
        raise HTTPException(400, "Domain is required")
    db = get_db()
    pattern = {"$regex": f"^{_re.escape(clean)}$", "$options": "i"}
    result = await db["trainer_profile_leads"].delete_many({
        "$or": [{"domain": pattern}, {"searched_domain": pattern}],
    })
    return {"success": True, "domain": clean, "deleted_count": result.deleted_count}


@router.delete("/trainer-profile-leads/{lead_id}")
async def delete_trainer_profile_lead(lead_id: str):
    db = get_db()
    result = await db["trainer_profile_leads"].delete_one({"lead_id": lead_id})
    if not result.deleted_count:
        raise HTTPException(404, "Trainer profile lead not found")
    return {"success": True, "deleted": lead_id}


@router.patch("/client-leads/{lead_id}")
async def update_client_lead(lead_id: str, payload: dict):
    db = get_db()
    allowed = {"source", "source_url", "company_name", "contact_name", "contact_email", "contact_phone", "domain", "post_text", "notes", "status", "draft"}
    updates = {key: value for key, value in payload.items() if key in allowed}
    updates["updated_at"] = utc_now()
    doc = await db["client_leads"].find_one_and_update(
        {"lead_id": lead_id},
        {"$set": updates},
        projection={"_id": 0},
        return_document=ReturnDocument.AFTER,
    )
    if not doc:
        raise HTTPException(404, "Client lead not found")
    return {"success": True, "lead": _public_doc(doc)}


@router.post("/client-leads/{lead_id}/regenerate-draft")
async def regenerate_client_lead_draft(lead_id: str):
    db = get_db()
    lead = await db["client_leads"].find_one({"lead_id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(404, "Client lead not found")
    draft = _client_lead_draft(lead)
    await db["client_leads"].update_one({"lead_id": lead_id}, {"$set": {"draft": draft, "updated_at": utc_now()}})
    return {"success": True, "draft": draft}


@router.post("/client-leads/{lead_id}/send-email")
async def send_client_lead_email(lead_id: str, payload: dict = {}):
    db = get_db()
    lead = await db["client_leads"].find_one({"lead_id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(404, "Client lead not found")
    to_email = str(payload.get("to_email") or lead.get("contact_email") or "").strip()
    if not to_email:
        raise HTTPException(400, "Contact email is required before sending")
    draft = payload.get("draft") or lead.get("draft") or _client_lead_draft(lead)
    subject = str(draft.get("subject") or f"Trainer Support for {lead.get('domain') or 'Training'} Requirement").strip()
    body = str(draft.get("body") or "").strip()
    smtp_config = await get_admin_email_config(db)
    email_id = f"LEADMAIL-{uuid.uuid4().hex[:8].upper()}"
    sent_at = utc_now()
    success, error = await send_email_async(to_email, subject, body, smtp_config, "")
    status_value = "sent" if success else "failed"
    await db["email_logs"].insert_one({
        "email_id": email_id,
        "mail_type": "client_lead_outreach",
        "source": "client_lead_finder",
        "lead_id": lead_id,
        "to_email": to_email,
        "to_name": lead.get("contact_name") or "",
        "subject": subject,
        "body": body,
        "status": status_value,
        "error_message": error if not success else "",
        "sent_at": sent_at if success else None,
        "created_at": sent_at,
        "reply_received": False,
        "opened": False,
        "open_count": 0,
    })
    await db["client_leads"].update_one(
        {"lead_id": lead_id},
        {"$set": {
            "contact_email": to_email,
            "status": "contacted" if success else lead.get("status", "new"),
            "last_email_id": email_id,
            "last_contacted_at": sent_at if success else None,
            "last_error": error if not success else "",
            "updated_at": utc_now(),
        }},
    )
    return {"success": success, "status": status_value, "error": error, "email_id": email_id}


@router.delete("/client-leads/by-domain")
async def delete_client_leads_by_domain(domain: str):
    clean = str(domain or "").strip()
    if not clean:
        raise HTTPException(400, "Domain is required")
    db = get_db()
    pattern = {"$regex": f"^{_re.escape(clean)}$", "$options": "i"}
    result = await db["client_leads"].delete_many({
        "$or": [{"domain": pattern}, {"searched_domain": pattern}],
    })
    return {"success": True, "domain": clean, "deleted_count": result.deleted_count}


@router.delete("/client-leads/{lead_id}")
async def delete_client_lead(lead_id: str):
    db = get_db()
    result = await db["client_leads"].delete_one({"lead_id": lead_id})
    if not result.deleted_count:
        raise HTTPException(404, "Client lead not found")
    return {"success": True, "deleted": lead_id}


@router.get("/client-conversations")
async def get_client_conversations(
    q: Optional[str] = None,
    client: Optional[str] = None,
    domain: Optional[str] = None,
    requirement_id: Optional[str] = None,
    limit: int = 60,
):
    db = get_db()
    limit = max(10, min(int(limit or 60), 150))
    filters = []

    if requirement_id:
        filters.append({"requirement_id": requirement_id})

    if client:
        pattern = {"$regex": _re.escape(client.strip()), "$options": "i"}
        filters.append({"$or": [
            {"from_email": pattern},
            {"from_name": pattern},
            {"extracted.client_email": pattern},
            {"extracted.client_name": pattern},
            {"extracted.client_company": pattern},
        ]})

    domain_requirement_ids = []
    if domain:
        domain_pattern = {"$regex": _re.escape(domain.strip()), "$options": "i"}
        domain_requirements = await db["requirements"].find(
            {"$or": [
                {"technology_needed": domain_pattern},
                {"job_title": domain_pattern},
                {"job_description": domain_pattern},
            ]},
            {"_id": 0, "requirement_id": 1},
        ).limit(200).to_list(200)
        domain_requirement_ids = [doc.get("requirement_id") for doc in domain_requirements if doc.get("requirement_id")]
        domain_or = [
            {"extracted.technology_needed": domain_pattern},
            {"subject": domain_pattern},
            {"clean_body": domain_pattern},
            {"raw_body": domain_pattern},
        ]
        if domain_requirement_ids:
            domain_or.append({"requirement_id": {"$in": domain_requirement_ids}})
        filters.append({"$or": domain_or})

    if q:
        search_pattern = {"$regex": _re.escape(q.strip()), "$options": "i"}
        filters.append({"$or": [
            {"from_email": search_pattern},
            {"from_name": search_pattern},
            {"subject": search_pattern},
            {"clean_body": search_pattern},
            {"raw_body": search_pattern},
            {"extracted.client_company": search_pattern},
            {"extracted.technology_needed": search_pattern},
        ]})

    query = {"$and": filters} if filters else {}
    client_docs = await db["client_emails"].find(query, {"_id": 0}).sort(
        "received_at", -1
    ).limit(600).to_list(600)

    requirement_ids = {
        doc.get("requirement_id")
        for doc in client_docs
        if doc.get("requirement_id")
    }
    requirement_ids.update(domain_requirement_ids)

    requirements = {}
    if requirement_ids:
        req_docs = await db["requirements"].find(
            {"requirement_id": {"$in": list(requirement_ids)}},
            {"_id": 0},
        ).to_list(len(requirement_ids))
        requirements = {doc.get("requirement_id"): doc for doc in req_docs}

    client_emails = sorted({
        (doc.get("from_email") or (doc.get("extracted") or {}).get("client_email") or "").lower()
        for doc in client_docs
        if doc.get("from_email") or (doc.get("extracted") or {}).get("client_email")
    })

    scoped_to_requirement_or_domain = bool(requirement_id or domain)
    slot_filters = []
    if requirement_id:
        slot_filters.append({"requirement_id": requirement_id})
    elif requirement_ids:
        slot_filters.append({"requirement_id": {"$in": list(requirement_ids)}})
    if client_emails and not scoped_to_requirement_or_domain:
        slot_filters.append({"to_email": {"$in": client_emails}})
    slot_docs = []
    if slot_filters:
        slot_docs = await db["client_slot_emails"].find(
            {"$or": slot_filters},
            {"_id": 0},
        ).sort("created_at", -1).limit(400).to_list(400)

    slot_ids = [doc.get("email_id") for doc in slot_docs if doc.get("email_id")]
    confirmations = []
    if slot_ids or requirement_ids:
        confirmation_filters = []
        if slot_ids:
            confirmation_filters.append({"client_slot_email_id": {"$in": slot_ids}})
        if requirement_id:
            confirmation_filters.append({"requirement_id": requirement_id})
        elif requirement_ids:
            confirmation_filters.append({"requirement_id": {"$in": list(requirement_ids)}})
        confirmations = await db["client_slot_confirmations"].find(
            {"$or": confirmation_filters},
            {"_id": 0},
        ).sort("updated_at", -1).limit(400).to_list(400)

    client_message_filters = []
    if requirement_id:
        client_message_filters.append({"requirement_id": requirement_id})
    elif requirement_ids:
        client_message_filters.append({"requirement_id": {"$in": list(requirement_ids)}})
    if slot_ids:
        client_message_filters.append({"client_slot_email_id": {"$in": slot_ids}})
    if client_emails and not scoped_to_requirement_or_domain:
        client_message_filters.append({"client_email": {"$in": client_emails}})
        client_message_filters.append({"to_email": {"$in": client_emails}})
    client_messages = []
    if client_message_filters:
        client_messages = await db["client_messages"].find(
            {"$or": client_message_filters},
            {"_id": 0},
        ).sort("created_at", -1).limit(400).to_list(400)

    threads = {}

    def ensure_group(seed_doc: dict, requirement: dict = None) -> dict:
        requirement = requirement or {}
        key = _client_conversation_key(seed_doc, requirement)
        if key not in threads:
            meta = _client_conversation_meta(seed_doc, requirement)
            threads[key] = {
                "thread_key": key,
                **meta,
                "trainers": [],
                "messages": [],
                "message_count": 0,
                "latest_at": None,
                "last_subject": "",
                "last_preview": "",
                "_seen": set(),
            }
        else:
            meta = _client_conversation_meta(seed_doc, requirement)
            for field in ["client_name", "client_email", "client_company", "domain", "requirement_id", "thread_id", "status"]:
                if meta.get(field) and not threads[key].get(field):
                    threads[key][field] = meta[field]
        return threads[key]

    def add_message(group: dict, item: dict):
        body = str(item.get("body") or "").strip()
        subject = str(item.get("subject") or "").strip()
        if not body and not subject:
            return
        direction = item.get("direction") or "received"
        source = item.get("source") or ""
        normal_body = _re.sub(r"\s+", " ", body.lower()).strip()
        normal_subject = _re.sub(r"\s+", " ", subject.lower()).strip()
        if direction == "received":
            identity = f"{direction}|{normal_subject}|{normal_body[:260]}"
        else:
            identity = f"{source}|{item.get('message_id')}|{direction}|{normal_subject}|{normal_body[:160]}"
        if identity in group["_seen"]:
            return
        group["_seen"].add(identity)
        message = {
            "message_id": item.get("message_id") or "",
            "direction": direction,
            "source": source,
            "subject": subject,
            "body": body,
            "sent_at": item.get("sent_at"),
            "sort_at": item.get("sort_at") or item.get("sent_at"),
            "sort_order": item.get("sort_order", 50),
            "status": item.get("status") or "",
            "from_label": item.get("from_label") or "",
            "to_label": item.get("to_label") or "",
            "meta": item.get("meta") or {},
        }
        trainer_id = str(message["meta"].get("trainer_id") or item.get("trainer_id") or "").strip()
        trainer_name = str(message["meta"].get("trainer_name") or item.get("trainer_name") or "").strip()
        if trainer_id or trainer_name:
            trainer_key = trainer_id or trainer_name.lower()
            if not any((existing.get("trainer_id") or existing.get("trainer_name", "").lower()) == trainer_key for existing in group.get("trainers", [])):
                group.setdefault("trainers", []).append({
                    "trainer_id": trainer_id,
                    "trainer_name": trainer_name or trainer_id or "Trainer",
                })
        group["messages"].append(message)
        when = _thread_datetime(message.get("sent_at"))
        latest = _thread_datetime(group.get("latest_at"))
        if when >= latest:
            group["latest_at"] = message.get("sent_at")
            group["last_subject"] = subject
            group["last_preview"] = body[:180]

    for doc in client_docs:
        req = requirements.get(doc.get("requirement_id")) or {}
        group = ensure_group(doc, req)
        client_label = doc.get("from_name") or doc.get("from_email") or "Client"
        add_message(group, {
            "message_id": doc.get("email_id"),
            "direction": "received",
            "source": "client_inbox",
            "subject": doc.get("subject"),
            "body": doc.get("clean_body") or doc.get("raw_body") or doc.get("snippet"),
            "sent_at": doc.get("received_at") or doc.get("created_at"),
            "sort_order": 10,
            "status": doc.get("status"),
            "from_label": client_label,
            "to_label": "Clahan Technologies",
            "meta": {
                "requirement_id": doc.get("requirement_id"),
                "confidence": doc.get("confidence"),
                "thread_id": doc.get("thread_id"),
            },
        })
        reply = doc.get("generated_reply") or {}
        if reply.get("body"):
            sent_at = doc.get("sent_at")
            add_message(group, {
                "message_id": f"reply:{doc.get('email_id')}",
                "direction": "sent" if sent_at else "draft",
                "source": "calhan_reply",
                "subject": reply.get("subject") or f"Re: {doc.get('subject', '')}",
                "body": reply.get("body"),
                "sent_at": sent_at or doc.get("created_at") or doc.get("received_at"),
                "sort_order": 20,
                "status": doc.get("status"),
                "from_label": "Clahan Technologies",
                "to_label": client_label,
                "meta": {"sent_by": doc.get("sent_by") or ("draft" if not sent_at else "")},
            })

    for slot in slot_docs:
        req = requirements.get(slot.get("requirement_id")) or {}
        group = ensure_group(slot, req)
        client_label = slot.get("client_name") or slot.get("to_email") or "Client"
        add_message(group, {
            "message_id": slot.get("email_id"),
            "direction": "sent",
            "source": "client_slot_options",
            "subject": slot.get("subject"),
            "body": slot.get("body"),
            "sent_at": slot.get("sent_at") or slot.get("created_at"),
            "sort_order": 30,
            "status": slot.get("status"),
            "from_label": "Clahan Technologies",
            "to_label": client_label,
            "meta": {
                "trainer_id": slot.get("trainer_id"),
                "trainer_name": slot.get("trainer_name"),
                "slot_ref": slot.get("slot_ref"),
                "slot_text": slot.get("slot_text"),
            },
        })
        if slot.get("last_client_reply_text"):
            add_message(group, {
                "message_id": f"slot-reply:{slot.get('email_id')}",
                "direction": "received",
                "source": "client_slot_reply",
                "subject": f"Re: {slot.get('subject', '')}",
                "body": slot.get("last_client_reply_text"),
                "sent_at": slot.get("last_client_reply_at") or slot.get("client_confirmed_at"),
                "sort_order": 40,
                "status": slot.get("status"),
                "from_label": client_label,
                "to_label": "Clahan Technologies",
                "meta": {
                    "trainer_id": slot.get("trainer_id"),
                    "trainer_name": slot.get("trainer_name"),
                    "slot_ref": slot.get("slot_ref"),
                },
            })

    for confirmation in confirmations:
        req = requirements.get(confirmation.get("requirement_id")) or {}
        group = ensure_group(confirmation, req)
        client_label = confirmation.get("client_name") or confirmation.get("client_email") or "Client"
        add_message(group, {
            "message_id": confirmation.get("gmail_message_id") or confirmation.get("confirmation_id"),
            "direction": "received",
            "source": "client_slot_confirmation",
            "subject": confirmation.get("subject"),
            "body": confirmation.get("reply_text"),
            "sent_at": confirmation.get("created_at") or confirmation.get("updated_at"),
            "sort_order": 40,
            "status": confirmation.get("status"),
            "from_label": client_label,
            "to_label": "Clahan Technologies",
            "meta": {
                "trainer_id": confirmation.get("trainer_id"),
                "trainer_name": confirmation.get("trainer_name"),
                "parsed_slot": confirmation.get("parsed_slot"),
            },
        })
        calendar_event = confirmation.get("calendar_event") or {}
        meet_link = calendar_event.get("meet_link") or calendar_event.get("html_link") or ""
        if meet_link:
            add_message(group, {
                "message_id": f"meet:{confirmation.get('confirmation_id')}",
                "direction": "system",
                "source": "google_calendar",
                "subject": "Google Meet scheduled",
                "body": f"Meeting link created and trainer notified.\n\nMeet link: {meet_link}",
                "sent_at": confirmation.get("scheduled_at") or confirmation.get("updated_at"),
                "sort_order": 50,
                "status": confirmation.get("status"),
                "from_label": "TrainerSync",
                "to_label": "Client + Trainer",
                "meta": {
                    "trainer_id": confirmation.get("trainer_id"),
                    "trainer_name": confirmation.get("trainer_name"),
                    "meet_link": meet_link,
                },
            })

    for client_message in client_messages:
        req = requirements.get(client_message.get("requirement_id")) or {}
        group = ensure_group(client_message, req)
        client_label = (
            client_message.get("client_name")
            or client_message.get("client_email")
            or client_message.get("to_email")
            or "Client"
        )
        calendar_event = client_message.get("calendar_event") or {}
        meet_link = calendar_event.get("meet_link") or calendar_event.get("html_link") or client_message.get("interview_link") or ""
        add_message(group, {
            "message_id": client_message.get("email_id"),
            "direction": client_message.get("direction") or "sent",
            "source": client_message.get("mail_type") or "client_message",
            "subject": client_message.get("subject"),
            "body": client_message.get("body"),
            "sent_at": client_message.get("sent_at") or client_message.get("created_at"),
            "sort_order": 45,
            "status": client_message.get("status"),
            "from_label": "Clahan Technologies",
            "to_label": client_label,
            "meta": {
                "trainer_id": client_message.get("trainer_id"),
                "trainer_name": client_message.get("trainer_name"),
                "client_slot_email_id": client_message.get("client_slot_email_id"),
                "meet_link": meet_link,
                "platform": client_message.get("platform"),
                "interview_date": client_message.get("interview_date"),
            },
        })

    result_threads = []
    for group in threads.values():
        group["messages"].sort(key=_message_sort_key)
        group["message_count"] = len(group["messages"])
        if not group.get("latest_at") and group["messages"]:
            group["latest_at"] = group["messages"][-1].get("sent_at")
        group.pop("_seen", None)
        result_threads.append(group)

    search_text = (q or "").strip().lower()
    if search_text:
        result_threads = [
            thread for thread in result_threads
            if search_text in " ".join([
                str(thread.get("client_name") or ""),
                str(thread.get("client_email") or ""),
                str(thread.get("client_company") or ""),
                str(thread.get("domain") or ""),
                str(thread.get("requirement_id") or ""),
                " ".join(str(msg.get("subject") or "") + " " + str(msg.get("body") or "") for msg in thread.get("messages", [])),
            ]).lower()
        ]

    result_threads.sort(key=lambda thread: _thread_datetime(thread.get("latest_at")), reverse=True)

    facet_docs = await db["client_emails"].find({}, {
        "_id": 0,
        "from_email": 1,
        "from_name": 1,
        "extracted.client_company": 1,
        "extracted.technology_needed": 1,
    }).sort("received_at", -1).limit(300).to_list(300)
    clients = []
    domains = set()
    seen_clients = set()
    for doc in facet_docs:
        extracted = doc.get("extracted") or {}
        email = (doc.get("from_email") or "").lower()
        name = doc.get("from_name") or extracted.get("client_company") or email
        key = email or name.lower()
        if key and key not in seen_clients:
            seen_clients.add(key)
            clients.append({
                "name": name or "Client",
                "email": email,
                "company": extracted.get("client_company") or sender_domain(email),
            })
        if extracted.get("technology_needed"):
            domains.add(str(extracted["technology_needed"]))

    return {
        "threads": [_public_doc(thread) for thread in result_threads[:limit]],
        "total": len(result_threads),
        "clients": clients[:100],
        "domains": sorted(domains),
    }


@router.get("/client-updates")
async def get_client_updates(requirement_id: Optional[str] = None, limit: int = 30):
    db = get_db()
    query = {}
    if requirement_id:
        query["requirement_id"] = requirement_id

    limit = max(1, min(int(limit or 30), 100))
    try:
        docs = await db["client_slot_emails"].find(query, {"_id": 0}).sort(
            "_id", -1
        ).limit(limit).max_time_ms(3000).to_list(limit)
    except ExecutionTimeout:
        return {
            "updates": [],
            "total": 0,
            "warning": "Client updates are still loading. Please try again.",
        }

    requirement_ids = sorted({doc.get("requirement_id") for doc in docs if doc.get("requirement_id")})
    requirements = {}
    if requirement_ids:
        req_docs = await db["requirements"].find(
            {"requirement_id": {"$in": requirement_ids}},
            {"_id": 0, "requirement_id": 1, "technology_needed": 1, "client_company": 1, "client_name": 1},
        ).to_list(len(requirement_ids))
        requirements = {doc.get("requirement_id"): doc for doc in req_docs}

    email_ids = sorted({doc.get("email_id") for doc in docs if doc.get("email_id")})
    confirmations = {}
    if email_ids:
        try:
            conf_docs = await db["client_slot_confirmations"].find(
                {"client_slot_email_id": {"$in": email_ids}},
                {"_id": 0},
            ).sort("_id", -1).max_time_ms(3000).to_list(len(email_ids) * 2)
            for confirmation in conf_docs:
                confirmations.setdefault(confirmation.get("client_slot_email_id"), confirmation)
        except ExecutionTimeout:
            confirmations = {}

    updates = []
    for doc in docs:
        req = requirements.get(doc.get("requirement_id")) or {}
        confirmation = confirmations.get(doc.get("email_id")) or {}
        parsed_slot = doc.get("client_confirmed_slot") or confirmation.get("parsed_slot") or {}
        calendar_event = doc.get("calendar_event") or confirmation.get("calendar_event") or {}
        trainer_schedule_email = doc.get("trainer_schedule_email") or confirmation.get("trainer_schedule_email") or {}
        client_schedule_email = doc.get("client_schedule_email") or confirmation.get("client_schedule_email") or {}
        updates.append({
            **doc,
            "technology": req.get("technology_needed") or doc.get("technology") or "Training",
            "client_company": req.get("client_company") or doc.get("client_name") or req.get("client_name"),
            "confirmation_status": confirmation.get("status") or doc.get("status"),
            "confirmed_slot": parsed_slot,
            "meet_link": calendar_event.get("meet_link") or calendar_event.get("html_link") or "",
            "calendar_event_id": calendar_event.get("event_id"),
            "trainer_email_sent": bool(trainer_schedule_email.get("success")),
            "client_email_sent": bool(client_schedule_email.get("success")),
            "last_error": (
                doc.get("calendar_error")
                or confirmation.get("error")
                or trainer_schedule_email.get("error")
                or client_schedule_email.get("error")
                or doc.get("error_message")
                or ""
            ),
        })

    return {"updates": [_public_doc(update) for update in updates], "total": len(updates)}


@router.get("/interview-schedules")
async def get_interview_schedules(requirement_id: Optional[str] = None, limit: int = 100):
    db = get_db()
    query = {
        "$or": [
            {"status": "confirmed_scheduled"},
            {"calendar_event": {"$exists": True}},
            {"client_confirmed_slot": {"$exists": True}},
        ]
    }
    if requirement_id:
        query["requirement_id"] = requirement_id

    limit = max(1, min(int(limit or 100), 500))
    docs = await db["client_slot_emails"].find(query, {"_id": 0}).sort(
        "client_confirmed_at", -1
    ).limit(limit).to_list(limit)

    requirement_ids = sorted({doc.get("requirement_id") for doc in docs if doc.get("requirement_id")})
    trainer_ids = sorted({doc.get("trainer_id") for doc in docs if doc.get("trainer_id")})
    requirements = {}
    trainers = {}
    confirmations = {}

    if requirement_ids:
        req_docs = await db["requirements"].find(
            {"requirement_id": {"$in": requirement_ids}},
            {
                "_id": 0,
                "requirement_id": 1,
                "technology_needed": 1,
                "domain": 1,
                "job_title": 1,
                "client_name": 1,
                "client_company": 1,
                "client_email": 1,
                "mode": 1,
                "training_mode": 1,
            },
        ).to_list(len(requirement_ids))
        requirements = {doc.get("requirement_id"): doc for doc in req_docs}

    if trainer_ids:
        trainer_docs = await db["trainers"].find(
            {"trainer_id": {"$in": trainer_ids}},
            {"_id": 0, "trainer_id": 1, "name": 1, "trainer_name": 1, "email": 1, "trainer_email": 1, "phone": 1},
        ).to_list(len(trainer_ids))
        trainers = {doc.get("trainer_id"): doc for doc in trainer_docs}

    email_ids = sorted({doc.get("email_id") for doc in docs if doc.get("email_id")})
    if email_ids:
        conf_docs = await db["client_slot_confirmations"].find(
            {"client_slot_email_id": {"$in": email_ids}},
            {"_id": 0},
        ).sort("updated_at", -1).to_list(len(email_ids) * 2)
        for conf in conf_docs:
            confirmations.setdefault(conf.get("client_slot_email_id"), conf)

    schedules = []
    for doc in docs:
        req = requirements.get(doc.get("requirement_id")) or {}
        trainer = trainers.get(doc.get("trainer_id")) or {}
        confirmation = confirmations.get(doc.get("email_id")) or {}
        slot = doc.get("client_confirmed_slot") or confirmation.get("parsed_slot") or {}
        calendar_event = doc.get("calendar_event") or confirmation.get("calendar_event") or {}
        trainer_schedule_email = doc.get("trainer_schedule_email") or confirmation.get("trainer_schedule_email") or {}
        client_schedule_email = doc.get("client_schedule_email") or confirmation.get("client_schedule_email") or {}
        schedules.append({
            "email_id": doc.get("email_id"),
            "requirement_id": doc.get("requirement_id"),
            "domain": req.get("technology_needed") or req.get("domain") or req.get("job_title") or doc.get("technology") or "Training",
            "client_name": req.get("client_name") or req.get("client_company") or doc.get("client_name") or "Client",
            "client_company": req.get("client_company") or "",
            "client_email": req.get("client_email") or doc.get("to_email") or "",
            "trainer_name": trainer.get("name") or trainer.get("trainer_name") or doc.get("trainer_name") or "Trainer",
            "trainer_email": trainer.get("email") or trainer.get("trainer_email") or doc.get("trainer_email") or "",
            "trainer_phone": trainer.get("phone") or doc.get("trainer_phone") or "",
            "date_time_text": slot.get("date_time_text") or "",
            "start_iso": slot.get("start_iso") or calendar_event.get("start") or "",
            "end_iso": slot.get("end_iso") or calendar_event.get("end") or "",
            "timezone": slot.get("timezone") or "Asia/Kolkata",
            "meet_link": calendar_event.get("meet_link") or calendar_event.get("html_link") or "",
            "calendar_event_id": calendar_event.get("event_id") or "",
            "status": doc.get("status") or confirmation.get("status") or "",
            "slot_ref": doc.get("slot_ref") or "",
            "client_email_sent": bool(client_schedule_email.get("success")),
            "trainer_email_sent": bool(trainer_schedule_email.get("success")),
            "scheduled_at": confirmation.get("scheduled_at") or doc.get("client_confirmed_at") or doc.get("updated_at") or doc.get("created_at"),
        })

    return {"schedules": [_public_doc(item) for item in schedules], "total": len(schedules)}


@router.post("/client-updates/{email_id}/retry-schedule")
async def retry_client_slot_schedule(email_id: str, request: Request):
    db = get_db()
    slot_doc = await db["client_slot_emails"].find_one({"email_id": email_id}, {"_id": 0})
    if not slot_doc:
        raise HTTPException(404, "Client slot update not found")
    if slot_doc.get("status") == "confirmed_scheduled":
        calendar_event = slot_doc.get("calendar_event") or {}
        return {
            "status": "confirmed_scheduled",
            "email_id": email_id,
            "requirement_id": slot_doc.get("requirement_id"),
            "trainer_id": slot_doc.get("trainer_id"),
            "meet_link": calendar_event.get("meet_link") or calendar_event.get("html_link") or "",
            "calendar_event_id": calendar_event.get("event_id"),
            "trainer_email_sent": bool((slot_doc.get("trainer_schedule_email") or {}).get("success")),
            "client_email_sent": bool((slot_doc.get("client_schedule_email") or {}).get("success")),
        }

    confirmation = await db["client_slot_confirmations"].find_one(
        {"client_slot_email_id": email_id},
        {"_id": 0},
        sort=[("updated_at", -1), ("created_at", -1)],
    ) or {}
    reply_text = (
        slot_doc.get("last_client_reply_text")
        or confirmation.get("reply_text")
        or ""
    )
    if not reply_text:
        raise HTTPException(400, "Client confirmation reply is missing. Ask the client to confirm a slot first.")

    message_id = (
        confirmation.get("gmail_message_id")
        or slot_doc.get("client_reply_message_id")
        or f"retry:{email_id}"
    )
    meta = {
        "email_id": message_id,
        "thread_id": confirmation.get("thread_id") or "",
        "received_at": slot_doc.get("client_confirmed_at") or confirmation.get("created_at") or utc_now(),
        "from_email": confirmation.get("client_email") or slot_doc.get("to_email") or "",
        "from_name": confirmation.get("client_name") or slot_doc.get("client_name") or "Client",
        "subject": confirmation.get("subject") or f"Re: {slot_doc.get('subject', '')}",
        "headers": {},
        "message_id_header": message_id,
        "raw_body": reply_text,
        "clean_body": reply_text,
        "snippet": reply_text[:300],
    }
    result = await _process_client_slot_reply_from_meta(
        db,
        message_id,
        request=request,
        meta_hint=meta,
        slot_doc=slot_doc,
    )
    if not result:
        raise HTTPException(400, "Could not retry this client slot confirmation")
    return result


@router.post("/inbox/{email_id}/approve")
async def approve_client_email(email_id: str, payload: dict = {}):
    db = get_db()
    doc = await db["client_emails"].find_one({"email_id": email_id})
    if not doc:
        raise HTTPException(404, "Client email not found")

    reply = doc.get("generated_reply") or {}
    body = payload.get("body") or reply.get("body")
    subject = payload.get("subject") or reply.get("subject") or f"Re: {doc.get('subject', 'Training Requirement')}"
    if not body:
        raise HTTPException(400, "Reply body is required")

    extracted = doc.get("extracted") or {}
    outgoing_reply = {**reply, "subject": subject, "body": body}
    if not payload.get("force") and is_client_clarification_reply(extracted, outgoing_reply):
        existing_clarification = await find_existing_client_clarification_request(
            db,
            from_email=doc.get("from_email", ""),
            requirement_id=doc.get("requirement_id") or "",
            generated_reply=outgoing_reply,
            extracted=extracted,
            exclude_email_id=email_id,
        )
        if existing_clarification:
            await db["client_emails"].update_one(
                {"email_id": email_id},
                {"$set": {
                    "status": "skipped_duplicate_clarification",
                    "auto_send_eligible": False,
                    "duplicate_clarification_email_id": existing_clarification.get("email_id", ""),
                    "duplicate_clarification_sent_at": existing_clarification.get("sent_at"),
                    "duplicate_clarification_checked_at": utc_now(),
                }},
            )
            return {
                "success": True,
                "skipped": True,
                "status": "skipped_duplicate_clarification",
                "existing_email_id": existing_clarification.get("email_id"),
            }

    settings = await _client_inbox_settings(db)
    if settings.get("inboxProvider") in {"imap", "imap_poll", "imap_polling", "smtp_only", "smtp"}:
        smtp_config = await get_admin_email_config(db)
        success, error = await send_email_async(doc.get("from_email", ""), subject, body, smtp_config)
        if not success:
            raise HTTPException(400, error or "Could not send reply through SMTP")
        send_result = {"success": True, "provider": "smtp_imap_mode"}
    else:
        service = get_gmail_service()
        send_result = send_gmail_reply(
            service,
            to_email=doc.get("from_email", ""),
            subject=subject,
            body=body,
            thread_id=doc.get("thread_id", ""),
            in_reply_to=doc.get("message_id_header", ""),
        )
    now = utc_now()
    await db["client_emails"].update_one(
        {"email_id": email_id},
        {"$set": {
            "generated_reply.subject": subject,
            "generated_reply.body": body,
            "status": "approved",
            "sent_at": now,
            "sent_by": payload.get("sent_by") or "recruiter",
            "gmail_send_result": send_result,
        }},
    )
    if doc.get("requirement_id"):
        await db["requirements"].update_one(
            {"requirement_id": doc["requirement_id"]},
            {"$set": {"status": "active", "client_reply_sent_at": now}},
        )
    return {"success": True, "gmail": send_result}


@router.post("/inbox/{email_id}/reject")
async def reject_client_email(email_id: str):
    db = get_db()
    doc = await db["client_emails"].find_one({"email_id": email_id})
    if not doc:
        raise HTTPException(404, "Client email not found")
    if doc.get("requirement_id"):
        await db["requirements"].delete_one({
            "requirement_id": doc["requirement_id"],
            "source": "email_auto",
        })
    await db["client_emails"].update_one(
        {"email_id": email_id},
        {"$set": {"status": "rejected", "rejected_at": utc_now()}},
    )
    return {"success": True}


@router.post("/inbox/{email_id}/regenerate-reply")
async def regenerate_client_reply(email_id: str, payload: dict = {}):
    db = get_db()
    doc = await db["client_emails"].find_one({"email_id": email_id})
    if not doc:
        raise HTTPException(404, "Client email not found")
    settings = await _client_inbox_settings(db)
    context = {
        "subject": doc.get("subject", ""),
        "reply_signature": settings.get("replySignature"),
        "instruction": payload.get("instruction", ""),
    }
    extracted = doc.get("extracted") or {}
    if payload.get("instruction"):
        extracted = {
            **extracted,
            "needs_clarification": [
                *(extracted.get("needs_clarification") or []),
                f"Recruiter instruction: {payload.get('instruction')}",
            ],
        }
    reply = await generate_calhan_reply(extracted, context)
    await db["client_emails"].update_one(
        {"email_id": email_id},
        {"$set": {"generated_reply": reply, "reply_regenerated_at": utc_now()}},
    )
    return {"success": True, "generated_reply": reply}


@router.get("/gmail/auth-status")
async def gmail_auth_status():
    db = get_db()
    return await get_gmail_auth_status(db)


@router.get("/gmail/oauth-url")
async def gmail_oauth_url(redirect_uri: Optional[str] = None):
    try:
        return get_gmail_oauth_url(redirect_uri)
    except FileNotFoundError as exc:
        raise HTTPException(
            400,
            f"{exc}. Download OAuth credentials from Google Cloud and save them as backend/config/credentials.json.",
        )
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.post("/gmail/oauth-callback")
async def gmail_oauth_callback(payload: dict):
    try:
        return save_gmail_oauth_token(
            code=payload.get("code", ""),
            redirect_uri=payload.get("redirect_uri"),
        )
    except Exception as exc:
        raise HTTPException(400, f"Gmail OAuth failed: {exc}")


@router.post("/gmail/renew-watch")
async def gmail_renew_watch():
    db = get_db()
    try:
        return await renew_gmail_watch(db)
    except FileNotFoundError as exc:
        raise HTTPException(
            400,
            (
                f"{exc}. Put your Google OAuth Desktop credentials at "
                "backend/config/credentials.json, then run "
                "python scripts/gmail_auth.py from the backend folder to create token.json."
            ),
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Gmail watch renewal failed: {exc}")


@router.post("/gmail/disconnect")
async def gmail_disconnect():
    try:
        from agents.client_intelligence_agent import TOKEN_PATH
        if os.path.exists(TOKEN_PATH):
            os.remove(TOKEN_PATH)
    except Exception as exc:
        raise HTTPException(500, str(exc))
    db = get_db()
    await db["gmail_sync"].update_one(
        {"sync_id": "default"},
        {"$set": {"disconnected_at": utc_now()}},
        upsert=True,
    )
    return {"success": True, "connected": False}
