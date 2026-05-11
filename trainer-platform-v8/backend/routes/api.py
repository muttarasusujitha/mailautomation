from fastapi import APIRouter, UploadFile, File, HTTPException
from typing import Optional
from datetime import datetime
import uuid

from database import get_db
from utils.excel_parser import parse_excel_file
from agents.pipeline import run_pipeline
from agents.email_agent import (
    send_bulk_emails, check_email_replies,
    send_email_async, compose_retry_email, compose_interview_email
)
from models.schemas import RequirementCreate

router = APIRouter()


# ─── Upload Trainer Excel ─────────────────────────────────────────────────────

@router.post("/trainers/upload")
async def upload_trainers(file: UploadFile = File(...)):
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(400, "Only .xlsx or .xls files accepted")
    content = await file.read()
    try:
        trainers = parse_excel_file(content)
    except Exception as e:
        raise HTTPException(400, f"Failed to parse Excel: {e}")
    db = get_db()
    inserted = updated = 0
    for t in trainers:
        existing = await db["trainers"].find_one({"trainer_id": t["trainer_id"]})
        if existing:
            await db["trainers"].update_one({"trainer_id": t["trainer_id"]}, {"$set": t})
            updated += 1
        else:
            t["created_at"] = datetime.utcnow()
            await db["trainers"].insert_one(t)
            inserted += 1
    return {"message": f"✅ Parsed {len(trainers)} trainers", "total": len(trainers),
            "inserted": inserted, "updated": updated,
            "sheets_parsed": list(set(t["source_sheet"] for t in trainers))}


# ─── Clear Database ───────────────────────────────────────────────────────────

@router.delete("/database/clear")
async def clear_database():
    """Clear ALL collections — trainers, requirements, shortlists, email_logs"""
    db = get_db()
    results = {}
    for col in ["trainers", "requirements", "shortlists", "email_logs"]:
        r = await db[col].delete_many({})
        results[col] = r.deleted_count
    return {"message": "✅ Database cleared", "deleted": results}


# ─── Get All Trainers ─────────────────────────────────────────────────────────

@router.get("/trainers")
async def get_trainers(status: Optional[str] = None, search: Optional[str] = None,
                       page: int = 1, limit: int = 20):
    db = get_db()
    query = {}
    if status:
        query["status"] = status
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"technologies": {"$regex": search, "$options": "i"}},
            {"location": {"$regex": search, "$options": "i"}},
        ]
    total = await db["trainers"].count_documents(query)
    skip = (page - 1) * limit
    trainers = await db["trainers"].find(query, {"_id": 0}).skip(skip).limit(limit).to_list(limit)
    return {"trainers": trainers, "total": total, "page": page, "pages": -(-total // limit)}


# ─── Create Requirement & Run Pipeline ───────────────────────────────────────

@router.post("/requirements")
async def create_requirement(req: RequirementCreate):
    db = get_db()
    req_id = f"REQ-{uuid.uuid4().hex[:8].upper()}"
    req_dict = req.dict()
    req_dict.update({"requirement_id": req_id, "status": "active", "created_at": datetime.utcnow()})

    all_trainers = await db["trainers"].find({}, {"_id": 0}).to_list(10000)
    if not all_trainers:
        raise HTTPException(400, "No trainers in database. Upload Excel first.")

    result = await run_pipeline(all_trainers, req_dict)
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
        "created_at": datetime.utcnow()
    })

    for t in top_trainers:
        await db["trainers"].update_one(
            {"trainer_id": t["trainer_id"]},
            {"$set": {"match_score": t["match_score"], "rank": t["rank"], "status": "contacted" if req_dict.get("send_emails") else "pending_review"}}
        )

    send_emails = req_dict.get('send_emails', False)
    email_results = await send_bulk_emails(email_payloads) if send_emails and email_payloads else []

    for er in email_results:
        await db["email_logs"].insert_one({
            "email_id": f"EMAIL-{uuid.uuid4().hex[:8].upper()}",
            "trainer_id": er["trainer_id"],
            "trainer_name": er["trainer_name"],
            "requirement_id": req_id,
            "to_email": er["to"],
            "subject": er["subject"],
            "body": er["body"],
            "status": er["status"],
            "error_message": er.get("error_message", ""),
            "sent_at": datetime.fromisoformat(er["sent_at"]) if er.get("sent_at") else None,
            "reply_received": False,
            "retry_count": 0,
            "created_at": datetime.utcnow()
        })

    return {
        "requirement_id": req_id,
        "total_trainers_scanned": len(all_trainers),
        "total_matched": len(result.get("ranked_trainers", [])),
        "top_trainers": len(top_trainers),
        "emails_sent": sum(1 for e in email_results if e["status"] == "sent"),
        "emails_failed": sum(1 for e in email_results if e["status"] == "failed"),
        "top_trainers_list": top_trainers,
    }


# ─── Retry Single Failed Email ────────────────────────────────────────────────

@router.post("/emails/{email_id}/retry")
async def retry_email(email_id: str):
    db = get_db()
    log = await db["email_logs"].find_one({"email_id": email_id})
    if not log:
        raise HTTPException(404, "Email log not found")
    if log.get("retry_count", 0) >= 3:
        raise HTTPException(400, "Max retry attempts (3) reached")

    success, error = await send_email_async(log["to_email"], log["subject"], log["body"])
    await db["email_logs"].update_one(
        {"email_id": email_id},
        {"$set": {
            "status": "sent" if success else "failed",
            "error_message": error if not success else "",
            "sent_at": datetime.utcnow() if success else None,
        },
         "$inc": {"retry_count": 1}}
    )
    return {"success": success, "error": error, "email_id": email_id}


# ─── Schedule Interview ───────────────────────────────────────────────────────

@router.post("/emails/{email_id}/schedule-interview")
async def schedule_interview(email_id: str, interview_date: str = "", interview_link: str = ""):
    db = get_db()
    log = await db["email_logs"].find_one({"email_id": email_id})
    if not log:
        raise HTTPException(404, "Email log not found")

    req = await db["requirements"].find_one({"requirement_id": log["requirement_id"]})
    technology = req.get("technology_needed", "Training") if req else "Training"

    body = compose_interview_email(
        trainer_name=log["trainer_name"],
        technology=technology,
        req_id=log["requirement_id"],
        interview_date=interview_date,
        interview_link=interview_link,
    )
    subject = f"Interview Scheduled — {technology} | {log['requirement_id']}"
    success, error = await send_email_async(log["to_email"], subject, body)

    await db["email_logs"].update_one(
        {"email_id": email_id},
        {"$set": {
            "interview_scheduled": success,
            "interview_date": interview_date,
            "interview_link": interview_link,
            "interview_email_sent_at": datetime.utcnow() if success else None,
        }}
    )
    await db["trainers"].update_one(
        {"trainer_id": log["trainer_id"]},
        {"$set": {"status": "confirmed"}}
    )
    return {"success": success, "error": error}


# ─── Get Requirements ─────────────────────────────────────────────────────────

@router.get("/requirements")
async def get_requirements():
    db = get_db()
    reqs = await db["requirements"].find({}, {"_id": 0}).sort("created_at", -1).to_list(100)
    return {"requirements": reqs}


# ─── Send Shortlist Mail (First Contact / ToC) ─────────────────────────────────

@router.post("/shortlists/send-mail")
async def send_shortlist_mail(payload: dict):
    """Send first-contact or ToC email to a shortlisted trainer and store in conversation thread."""
    db = get_db()
    trainer_id    = payload.get("trainer_id")
    trainer_name  = payload.get("trainer_name")
    to_email      = payload.get("to_email")
    requirement_id= payload.get("requirement_id")
    subject       = payload.get("subject")
    body          = payload.get("body")
    mail_type     = payload.get("mail_type", "first")  # 'first' | 'toc'

    if not to_email or not body:
        raise HTTPException(400, "to_email and body are required")

    success, error = await send_email_async(to_email, subject, body)

    # Store in conversations collection
    msg = {
        "trainer_id":     trainer_id,
        "trainer_name":   trainer_name,
        "to_email":       to_email,
        "requirement_id": requirement_id,
        "subject":        subject,
        "body":           body,
        "mail_type":      mail_type,
        "direction":      "sent",
        "status":         "sent" if success else "failed",
        "error":          error if not success else "",
        "sent_at":        datetime.utcnow(),
    }
    await db["conversations"].insert_one(msg)

    # Also log in email_logs so dashboard counts it
    email_id = f"EMAIL-{uuid.uuid4().hex[:8].upper()}"
    await db["email_logs"].insert_one({
        "email_id":      email_id,
        "trainer_id":    trainer_id,
        "trainer_name":  trainer_name,
        "requirement_id":requirement_id,
        "to_email":      to_email,
        "subject":       subject,
        "body":          body,
        "status":        "sent" if success else "failed",
        "error_message": error if not success else "",
        "sent_at":       datetime.utcnow() if success else None,
        "reply_received":False,
        "retry_count":   0,
        "mail_type":     mail_type,
        "created_at":    datetime.utcnow(),
    })

    # Update trainer status
    if success:
        new_status = "contacted" if mail_type == "first" else "pending_review"
        await db["trainers"].update_one({"trainer_id": trainer_id}, {"$set": {"status": new_status}})

    return {"success": success, "error": error, "email_id": email_id}


# ─── Get Conversation Thread ──────────────────────────────────────────────────

@router.get("/shortlists/thread")
async def get_conversation_thread(trainer_id: str, requirement_id: str):
    """Get full conversation thread (sent + received) for a trainer/requirement pair."""
    db = get_db()

    # Sent messages from conversations collection
    sent = await db["conversations"].find(
        {"trainer_id": trainer_id, "requirement_id": requirement_id},
        {"_id": 0}
    ).sort("sent_at", 1).to_list(100)

    # Received replies from email_logs
    replies = await db["email_logs"].find(
        {"trainer_id": trainer_id, "requirement_id": requirement_id, "reply_received": True},
        {"_id": 0}
    ).sort("replied_at", 1).to_list(100)

    # Merge and sort chronologically
    messages = []
    for m in sent:
        messages.append({**m, "direction": "sent"})
    for r in replies:
        if r.get("reply_text"):
            messages.append({
                "trainer_id":     r["trainer_id"],
                "requirement_id": r["requirement_id"],
                "subject":        f"Re: {r.get('subject','')}",
                "body":           r["reply_text"],
                "direction":      "received",
                "sent_at":        r.get("replied_at"),
                "mail_type":      "reply",
            })

    messages.sort(key=lambda x: x.get("sent_at") or datetime.min)

    return {"messages": messages, "total": len(messages)}


# ─── Get Shortlists ───────────────────────────────────────────────────────────

@router.get("/shortlists/{requirement_id}")
async def get_shortlist(requirement_id: str):
    db = get_db()
    s = await db["shortlists"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    if not s:
        raise HTTPException(404, "Shortlist not found")
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


# ─── Check Replies ────────────────────────────────────────────────────────────

@router.post("/emails/check-replies")
async def manual_reply_check():
    db = get_db()
    replies = check_email_replies(since_days=7)
    processed = 0
    for reply in replies:
        # Extract plain email from "Name <email>" format
        from_raw = reply["from_email"]
        import re as _re
        m = _re.search(r'<([^>]+)>', from_raw)
        from_email_clean = m.group(1) if m else from_raw.strip()

        # Try email_logs first
        log = await db["email_logs"].find_one({"to_email": {"$regex": from_email_clean, "$options": "i"}})
        if not log:
            # Try conversations
            log = await db["conversations"].find_one({"to_email": {"$regex": from_email_clean, "$options": "i"}})
        if log:
            status_map = {"mark_interested": "interested", "mark_declined": "declined", "requires_review": "pending_review"}
            await db["email_logs"].update_many(
                {"to_email": {"$regex": from_email_clean, "$options": "i"}},
                {"$set": {"reply_received": True, "reply_sentiment": reply["sentiment"],
                           "reply_text": reply["body"], "replied_at": datetime.utcnow()}}
            )
            # Also store reply in conversations
            await db["conversations"].insert_one({
                "trainer_id":     log.get("trainer_id"),
                "trainer_name":   log.get("trainer_name"),
                "to_email":       from_email_clean,
                "requirement_id": log.get("requirement_id"),
                "subject":        reply["subject"],
                "body":           reply["body"],
                "direction":      "received",
                "mail_type":      "reply",
                "status":         "received",
                "sent_at":        datetime.utcnow(),
            })
            await db["trainers"].update_one(
                {"trainer_id": log.get("trainer_id")},
                {"$set": {"status": status_map.get(reply["action"], "pending_review")}}
            )
            processed += 1
    return {"replies_found": len(replies), "processed": processed}


# ─── Dashboard Stats ──────────────────────────────────────────────────────────

@router.get("/dashboard/stats")
async def get_dashboard_stats():
    db = get_db()
    total_trainers     = await db["trainers"].count_documents({})
    total_requirements = await db["requirements"].count_documents({})
    total_emails       = await db["email_logs"].count_documents({"status": "sent"})
    total_failed       = await db["email_logs"].count_documents({"status": "failed"})
    total_replies      = await db["email_logs"].count_documents({"reply_received": True})
    interested         = await db["trainers"].count_documents({"status": "interested"})
    declined           = await db["trainers"].count_documents({"status": "declined"})
    pending_review     = await db["trainers"].count_documents({"status": "pending_review"})
    contacted          = await db["trainers"].count_documents({"status": "contacted"})
    confirmed          = await db["trainers"].count_documents({"status": "confirmed"})

    reply_rate    = round((total_replies / total_emails * 100) if total_emails > 0 else 0, 1)
    interest_rate = round((interested / total_replies * 100) if total_replies > 0 else 0, 1)

    recent_emails = await db["email_logs"].find({}, {"_id": 0}).sort("created_at", -1).limit(5).to_list(5)

    # Score distribution
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
        "total_replies": total_replies, "interested_count": interested,
        "declined_count": declined, "pending_review": pending_review,
        "contacted_count": contacted, "confirmed_count": confirmed,
        "reply_rate": reply_rate, "interest_rate": interest_rate,
        "recent_emails": recent_emails, "score_distribution": score_dist,
    }


# ─── Delete Single Trainer ─────────────────────────────────────────────────────

@router.delete("/trainers/{trainer_id}")
async def delete_trainer(trainer_id: str):
    db = get_db()
    result = await db["trainers"].delete_one({"trainer_id": trainer_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Trainer not found")
    return {"message": f"Trainer {trainer_id} deleted", "deleted": True}


# ─── Send Email to Single Shortlisted Trainer ─────────────────────────────────

@router.post("/emails/{email_id}/send-one")
async def send_email_to_one(email_id: str, body: dict = {}):
    db = get_db()
    log = await db["email_logs"].find_one({"email_id": email_id})
    if not log:
        raise HTTPException(404, "Email log not found")

    email_body = log["body"]
    custom_msg = body.get("message", "")
    if custom_msg:
        email_body = f"{custom_msg}\n\n---\n{email_body}"

    success, error = await send_email_async(log["to_email"], log["subject"], email_body)
    if success:
        await db["email_logs"].update_one(
            {"email_id": email_id},
            {"$set": {"status": "sent", "sent_at": datetime.utcnow(), "error_message": ""},
             "$inc": {"retry_count": 1}}
        )
    return {"success": success, "error": error}


# ─── Delete Requirement ────────────────────────────────────────────────────────

@router.delete("/requirements/{requirement_id}")
async def delete_requirement(requirement_id: str):
    db = get_db()
    r = await db["requirements"].delete_one({"requirement_id": requirement_id})
    if r.deleted_count == 0:
        raise HTTPException(404, "Requirement not found")
    # Also remove shortlist
    await db["shortlists"].delete_many({"requirement_id": requirement_id})
    return {"message": f"Requirement {requirement_id} deleted", "deleted": True}
