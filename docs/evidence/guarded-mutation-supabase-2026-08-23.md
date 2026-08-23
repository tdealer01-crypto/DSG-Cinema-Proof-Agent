# Live Supabase guarded mutation test — 2026-08-23

Target: Supabase project `dsg-control-plane-dev` (`zeyguilldygozufpgxms`, PostgreSQL
17, ap-southeast-2), the database that already held the earlier `dsg_guarded_evidence`
skeleton.

What was checked is the part the unit suite cannot prove with fakes: that the
constraints exist in the database, and that they behave the way the code assumes.

## Schema convergence

The project already carried `dsg_guarded_evidence` with `evidence_id`, `tenant_id`,
`idempotency_key`, `action_hash`, `label`, `created_at`, a foreign key to
`dsg_revenue_accounts(account_id)` and `UNIQUE (tenant_id, idempotency_key)`.
`scripts/sql/0002_extend_dsg_guarded_evidence.sql` was applied to bring it to the
shape `api_v1/guarded_store.py` writes.

The one pre-existing row was kept rather than deleted, and is marked as
pre-migration rather than backfilled to look like real evidence:

| evidence_id | label | decision | plan_id | evidence_hash |
|---|---|---|---|---|
| `ac823896-…615862` | live Supabase evidence | `PROTOTYPE` | `prototype` | *(empty)* |

An empty `evidence_hash` fails an integrity check on purpose: no DSG digest was ever
computed for that row, and inventing one would be the exact dishonesty this feature
exists to prevent.

## Results

| Check | Result |
|---|---|
| Insert + read-back in one transaction returns the row | PASS |
| Read-back is byte-identical to what was written | PASS |
| `evidence_hash` recomputed from the read-back matches the stored digest | PASS — `85ca418e…0235fa` |
| Retry of the same key writes no second row | PASS — still `cc843a15-…b992c61`, `revision=live-1` |
| Retry does not overwrite the stored outputs | PASS — the second request's `live-2` was discarded |
| Same key + different `action_hash` is detectable from the read-back | PASS — stored `58c46b41…` ≠ submitted `eeee…`, so the store raises `IdempotencyConflict` |
| Two tenants may hold the same idempotency key | PASS — one row each |
| A row for an unregistered tenant is rejected by the database | PASS — `23503 … violates foreign key constraint "dsg_guarded_evidence_tenant_id_fkey"` |

The `ON CONFLICT (tenant_id, idempotency_key) DO NOTHING` insert followed by a
`SELECT` on the same connection is what makes the retry path return the original
row: the second insert is discarded by the constraint, and the select then reads the
committed original.

## Second run — after independent review

Review found that `parameters`/`outputs` as JSONB would break the product's central
promise: JSONB normalises numbers on the way out, so a correctly written row could
report `matches_stored: false` against its own digest. The columns were changed to
canonical JSON text and the migration converts an existing JSONB column in place.

Re-run with the value that exposes it, plus the executor observations the first
version silently dropped:

| Check | Result |
|---|---|
| `1e16` in `parameters` reads back unchanged | PASS — stored and returned as `1e+16`, not `10000000000000000` |
| `evidence_hash` recomputed from that read-back matches | PASS — `f46784c2…0ba3e9d` |
| `output_sha256`, `started_at`, `finished_at` are stored | PASS |

## Third run — the migration applied by the deployment path

The first two runs drove SQL through the Supabase API from a container that had
no PostgreSQL URI. `.github/workflows/apply-guarded-migration.yml` closes that
gap: the URI is a `production` environment secret, so only a workflow run can
reach it, and `scripts/apply_guarded_migration.py` bootstraps the schema, applies
0002, and then reports what the database actually holds.

Four attempts were needed, and each stopped before touching the database:

| Attempt | Stopped at | Fix |
|---|---|---|
| 1 | the secret read back empty | the job has to name `environment: production` |
| 2 | `sslmode` was not written into the URI | enforce TLS on the connection instead of validating the string |
| 3 | prepared statements against the pooler on port 6543 | disable them; a pooled transaction lands on another backend |
| 4 | — | applied |

The fourth run reported the live schema and its own verdict:

```
OK: schema matches what this runtime writes
```

22 columns, and the four constraints this feature depends on, read back from the
database rather than asserted:

```
PRIMARY KEY (evidence_id)
FOREIGN KEY (tenant_id) REFERENCES dsg_revenue_accounts(account_id)
UNIQUE (tenant_id, idempotency_key)
CHECK (char_length(label) >= 1 AND char_length(label) <= 200)
```

`parameters` and `outputs` came back as `text`. The script fails the run if they
are `jsonb`, because a payload that reads back normalised cannot reproduce its own
`evidence_hash`.

## Cleanup

Both runs' test tenants (`acct_dsg_live_…`, `acct_dsg_other_…`) and every guarded
evidence row they produced were deleted. The database was left holding only the one
pre-existing prototype row described above.

## Reproducing with the full stack

This run drove SQL directly, because the container had no PostgreSQL URI — only
Supabase API access. `scripts/live_supabase_mutation_test.py` runs the same checks
through the HTTP endpoint and the real `psycopg` store, including verifying the
committed row from a second, independent connection:

```bash
export DSG_REVENUE_DATABASE_URL='postgresql://…@…pooler.supabase.com:5432/postgres?sslmode=require'
python scripts/live_supabase_mutation_test.py
```

It creates a throwaway tenant, exercises execute → read-back → retry → conflict →
cross-tenant isolation, and deletes its own rows unless `--keep` is passed.
