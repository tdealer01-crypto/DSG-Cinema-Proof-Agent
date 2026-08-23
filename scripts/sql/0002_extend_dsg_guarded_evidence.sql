-- Extend an already-deployed dsg_guarded_evidence table to the full guarded
-- mutation shape (see api_v1/guarded_store.py GUARDED_EVIDENCE_SCHEMA_SQL).
--
-- A fresh database needs nothing from this file: the application's own bootstrap
-- creates the final shape directly. This exists for databases that already carry
-- the earlier skeleton (evidence_id, tenant_id, idempotency_key, action_hash,
-- label, created_at), so both converge on one schema.
--
-- Rows written before this migration cannot be given a plan, a decision, or a
-- DSG digest after the fact. They are marked as pre-migration rather than
-- backfilled with values that would read as real evidence: decision='PROTOTYPE'
-- and an empty evidence_hash, which fails an integrity check on purpose.

BEGIN;

ALTER TABLE dsg_guarded_evidence
    ADD COLUMN IF NOT EXISTS plan_id TEXT NOT NULL DEFAULT 'prototype',
    ADD COLUMN IF NOT EXISTS plan_hash TEXT NOT NULL DEFAULT repeat('0', 64),
    ADD COLUMN IF NOT EXISTS agent_identity TEXT NOT NULL DEFAULT 'prototype',
    ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'api',
    ADD COLUMN IF NOT EXISTS step_id TEXT,
    ADD COLUMN IF NOT EXISTS action TEXT NOT NULL DEFAULT 'prototype',
    ADD COLUMN IF NOT EXISTS target TEXT NOT NULL DEFAULT 'prototype',
    ADD COLUMN IF NOT EXISTS parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS decision TEXT NOT NULL DEFAULT 'PROTOTYPE',
    ADD COLUMN IF NOT EXISTS control_hash TEXT NOT NULL DEFAULT repeat('0', 64),
    ADD COLUMN IF NOT EXISTS mutation_status TEXT NOT NULL DEFAULT 'succeeded',
    ADD COLUMN IF NOT EXISTS outputs JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS evidence_hash TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS recorded_at TEXT NOT NULL DEFAULT '';

-- recorded_at is the timestamp the evidence hash covers, so it is stored as the
-- exact ISO-8601 string rather than as a TIMESTAMPTZ that would render back
-- differently. Pre-migration rows take theirs from created_at.
UPDATE dsg_guarded_evidence
   SET recorded_at = to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
 WHERE recorded_at = '';

-- Every later insert supplies these itself; only the one-time backfill needed a
-- default, and leaving them in place would let an incomplete write succeed.
ALTER TABLE dsg_guarded_evidence
    ALTER COLUMN plan_id DROP DEFAULT,
    ALTER COLUMN plan_hash DROP DEFAULT,
    ALTER COLUMN agent_identity DROP DEFAULT,
    ALTER COLUMN channel DROP DEFAULT,
    ALTER COLUMN action DROP DEFAULT,
    ALTER COLUMN target DROP DEFAULT,
    ALTER COLUMN decision DROP DEFAULT,
    ALTER COLUMN control_hash DROP DEFAULT,
    ALTER COLUMN mutation_status DROP DEFAULT,
    ALTER COLUMN evidence_hash DROP DEFAULT,
    ALTER COLUMN recorded_at DROP DEFAULT;

CREATE INDEX IF NOT EXISTS dsg_guarded_evidence_tenant_created_idx
    ON dsg_guarded_evidence (tenant_id, created_at DESC);

COMMIT;
