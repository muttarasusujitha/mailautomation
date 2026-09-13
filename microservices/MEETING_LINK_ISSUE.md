# Meeting link send failure

Recorded: 2026-09-05
Status: Code fix applied; Google Calendar authorization confirmed; delivery verification pending.

## Latest verification

After the user reconnected Gmail, the live `/api/v1/gmail/auth-status` check returned `connected: true`, `valid: true`, `calendar_connected: true`, and `calendar_ready: true`. The saved scopes include Google Calendar. The authorization blocker is cleared; meeting-link creation and recipient delivery still need verification.

## Issue

Meeting-link sending is still blocked. The live email service is healthy and Gmail is connected, but `/api/v1/gmail/auth-status` reports:

```json
{"connected":true,"valid":true,"calendar_connected":false,"calendar_ready":false}
```

## Finding and fix

The Gmail credential loader supplied Gmail-only scopes when loading the shared OAuth token. Saving that token after refresh could remove the stored Calendar scope. All three credential loaders now preserve the scopes stored in the token rather than overriding them:

- `services/email-service/app/gmail_client.py`
- `services/email-service/app/calendar_client.py`
- `services/email-service/app/routes/gmail.py`

The scope-preservation regression test passed, and Python compilation checks passed. The email-service Docker image was rebuilt and its container restarted successfully. The health endpoint returned `status: ok` after restart.

Regression test: `services/email-service/tests/test_oauth_scope_preservation.py`.

## Remaining steps

1. Reconnect Gmail in the application and grant Google Calendar permission.
2. Verify `calendar_connected` and `calendar_ready` are both `true`.
3. Retry the intended meeting-link send and verify delivery to the intended recipients. Check existing events and delivery records before retrying to avoid duplicates.

No meeting invitation or email was manually sent during this investigation. Successful meeting-link delivery has not been verified. Do not mark the issue resolved until authorization and delivery are confirmed.
