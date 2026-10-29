from pathlib import Path

p = Path('mailautomation/microservices/services/trainer-service/app/routes/shortlists.py')
s = p.read_text(encoding='utf-8')
start = s.index('@router.post("/send-client-slots")')
before, flow = s[:start], s[start:]
flow = flow.replace('"""Forward trainer availability slots to the client via email."""', '"""Prepare a complete package; only the versioned approval route may send it."""')
flow = flow.replace('    slots_text = _clean(payload.slot_text)', '    slots_text = _clean(payload.slot_text or trainer.get("slot_reply_text"))', 1)
flow = flow.replace("s.get('date_display', '')", "s.get('date_display') or s.get('date', '')").replace("s.get('time_display', '')", "s.get('time_display') or s.get('time', '')")
anchor = '    latest_detail_reply = await db["email_logs"].find_one('
flow = flow.replace(anchor, '''    from app.handoff import package_key, package_response, deliver_approved_package
    cached = await db["client_handoff_packages"].find_one({
        "_id": package_key(payload.requirement_id, payload.trainer_id),
    })
    if cached:
        if cached["status"] == "approved":
            retry_at = cached.get("retry_after")
            if retry_at and retry_at > datetime.utcnow():
                return {"success": False, "retry_pending": True, "retry_after": retry_at,
                        "message": "Approved handoff is queued for retry"}
            return await deliver_approved_package(db, cached)
        return package_response(cached)

''' + anchor, 1)
flow = flow.replace('    wants_lab_cost = True\n', '')
flow = flow.replace('    # Every automated client handoff includes the lab-cost workbook.', '    # Lab costing is required only when the client requested it.')
flow = flow.replace('            logger.exception("Failed to generate lab-cost workbook for client handoff")', '            logger.exception("Failed to generate lab-cost workbook for client handoff")')
flow = flow.replace('    lab_cost_attachment: Optional[bytes] = None', '    lab_cost_attachment: Optional[bytes] = None\n    lab_error = ""')
flow = flow.replace('                logger.error("Lab-cost workbook generation failed: %s", lab_response.text[:300])', '                lab_error = lab_response.text[:1000]\n                logger.error("Lab-cost workbook generation failed: %s", lab_error)')
flow = flow.replace('502, "Could not generate the required lab-cost workbook for the client handoff",', '502, {"message": "Could not generate the requested lab-cost workbook", "upstream_detail": lab_error},')
# Reuse delivery/error handling, but move it behind persisted approval.
send_start = flow.index('            response = await client.post(f"{EMAIL_SVC}/api/v1/email/send", json=email_payload)')
delivery = flow[send_start:]
flow = flow[:send_start]
build_start = flow.rindex('    try:\n        async with httpx.AsyncClient(timeout=30) as client:')
builder = flow[build_start:].split('\n', 2)[2]
builder = '\n'.join(line[8:] if line.startswith('        ') else line for line in builder.split('\n'))
builder = builder.replace('"smtp_config": payload.smtp_config,', '')
builder = builder.replace('"ai_generate": True,', '"ai_generate": False,')
builder = builder.replace('    # Let email-service select AI or the approved template from\n    # the single global setting.  Attachments, slots and all\n    # commercial/lab-cost facts are still created by the system.', '    # Freeze reviewed wording: delivery must not rewrite the approved email.')
flow = flow[:build_start] + builder + '''
    from app.handoff import save_package
    package = await save_package(db, {
        "_id": package_key(payload.requirement_id, payload.trainer_id),
        "package_id": f"PKG-{uuid.uuid4().hex}",
        "requirement_id": payload.requirement_id,
        "trainer_id": payload.trainer_id,
        "status": "pending_approval",
        "created_at": datetime.utcnow(),
        "slot_text": slots_text,
        "email_payload": email_payload,
    })
    return package_response(package)


async def _deliver_client_handoff(package, db):
    # Only called by the durable delivery service after checking approval.
    if package.get("status") != "approved":
        raise HTTPException(409, "Package approval is required")
    email_payload = dict(package["email_payload"])
    settings_doc = await db["settings"].find_one({"key": "admin_settings"}) or {}
    # Keep credentials out of stored/reviewed packages. Use current settings.
    email_payload["smtp_config"] = (settings_doc.get("value") or {}).get("emailCfg") or None
    payload = SendClientSlotsRequest(requirement_id=package["requirement_id"], trainer_id=package["trainer_id"])
    client_email = email_payload["to"]
    slots_text = package["slot_text"]
    slot_count = 3
    try:
        async with httpx.AsyncClient(timeout=60) as client:
''' + delivery
s = before + flow
s = s.replace('    elif handoff_retry_pending:\n', '    elif any(t.get("slot_status") == "pending_approval" for t in trainers):\n        status, current_stage = "in_progress", "client_handoff_pending_approval"\n    elif handoff_retry_pending:\n', 1)
p.write_text(s, encoding='utf-8')
