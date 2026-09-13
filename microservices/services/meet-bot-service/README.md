# TrainerSync Meet Host Bot

This optional service joins confirmed Google Meet interviews shortly before the
scheduled start, keeps the camera off, unmutes only for the opening instruction, and leaves after the scheduled
end plus a grace period.

## Opening voice and reminders

The Clahan opening instruction uses offline `espeak-ng` speech synthesis. Each
meeting tab feeds its own audio into a WebRTC microphone stream; browser speaker
text-to-speech is not used. The instruction is also posted in Meet chat. It starts
after both the trainer and client are observed in the participant list.

Run `docker compose run --rm --no-deps meet-bot-service python -m app.verify_voice`
to test speech transmission between local WebRTC peers and check that another
tab remains silent. This test neither joins a Google meeting nor sends email.
The test uses a temporary browser profile, not the signed-in bot profile.

The health endpoint reports `google_account.status`, its startup check timestamp,
and `voice_transport`. `signed_in` confirms the Google account control was visible;
it does not confirm admission to a particular meeting. A real internal meeting
is still required to verify the Google Meet UI and participant reception.

The scheduler checks five-minute interview email reminders every minute and
sends them to the trainer, client, and configured Clahan coordinator. Reminder
email is separate from in-meeting voice; email cannot force a recipient's device
to play an audible alarm.

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

The service runs up to `MEET_BOT_MAX_CONCURRENT_MEETINGS` interviews at once
(default 4, range 1–20). One signed-in browser owns the persistent profile;
each meeting has its own tab, task, admission check, retry state, and cleanup.
Trainer/client invitation copies of the same meeting share status and launch
only one tab. Meetings beyond capacity wait until a slot is free and are only
started while their scheduled window is still valid.

Run one service instance per persistent profile. The tabs share the bot account,
so Google account restrictions and available CPU/memory can still limit capacity.
Check the health endpoint for `max_concurrent_meetings` and `active_meetings`.

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
