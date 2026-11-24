# Service, agent and decision-logic review

Scope: all nine application services, with focused source tracing of agent decisions, matching, classification, extraction, handoff, scheduled claims, meeting lifecycle and delivery boundaries. This is not a line-by-line review of every route or a live semantic benchmark. No application changes or external deliveries were made. Test results are from the preceding audit in this session: 437 passed, 1 failed, 2 skipped, plus 3 passing subtests.

## Architecture

The system combines rule-based decisions, model-assisted content generation and stateful delivery automation. The core orchestrator reads recent client emails, requirements, shortlists and scheduled interviews; it creates deduplicated agent-decision records. Its `/run` endpoint logs recommendations rather than executing those recommendations. Actual effects occur in individual service routes and scheduler tasks. A `requires_human` field in the decision log alone does not prove that every execution route enforces that decision.

### Six named core agents

Source: `mailautomation/microservices/services/core-api/app/routes/agent_orchestrator.py`.

| Agent | Actual decision logic | Limitation |
| --- | --- | --- |
| Client requirement | Checks technology, duration and budget; preserves supplied confidence; malformed confidence becomes zero | Field presence does not validate consistency or factual correctness |
| Trainer matching | Sorts existing shortlist scores, removes declined/rejected/unavailable trainers | Reuses upstream scores rather than independently evaluating suitability |
| Outreach | Recommends clarification or shortlist review; always requests human review | Creates a recommendation, not a sent email |
| Commercial | Budget plus dates produces a comparison recommendation at fixed confidence 0.86 | This recommendation does not itself calculate or approve the commercial offer |
| Interview scheduling | A meeting link produces a reminder recommendation at fixed confidence 0.90 | Helper does not require a valid interview timestamp even though its reason claims one exists |
| Exception review | Creates a review recommendation for low-confidence, explicitly flagged or non-allowlisted actions | No approval execution loop is established by these routes |

Common gate: confidence below 0.70, explicit review, or actions outside SAFE_AUTO_ACTIONS require review. Deterministic hashes and MongoDB unique IDs deduplicate identical decision records.

## Service assessment

| Service | Logic and safeguards | Assessment |
| --- | --- | --- |
| Core API | Requirement normalization, trainer scoring, commercial options and the six recommendation roles | Useful workflow decisions; fixed confidence is not calibrated model accuracy |
| Trainer | Separate matching endpoint; dataset/AI TOCs; scope and duration gates; profile-gap analysis; lab planning; shortlist/finance workflows | Substantial validation, but required-document completion has a confirmed failure |
| Email | Keyword classification and ordered scenario overrides; contextual drafts; human-review and confidence checks; recipient guards and idempotent sending | Extensive fixture coverage; ambiguous language and override paths need more semantic evaluation |
| Intelligence | Provider-backed chat; regex plus AI requirement extraction; keyword reply analysis and intent scores | Mixed quality: some endpoints named AI are simple keyword rules; chat hides total provider failure |
| Document | PDF/DOCX extraction, OpenAI then Gemini then regex profile extraction; normalization; document and workbook generation | Source-only LinkedIn extraction is a useful safeguard; other generated fields and ranking still need stronger evidence validation |
| Scheduler | Inbox polling, follow-ups, interview/start/no-show notices; delivery tracking and atomic claims | Useful duplicate protection; no-show claim recovery has a crash-related gap |
| Meet bot | Due-meeting claims, stale-claim recovery, browser joining, attendance observation, speech/chat welcome and concurrent lifecycle management | Operational automation; live admission and participant receipt of audio remain unverified |
| Notification | Teams/WhatsApp delivery and callback status updates | Delivery infrastructure; webhook trust boundaries remain defective |
| Auth | Authentication-related routes, admin configuration and reset-token creation | Infrastructure; password-reset email delivery is unfinished |

## Concrete logic findings

1. **Required lab workbook can be missing while handoff completes.** The existing regression fails at `trainer-service/tests/test_client_handoff_package.py:125`. `trainer-service/app/routes/shortlists.py:3942` continues after failure; line 4193 can mark completion. The attachment wording also checks intermediate provider results rather than the final attachment. Highest workflow priority: either require the full package or persist explicit partial completion with a pending lab task.

2. **Trainer matching accepts false skill matches and candidates with no requested skill.** In `trainer-service/app/routes/matching.py:16`, substring matching awards Java credit for JavaScript. An isolated execution of the actual scoring function returned 10 for this case. A Python request against an Excel-only trainer with ten years of experience and resume rank 100 returned 35. The route accepts any positive score. These examples apply to this matching endpoint; core-api has a separate scorer and must not be assumed to behave identically. Require skill eligibility before experience/rank bonuses and use normalized skill identities. The endpoint also compares day_rate against a generic budget, so callers must establish a common rate basis.

3. **Reply analysis can turn partial availability into a decline.** `intelligence-service/app/routes/ai.py:42` checks negative substrings before positive ones. Evaluating its actual keyword lists on “I am not available Monday, but available Tuesday.” produces `mark_declined`. With an email ID, this endpoint writes the action into the email log; it does not directly establish that the trainer record is rejected. Add a separate partial-availability/clarification outcome and interpret the current reply separately from quoted history.

4. **Profile fallback overstates evidence.** `trainer-service/app/routes/profile_enhancements.py:73` treats substring presence as confirmed skill evidence and proposes “Applied [skill] in relevant delivery, implementation, or training assignments,” with `requires_trainer_confirmation=False`. Mentioning a skill does not establish practical delivery experience. The AI instructions are more cautious than this fallback. Preserve source wording and require confirmation for inferred experience.

5. **Resume scores can retain unsupported AI inflation.** `document-service/app/routes/resume.py:359` takes the maximum of computed completeness and supplied profile_score, then uses it for resume_rank_score and trainer_rating without an upper bound there. The upload route sets needs_review=False when an AI profile has a name. Neither a name nor completeness proves factual accuracy. Validate evidence and score ranges independently of provider output.

6. **No-show claims lack an expiry in the claim predicate.** `scheduler-service/app/tasks/no_show_notices.py:90` only claims records where no_show_check_claimed is not true. Normal completion clears the claim, but a process death after claiming can leave it permanently excluded by this path. No recovery mechanism was established in this review. Add an expiring claim, as the meet-bot already does for its lifecycle records.

7. **Existing provider-failure and infrastructure issues remain.** Assistant chat returns success after all providers fail; notification callbacks do not enforce adequate signature validation; reset-token creation does not deliver the reset email. See the companion service audit for exact paths and details.

## Frontend policy

`frontend/src/utils/batchEmailRules.js` distinguishes proposal from confirmed requirement, prohibits invented trainer details, keeps selection/booking/payment separate from scope confirmation, and includes commercial disclosure instructions. These are prompt instructions, not backend state or pricing enforcement. Corresponding backend validation remains necessary. Its three existing utility tests passed in the preceding audit.

## Recommended order

1. Correct handoff completion and callback authentication.
2. Fix matching eligibility, partial-availability interpretation and profile evidence handling.
3. Make provider failure explicit and implement claim expiry/recovery.
4. Enforce shared business rules at execution boundaries, then evaluate representative ambiguous emails, profiles, TOCs and lab requirements with expected outcomes.

The reviewed system has meaningful workflow safeguards but does not yet support a claim that every agent's reasoning or every execution path is verified. Prior lab credit exhaustion applies only to the tested account/path; no live provider calls were made during this review.
