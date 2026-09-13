# Client package workflow

1. A linked trainer reply supplies profile information and three dated interview options. Mail 1 asks the trainer to confirm the offered commercials or provide a proposed rate.
2. The inbox calls `POST /api/v1/shortlists/send-client-slots` to prepare the package. Despite the legacy route name, this does not authorize a new delivery. A legacy `approved: true` field cannot bypass review.
3. The trainer service saves the complete email and attachments in `client_handoff_packages`. Profile and ToC are required; lab cost is required only when requested by the client. A requested document failure leaves preparation incomplete and reports the upstream error.
4. In either Shortlist page, choose **Review client package**. Review the recipient, commercials, slots, email and downloadable documents. **Rebuild from latest details** is available before approval and creates a new version.
5. **Approve & send to client** submits the reviewed package ID. A stale version or changed client recipient is rejected. Email wording and attachments are frozen after approval. The email service owns the single delivery log and persistent idempotency key.
6. Approved failures are retained in the database and retried by the trainer service every 30 seconds when their retry window is due (five minutes after a failed attempt). A three-minute worker lease prevents competing retries and recovers after a process crash. Unapproved packages are never sent by this worker.
7. Only a reply from the linked client after a delivered handoff can select a slot. Existing calendar handling creates the meeting with both client and trainer as attendees.

## Deploy local changes

From `mailautomation`, build the changed services and frontend, then recreate them. Source is copied into Docker images; `docker restart` does not apply workspace edits.

```powershell
docker compose -f microservices/docker-compose.yml build trainer-service email-service document-service gateway
docker compose -f docker-compose.yml build frontend
docker compose -f microservices/docker-compose.yml up -d --no-deps trainer-service email-service document-service
docker compose -f microservices/docker-compose.yml up -d --no-deps gateway
docker compose -f docker-compose.yml up -d --no-deps frontend
```

The gateway is recreated after service replacement so its upstream DNS addresses are refreshed. Preparation permits up to 300 seconds through the gateway; optional ToC enrichment is bounded and retains deterministic curriculum when unavailable.

No test should send a real email or calendar invitation. Unit tests use mocked providers. External delivery still requires working sender/calendar credentials, provider quota, and valid pricing selections for requested managed lab resources.
