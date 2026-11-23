# Connected LinkedIn fetching

Select trainer profiles or client posts in LinkedIn Search, enter domains, and
click Find. Automatic collection and the search page use `auto`: public search
followed by the connected account when more matches are needed.
Fetches only save leads; they never send email, messages or connection requests.
Search cards are unverified signals, not confirmation that a requirement remains open.

## One-time connection on a desktop host

From this service directory, install requirements and Chromium:

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
$env:LINKEDIN_BOT_PROFILE_PATH = (Join-Path $PWD 'linkedin-bot-profile')
python -m app.linkedin_authenticate --domain "SAP" --mode trainer
```

Sign in manually in the opened browser, complete any verification, and leave it
open. The helper opens the requested search and waits for search access, then
closes the browser and checks that search again in a fresh fetcher browser.
It prints SESSION_READY only if search works on that host; a working feed alone
is insufficient. Do not provide passwords to the application.
Use this same absolute profile path when starting intelligence-service and set
`LINKEDIN_BOT_ENABLED=true` in its environment. Run one service process/worker
per profile; stop fetching before opening the sign-in helper again.

The profile contains account cookies; do not commit or share it. It must be a
dedicated profile, separate from everyday Chrome and the meeting bot.
The helper also saves LinkedIn cookies in `linkedin-session.json` inside that
ignored profile directory and reloads them before the restart verification and
fetching. Treat this file as an account credential. Its contents are never logged.
The fetcher updates this snapshot after authenticated searches, including searches
that return partial results, so later launches reuse refreshed cookies. The helper
also saves cookies again after its fresh-browser verification. Login/checkpoint
pages do not replace the saved snapshot. The Docker named volume preserves the
profile and snapshot across service/container restarts; do not delete that volume.
This remembers the login, but cannot prevent LinkedIn from expiring or revoking a
session or requesting manual verification.
When LinkedIn requests sign-in or verification, the fetcher records the rejected
snapshot in `linkedin-verification-required.json` in the same private volume.
Manual and scheduled account searches then stop before launching a browser.
Public discovery can continue. Supplying a different login snapshot allows one
new attempt; the helper also clears the block after verifying search access.
Restarting the service or rewriting the same rejected snapshot does not clear it.

## Docker deployment

For the local Windows + Docker setup, run from `microservices`:
`./tools/connect-linkedin.ps1 -Domain "sap trainer" -Python "C:\path\to\python.exe"`.
This opens manual sign-in, verifies that exact search locally, privately transfers
the snapshot into the existing container volume, then performs one actual application
search and saves its leads. It never sends outreach. Only APPLICATION_SEARCH_READY
means the deployed search completed; a local SESSION_READY alone is insufficient.

Rebuild the intelligence-service image using its Dockerfile; it installs
Playwright Chromium and the session helper. Compose mounts `linkedin_bot_profile` at
`/data/linkedin-bot-profile`. Set `LINKEDIN_BOT_ENABLED=true` in `.env` only after
sign-in. Authentication must run with that same volume on a host with a trusted
graphical desktop/display; the normal container does not expose a remote login
screen. Do not copy a Windows Chromium profile into the Linux container. The
dedicated helper's `linkedin-session.json` contains portable LinkedIn cookies
and may be provisioned privately into that volume; never put it in an image.
After privately provisioning the cookies, verify search in the deployment itself:
`docker exec ts-intelligence-service python -m app.linkedin_authenticate --verify-only --domain "SAP"`.
Windows verification does not prove that the Linux fetcher is authenticated.
If deployment verification fails, stop and complete LinkedIn's required manual
verification; do not repeatedly retry fetches or report the session as ready.

To add browser support to the installed registry image while retaining its
other modules, build from the repository root:

```powershell
docker build -f microservices/services/intelligence-service/Dockerfile.linkedin -t trainersync-intelligence-linkedin:local .
```

Set `INTELLIGENCE_IMAGE=trainersync-intelligence-linkedin:local` and
`LINKEDIN_BOT_ENABLED=true` in `microservices/.env`, then from `microservices` run
`docker compose up -d --no-deps intelligence-service`. The dedicated build
context excludes credentials and browser profiles. Fetching runs headlessly.
Enable the trainer bot in the application to collect hourly; the account flag
and the automatic-collection setting are separate controls.

## Limits and verification

Client automatic collection defaults to `domain_source=all`. Every ten minutes it
scans up to 50 training-request posts using broad request-intent searches and saves
every qualified request, including non-IT topics and requests outside the course
catalog. Catalog names (including Project Management) are optional labels, never
an admission filter; unrecognized topics appear as Unclassified. Duration variants
count as one label. Manual client domains remain available as an explicit filter.
Coverage depends on accessible results; this does not guarantee finding every
LinkedIn post. Repeat posts use LinkedIn activity IDs or normalized URLs, with a
unique database key to prevent concurrent duplicate saves. Updates preserve review
status and accumulate domain labels. The pipeline loads every saved page.
Existing IT-catalog settings migrate to all domains on startup without enabling
paused bots. Runs use a lease
to prevent overlap and a 240-second scan timeout, with ten-minute start-to-start
scheduling (up to 30 seconds of polling delay). Trainer collection stays hourly.

Trainer discovery reads people search across result pages, using plain keywords
such as "DevOps trainer", then a short content fallback when more profiles are
still needed. Matches already collected are kept if a later page slows down.
People results are paged for about 180 seconds, including headlines carried in the search payload. If that pass has not already kept profiles, a content fallback gets its own 40 seconds.
It saves at most 60 cards per domain within the requested total, up to 100. Only one fetch uses the
profile at once. Login, checkpoints, rate limits and unrecognized result layouts
produce explicit errors. The bot does not bypass them or switch to a paid API.

Tests cover routing, domain filtering, URL validation, session persistence,
disabled operation, checkpoint errors and separating author credentials from
hiring-post text. A local live Python search returned three client requirements
and two trainer profiles. These are discovery signals, not verified availability.
When people-search identities are hidden, trainer discovery uses visible post
author profile links and headlines. Client posts use their Copy link action and
resolve LinkedIn short links. No hidden profile identity is reconstructed.
Those original samples were written to a local review file. Validate deployment
with a live application fetch and confirm saved lead IDs in the database.

Persistent profiles follow the [Playwright browser documentation](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context).
