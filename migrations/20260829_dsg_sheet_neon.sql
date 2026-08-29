-- DSG Sheet / Fabric registry.
-- Source-controlled PostgreSQL migration intended for Neon Postgres.
-- The runtime remains provider-agnostic; Neon persists the sheet state only.

CREATE SCHEMA IF NOT EXISTS dsg_fabric;

CREATE TABLE IF NOT EXISTS dsg_fabric.cells (
    cell_id SMALLINT PRIMARY KEY CHECK (cell_id BETWEEN 1 AND 100),
    slug TEXT UNIQUE,
    display_name TEXT,
    kind TEXT NOT NULL DEFAULT 'empty',
    provider TEXT,
    occupied BOOLEAN NOT NULL DEFAULT FALSE,
    capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK ((occupied = FALSE AND slug IS NULL AND display_name IS NULL AND provider IS NULL)
        OR (occupied = TRUE AND slug IS NOT NULL AND display_name IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS dsg_fabric.compositions (
    composition_id TEXT PRIMARY KEY,
    goal TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PASSED', 'BLOCKED')),
    required_capabilities JSONB NOT NULL,
    missing_capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dsg_fabric.composition_cells (
    composition_id TEXT NOT NULL REFERENCES dsg_fabric.compositions(composition_id) ON DELETE CASCADE,
    cell_id SMALLINT NOT NULL REFERENCES dsg_fabric.cells(cell_id),
    PRIMARY KEY (composition_id, cell_id)
);

CREATE TABLE IF NOT EXISTS dsg_fabric.evidence_refs (
    evidence_hash TEXT PRIMARY KEY,
    composition_id TEXT REFERENCES dsg_fabric.compositions(composition_id) ON DELETE SET NULL,
    proof_ref TEXT,
    source TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO dsg_fabric.cells (cell_id)
SELECT value FROM generate_series(1, 100) AS value
ON CONFLICT (cell_id) DO NOTHING;

WITH assigned(cell_id, slug, display_name, kind, provider, capabilities) AS (
    VALUES
      (1, 'dsg-core', 'DSG Core', 'core', 'dsg', '["runtime"]'::jsonb),
      (2, 'governance', 'Governance', 'core', 'dsg', '["governance","policy","permission"]'::jsonb),
      (3, 'execution', 'Execution', 'core', 'dsg', '["execution"]'::jsonb),
      (4, 'z3', 'Z3', 'core', 'dsg', '["exact-verification","solver"]'::jsonb),
      (5, 'evidence', 'Evidence', 'core', 'dsg', '["evidence"]'::jsonb),
      (6, 'proof', 'Proof', 'core', 'dsg', '["proof"]'::jsonb),
      (7, 'replay', 'Replay', 'core', 'dsg', '["replay"]'::jsonb),
      (8, 'identity', 'Identity', 'core', 'dsg', '["identity"]'::jsonb),
      (9, 'connection-broker', 'Connection Broker', 'core', 'dsg', '["connection","credential-broker"]'::jsonb),
      (10, 'mcp', 'MCP Surface', 'interface', 'dsg', '["mcp"]'::jsonb),
      (11, 'neon-postgres', 'Neon Postgres', 'provider', 'neon', '["memory","postgres","state"]'::jsonb),
      (12, 'github', 'GitHub', 'provider', 'github', '["source","repository","ci"]'::jsonb),
      (13, 'stripe', 'Stripe', 'provider', 'stripe', '["payment","billing","commerce"]'::jsonb),
      (14, 'azure-devops', 'Azure DevOps', 'provider', 'microsoft', '["devops","pipeline","deployment"]'::jsonb),
      (15, 'aws-cdk', 'AWS CDK', 'provider', 'aws', '["infrastructure","cloud","deployment"]'::jsonb),
      (16, 'nvidia', 'NVIDIA', 'provider', 'nvidia', '["gpu","inference"]'::jsonb),
      (17, 'openai', 'OpenAI Developers', 'provider', 'openai', '["model","agent","inference"]'::jsonb),
      (18, 'activecampaign', 'ActiveCampaign', 'provider', 'activecampaign', '["crm","marketing"]'::jsonb),
      (19, 'appdeploy', 'AppDeploy', 'provider', 'appdeploy', '["app-delivery","deployment"]'::jsonb),
      (20, 'marketplace', 'Marketplace', 'surface', 'dsg', '["storefront","distribution"]'::jsonb),
      (21, 'supabase', 'Supabase', 'provider', 'supabase', '["database","auth","storage","realtime"]'::jsonb)
)
UPDATE dsg_fabric.cells AS cell
SET slug = assigned.slug,
    display_name = assigned.display_name,
    kind = assigned.kind,
    provider = assigned.provider,
    occupied = TRUE,
    capabilities = assigned.capabilities,
    updated_at = CURRENT_TIMESTAMP
FROM assigned
WHERE cell.cell_id = assigned.cell_id;

CREATE INDEX IF NOT EXISTS dsg_fabric_cells_provider_idx ON dsg_fabric.cells(provider) WHERE occupied;
CREATE INDEX IF NOT EXISTS dsg_fabric_compositions_status_idx ON dsg_fabric.compositions(status, created_at DESC);
