# Privacy Policy — DSG Governance Gate

**Effective date:** 24 August 2026  
**Service:** DSG Governance Gate / DSG Verified Execution  
**Rights holder and primary contact:** Thanawat Suparongsuwan  
**Contact:** [t.dealer01@dsg.pics](mailto:t.dealer01@dsg.pics)

This policy describes how DSG Governance Gate processes information when a
Stripe user installs the app or requests a payment verification.

## Information processed

For a verification, the app processes the Stripe account and Dashboard user
identifiers, the current charge or PaymentIntent identifier, amount, currency,
status, and an available Radar risk level. The backend derives a risk score,
policy decision, request hash, context hash, and exact-proof metadata.

The app is not designed to collect card numbers, bank-account credentials,
passwords, API keys, OAuth secrets, government identifiers, health data, or
other sensitive personal data. Users must not place secrets or unnecessary
personal information in support reports.

## Purposes

Information is processed to authenticate the Stripe-signed request, resolve the
installed account's DSG entitlement, calculate a bounded deterministic policy
decision, verify the exact proof, meter verified usage, prevent abuse, maintain
reliability, and respond to support or privacy requests.

## Logs, proof receipts, and retention

Operational logs may contain truncated account identifiers, object type,
status codes, timestamps, and technical error information. Proof and metering
records contain hashes, policy metadata, and the DSG account identifier needed
for quota and replay integrity. The public response does not expose Stripe,
OAuth, webhook, app-signing, or solver secrets.

Retention depends on the deployed service configuration and may be extended
when reasonably necessary for receipt replay, security investigation, billing
disputes, or legal obligations. Access or deletion requests can be sent to the
contact above with a non-secret account or proof reference sufficient to locate
the record.

## Service providers

Stripe provides app installation, Dashboard context, API access, request
signatures, and billing services. Microsoft Azure hosts the production Cinema
service and its configured durable stores. GitHub hosts source code,
documentation, issue-based support, and deployment automation. Each provider
processes information under its own terms and privacy documentation.

## Security

The production endpoint uses HTTPS. UI-to-backend requests are signed by
Stripe and verified before entitlement lookup. Backend solver and signing
credentials remain server-side. Verification fails closed when required
context, authentication, entitlement, or exact proof is unavailable. These
controls reduce risk but are not a guarantee against every security incident.

## Contact and requests

For privacy questions, access or deletion requests, contact
[t.dealer01@dsg.pics](mailto:t.dealer01@dsg.pics). Do not email passwords,
payment-card data, API keys, OAuth tokens, webhook secrets, or app signing
secrets.

This policy is not a certification of regulatory compliance or evidence that
Stripe has approved the Marketplace listing.
