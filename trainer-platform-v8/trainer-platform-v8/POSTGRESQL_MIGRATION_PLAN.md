# PostgreSQL Migration Plan

This plan moves TrainerSync from the current shared MongoDB database to PostgreSQL while preserving the public string IDs already used by the API, such as `REQ-*`, `TR-*`, `SL-*`, `email_id`, `po_id`, `invoice_id`, and `lead_id`.

The schema draft is in [POSTGRESQL_SCHEMA.sql](POSTGRESQL_SCHEMA.sql).

## Recommendation

Use PostgreSQL as the primary database for TrainerSync business data.

Keep high-variance content in `jsonb` columns instead of forcing it into rigid columns:

- AI analysis results and usage payloads
- Raw resume parsing output
- Provider webhook payloads from Gmail, WhatsApp, and Teams
- Shortlist scoring details and trainer snapshots
- Admin provider configuration objects
- Temporary raw migration documents

This gives the platform relational integrity for core workflows while keeping flexibility for AI and integration data.

## Current MongoDB Collections

The current microservices read and write these collections:

| MongoDB collection | PostgreSQL target |
| --- | --- |
| `auth_users` | `users` |
| `password_resets` | `password_resets` |
| `admin_settings` | `admin_settings` |
| `customers` | `customers` |
| `requirements` | `requirements` |
| `trainers` | `trainers` |
| `resume_uploads` | `resume_uploads` |
| `shortlists` | `shortlists`, `shortlist_trainers` |
| `trainer_slot_responses` | `trainer_slot_responses` |
| `slots` | `slots` |
| `interview_reminders` | `interview_reminders` |
| `email_logs` | `email_logs` |
| `client_emails` | `client_emails`, `approvals` |
| `purchase_orders` | `purchase_orders`, `purchase_order_items` |
| `invoices` | `invoices`, `invoice_items` |
| `journeys` | `journeys`, `journey_steps` |
| `automations` | `automations` |
| `toc_knowledge` | `toc_knowledge` |
| `toc_generations` | `toc_generations` |
| `client_leads` | `client_leads` |
| `trainer_profile_leads` | `trainer_profile_leads` |
| `linkedin_leads` | `linkedin_leads` |
| `email_analysis` | `email_analysis` |
| `ai_usage_logs` | `ai_usage_logs` |
| `whatsapp_logs` | `whatsapp_logs` |
| `teams_logs` | `teams_logs` |
| `gmail_oauth_states` | `gmail_oauth_states` |
| `gmail_watch` | `gmail_watch` |
| `business_excel_sync` | `business_excel_sync` |
| `categorise_jobs` | `categorise_jobs` |

Any collection not mapped above should first be copied into `raw_migration_documents`, then reviewed before adding a first-class table.

## Relationship Model

The central relationships should be:

| Relationship | PostgreSQL enforcement |
| --- | --- |
| Customer to requirements | `requirements.customer_id -> customers.customer_id` |
| Requirement to shortlist | `shortlists.requirement_id -> requirements.requirement_id` |
| Shortlist to trainers | `shortlist_trainers.shortlist_id -> shortlists.shortlist_id`, `shortlist_trainers.trainer_id -> trainers.trainer_id` |
| Requirement to email logs | `email_logs.requirement_id -> requirements.requirement_id` |
| Trainer to email logs | `email_logs.trainer_id -> trainers.trainer_id` |
| Requirement to purchase order | `purchase_orders.requirement_id -> requirements.requirement_id` |
| Purchase order to invoice | `invoices.po_id -> purchase_orders.po_id` |
| Requirement and trainer to slots | `slots.requirement_id`, `slots.trainer_id` |
| Client inbox approvals | `approvals.email_id -> client_emails.email_id` |

The schema uses PostgreSQL `uuid` primary keys internally, but the application-facing IDs remain text and unique. This makes the migration easier because the current routes can continue accepting the same IDs while the database gains foreign keys.

## Migration Phases

### Phase 1: Prepare PostgreSQL

1. Add PostgreSQL to Docker Compose beside MongoDB.
2. Create a new `DATABASE_URL` environment variable.
3. Apply `POSTGRESQL_SCHEMA.sql`.
4. Add a shared PostgreSQL connection helper using `asyncpg` or SQLAlchemy async.
5. Keep MongoDB running as the source of truth during this phase.

### Phase 2: Build ETL Scripts

Create repeatable scripts that read each MongoDB collection, normalize the document, and upsert into PostgreSQL by the public business ID.

Recommended order:

1. `admin_settings`, `users`, `customers`
2. `trainers`, `resume_uploads`
3. `requirements`
4. `shortlists`, then explode embedded `top_trainers` into `shortlist_trainers`
5. `email_logs`, `client_emails`, `approvals`
6. `slots`, `trainer_slot_responses`, `interview_reminders`
7. `purchase_orders`, `purchase_order_items`, `invoices`, `invoice_items`
8. `client_leads`, `trainer_profile_leads`, `linkedin_leads`
9. `toc_*`, `automations`, `journeys`, notification logs, AI logs

Each script should be idempotent:

- Use `INSERT ... ON CONFLICT (...) DO UPDATE`.
- Store Mongo `_id` in `legacy_mongo_id`.
- Store original documents in `raw_migration_documents` for auditability.
- Log skipped or malformed records with the collection name and `_id`.

### Phase 3: Dual Write

For routes with active writes, write to both MongoDB and PostgreSQL for a short transition window.

Start with lower-risk modules:

1. `client_leads`
2. `trainer_profile_leads`
3. `email_logs`
4. `requirements`
5. `shortlists`

During dual write, compare counts and important queries between MongoDB and PostgreSQL.

### Phase 4: Read Switch

Move read paths service by service:

1. Dashboard and stats reads
2. Leads and trainer profile leads
3. Trainers and resume uploads
4. Requirements and shortlists
5. Email inbox and outbound email logs
6. Purchase orders, invoices, slots, reminders

Keep dual write enabled until the highest-traffic workflows have passed production validation.

### Phase 5: PostgreSQL Becomes Source of Truth

1. Disable MongoDB writes.
2. Run a final sync from MongoDB to PostgreSQL.
3. Compare row counts and sampled records.
4. Remove MongoDB connection dependencies from services.
5. Keep a read-only MongoDB backup until the next stable release is complete.

## ETL Notes

### Shortlists

MongoDB stores shortlisted trainers embedded in `shortlists.top_trainers`. PostgreSQL should split this into:

- `shortlists`: one row per requirement shortlist
- `shortlist_trainers`: one row per shortlisted trainer

Keep the complete embedded trainer object in `shortlist_trainers.trainer_snapshot` so no UI data is lost.

### Purchase Orders And Invoices

MongoDB stores `items` as arrays. PostgreSQL should split them into:

- `purchase_order_items`
- `invoice_items`

If an item does not have a clean quantity or unit price, preserve the raw item in `metadata` and default numeric values to `1` and `0`.

### Emails

Use `email_logs` for sent and received operational email events.

Use `client_emails` for client inbox review, approval, rejection, generated replies, and trainer automation state.

Use `approvals` for a normalized approval trail instead of only storing status flags on `client_emails`.

### AI And Raw Payloads

Keep these as `jsonb`:

- `email_logs.ai_analysis`
- `client_emails.generated_reply`
- `client_emails.extracted_requirement`
- `email_analysis.result`
- `ai_usage_logs.request_payload`
- `ai_usage_logs.response_payload`
- `whatsapp_logs.raw_payload`
- `teams_logs.raw_payload`
- `resume_uploads.parsed_profile`

## Validation Checklist

After ETL, verify:

- Row counts match each MongoDB collection, except embedded arrays now split into child tables.
- Every `requirements.requirement_id` referenced by `shortlists`, `email_logs`, `slots`, `purchase_orders`, and `invoices` exists.
- Every `shortlist_trainers.trainer_id` either exists in `trainers` or is null with a preserved `trainer_snapshot`.
- Recent dashboard totals match MongoDB for requirements, trainers, email sends, client requests, shortlists, WhatsApp logs, and Teams logs.
- API pages still support existing IDs like `REQ-*`, `TR-*`, `SL-*`, and `email_id`.
- Search and filters are covered by indexes before production traffic moves.

## Application Changes Needed

The code migration should be done after the schema is accepted:

1. Replace `shared/database/connection.py` with a PostgreSQL helper or add a parallel `postgres_connection.py`.
2. Add repository modules per service, such as `RequirementRepository`, `TrainerRepository`, and `EmailLogRepository`.
3. Convert Mongo query operators into SQL query builders.
4. Convert embedded updates like `top_trainers.$.pipeline_status` into updates on `shortlist_trainers`.
5. Convert Mongo aggregations in dashboard and stats routes into SQL aggregate queries.
6. Add database tests for the repository layer before switching reads.

## First Implementation Target

Start with `client_leads` or `trainer_profile_leads`. They are self-contained, already use stable `lead_id` values, and have fewer cross-table dependencies than requirements, shortlists, and email automation.
