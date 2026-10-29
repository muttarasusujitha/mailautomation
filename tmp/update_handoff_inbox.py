from pathlib import Path
p = Path('mailautomation/microservices/services/email-service/app/routes/inbox.py')
s = p.read_text(encoding='utf-8')
s = s.replace('async with httpx.AsyncClient(timeout=90) as client:\n            response = await _post_with_local_fallback(\n                client,\n                f"{TRAINER_SERVICE_URL}/api/v1/shortlists/send-client-slots"', 'async with httpx.AsyncClient(timeout=300) as client:\n            response = await _post_with_local_fallback(\n                client,\n                f"{TRAINER_SERVICE_URL}/api/v1/shortlists/send-client-slots"', 1)
lines = s.splitlines(keepends=True)
variable = None
for i, line in enumerate(lines):
    if 'handoff_retry_pending = _client_handoff_retry_pending(' in line:
        variable = line.split('_client_handoff_retry_pending(')[1].split(')')[0]
    if variable and 'handoff_retry_pending' in line:
        if '"status":' in line:
            lines[i] = line.replace('"status": ', f'"status": "processed" if {variable}.get("pending_approval") else ', 1)
        elif '"reply_status":' in line:
            lines[i] = line.replace('"reply_status": ', f'"reply_status": "client_handoff_pending_approval" if {variable}.get("pending_approval") else ', 1)
s = ''.join(lines)
# Email service's /send endpoint owns the one successful outbound log.
anchor = s.index('    if handoff_in_progress:', s.index('async def _handle_trainer_slot_reply'))
start = s.index('    await db["email_logs"].insert_one({', anchor)
end = s.index('    retry_pending = not success', start)
block = s[start:end]
s = s[:start] + '    if not success:\n' + ''.join('    ' + line if line.strip() else line for line in block.splitlines(keepends=True)) + s[end:]
p.write_text(s, encoding='utf-8')
