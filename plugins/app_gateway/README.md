# Hermes App Gateway

Implements the **Hermes** layers from `tgs.html` (sections 1–3), with **phase 2** enterprise storage.

## Phase 1 (MVP)

| tgs.html | Implementation |
|----------|----------------|
| App + SDK | `sdk/client.py` + **Flutter** `flutter_app/` (Web/iOS/Android) |
| JWT Gateway | `auth.py` + `server.py` |
| Agent Runtime | `runtime.py` → `AIAgent` |
| Redis hot cache | `redis_store.py` |
| SSE streaming | `POST /v1/chat/completions` |

## Phase 2 (this release)

| tgs.html | Implementation |
|----------|----------------|
| PostgreSQL 审计 | `audit_backends.py` — `audit_backend: postgres`, `dual`, or **`auto`** (PG when `postgres_url` set) |
| 向量记忆 / user namespace | `vector_memory.py` (SQLite FTS5) or **`postgres_vector_memory.py`** — `vector_memory_backend: auto|sqlite|postgres`; **filter=user_id** |
| 配置中心热更新 | `config_registry.py` + `POST /v1/admin/config/reload` |
| 反馈 → 记忆 | `POST /v1/feedback` + `store_memory: true` |
| 统一入口（可选） | `proxy_to_api_server` → `:8642` with JWT headers |
| 限流 | `rate_limit.py` — per-user RPM |

## App flow: phone register → model + API key → chat

Typical mobile app sequence:

```mermaid
sequenceDiagram
  participant App
  participant GW as App Gateway
  App->>GW: POST /v1/auth/sms/send {phone}
  GW-->>App: ok (SMS via configured provider)
  App->>GW: POST /v1/auth/register {phone, code}
  GW-->>App: access_token, initialized=false
  App->>GW: GET /v1/onboarding/models
  GW-->>App: model list for picker
  App->>GW: POST /v1/onboarding/complete {model, api_key}
  Note over GW: creates users/&lt;id&gt;/.env + config, mark initialized
  GW-->>App: ready_for_chat=true
  App->>GW: POST /v1/chat/completions Bearer token
```

| Step | API | Notes |
|------|-----|--------|
| 0 | `GET /v1/auth/sms/captcha` | Slider challenge before SMS (when `sms_captcha_enabled`) |
| 1 | `POST /v1/auth/sms/send` | Body: `{"phone","captcha_token","captcha_answer"}` — `captcha_answer` is slider position 0–1000 (basis points) |
| 2 | `POST /v1/auth/register` or `/login` | Body: `{"phone","code","device_id"?}` → `access_token`, `refresh_token`, `expires_in` |
| 2b | `POST /v1/auth/refresh` | Body: `{"refresh_token"}` → new access + refresh pair (rotation) |
| 2c | `POST /v1/auth/logout` | Body: `{"refresh_token"}` → revoke refresh token (best-effort) |
| 3 | `GET /v1/onboarding/models` | Model picker (no auth required) |
| 4 | `POST /v1/onboarding/complete` | Bearer token + `model` + `api_key` → **initialized** |
| 5 | `POST /v1/chat/completions` | Only if `ready_for_chat` (403 `NEED_ONBOARDING` otherwise) |

### SMS / phone auth

| `auth_mode` | Behavior |
|-------------|----------|
| `dev` (default) | No external SMS; stores fixed `dev_sms_code` (default `111111`). Set `expose_dev_code: true` to return `code` in JSON for local testing. |
| `aliyun` | Aliyun dysmsapi `SendSms` — set `sms_sign_name`, `sms_template_code` in config; keys in `.env` (`ALIYUN_SMS_ACCESS_KEY_ID`, `ALIYUN_SMS_ACCESS_KEY_SECRET`). |
| `tencent` | Tencent Cloud SMS — `sms_sdk_app_id`, `sms_template_id`, `TENCENT_SMS_SECRET_ID`, `TENCENT_SMS_SECRET_KEY`. |
| `twilio` | Twilio Messages API — `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `sms_from_number`. |
| `http` | POST `{"phone","code"}` to `sms_webhook_url` (custom bridge). |

Production modes generate a random 6-digit OTP, send via the vendor, and verify only against the stored OTP (not the fixed dev code). Override mode with env `APP_GATEWAY_AUTH_MODE`.

### SMS anti-abuse (slider CAPTCHA)

Before `POST /v1/auth/sms/send`, clients should call `GET /v1/auth/sms/captcha` and submit `captcha_token` + `captcha_answer` (slider position as an integer 0–1000, matching the server’s random target within `tolerance_bp`, default ±35). Response includes `captcha_type: "slider"`, `target_ratio`, `target_bp`, and `tolerance_bp`. Tokens are HMAC-signed, expire in 5 minutes, and are **one-time use**. Disable with `sms_captcha_enabled: false` (local automation only).

## Quick start

```yaml
# ~/.hermes/config.yaml
app_gateway:
  enabled: true
  host: "0.0.0.0"
  port: 8787
  jwt_secret: "change-me"
  refresh_tokens_enabled: true
  jwt_access_ttl_minutes: 120   # short-lived access JWT when refresh enabled
  jwt_refresh_ttl_days: 30      # opaque refresh token TTL (Redis or in-memory)
  jwt_ttl_hours: 720            # used when refresh_tokens_enabled: false
  app_key: "backend-secret"
  audit_backend: auto          # auto = postgres if postgres_url set, else sqlite
  postgres_url: "postgresql://user:pass@localhost/hermes"
  vector_memory_enabled: true
  vector_memory_backend: auto  # auto = postgres if postgres_url + psycopg, else sqlite
  rate_limit_rpm: 120
  # 100+ simultaneous LLM/agent runs per process (129th+ waits, then 503)
  max_concurrent_agents: 128
  agent_executor_workers: 160
  agent_queue_timeout_seconds: 300
  user_registry_backend: auto      # auto = postgres when postgres_url set
  per_user_skills_isolated: true   # skills under ~/.hermes/app_gateway/users/<id>/
  include_global_skills: true      # read-only bundled repo skills/_bundled per user
  enable_shared_skills: false      # operator catalog → skills.external_dirs per user
  require_jwt: true
  fallback_global_credentials: false
  expose_dev_code: false           # production: never return SMS code in JSON
  daily_chat_limit: 0              # 0 = unlimited; e.g. 200 for SaaS
  daily_token_limit: 0
  max_concurrent_chats_per_user: 2
  auth_sms_per_ip_per_hour: 30
  auth_sms_per_phone_per_day: 10
  web_cookie_auth: true          # web: HttpOnly cookies when client sends X-Hermes-Cookie-Auth: 1
  cookie_secure: false           # set true behind HTTPS
  cookie_samesite: lax
  delete_account_sms_verify: true
  data_retention_days: 365       # prunes ended sessions + stale workspace/uploads/
  data_retention_interval_hours: 24
  shared_skills_dir: ""            # default: ~/.hermes/app_gateway/shared-skills
  proxy_to_api_server: false   # true = forward to hermes gateway api_server
  api_server_url: "http://127.0.0.1:8642"
  api_server_key: ""             # or API_SERVER_KEY in .env
```

```bash
hermes app-gateway init
hermes app-gateway start
```

## Endpoints

| Method | Path | Auth |
|--------|------|------|
| GET | `/health` | none |
| POST | `/v1/chat/attachments` | JWT — multipart `file` → user `workspace/uploads/` |
| POST | `/v1/chat/completions` | JWT — text + **image_url** multimodal (same as api_server) |
| POST | `/v1/audio/transcribe` | JWT — multipart `file` or JSON `audio_base64` → STT |
| POST | `/v1/audio/speech` | JWT — JSON `{"text":"..."}` → TTS file path |
| POST | `/v1/feedback` | JWT |
| GET | `/v1/memory/search?q=` | JWT |
| POST | `/v1/admin/config/reload` | app key |
| GET | `/v1/sessions` | JWT — list this user's chat sessions |
| POST | `/v1/sessions` | JWT — create a new logical session id |
| GET | `/v1/sessions/{session_id}/messages` | JWT — server-side history for App resume |
| POST | `/v1/chat/stop` | JWT — body `{"run_id":"..."}` interrupt in-flight chat |
| POST | `/v1/runs/{run_id}/approval` | JWT — body `{"choice":"once|session|always|deny"}` |
| GET | `/v1/skills` | JWT — list **this user's** skills only |
| GET | `/v1/skills/config` | JWT — `disabled`, `external_dirs`, `skills_home` |
| PUT | `/v1/skills/config` | JWT — body `{"disabled":["skill-a",...]}` |
| GET | `/v1/skills/{name}` | JWT — full `SKILL.md` + metadata |
| POST | `/v1/skills/reload` | JWT — rescan slash commands + clear prompt cache |
| GET | `/v1/legal/{terms\|privacy\|data-retention}` | none — markdown legal templates |
| GET | `/v1/me/usage` | JWT — daily chat/token quota snapshot |
| GET | `/v1/me/storage` | JWT — workspace usage (MinIO-aware when enabled) |
| DELETE | `/v1/me` | JWT — self-service account deletion (`{"confirm": true, "code": "<sms>"}` when `delete_account_sms_verify`) |
| POST | `/v1/me/delete/sms` | JWT — send SMS OTP for account deletion |
| POST | `/v1/auth/logout/all` | JWT — revoke all refresh tokens for user |

**Workspace file tools:** paths must be **relative** to each user's `workspace/` (no absolute paths, no `..`). Enforced in `file_tools` when `platform=app_gateway`.

**Production checklist:** `require_jwt: true`, `postgres_only: true`, `redis_url` set (required automatically when PG-only — session cache, quotas, auth limits, refresh tokens, RPM), `trusted_proxy_ips` when behind nginx/ALB (for accurate SMS IP limits), `expose_dev_code: false`, `auth_mode` not `dev`, `fallback_global_credentials: false`, `enable_shared_skills: false`. Monitor `/health?deep=true` and scrape `/metrics`. Put a reverse proxy/WAF in front for additional IP throttling.

| GET | `/metrics` | Prometheus text (request counts, agent pool, Redis up, upload queue) |

## CLI alignment (phased)

| Phase | Capability |
|-------|------------|
| 1 ✅ | Multimodal chat (`image_url` / data URLs) |
| 2 ✅ | Default tools = **hermes-app-gateway** (near-CLI: no terminal/browser) |
| 3 ✅ | `/v1/audio/transcribe`, `/v1/audio/speech` |
| 4 ✅ | SSE `tool.start` / `tool.complete` / `approval.request`; `POST /v1/chat/stop` |
| 5–6 | Sessions API, Flutter history/stop — see below |

## Per-user skills (no cross-user sharing)

Each JWT `sub` gets an isolated Hermes home:

`~/.hermes/app_gateway/users/<user_id>/`

| Path | Purpose |
|------|---------|
| `skills/` | Read-only bundled overlay (`_bundled` symlink) + optional agent `skill_manage` writes |
| `workspace/` | **File-tool sandbox** — `read_file` / `write_file` / `patch` / `search_files` resolve here |
| `.env` | BYOK API keys (file mode) |
| `config.yaml` | Model provider + `terminal.cwd` → workspace (file mode) |

Operator **public** skills live in PostgreSQL + `public-skills/` (managed via `app_admin`).

- Users list bundled + public skills via `GET /v1/skills`; disable via `PUT /v1/skills/config`.
- `skill_manage` during chat only sees **that user's** scoped tree.
- Skills prompt LRU cache is keyed by **user id + skills directory** (not shared).
- Optional read-only bundled skills via `skills/_bundled` symlink (`include_global_skills: true`).

After disk/catalog changes, call `POST /v1/skills/reload` to refresh slash-command registration.

## Per-user API keys (BYOK)

Each user has a private tree:

`~/.hermes/app_gateway/users/<user_id>/.env` — secrets only (`OPENROUTER_API_KEY`, …)  
`~/.hermes/app_gateway/users/<user_id>/config.yaml` — `model.provider`, `model.default`, `model.api_key_env`

Keys are passed to the LLM as **explicit** credentials inside that user's request scope — they are **not** written to process-global `os.environ`, so concurrent users never share keys.

| Method | Path | Auth |
|--------|------|------|
| GET | `/v1/me/inference` | JWT — status only (no secret returned) |
| PUT | `/v1/me/inference` | JWT — set your key/model |
| PUT | `/v1/admin/users/{user_id}/inference` | `app_key` — backend assigns key for a user |

Example (user JWT):

```json
PUT /v1/me/inference
{
  "api_key": "sk-or-v1-...",
  "api_key_env": "OPENROUTER_API_KEY",
  "provider": "openrouter",
  "model": "anthropic/claude-sonnet-4"
}
```

Or edit the file directly:

```bash
# ~/.hermes/app_gateway/users/alice/.env
OPENROUTER_API_KEY=sk-or-v1-...
```

Config (`app_gateway.per_user_api_keys: true`, default): each chat uses that user's `.env`.  
`fallback_global_credentials: true` uses `~/.hermes/.env` only when the user has no key (optional shared fallback).

## Concurrency (100+ simultaneous LLM per process)

| Knob | Default | Role |
|------|---------|------|
| `max_concurrent_agents` | **128** | In-flight LLM/agent runs per process |
| `agent_executor_workers` | **160** | Thread pool (≥ `max_concurrent_agents`) |
| `storage.postgres_pool_size` | **48** | PG connections for session I/O (avoid single-connection bottleneck) |
| `agent_queue_timeout_seconds` | 300 | Queue wait; then **503** + `Retry-After: 30` |

**Sizing (single instance, 100+ concurrent LLM):**

- **Hardware:** ~**8–16 CPU cores**, **16–32 GB RAM** (128 blocking threads + agent memory).
- **PostgreSQL:** required; tune `postgres_pool_size` to **32–64** under load.
- **Model APIs:** 100+ concurrent calls — use **per-user API keys** (BYOK) or a provider tier that allows high parallelism.
- **Beyond ~128:** run **2+ gateway instances** behind a load balancer (each with `max_concurrent_agents: 128`).

`GET /health` → `concurrency.max` should match your config (default **128**).

**Example for 100+ on one box:**

```yaml
storage:
  postgres_url: "postgresql://..."
  session_backend: postgres
  postgres_pool_size: 64

app_gateway:
  max_concurrent_agents: 120
  agent_executor_workers: 150
  agent_queue_timeout_seconds: 600
```

## PostgreSQL storage (`storage` in config.yaml)

Shared DSN: `storage.postgres_url` (or `app_gateway.postgres_url` / `HERMES_STORAGE_POSTGRES_URL`).

| Component | Config key | Legacy store |
|-----------|------------|--------------|
| Sessions | `session_backend: auto` | `state.db` |
| Kanban | `kanban_backend: auto` | `kanban.db` / `boards/*/kanban.db` |
| Cron jobs | `cron_backend: auto` | `cron/jobs.json` |
| **App phone users + OTP** | `user_registry_backend: auto` | `app_gateway/users_registry.db` |
| App audit / vector memory | `audit_backend` / `vector_memory_backend` | `app_gateway/*.db` |

One-shot migration:

```bash
uv pip install -e ".[postgres]"
python scripts/migrate_hermes_to_postgres.py --dry-run
python scripts/migrate_hermes_to_postgres.py
python scripts/migrate_hermes_to_postgres.py --only kanban
python scripts/migrate_hermes_to_postgres.py --only cron
```

Kanban boards become PostgreSQL schemas `kanban_<slug>` (e.g. `kanban_default`).
Cron stores one row per job in `hermes_cron_jobs` (legacy `hermes_cron_store` JSON blob kept in sync).

**Performance (multi-user, local PG):** one persistent connection per DSN per process
(same pattern as SQLite `SessionDB`). Enable `pg_trgm` in PostgreSQL for session search parity
(`scripts/postgres-init-extensions.sql` or Docker compose init).

## Memory isolation (phase 2)

- **Session DB**: `app:{user_id}:{session_id}`
- **gateway_session_key**: `agent:app:{user_id}:session:...`
- **Vector FTS**: every query includes `WHERE user_id = ?` — no cross-user reads

## PostgreSQL

```bash
uv pip install -e ".[postgres]"
export APP_GATEWAY_POSTGRES_URL=postgresql://...
# or shared DSN for multiple features:
export HERMES_STORAGE_POSTGRES_URL=postgresql://...
```

You can also set `storage.postgres_url` in `config.yaml` (merged when `app_gateway.postgres_url` is empty).

Set `audit_backend: postgres`, `dual` (SQLite + Postgres), or **`auto`**.

For vector memory on PostgreSQL, set `vector_memory_backend: postgres` (requires DSN) or **`auto`** with a DSN and `hermes-agent[postgres]` installed.

## Proxy mode

When `proxy_to_api_server: true`, mobile clients hit **8787** (JWT), and the gateway forwards to the existing **api_server** on **8642**, injecting `X-Hermes-Session-Id` / `X-Hermes-Session-Key`. Start api_server via `hermes gateway` with `API_SERVER_ENABLED=true`.

## Overrides file

`~/.hermes/app_gateway/overrides.yaml`:

```yaml
system_prompt_prefix: |
  You serve authenticated mobile users only.
tools_note: Never reveal other users' data.
```

Reload without restart: `POST /v1/admin/config/reload` with `X-App-Key`.
