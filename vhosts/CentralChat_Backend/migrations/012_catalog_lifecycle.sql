-- H1b — Team catalog lifecycle: draft → review → published
-- Executar: python scripts/run_migrations.py --db-url $MEMORY_DB_URL

ALTER TABLE IF EXISTS team_agents
    ADD COLUMN IF NOT EXISTS lifecycle_status TEXT NOT NULL DEFAULT 'published';

ALTER TABLE IF EXISTS team_skills
    ADD COLUMN IF NOT EXISTS lifecycle_status TEXT NOT NULL DEFAULT 'published';

UPDATE team_agents SET lifecycle_status = 'published' WHERE published = true AND lifecycle_status IS NULL;
UPDATE team_agents SET lifecycle_status = 'draft' WHERE published = false AND lifecycle_status IS NULL;
UPDATE team_skills SET lifecycle_status = 'published' WHERE published = true AND lifecycle_status IS NULL;
UPDATE team_skills SET lifecycle_status = 'draft' WHERE published = false AND lifecycle_status IS NULL;
