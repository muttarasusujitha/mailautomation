# TrainerSync Meet Host Bot

This optional service joins confirmed Google Meet interviews shortly before the
scheduled start, keeps microphone and camera off, and leaves after the scheduled
end plus a grace period.

## Safety defaults

- `MEET_BOT_ENABLED=false`: no browser starts until explicitly enabled.
- `MEET_BOT_AUTO_ADMIT=false`: the bot never admits unknown users by default.
- Use Calendar invite-restricted meetings before enabling auto-admit.
- Use a dedicated Google Workspace account, never a personal/admin account.
- Never place a Google password or two-factor secret in `.env`.

## Activation checklist

1. Create the dedicated Meet bot account.
2. Build the service: `docker compose build meet-bot-service`.
3. Authenticate the persistent Chrome profile through an administrator-controlled
   interactive session. The profile mounted at `/data/chrome-profile` must show
   the bot account already signed in to Google Meet.
4. Test with internal invite-only meetings.
5. Set `MEET_BOT_ENABLED=true`.
6. Keep `MEET_BOT_AUTO_ADMIT=false` until access control has been verified. If it
   is enabled, all visible admission requests may be admitted because Meet's UI
   does not reliably expose the requester's email address to automation.
7. Start the service and monitor `meet_bot_status` / `meet_bot_error` in
   `email_logs`.

The service handles one meeting at a time. Run one independently authenticated
bot instance/account for each simultaneous interview slot.

For local development, install the pinned requirements and browser, then run
`python -m app.authenticate` from this service directory. Production container
authentication requires an administrator-controlled interactive display; do not
copy a Windows Chrome profile into Linux because browser credential encryption is
operating-system specific.

Google can change Meet's UI or challenge automated sign-ins. Treat this service
as best-effort browser automation and keep a human fallback for interviews.

## Production monitoring

- Container health is served on port `8010` internally.
- `meet_bot_status` progresses through `claimed`, `joined`, and `completed`.
- Authentication/UI failures retry up to `MEET_BOT_MAX_ATTEMPTS`, then become
  `failed_permanent` with `meet_bot_error` for operator review.
- Only HTTPS links on `MEET_BOT_ALLOWED_HOSTS` are opened.
- Cancellation while the bot is present causes it to leave on the next check.
