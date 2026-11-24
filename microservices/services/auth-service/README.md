# Account activation

Public signups create trainer and client accounts. Administrator accounts are
provisioned explicitly by an operator. Each authenticated request checks the
current account status and session version in MongoDB.
Client and trainer APIs are protected by the gateway; keep upstream service ports
private and route browser traffic through the gateway.

From the repository root, create the first administrator in a running deployment:

```sh
docker compose -f microservices/docker-compose.yml exec auth-service python -m app.manage_users create-admin admin@example.com --name "Administrator"
```

Replace the example email with your own. The command prompts twice for a hidden
password of 12-128 characters and stores a salted password hash. There are no
default administrator credentials. An existing account is never overwritten.

To activate a registered trainer or client account, use:

```sh
docker compose -f microservices/docker-compose.yml exec auth-service python -m app.manage_users activate user@example.com --role trainer
```

The only account roles are `admin`, `trainer`, and `client`. Public signup is
limited to trainer and client. `activate` without `--role` preserves the saved
role. Use `--role admin` only when an operator has reviewed and authorized the
account; use `--role client` for a client account.
`disable user@example.com` disables an account. These are trusted
server-operator commands; role and status changes invalidate existing sessions.
Legacy employee and recruiter accounts are not automatically promoted.

For local Python execution, run `python -m app.manage_users ...` from this
service directory with the microservices directory on `PYTHONPATH` and
`MONGODB_URL` / `MONGODB_DB_NAME` set to the intended database. Use a terminal
that supports hidden password input. Production cookies require HTTPS;
`AUTH_COOKIE_SECURE=false` is only for local HTTP development.
