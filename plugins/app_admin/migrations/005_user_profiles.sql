CREATE TABLE IF NOT EXISTS hermes_app_user_profiles (
    user_id TEXT PRIMARY KEY,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    env_secrets JSONB NOT NULL DEFAULT '{}'::jsonb,
    initialized_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL
);
