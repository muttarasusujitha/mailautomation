# Account activation

New registrations are pending and receive no session. An operator must activate
the account before password or social sign-in can succeed. Each authenticated
request checks the current account status and session version in MongoDB.
Client and trainer APIs are protected by the gateway; keep upstream service ports
private and route browser traffic through the gateway.

From the repository root, create the first administrator in a running deployment:

```sh
docker compose -f microservices/docker-compose.yml exec auth-service python -m app.manage_users create-admin admin@example.com --name "Administrator"
```

Replace the example email with your own. The command prompts twice for a hidden
password of 12-128 characters and stores a salted password hash. There are no
default administrator credentials. An existing account is never overwritten.

After reviewing a registration, activate it with:

```sh
docker compose -f microservices/docker-compose.yml exec auth-service python -m app.manage_users activate user@example.com --role recruiter
```

Use `--role admin` to grant administrator access to an existing account, or
`disable user@example.com` to disable it. These are trusted server-operator
commands; role and status changes invalidate existing sessions. A requested
signup role does not grant access. This workspace supports active recruiters
and administrators; activation defaults to recruiter.

For local Python execution, run `python -m app.manage_users ...` from this
service directory with the microservices directory on `PYTHONPATH` and
`MONGODB_URL` / `MONGODB_DB_NAME` set to the intended database. Use a terminal
that supports hidden password input. Production cookies require HTTPS;
`AUTH_COOKIE_SECURE=false` is only for local HTTP development.
