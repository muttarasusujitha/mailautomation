# Connected LinkedIn fetching

Select trainer profiles or client posts in LinkedIn Search, enter domains, and
click Find. Searches use the connected LinkedIn account first. If LinkedIn
rate-limits the session, the manual search falls back to public indexed LinkedIn
results and labels them as a public search fallback. Sign-in verification errors
remain paused until manually addressed. Scheduled background collection remains
account-only. The fallback uses no paid API. Fetches only save leads; they never
send email, messages or connection requests. Search cards are unverified signals,
not confirmation that a requirement remains open.

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

LinkedIn runs inside `ts-intelligence-service`; it is not a separate container.
Stage 3 builds its regular Dockerfile, including Playwright and Chromium. Stage 4
pulls and starts that image and runs **Verify LinkedIn Bot Deployment**. This checks
the API, enabled flag, writable profile, Chromium launch, stored session, and both
automatic-collection settings. Missing, expired, corrupt, or blocked sessions fail
that step with an account-reconnection error. A rate-limited session emits a warning
and keeps its cooldown. A saved cookie is reported as `saved_unverified`, not proof
of live LinkedIn search access. The check does not run searches or change settings.
Run it manually with:
`docker exec ts-intelligence-service python -m app.linkedin_deployment`.

During a stored account cooldown, both enabled collectors report `paused` and
schedule their next attempt after the cooldown. They do not run a scheduled scan
while paused. A new limit during a scan preserves saved result counts and postpones
the next attempt. Manual public searches remain available separately.

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
The account request allows about 110 seconds including browser startup and cleanup.
It saves at most 50 cards per domain within the requested total. Only one fetch uses the
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

## Self-hosted finder (web engines) for trainers and clients

When the account search returns fewer trainer profiles than the target, for any
reason (cooldown, sign-in needed, bot disabled, or not enough results), the
`auto` search runs `app/clients/trainer_finder.py` for the rest. No API key is
needed.

- **Engines**: Bing, DuckDuckGo, DuckDuckGo Lite, Yahoo, Mojeek and Brave Search
  run in parallel (`app/clients/serp_engines.py`). No search API or key is used.
- **Queries**: about 30 per skill, starting with `site:linkedin.com/in` profile
  queries (trainer, corporate trainer, instructor, consultant, and so on), then
  plain and city queries.
- **Paging**: each engine reads up to 3 result pages per query while new profile
  links appear.
- **Only result pages are requested.** LinkedIn profile links are read from the
  result page and never opened.
- **Blocks**: a captcha, consent page or HTTP 202/403/429/503 marks the engine
  blocked. The page is first retried once in a plain headless Chromium (no
  LinkedIn cookies). A blocked engine pauses 15 minutes, doubling on each repeat
  up to 6 hours. The state is saved in `serp-engine-health.json` in the bot
  profile volume; delete it to retry every engine immediately.
- **Quality**: a profile counts only when its title or snippet names the skill
  and uses trainer wording, and it passes the same `_normalize_result` check as
  account results. Profiles already in `trainer_profile_leads` are skipped.
  Profiles found by several engines rank first.
- **Client posts**: the same engines also run for **Find Client Posts**. They
  search `site:linkedin.com/posts` and `site:linkedin.com/feed/update` for
  phrases such as "trainer required", "looking for a trainer", "need a trainer"
  and "training requirement", plus city queries. Only posts from the past month
  are requested on engines that support a date filter (`CLIENT_POST_MAX_AGE`).
  A post counts only when it names the domain and asks for a trainer (the same
  `_normalize_result` client check). Saved posts are skipped by activity ID.
  Posts with an email or phone number rank first. The hourly client bot
  (`scan_client_posts`) does not use the engines.
- **Stronger search**: a query that returns 3 or more new leads on a page earns
  two extra pages; an engine that returns no LinkedIn links for 6 queries in a
  row stops early; common skill aliases (AWS / Amazon Web Services, K8s /
  Kubernetes, and so on) add trainer queries and also count as a skill match.
- **Report**: each domain outcome has `sources` (one entry per source with
  `status`: ok, filtered, no_results, blocked, paused, error, not_configured or
  not_needed, plus counts and a reason) and `limit_reason` when the target was
  not reached. The LinkedIn Search page shows both.

Settings: `TRAINER_FINDER_ENABLED`, `TRAINER_FINDER_BUDGET_SECONDS` (default 180),
`TRAINER_FINDER_ENGINES`, `TRAINER_FINDER_BROWSER` and `CLIENT_POST_MAX_AGE`; see `.env.example`.

To check the parser against live pages, set `TRAINER_FINDER_DEBUG_DIR=/tmp/finder`
for a diagnostic run. Each engine's first results page is saved there as
`<engine>.html`, with the query in `<engine>.query.txt`.
