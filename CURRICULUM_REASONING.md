# Requirement-driven TOC planning

AI mode now interprets the client proposal before designing its curriculum. It no longer chooses a fixed day sequence and only rewrites outcomes. Manual/template mode remains available explicitly; failed AI planning produces a review-only template draft that existing export and delivery gates reject.

## Pipeline

1. Extract audience, prior knowledge, outcomes, required and excluded topics, constraints, and clarification questions from the request.
2. Match prepared dataset records locally using topic keywords and normalized aliases. Filter excluded module titles and reserve candidates for each requested topic. No embedding API, vector database, semantic index or indexing step is used during generation.
3. Design a new day sequence using the request and matched examples, including source IDs, prerequisite days, workload, measurable outcomes, scenarios, explicit participant deliverables, labs and assessments.
4. Validate day count, topic coverage, exclusions, source IDs, prerequisite order, explicit technology allocations and time budgets. Allow one repair attempt.
5. Run a separate model review against the original proposal and source content. Store coverage, sources, assumptions, questions and review findings with the TOC.
6. Block delivery when validation fails, source review is missing, assumptions need confirmation or requirements need clarification.

The model review is an additional check, not proof of factual accuracy. Source ownership and representative live evaluations remain necessary. No generated content is automatically promoted into approved source knowledge.

## Preparing datasets

Run from `microservices/services/trainer-service`, with `PYTHONPATH` including `microservices`:

```powershell
python -m app.index_curriculum --output prepared-curriculum.json
```

The initial offline preparation produced 2,950 records across 139 domains. The legacy material is marked unreviewed. Each record contains a stable content hash, domain, topic, subtopics, tools, lab, objectives, prerequisites, level, source location, version and review metadata.

Use the existing TOC Knowledge screen or knowledge import API to maintain reviewed content. Prefer small modules describing one teachable outcome rather than an entire fixed-duration course. Include:

- Explicit product/version scope and official documentation URLs.
- Specific subtopics, required prior knowledge, tools, lab deliverables and measurable outcomes.
- A real subject-matter reviewer, review date and curriculum version.
- `review_status: approved` only after checking the content against those sources.

The knowledge screen now exposes reviewer, date, version and review status. The API rejects approved records without provenance metadata. A URL or review flag is not independently verified by the application; review access must be controlled by the deployment's authentication layer.

## Excel layouts and repeat clients

New TOCs default to reference-inspired `execution_plan`, `technical_plan`, `skills_matrix`, and `detailed_syllabus` layouts. Each preserves the same validated topics, dates, timing, labs, outcomes and assessments. These are structural adaptations of the supplied examples, not exact visual copies. The original files are not dependencies of the deployed application.

`POST /toc/generate` accepts `excel_layout` (default `auto`) and `client_email`. If the address is omitted, the linked requirement's client email/sender is used. Addresses are normalized before looking up previous TOCs. Sequential new TOCs for a sender cycle through the four layouts. Regenerating a supplied `toc_id` retains its saved layout; an explicit layout overrides automatic selection. Concurrent requests may select the same next layout because selection uses generation history rather than a locked counter. A download only renders the stored selection. Records predating layout selection retain the original green/orange export; `legacy` explicitly requests that format.

The generation model still incurs normal API usage: brief extraction, curriculum planning, independent review, and at most one repair. Local dataset matching adds no embedding usage. The legacy `index_curriculum --embed` utility is not needed and is not called by this flow.

## Validation and operational limits

Tests cover source preparation, content invalidation, local matching with zero embedding calls, sender layout selection, Excel content preservation, different client context, omitted topics, forbidden topics, invented source IDs, prerequisite order, overload, source review and failed reviewer output. Model calls are mocked in these tests. Run real evaluations on contrasting client proposals before claiming content accuracy.

Current planning supports whole-day schedules. Daily training hours must be supplied separately from lab-access hours. Clarifications should be resolved in the request and the TOC regenerated. Source corrections should be reviewed and saved; restart the trainer service when changing built-in dataset files because those records are cached in-process. Unreviewed drafts cannot be sent by the existing TOC delivery gates.

Related service corrections: required lab attachments block handoff; trainer matching requires skill eligibility; ambiguous availability replies require review; profile claims require evidence confirmation; AI-supplied resume scores cannot inflate local ranking; exhausted chat providers return a failure; no-show claims can expire; Twilio/Meta callbacks verify signatures. Configure `META_APP_SECRET`, `META_WEBHOOK_VERIFY_TOKEN`, and, behind a proxy, `TWILIO_WEBHOOK_BASE_URL` as the public origin used by Twilio.

Password recovery now reports unavailable rather than creating unusable tokens or claiming email delivery. The existing password sign-in is a frontend stub; implementing server-side authentication and recovery remains separate unfinished work. These changes do not make the app's overall access-control system production-ready.

## Supplied references and module-level planning (2026-09-22)

The five supplied files are imported into `app/reference_curricula/` as 64 reference units (18 BI, 8 engineering/security, 10 AWS day units, 13 QE/core-leadership, 15 Codex modules). Imports retain source filenames, SHA-256 hashes, sheet/row or module locators, available durations, outcomes, labs, deliverables and individual scenarios. They are unreviewed examples, not approved facts or paired client requirements. The BI duration conflict and the Codex title/duration issues are recorded. No original client email was invented.

Regenerate these portable JSON files with `python -m app.import_reference_curricula --source-dir <reference-folder>`. The PDF import retains module text as source evidence; it does not pretend that prose contains a fully structured lab or timed schedule. The importer is an offline maintenance command, not a runtime dependency.

AI planning now produces individually timed modules within days. Coverage checks inspect actual modules, module minutes must sum to day minutes, citations must be valid, and modules need labs, scenarios, deliverables, outcomes and assessments. Excel exports one row per module and keeps the programme day count separate from its module count. Scenario references retain one row per scenario and its own evidence. Readiness sheets expose supplied prerequisites, assumptions, questions and constraints.

AI OFF recognizes exact reference course names and selected aliases. It creates review-only reference drafts, preserving the original module times. It does not silently squeeze the BI four-day schedule into two days. Long QE modules may span days with explicit continuation labels and a trainer-review warning. Missing Codex module times stay unknown. Other domains retain the established deterministic dataset path.

The local trainer and document containers were backed up, updated and restarted. Both health endpoints passed. Container file updates are local; build/publish the repository images to make the deployment reproducible after container recreation. A live AI attempt reached the configured provider but returned HTTP 429 `credit_balance_exhausted`; live model output could not be verified. Unit tests mock model responses and do not establish factual accuracy.

## Offline completion and review downloads

AI OFF now rejects the legacy implicit AI-enrichment path: even `allow_ai_enrichment=true` causes no model call. Explicit topic lists select matching reference modules (title matches first), preserve source order, and report unmatched topics. Known module hours remain intact when repacking to a new daily budget. Continuations receive separate topic portions. Unknown module hours can receive explicitly proposed allocations from the client budget; these are estimates requiring trainer review, not source facts.

Offline completion preserves supplied activities and fills missing labs, deliverables, scenarios, outcomes and assessments with topic-based proposals recorded in `proposed_fields`. Both reference and ordinary dataset outputs contain module arrays. Known client identities in reference text are replaced with sample-organisation wording. Training dates use the existing business-day scheduler.

The Shortlist and Shortlist1 download actions request `draft: true` for review-required results. The document API returns a prominently titled DRAFT workbook with review issues on Readiness & Risks; it does not change the TOC approval status. Ordinary exports and email delivery still enforce the original quality gate. Long cell text is split across continuation rows to avoid Excel's row-height cap; hours appear once and totals cover all schedule rows.

Verified five AI-OFF plans in the running trainer using an in-memory database: engineering/security 2 days / 12 hours, AWS security 10 / 40, QE 18 / 72, Codex 3 / 24 (estimated module times), and Python 2 / 8. These checks sent no emails and created no live TOC database records. The local frontend pages and backend modules were backed up and activated; published container images still require the normal build/release process.
