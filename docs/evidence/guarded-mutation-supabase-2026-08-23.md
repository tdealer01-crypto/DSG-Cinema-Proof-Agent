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

## Cleanup

The two test tenants (`acct_dsg_live_…`, `acct_dsg_other_…`) and every guarded
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
