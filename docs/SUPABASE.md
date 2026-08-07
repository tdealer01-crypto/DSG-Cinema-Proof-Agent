# Supabase audit backend

Provisioned project:

- name: `DSG-Cinema-Proof-Agent`
- ref: `iaekzuaxkctfyfxuzxyf`
- region: `ap-southeast-1`
- non-secret URL: `https://iaekzuaxkctfyfxuzxyf.supabase.co`

The service-role key is intentionally not stored in Git.

Migration: `supabase/migrations/202608071217_create_dsg_audit_chain.sql`.

Security design:

- RLS enabled on audit tables;
- no anon/authenticated policies by design (deny-by-default);
- append/get RPC execute granted only to `service_role`;
- append function serializes chain-head updates with a row lock.

A database-level self-test was run during provisioning: append -> lookup -> hash-shape check -> cleanup/reset. After cleanup the audit event count was 0 and the head returned to sequence 0 / zero hash. Application-to-Supabase runtime still requires a server-only service-role key.
