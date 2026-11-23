# Client package workflow

1. A linked trainer reply supplies profile information and three dated interview options. Mail 1 asks the trainer to confirm the offered commercials or provide a proposed rate.
2. The inbox calls `POST /api/v1/shortlists/send-client-slots`. The trainer service validates the reply, builds the package, marks it approved for this automated workflow, and immediately attempts delivery. There is no manual approval step in this path. The review panel lets the team view the saved package and delivery status.
3. The trainer profile, ToC, lab-cost workbook, and interview slots are included as one package. If participant count or lab hours are missing, the workbook uses the approved one-participant / three-hour baseline and the email discloses those assumptions. Document-generation failures prevent the email from being sent.
4. The email wording and attachments are frozen in `client_handoff_packages`. Email service owns the single delivery log and persistent idempotency key, so retries reuse the same package and do not intentionally send duplicates.
5. Transient send failures are retained and retried by the trainer service every 30 seconds once their retry window is due (five minutes after a failed attempt). A three-minute worker lease prevents competing retries and recovers after a process crash.
6. A reply from the linked client can select a slot only after a delivered handoff. Existing calendar handling creates the meeting with both client and trainer as attendees.

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
