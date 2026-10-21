# DSG OS: Auth0 user login to existing Cinema Free account

## Scope and status (2026-10-22)

**Implemented in this PR:** The customer dashboard offers the existing DSG ONE OAuth Workroom as the primary browser entry, with developer-managed API keys behind an advanced disclosure. Existing API and billing controls are unchanged. This is a UX entry correction, **not** a completed OAuth-to-Cinema account-binding or shared-viewer activation.

**Still required before claiming account migration / same-session login:** a separately reviewed, server-side, verified identity binding that uses the user's *existing* Cinema Free account (or creates a new Free account with explicit consent), with no bearer/access token or Cinema master key in browser links, localStorage, logs, or public plugin payloads.

## Canonical identity and authority

1. The user signs into DSG ONE via the existing Auth0 **Authorization Code + PKCE** flow at `dsg.pics`, never a second Auth0 application or new OAuth client. For ordinary user access use the existing `dsg.use` client; approver-only tokens (`dsg.approve`) cannot be accepted as an agent executor.
2. The existing DSG ONE server independently verifies **RS256/JWKS**, exact HTTPS issuer `https://dev-kcddqmnusbxxo25s.us.auth0.com/`, audience `https://aws.dsg.pics`, allowed `azp`, `exp/iat`, and `dsg.use`. `sub` alone, browser cookie alone, untrusted headers, account name, email, or a session-claim URL cannot confer Cinema access.
3. The existing `dsg_auth0_identity_links` mapping enforces a unique, double-authenticated link between a DSG ONE actor and Auth0 `sub`. The server must check current workspace membership/authority on every account bind, not trust client-supplied account IDs or role strings.
4. The resulting Cinema account binding MUST be account-scoped. An old Free Cinema API key/account can be linked only after proof of ownership of **both** identities. Do not silently attach a shared production enterprise account to all OAuth users or recreate duplicate Free accounts on each login. A missing/ambiguous mapping must fail closed with a specific remediation.
5. The browser receives only an HttpOnly/Secure/SameSite bound user session (or another standard OAuth session); never the master Cinema key. Keep internal credentials server-side; use CSRF and Origin protection on mutations. Tokens are not transferred in redirects, fragments, query strings, `postMessage`, logging, or analytics.
6. The existing signed Spacetime plan/approval/evidence authority is unchanged. Viewer access must be authorized against the same actual Cinema account/profile/session as the agent connection. Shared Browser `connected`, human viewer session ID, exact provider and signed agent evidence must match to claim same-session E2E.
7. Free entitlements remain Free and metered/limited; server-side account claims cannot bypass `billing.authorize_account` or uplift paid plans. Developer API-key mode remains opt-in for existing integrations.
8. Deployment is **AWS-only**. No Azure runtime/fallback, no hosted third-party RDC, no new independent browser service.

## Acceptance gates

- Normal user: DSG ONE login -> OAuth verified -> unique website actor/workspace -> explicit/verified Cinema Free account binding -> account-scoped session -> Shared Browser live human viewer -> approved agent joins same immutable browser context -> signed execution -> independently verified evidence.
- Negative: unsigned/expired/wrong-audience/wrong-azp/missing-scope JWT, mismatched site actor, wrong Cinema account, revoked membership, unapproved remote write, expired session, cross-account session ID, missing viewer, or token replay must be **DENIED**, not auto-provisioned.
- Existing developer keys and historical Free accounts continue working unchanged. A source build and CI PASS alone do **not** satisfy runtime acceptance. Verify the deployed image digest and exact ECR zero Critical/High before promotion.

## Immediate supported no-key browser path

`https://dsg.pics/dsg/workroom?tool=browser#live-controls`

The current Workroom uses the existing OAuth user-bound Spacetime tools and does not require pasting a Cinema API key. It is NOT yet a proof that the direct Cinema customer Dashboard and Workroom share a Free account or viewer.
