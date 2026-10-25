# Cinema Auth0 audience interoperability

## Actual user journey

The production DSG website Viewer entry was initially disabled while its help text said to click it. WebsitePR261 fixed that entry, passed exact-source CI and deployed source53782f1c. A real browser click on the repaired primary entry reached Auth0. The owner then used the browser's secure Google authentication flow; no secret value was exposed to the agent. The real Workroom subsequently showed its tool session ready.

The next real Viewer click obtained and verified the governed Cinema status receipt, then failed with `AUTH0_ISSUER_AUDIENCE_CLIENT_DENIED`. This is a provider authentication interoperability failure; the authenticated frontend browser is not the canonical Cinema execution browser, and its cookies were never copied there.

## Narrow source defect and repair

The Cinema verifier compared the signed `aud` claim only with one string. [Auth0 documents](https://auth0.com/docs/secure/tokens/access-tokens/get-access-tokens#multiple-audiences) that requesting a custom API audience with `openid` produces an array including that API and `/userinfo`. [RFC7519 section4.1.3](https://www.rfc-editor.org/rfc/rfc7519#section-4.1.3) permits an audience string or an array of case-sensitive strings.

The repair accepts an exact expected audience string or a well-formed string array containing that exact audience. It rejects empty, malformed and nonmatching values. Fixed issuer/client, pinned-issuer RSA signature, scope, expiry, subject, independent site assertion, membership, account ownership and replay checks remain unchanged. No allowlist, audience, client, account binding, MFA policy or browser session is replaced.

The actual user access token was never inspected or retained. Array-audience incompatibility is reproduced with locally signed fixtures; live resolution must still be established after a source-bound deployment and another actual Viewer attempt.

## Actual validation and constraints

- Before repair: four new valid-array cases failed,42 tests passed, including the existing scalar audience. The complete Viewer handler also rejected the otherwise valid array token.
- After repair:46 targeted OAuth/account/viewer tests passed, including malformed audiences and issuer/client/scope/time/subject denials.
- Full repository run (optional benchmarks excluded as permitted byAGENTS):836 passed, one failed,15subtests passed. The unchanged baseline also reproduces that failure: this managed local root process cannot call `setgroups([])` in the sandbox privilege-drop preexec. A disposable child confirmed PermissionError/errno1. Two additional initial environment failures were resolved by installing local `socksio` support for this environment's existing proxy; no proxy setting or product dependency was changed.
- No sandbox test or production privilege-drop guard is skipped, mocked out or weakened. The branch is prepared for independent exact-source CI; local full-suite success is NOT claimed. The API CI now runs the complete repository suite, including the unchanged sandbox test, and verifies checkout SHA before testing. No merge or production readiness is inferred before the required CI succeeds.
- This CI-only draft preparation is an explicit local-environment exception to the usual green-before-push rule, within the owner's authorized repair. It is not a release waiver. Production activation remains gated by full CI, a zero-HIGH/CRITICAL Noble image, the existing protected Cinema-only promotion and fresh live observations.

The existing Noble validation/staging workflows now include this OAuth source path, so the repair is tested and staged in the same canonical image family. No new infrastructure, browser execution provider, unrelated service recreation, secret retrieval or automatic business action is included.
