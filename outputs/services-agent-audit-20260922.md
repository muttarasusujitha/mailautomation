# Service and agent audit continuation - 22 September 2026

Rechecked the current `mailautomation` working tree, reran seven service test suites and frontend utility tests, and read Docker container status. Existing uncommitted application changes were preserved. No application fixes, deployments, external messages, meeting joins, or live AI-provider calls were performed.

## Confirmed results

| Component | Result |
| --- | --- |
| Core API | 33 passed |
| Trainer | 160 passed, 1 failed |
| Document | 34 passed, 2 skipped |
| Email | 168 passed, plus 3 passing subtests |
| Intelligence | 2 passed |
| Scheduler | 15 passed |
| Meet bot | 13 passed |
| Frontend utilities | 12 passed |
| Auth and Notification | No dedicated service test files found |

Total: **437 passed, 1 failed, 2 skipped**, plus 3 passing subtests. Document skips require a LibreOffice/soffice calculator. Frontend coverage includes batchEmailRules, handoffStatus, and trainerIdentity.

All nine application containers reported healthy, as did the gateway, MongoDB, and Redis. Frontend and Celery worker/beat were running. Health status does not establish business-workflow correctness or AI accuracy.

## Unresolved findings

1. **High: required lab workbook failure still permits client handoff.** `microservices/services/trainer-service/tests/test_client_handoff_package.py::test_missing_required_document_prevents_send_and_completion[lab]` fails because the route does not raise the expected HTTPException. The log explicitly reports proceeding without the workbook. In `app/routes/shortlists.py`, line 3942 continues, while line 4193 can mark handoff complete. Line 3957 checks intermediate lab attachments to choose the attachment claim, although the final workbook requires all requested providers. This also leaves a partial-provider case where the email can claim an attachment that was not added. The code comments express conflicting policies; either block incomplete required packages or implement explicit partial completion and pending delivery consistently.

2. **High: webhook authentication remains permissive.** `microservices/services/notification-service/app/routes/whatsapp_webhooks.py` still accepts absent configuration or validation exceptions in `_verify_twilio_signature`, continues after invalid inbound signatures, and skips verification for missing signatures. Twilio status callbacks also update records without checking signatures. Meta verification accepts arbitrary tokens when the expected token is empty; Meta POST payloads have no signature verification. These are current source findings; no unauthenticated requests were sent to the running service.

3. **Medium: assistant chat still reports success after every provider fails.** `microservices/services/intelligence-service/app/routes/assistant.py` returns `success: True` after substituting an apology for an empty reply. The configuration advice omits the preferred OpenAI provider. Only two requirement-duration tests exist in this service suite; these do not validate chat quality or provider fallback behavior.

4. **Medium: password-reset email delivery remains unfinished.** `microservices/services/auth-service/app/routes/auth.py:57` records the intended email step as a comment and only logs token creation. The generic success response protects against enumeration but does not establish delivery.

## Live evaluation limits

The 21 September report recorded HTTP 429 `credit_balance_exhausted` on the lab AI-planner path. This continuation did not retry that paid provider call, so its present credit balance is unknown. That historical result cannot establish availability of other providers or services.

The passing tests establish behavior for their fixtures, mostly with mocked dependencies. Live TOC correctness, resume extraction accuracy, draft factuality, requirement interpretation, meeting audio reception, and external delivery remain unverified. A full quality claim still requires representative fixtures with expected outcomes and controlled live evaluation.

## Reproduction notes

Run each service's `python -m pytest tests -q --disable-warnings --tb=short` from its own directory, with process-local `DEBUG=false` and PYTHONPATH including the repository `microservices` directory and workspace `.test-deps`. Initial collection failures caused by an omitted shared-module path were corrected before recording results. Run frontend checks using `npm.cmd test --prefix frontend` from `mailautomation`; the PowerShell npm wrapper is blocked by the local execution policy. Docker health was read with approved elevated access after sandbox access was denied.
