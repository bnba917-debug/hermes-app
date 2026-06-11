CREATE TABLE IF NOT EXISTS hermes_app_skill_files (
    id BIGSERIAL PRIMARY KEY,
    skill_id BIGINT NOT NULL REFERENCES hermes_app_skills(id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    content TEXT NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL,
    UNIQUE (skill_id, relative_path)
);

CREATE INDEX IF NOT EXISTS idx_hermes_app_skill_files_skill
ON hermes_app_skill_files (skill_id, relative_path);
