# Logic fixes and TOC validation

Implemented in the mailautomation working tree; not deployed. Existing unrelated edits were preserved.

## Results

| Suite | Passed | Skipped |
| --- | ---: | ---: |
| Trainer | 175 | 0 |
| Document | 35 | 2 |
| Email | 168 | 0 |
| Intelligence | 8 | 0 |
| Scheduler | 15 | 0 |
| Meet bot | 13 | 0 |
| Core API | 33 | 0 |
| Notification | 5 | 0 |
| Auth | 1 | 0 |
| Frontend utilities | 12 | 0 |

Total: **465 passed, 2 skipped**, plus 3 passing email subtests. Frontend production build passed. Document skips require LibreOffice. Targeted TOC tests were rerun after preserving date enrichment. No external email, notification or meeting action was initiated.

## Delivered

- Requirement interpretation, topic retrieval, fresh curriculum planning, one repair attempt and a separate source/scope review replace the fixed AI backbone.
- Hybrid semantic/keyword retrieval, model/content-addressed embedding caching, offline preparation and an explicit full-index CLI.
- 2,950 prepared source records across 139 domains; legacy sources remain unreviewed.
- Source IDs, coverage matrix, assumptions, questions and quality failures are persisted with the TOC.
- Reviewed-source fields and validation; visible review warnings; separate training versus lab hours in the TOC UI.
- Required lab failure blocks handoff. Matching, mixed reply interpretation, profile evidence, resume ranking, chat failures, no-show claim recovery, interview recommendation inputs and webhook validation were corrected.

## Remaining operational work

Live indexing and provider-backed curriculum evaluation have not been run. Provider access/credit and reviewed source content are still required. The deterministic and mocked tests do not prove factual curriculum accuracy. No deployment was performed.

Password recovery now honestly returns unavailable instead of producing an unusable token. Investigation found frontend-only password sign-in with no server password verifier; implementing real authentication and a complete recovery flow remains unfinished. Webhook configuration now needs valid Twilio/Meta secrets and the correct public callback origin.

See `mailautomation/CURRICULUM_REASONING.md` for preparation, index commands, source review and limitations.
