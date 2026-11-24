# Service and agent audit — 21 September 2026

Scope: source review of all nine application services, available service unit
tests, Docker health status, and read-only confirmation of selected deployed
code. This is not an exhaustive security audit or a live AI accuracy benchmark.
No email, WhatsApp/Teams message, or meeting join was initiated by this audit.

## Findings, in priority order

1. **High — notification webhook authentication does not reject invalid requests.**
   `notification-service/app/routes/whatsapp_webhooks.py:32-58` returns true when
   the Twilio token is absent or verification throws; the inbound handler only
   logs a bad signature and continues processing. Missing signatures bypass the
   check. Confirmed these paths also exist in deployed code. Meta verification
   accepts any token when the expected token is empty (line 109), and the receive
   handler beginning at line 115 has no payload-signature verification. Reject
   unauthenticated callbacks before writing data. Network exposure and any
   upstream filtering were not evaluated.

2. **High — required lab attachment failure does not stop client handoff.**
   `trainer-service/app/routes/shortlists.py:3937-3942` continues after lab workbook
   generation fails. The flow can subsequently mark handoff complete at line
   4193. The required-document regression test fails for the lab case. Confirmed
   the continuation path in deployed code. Additionally, the body chooses
   “estimate is attached” from a nonempty partial provider-results list rather
   than the final attachment set (line 3957). Decide whether to block the handoff
   or explicitly record partial completion and pending lab delivery; do not
   represent the full package as delivered.

3. **Medium — AI chat reports success even when all providers fail.**
   `intelligence-service/app/routes/assistant.py:132-140` substitutes an apology
   when no provider returns a reply, then returns `success: true`. This can hide
   failures from callers and monitoring. Its configuration message also omits
   OpenAI despite OpenAI being the preferred provider. Report a machine-readable
   failure or degraded state. Source finding; no paid provider calls made here.

4. **Medium — password reset delivery is unfinished.**
   `auth-service/app/routes/auth.py:54-58` creates a reset token but does not send
   a reset email. The endpoint returns the usual generic success message. Email
   enumeration protection is appropriate, but users cannot complete this flow
   through that endpoint alone. Source finding; reset delivery was not invoked.

5. **Operational — lab AI credits are exhausted.**
   The earlier live lab-planner check returned HTTP 429 with
   `credit_balance_exhausted`. Default AI planning is deployed and its template
   fallback passes tests. This finding applies to that tested account/path;
   other services and providers were not live-tested for available credit.

## Service test results

| Service | Result | Scope / limits |
|---|---|---|
| Core API | 33 passed | Agent decisions, matching, review gates and workflow tests |
| Trainer | 160 passed, 1 failed | Failure: required lab document does not prevent handoff |
| Document | 34 passed, 2 skipped | Local skips require LibreOffice; deployed calculator was separately verified earlier |
| Email | 168 passed, 3 subtests passed | Includes routing, recipient protection, idempotency and workflow cases |
| Intelligence | 2 passed | Only requirement-duration extraction is covered by this service suite |
| Scheduler | 15 passed | Follow-up and interview notice logic with mocked delivery |
| Meet bot | 13 passed | Mocked browser/voice/lifecycle checks; no actual meeting reception test |
| Auth | No dedicated service tests found | Source review only |
| Notification | No dedicated service tests found | Source review plus deployed webhook source confirmation |

Total: **425 passed, 1 failed, 2 skipped**, plus 3 passing subtests.
Initial intelligence/scheduler collection errors came from local `DEBUG=release`;
rerunning with test-process `DEBUG=false` resolved them. Meet tests used the
existing workspace `.test-deps` Playwright package after the default Python path
could not find it. No runtime configuration was changed for the audit.

## Deployment observations and assessment

All nine application containers and the gateway reported healthy. MongoDB and
Redis also reported healthy. Celery worker/beat and frontend were running, which
does not independently verify their business workflows or external integrations.

The system mixes deterministic automation with model-assisted workflows. Passing
unit tests establish behavior for those fixtures, not semantic accuracy of every
AI response. Broader live evaluation still needs representative requirements,
trainer profiles, TOCs and email threads with expected outcomes, working provider
accounts, and controlled external-delivery/meeting tests. Fix the webhook and
handoff findings before treating all-service quality as verified.

No application fixes or redeployments were performed during this audit.
