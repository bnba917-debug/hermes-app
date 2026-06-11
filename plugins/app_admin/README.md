# Hermes App Admin

Standalone admin backend for the App Gateway. It is intentionally separate from
the Flutter app so operator-only capabilities can grow without exposing them in
the user client.

## Scope

- Admin login with a bearer session token.
- Public skill CRUD backed by PostgreSQL table `hermes_app_skills`.
- Initial PostgreSQL tables for future user wallets and recharge orders.
- Minimal built-in web UI served from `/`.

## Configuration

Use environment variables or `~/.hermes/config.yaml`:

```yaml
app_admin:
  enabled: true
  host: "127.0.0.1"
  port: 8790
  postgres_url: "postgresql://user:pass@localhost/hermes"
  admin_username: "admin"
  admin_password: "change-me"
  session_secret: "change-me-too" # Must be dedicated to app_admin.
```

If `app_admin.postgres_url` is empty, the service falls back to
`app_gateway.postgres_url`, then `storage.postgres_url`.
`app_admin.session_secret` intentionally does not fall back to the App Gateway
JWT secret; admin sessions must use a separate signing secret.

## Run

```bash
python -m plugins.app_admin.server
```

Install PostgreSQL support first when needed:

```bash
uv pip install -e '.[postgres,web]'
```
