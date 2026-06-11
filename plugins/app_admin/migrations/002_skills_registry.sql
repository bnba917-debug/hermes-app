CREATE TABLE IF NOT EXISTS hermes_app_skills (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    visibility TEXT NOT NULL CHECK (visibility IN ('public', 'private')),
    owner_user_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('active', 'disabled', 'deleted')),
    description TEXT NOT NULL DEFAULT '',
    skill_md TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL,
    UNIQUE NULLS NOT DISTINCT (name, visibility, owner_user_id)
);

CREATE INDEX IF NOT EXISTS idx_hermes_app_skills_visible
ON hermes_app_skills (visibility, status, name);
