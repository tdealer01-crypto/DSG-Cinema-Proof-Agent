# Privacy Policy — DSG Verified Execution

**Effective date:** 22 August 2026  
**Service:** DSG Verified Execution / DSG ONE  
**Rights holder and primary contact:** Thanawat Suparongsuwan  
**Contact:** [t.dealer01@dsg.pics](mailto:t.dealer01@dsg.pics)

This Privacy Policy describes how DSG Verified Execution processes information when a user installs, configures, or calls the service through a GitHub Marketplace integration, the DSG ONE console, or the public verification API.

## Information processed

The service processes the bounded execution facts required to verify a request. Depending on the integration, these may include an execution identifier, optional trace identifier, agent identity, channel, target, plan and action references, evidence metadata, output digests, verification flags, and caller-recorded cost information. The service derives hashes and proof metadata from those fields to produce a replayable Proof Receipt.

The service is designed not to require source code, passwords, private keys, payment-card numbers, or solver credentials. Users must not submit secrets or unnecessary personal information in request fields, evidence, logs, or issue reports.

When a user activates a free key in the DSG ONE console, the API issues an API key for the selected free plan. The console stores the key in that browser's local storage and sends it only to the configured DSG service endpoint. The key should be treated as a credential and must not be included in screenshots, logs, public issues, or source repositories.

## Purposes of processing

Information is processed to authenticate API requests, enforce plan limits, perform deterministic verification, generate proof and replay hashes, meter verified proof receipts where metering is enabled, prevent abuse, maintain service reliability, and respond to support requests. The service does not accept an agent-supplied verdict as proof; verification results are computed by the service and its exact verification backend.

## Logs, receipts, and retention

Operational logs may contain technical request metadata needed for reliability, abuse prevention, and security. Proof Receipts may contain execution or trace identifiers and hashes supplied or derived from a request. Users should use opaque identifiers rather than names, email addresses, customer records, or other personal data in those fields.

Retention periods depend on the deployed service configuration and the applicable integration. The publisher will retain information only for as long as reasonably necessary for the purposes above, security investigation, dispute handling, legal obligations, or receipt replay. Requests concerning deletion or retention can be sent to [t.dealer01@dsg.pics](mailto:t.dealer01@dsg.pics) with enough non-secret information to identify the relevant receipt or account.

## Processors and transfers

The third-party service providers used by the deployment are listed in the [Third-Party Processors and Subprocessors](./PROCESSORS.md) document. A provider is used only for the functions described there and only when the corresponding integration is enabled. The publisher may update that document when infrastructure or billing providers change.

## Security

The service uses HTTPS for public production endpoints, keeps backend solver credentials server-side, applies fail-closed authentication and entitlement checks, and avoids returning API keys or webhook secrets from public status routes. No security control is a guarantee against every possible threat; users remain responsible for protecting credentials and limiting the data they submit.

## Children and sensitive data

The service is a developer and automation tool and is not directed to children. Do not submit special-category, health, financial-account, payment-card, government-identifier, or other sensitive personal data unless a separately documented lawful basis and processing arrangement exists.

## Your requests and contact

For privacy questions, access or deletion requests, or concerns about data handling, contact [t.dealer01@dsg.pics](mailto:t.dealer01@dsg.pics). Do not send API keys, OAuth client secrets, webhook secrets, passwords, or payment-card data by email.

This policy describes the current intended handling for the DSG Verified Execution service. It is not a certification of regulatory compliance, an independent audit, or a promise that a third-party Marketplace has approved the listing.
