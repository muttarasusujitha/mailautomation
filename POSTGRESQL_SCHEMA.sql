-- TrainerSync PostgreSQL initial relational schema.
-- This is a migration target for the current MongoDB collections used by the
-- microservices stack. High-variance AI, resume, webhook, and provider payloads
-- stay in jsonb while operational relationships are normalized.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

CREATE SCHEMA IF NOT EXISTS trainersync;
SET search_path TO trainersync, public;

CREATE OR REPLACE FUNCTION trainersync.set_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text UNIQUE NOT NULL,
    name text NOT NULL,
    email citext UNIQUE NOT NULL,
    password_hash text,
    role text NOT NULL DEFAULT 'user',
    status text NOT NULL DEFAULT 'active',
    last_login_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    legacy_mongo_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS password_resets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text REFERENCES users(user_id) ON DELETE CASCADE,
    email citext NOT NULL,
    reset_token_hash text NOT NULL,
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS admin_settings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    settings_id text UNIQUE NOT NULL DEFAULT 'default',
    email_config jsonb NOT NULL DEFAULT '{}'::jsonb,
    twilio_config jsonb NOT NULL DEFAULT '{}'::jsonb,
    whatsapp_config jsonb NOT NULL DEFAULT '{}'::jsonb,
    teams_config jsonb NOT NULL DEFAULT '{}'::jsonb,
    teams_direct_config jsonb NOT NULL DEFAULT '{}'::jsonb,
    scheduler_config jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    legacy_mongo_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS customers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id text UNIQUE NOT NULL,
    name text NOT NULL,
    email citext UNIQUE NOT NULL,
    company text,
    phone text,
    linkedin_url text,
    notes text,
    tags text[] NOT NULL DEFAULT '{}',
    status text NOT NULL DEFAULT 'active',
    priority text NOT NULL DEFAULT 'medium',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    legacy_mongo_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS client_leads (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id text UNIQUE NOT NULL,
    company_name text NOT NULL,
    contact_name text,
    email citext,
    phone text,
    domain text,
    source text NOT NULL DEFAULT 'manual',
    linkedin_url text,
    website text,
    status text NOT NULL DEFAULT 'new',
    notes text,
    draft_subject text,
    draft_body text,
    draft_regenerated_at timestamptz,
    last_emailed_at timestamptz,
    intent_score numeric(5, 4),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    legacy_mongo_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS requirements (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    requirement_id text UNIQUE NOT NULL,
    customer_id text REFERENCES customers(customer_id) ON DELETE SET NULL,
    source_email_id text,
    title text NOT NULL,
    job_title text,
    description text,
    technology_needed text NOT NULL,
    domain text,
    required_skills text[] NOT NULL DEFAULT '{}',
    preferred_skills text[] NOT NULL DEFAULT '{}',
    required_certifications text[] NOT NULL DEFAULT '{}',
    client_name text,
    client_company text,
    client_email citext,
    client_phone text,
    client_whatsapp text,
    budget numeric(14, 2),
    budget_increase_amount numeric(14, 2),
    budget_increase_requested boolean NOT NULL DEFAULT false,
    budget_increase_requested_at timestamptz,
    duration_days numeric(8, 2),
    duration_hours numeric(8, 2),
    duration_text text,
    participant_count integer,
    location text,
    preferred_location text,
    delivery_mode text,
    mode text,
    timing text,
    training_dates text,
    timeline_start text,
    timeline_end text,
    top_n integer NOT NULL DEFAULT 5,
    min_experience_years numeric(5, 2) NOT NULL DEFAULT 2,
    must_have_linkedin boolean NOT NULL DEFAULT false,
    must_have_resume boolean NOT NULL DEFAULT false,
    send_emails boolean NOT NULL DEFAULT false,
    status text NOT NULL DEFAULT 'active',
    priority text NOT NULL DEFAULT 'medium',
    total_matched integer NOT NULL DEFAULT 0,
    top_count integer NOT NULL DEFAULT 0,
    client_po_requested boolean NOT NULL DEFAULT false,
    client_po_requested_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    legacy_mongo_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trainers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    trainer_id text UNIQUE NOT NULL,
    name text NOT NULL,
    trainer_name text,
    email citext,
    trainer_email citext,
    phone text,
    linkedin_url text,
    linkedin text,
    title text,
    role_designation text,
    technologies text,
    skills text[] NOT NULL DEFAULT '{}',
    domains text[] NOT NULL DEFAULT '{}',
    certifications text[] NOT NULL DEFAULT '{}',
    primary_category text,
    technology_category text,
    category text,
    secondary_categories text[] NOT NULL DEFAULT '{}',
    specialisation_tags text[] NOT NULL DEFAULT '{}',
    specialty_tags text[] NOT NULL DEFAULT '{}',
    industry_focus text[] NOT NULL DEFAULT '{}',
    experience_years numeric(5, 2),
    experience_raw text,
    location text,
    daily_rate numeric(14, 2),
    availability text,
    rating numeric(4, 2),
    training_count integer,
    past_clients text[] NOT NULL DEFAULT '{}',
    bio text,
    summary text,
    resume_url text,
    upload_id text,
    source_sheet text,
    resume_rank_score numeric(8, 2),
    match_score numeric(8, 2),
    rank integer,
    status text NOT NULL DEFAULT 'active',
    pipeline_status text,
    combined_text text,
    resume_text text,
    resume jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    legacy_mongo_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trainer_profile_leads (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id text UNIQUE NOT NULL,
    trainer_id text REFERENCES trainers(trainer_id) ON DELETE SET NULL,
    trainer_name text,
    email citext,
    phone text,
    domain text,
    skills text[] NOT NULL DEFAULT '{}',
    linkedin_url text,
    linkedin_slug text,
    source text NOT NULL DEFAULT 'manual',
    status text NOT NULL DEFAULT 'found',
    notes text,
    outreach_subject text,
    outreach_body text,
    outreach_sent_at timestamptz,
    verified_internal_at timestamptz,
    raw_profile jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    legacy_mongo_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS resume_uploads (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    upload_id text UNIQUE NOT NULL,
    trainer_id text REFERENCES trainers(trainer_id) ON DELETE SET NULL,
    filename text,
    original_filename text,
    content_type text,
    file_size_bytes bigint,
    source text,
    status text NOT NULL DEFAULT 'uploaded',
    confirmed boolean NOT NULL DEFAULT false,
    confirmed_at timestamptz,
    extracted_text text,
    parsed_profile jsonb NOT NULL DEFAULT '{}'::jsonb,
    parse_errors jsonb NOT NULL DEFAULT '[]'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    legacy_mongo_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS shortlists (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    shortlist_id text UNIQUE NOT NULL,
    requirement_id text UNIQUE NOT NULL REFERENCES requirements(requirement_id) ON DELETE CASCADE,
    technology_needed text,
    total_matched integer NOT NULL DEFAULT 0,
    total_trainers_scanned integer NOT NULL DEFAULT 0,
    total_available integer NOT NULL DEFAULT 0,
    category_filter_applied boolean NOT NULL DEFAULT false,
    no_category_match boolean NOT NULL DEFAULT false,
    category_match_count integer NOT NULL DEFAULT 0,
    matching_pipeline_version text,
    pipeline_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    pipeline_stage_log jsonb NOT NULL DEFAULT '[]'::jsonb,
    pipeline_warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
    pipeline_errors jsonb NOT NULL DEFAULT '[]'::jsonb,
    auto_created boolean NOT NULL DEFAULT false,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    legacy_mongo_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS shortlist_trainers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    shortlist_id text NOT NULL REFERENCES shortlists(shortlist_id) ON DELETE CASCADE,
    requirement_id text NOT NULL REFERENCES requirements(requirement_id) ON DELETE CASCADE,
    trainer_id text REFERENCES trainers(trainer_id) ON DELETE SET NULL,
    rank integer,
    match_score numeric(8, 2),
    match_quality text,
    score_breakdown jsonb NOT NULL DEFAULT '{}'::jsonb,
    pipeline_status text NOT NULL DEFAULT 'shortlisted',
    email_stage text,
    status text,
    selected boolean NOT NULL DEFAULT false,
    reply_received boolean NOT NULL DEFAULT false,
    reply_text text,
    reply_sentiment text,
    slots jsonb NOT NULL DEFAULT '[]'::jsonb,
    client_slot_sent boolean NOT NULL DEFAULT false,
    client_slot_sent_at timestamptz,
    commercial_status text,
    toc_status text,
    interview_date text,
    interview_link text,
    last_mail_type text,
    last_mailed_at timestamptz,
    last_mail_type_attempted text,
    last_mail_attempted_at timestamptz,
    last_mail_error text,
    recommended_next_action text,
    trainer_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (shortlist_id, trainer_id)
);

CREATE TABLE IF NOT EXISTS email_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email_id text UNIQUE NOT NULL,
    customer_id text REFERENCES customers(customer_id) ON DELETE SET NULL,
    requirement_id text REFERENCES requirements(requirement_id) ON DELETE SET NULL,
    trainer_id text REFERENCES trainers(trainer_id) ON DELETE SET NULL,
    client_lead_id text REFERENCES client_leads(lead_id) ON DELETE SET NULL,
    gmail_message_id text,
    gmail_thread_id text,
    direction text NOT NULL DEFAULT 'outbound',
    mail_type text,
    sender citext,
    recipient citext,
    subject text,
    body_snippet text,
    body text,
    status text NOT NULL DEFAULT 'pending',
    processed boolean NOT NULL DEFAULT false,
    sent_at timestamptz,
    opened_at timestamptz,
    replied_at timestamptz,
    retry_count integer NOT NULL DEFAULT 0,
    error_message text,
    interview_scheduled boolean NOT NULL DEFAULT false,
    interview_mail_sent boolean,
    interview_date text,
    interview_link text,
    interview_slot_start text,
    interview_slot_end text,
    client_slots_sent boolean NOT NULL DEFAULT false,
    client_slots_sent_at timestamptz,
    ai_analysis jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    legacy_mongo_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS client_emails (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email_id text UNIQUE NOT NULL,
    requirement_id text REFERENCES requirements(requirement_id) ON DELETE SET NULL,
    gmail_message_id text,
    gmail_thread_id text,
    from_email citext,
    from_name text,
    to_email citext,
    subject text,
    body text,
    raw_body text,
    status text NOT NULL DEFAULT 'pending_approval',
    reply_status text,
    processed boolean NOT NULL DEFAULT false,
    approved boolean NOT NULL DEFAULT false,
    approved_at timestamptz,
    reply_sent boolean NOT NULL DEFAULT false,
    reply_sent_at timestamptz,
    reply_error text,
    ai_reply text,
    draft_reply text,
    generated_reply jsonb NOT NULL DEFAULT '{}'::jsonb,
    pending_trainer_automation boolean NOT NULL DEFAULT false,
    client_authorized_trainer_search boolean NOT NULL DEFAULT false,
    trainer_automation_status text,
    trainer_automation_error text,
    trainer_automation_failed_at timestamptz,
    mail_automation jsonb NOT NULL DEFAULT '{}'::jsonb,
    extracted_requirement jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    legacy_mongo_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS approvals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_id text UNIQUE NOT NULL,
    resource_type text NOT NULL,
    resource_id text NOT NULL,
    email_id text REFERENCES client_emails(email_id) ON DELETE SET NULL,
    status text NOT NULL DEFAULT 'pending',
    approved_by text REFERENCES users(user_id) ON DELETE SET NULL,
    approved_at timestamptz,
    rejected_by text REFERENCES users(user_id) ON DELETE SET NULL,
    rejected_at timestamptz,
    notes text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trainer_slot_responses (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    response_id text UNIQUE NOT NULL,
    requirement_id text REFERENCES requirements(requirement_id) ON DELETE CASCADE,
    trainer_id text REFERENCES trainers(trainer_id) ON DELETE SET NULL,
    email_id text REFERENCES email_logs(email_id) ON DELETE SET NULL,
    raw_text text,
    parsed_slots jsonb NOT NULL DEFAULT '[]'::jsonb,
    status text NOT NULL DEFAULT 'parsed',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    legacy_mongo_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS slots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slot_id text UNIQUE NOT NULL,
    trainer_id text REFERENCES trainers(trainer_id) ON DELETE SET NULL,
    customer_id text REFERENCES customers(customer_id) ON DELETE SET NULL,
    requirement_id text REFERENCES requirements(requirement_id) ON DELETE SET NULL,
    slot_type text NOT NULL DEFAULT 'trainer',
    start_time timestamptz NOT NULL,
    end_time timestamptz NOT NULL,
    title text,
    description text,
    location text,
    meeting_link text,
    status text NOT NULL DEFAULT 'available',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    legacy_mongo_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS interview_reminders (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    reminder_id text UNIQUE NOT NULL,
    email_id text REFERENCES email_logs(email_id) ON DELETE SET NULL,
    requirement_id text REFERENCES requirements(requirement_id) ON DELETE SET NULL,
    trainer_id text REFERENCES trainers(trainer_id) ON DELETE SET NULL,
    interview_at timestamptz NOT NULL,
    remind_at timestamptz,
    channel text NOT NULL DEFAULT 'email',
    status text NOT NULL DEFAULT 'scheduled',
    sent_at timestamptz,
    cancelled_at timestamptz,
    notes text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    legacy_mongo_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    po_id text UNIQUE NOT NULL,
    po_number text UNIQUE NOT NULL,
    requirement_id text REFERENCES requirements(requirement_id) ON DELETE SET NULL,
    trainer_id text REFERENCES trainers(trainer_id) ON DELETE SET NULL,
    vendor_name text,
    client_name text,
    training_domain text,
    duration text,
    notes text,
    status text NOT NULL DEFAULT 'draft',
    po_date date,
    sent_to citext,
    sent_at timestamptz,
    acknowledged_by text,
    acknowledgement_notes text,
    acknowledged_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    legacy_mongo_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS purchase_order_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    po_id text NOT NULL REFERENCES purchase_orders(po_id) ON DELETE CASCADE,
    line_number integer NOT NULL,
    description text NOT NULL,
    quantity numeric(12, 2) NOT NULL DEFAULT 1,
    unit_price numeric(14, 2) NOT NULL DEFAULT 0,
    amount numeric(14, 2) GENERATED ALWAYS AS (quantity * unit_price) STORED,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (po_id, line_number)
);

CREATE TABLE IF NOT EXISTS invoices (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id text UNIQUE NOT NULL,
    po_id text REFERENCES purchase_orders(po_id) ON DELETE SET NULL,
    requirement_id text REFERENCES requirements(requirement_id) ON DELETE SET NULL,
    trainer_id text REFERENCES trainers(trainer_id) ON DELETE SET NULL,
    vendor_name text,
    client_name text,
    training_domain text,
    gst_number text,
    invoice_date date,
    notes text,
    status text NOT NULL DEFAULT 'draft',
    sent_to citext,
    sent_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    legacy_mongo_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS invoice_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id text NOT NULL REFERENCES invoices(invoice_id) ON DELETE CASCADE,
    line_number integer NOT NULL,
    description text NOT NULL,
    quantity numeric(12, 2) NOT NULL DEFAULT 1,
    unit_price numeric(14, 2) NOT NULL DEFAULT 0,
    amount numeric(14, 2) GENERATED ALWAYS AS (quantity * unit_price) STORED,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (invoice_id, line_number)
);

CREATE TABLE IF NOT EXISTS journeys (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    journey_id text UNIQUE NOT NULL,
    customer_id text REFERENCES customers(customer_id) ON DELETE CASCADE,
    requirement_id text REFERENCES requirements(requirement_id) ON DELETE SET NULL,
    current_stage text NOT NULL DEFAULT 'initial_contact',
    status text NOT NULL DEFAULT 'active',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    legacy_mongo_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS journey_steps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    journey_id text NOT NULL REFERENCES journeys(journey_id) ON DELETE CASCADE,
    step_order integer NOT NULL,
    step text NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    step_timestamp timestamptz,
    notes text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (journey_id, step_order)
);

CREATE TABLE IF NOT EXISTS automations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    automation_id text UNIQUE NOT NULL,
    name text NOT NULL,
    description text,
    trigger_config jsonb NOT NULL DEFAULT '{}'::jsonb,
    actions jsonb NOT NULL DEFAULT '[]'::jsonb,
    is_active boolean NOT NULL DEFAULT true,
    last_run timestamptz,
    run_count integer NOT NULL DEFAULT 0,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    legacy_mongo_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS toc_knowledge (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_id text UNIQUE NOT NULL,
    domain text NOT NULL,
    title text,
    content text,
    modules jsonb NOT NULL DEFAULT '[]'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    legacy_mongo_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS toc_generations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    generation_id text UNIQUE NOT NULL,
    requirement_id text REFERENCES requirements(requirement_id) ON DELETE SET NULL,
    trainer_id text REFERENCES trainers(trainer_id) ON DELETE SET NULL,
    domain text,
    request_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    generated_toc jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'generated',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    legacy_mongo_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS linkedin_leads (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id text UNIQUE NOT NULL,
    name text,
    title text,
    company text,
    email citext,
    phone text,
    linkedin_url text,
    domain text,
    source text,
    status text NOT NULL DEFAULT 'new',
    raw_result jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    legacy_mongo_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS email_analysis (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id text UNIQUE NOT NULL,
    email_id text,
    requirement_id text REFERENCES requirements(requirement_id) ON DELETE SET NULL,
    sentiment text,
    intent text,
    confidence numeric(5, 4),
    result jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    legacy_mongo_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai_usage_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    usage_id text UNIQUE NOT NULL,
    provider text,
    model text,
    feature text,
    prompt_tokens integer,
    completion_tokens integer,
    total_tokens integer,
    cost_usd numeric(12, 6),
    status text NOT NULL DEFAULT 'ok',
    request_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    response_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS whatsapp_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    log_id text UNIQUE NOT NULL,
    provider text,
    to_number text,
    from_number text,
    body text,
    status text NOT NULL DEFAULT 'pending',
    provider_message_id text,
    requirement_id text REFERENCES requirements(requirement_id) ON DELETE SET NULL,
    trainer_id text REFERENCES trainers(trainer_id) ON DELETE SET NULL,
    error_message text,
    raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    legacy_mongo_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS teams_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    log_id text UNIQUE NOT NULL,
    webhook_url text,
    conversation_id text,
    to_user text,
    title text,
    body text,
    status text NOT NULL DEFAULT 'pending',
    requirement_id text REFERENCES requirements(requirement_id) ON DELETE SET NULL,
    trainer_id text REFERENCES trainers(trainer_id) ON DELETE SET NULL,
    error_message text,
    raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    legacy_mongo_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gmail_oauth_states (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    state text UNIQUE NOT NULL,
    redirect_uri text,
    expires_at timestamptz NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gmail_watch (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    watch_id text UNIQUE NOT NULL DEFAULT 'default',
    history_id text,
    expiration timestamptz,
    topic_name text,
    raw_response jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS business_excel_sync (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sync_type text UNIQUE NOT NULL,
    status text NOT NULL DEFAULT 'idle',
    last_synced_at timestamptz,
    row_count integer NOT NULL DEFAULT 0,
    error_message text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS categorise_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id text UNIQUE NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    total_items integer NOT NULL DEFAULT 0,
    processed_items integer NOT NULL DEFAULT 0,
    result jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw_migration_documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_name text NOT NULL,
    legacy_mongo_id text NOT NULL,
    document jsonb NOT NULL,
    migrated_table text,
    migrated_record_key text,
    migration_status text NOT NULL DEFAULT 'pending',
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (collection_name, legacy_mongo_id)
);

CREATE INDEX IF NOT EXISTS idx_customers_email ON customers (email);
CREATE INDEX IF NOT EXISTS idx_client_leads_domain_status ON client_leads (domain, status);
CREATE INDEX IF NOT EXISTS idx_requirements_status_created ON requirements (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_requirements_client_email ON requirements (client_email);
CREATE INDEX IF NOT EXISTS idx_requirements_required_skills_gin ON requirements USING gin (required_skills);
CREATE INDEX IF NOT EXISTS idx_trainers_email ON trainers (email);
CREATE INDEX IF NOT EXISTS idx_trainers_status ON trainers (status);
CREATE INDEX IF NOT EXISTS idx_trainers_skills_gin ON trainers USING gin (skills);
CREATE INDEX IF NOT EXISTS idx_trainers_domains_gin ON trainers USING gin (domains);
CREATE INDEX IF NOT EXISTS idx_trainer_profile_leads_slug ON trainer_profile_leads (linkedin_slug);
CREATE INDEX IF NOT EXISTS idx_resume_uploads_trainer ON resume_uploads (trainer_id);
CREATE INDEX IF NOT EXISTS idx_shortlist_trainers_requirement ON shortlist_trainers (requirement_id, pipeline_status);
CREATE INDEX IF NOT EXISTS idx_shortlist_trainers_trainer ON shortlist_trainers (trainer_id);
CREATE INDEX IF NOT EXISTS idx_email_logs_requirement ON email_logs (requirement_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_email_logs_trainer ON email_logs (trainer_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_email_logs_status ON email_logs (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_email_logs_gmail_message ON email_logs (gmail_message_id);
CREATE INDEX IF NOT EXISTS idx_client_emails_status ON client_emails (status, reply_status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_client_emails_requirement ON client_emails (requirement_id);
CREATE INDEX IF NOT EXISTS idx_slots_requirement_time ON slots (requirement_id, start_time);
CREATE INDEX IF NOT EXISTS idx_slots_trainer_time ON slots (trainer_id, start_time);
CREATE INDEX IF NOT EXISTS idx_interview_reminders_due ON interview_reminders (status, remind_at);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_requirement ON purchase_orders (requirement_id);
CREATE INDEX IF NOT EXISTS idx_invoices_po ON invoices (po_id);
CREATE INDEX IF NOT EXISTS idx_journeys_customer ON journeys (customer_id, status);
CREATE INDEX IF NOT EXISTS idx_whatsapp_logs_status ON whatsapp_logs (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_teams_logs_status ON teams_logs (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_raw_migration_documents_status ON raw_migration_documents (migration_status);

DROP TRIGGER IF EXISTS trg_users_updated_at ON users;
CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_admin_settings_updated_at ON admin_settings;
CREATE TRIGGER trg_admin_settings_updated_at BEFORE UPDATE ON admin_settings
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_customers_updated_at ON customers;
CREATE TRIGGER trg_customers_updated_at BEFORE UPDATE ON customers
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_client_leads_updated_at ON client_leads;
CREATE TRIGGER trg_client_leads_updated_at BEFORE UPDATE ON client_leads
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_requirements_updated_at ON requirements;
CREATE TRIGGER trg_requirements_updated_at BEFORE UPDATE ON requirements
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_trainers_updated_at ON trainers;
CREATE TRIGGER trg_trainers_updated_at BEFORE UPDATE ON trainers
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_trainer_profile_leads_updated_at ON trainer_profile_leads;
CREATE TRIGGER trg_trainer_profile_leads_updated_at BEFORE UPDATE ON trainer_profile_leads
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_resume_uploads_updated_at ON resume_uploads;
CREATE TRIGGER trg_resume_uploads_updated_at BEFORE UPDATE ON resume_uploads
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_shortlists_updated_at ON shortlists;
CREATE TRIGGER trg_shortlists_updated_at BEFORE UPDATE ON shortlists
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_shortlist_trainers_updated_at ON shortlist_trainers;
CREATE TRIGGER trg_shortlist_trainers_updated_at BEFORE UPDATE ON shortlist_trainers
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_email_logs_updated_at ON email_logs;
CREATE TRIGGER trg_email_logs_updated_at BEFORE UPDATE ON email_logs
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_client_emails_updated_at ON client_emails;
CREATE TRIGGER trg_client_emails_updated_at BEFORE UPDATE ON client_emails
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_approvals_updated_at ON approvals;
CREATE TRIGGER trg_approvals_updated_at BEFORE UPDATE ON approvals
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_trainer_slot_responses_updated_at ON trainer_slot_responses;
CREATE TRIGGER trg_trainer_slot_responses_updated_at BEFORE UPDATE ON trainer_slot_responses
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_slots_updated_at ON slots;
CREATE TRIGGER trg_slots_updated_at BEFORE UPDATE ON slots
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_interview_reminders_updated_at ON interview_reminders;
CREATE TRIGGER trg_interview_reminders_updated_at BEFORE UPDATE ON interview_reminders
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_purchase_orders_updated_at ON purchase_orders;
CREATE TRIGGER trg_purchase_orders_updated_at BEFORE UPDATE ON purchase_orders
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_invoices_updated_at ON invoices;
CREATE TRIGGER trg_invoices_updated_at BEFORE UPDATE ON invoices
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_journeys_updated_at ON journeys;
CREATE TRIGGER trg_journeys_updated_at BEFORE UPDATE ON journeys
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_automations_updated_at ON automations;
CREATE TRIGGER trg_automations_updated_at BEFORE UPDATE ON automations
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_toc_knowledge_updated_at ON toc_knowledge;
CREATE TRIGGER trg_toc_knowledge_updated_at BEFORE UPDATE ON toc_knowledge
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_toc_generations_updated_at ON toc_generations;
CREATE TRIGGER trg_toc_generations_updated_at BEFORE UPDATE ON toc_generations
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_whatsapp_logs_updated_at ON whatsapp_logs;
CREATE TRIGGER trg_whatsapp_logs_updated_at BEFORE UPDATE ON whatsapp_logs
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_teams_logs_updated_at ON teams_logs;
CREATE TRIGGER trg_teams_logs_updated_at BEFORE UPDATE ON teams_logs
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_gmail_watch_updated_at ON gmail_watch;
CREATE TRIGGER trg_gmail_watch_updated_at BEFORE UPDATE ON gmail_watch
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_business_excel_sync_updated_at ON business_excel_sync;
CREATE TRIGGER trg_business_excel_sync_updated_at BEFORE UPDATE ON business_excel_sync
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();

DROP TRIGGER IF EXISTS trg_categorise_jobs_updated_at ON categorise_jobs;
CREATE TRIGGER trg_categorise_jobs_updated_at BEFORE UPDATE ON categorise_jobs
FOR EACH ROW EXECUTE FUNCTION trainersync.set_updated_at();
