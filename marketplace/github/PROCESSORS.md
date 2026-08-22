# Third-Party Processors and Subprocessors — DSG Verified Execution

**Effective date:** 22 August 2026  
**Service:** DSG Verified Execution / DSG ONE  
**Rights holder and primary contact:** Thanawat Suparongsuwan  
**Contact:** [t.dealer01@dsg.pics](mailto:t.dealer01@dsg.pics)

This document identifies the third-party providers that may process information for the production service. A provider is included because the deployment or an optional integration can use its infrastructure. The service does not send secrets or arbitrary solver programs to these providers through the public verification contract.

| Provider | Function | Data categories that may be processed | Activation condition |
|---|---|---|---|
| **Microsoft Azure** | Hosting for Azure Container Apps, container images, networking, and durable service infrastructure where configured | Request metadata, Proof Receipt data, operational logs, hashed identifiers, and service configuration metadata | Used for the production deployment and its configured Azure resources |
| **GitHub** | GitHub OAuth, GitHub Marketplace distribution, repository and GitHub Actions integration | GitHub account or organization identifiers, installation metadata, repository/workflow metadata, action inputs and outputs, and support correspondence submitted through GitHub | Used when a customer installs or operates the GitHub integration |
| **Stripe** | Optional billing, payment-status verification, usage metering, and signed webhook delivery | Stripe account and object identifiers, product/price/meter identifiers, subscription or payment status, risk fields, and webhook event metadata | Used only when the Stripe integration is enabled and verified for the relevant deployment |

## Providers not used by the public verification contract

The public verification endpoint does not require users to submit passwords, private keys, payment-card data, source code, or solver credentials. The exact Z3 verification backend is operated as part of the DSG service architecture; its backend credential is kept server-side and is not disclosed to callers.

The browser console may store an issued API key in local browser storage. Browser storage is controlled by the user's browser and is not a DSG subprocesser. Users must clear it when leaving a shared device and must never publish the key.

## Provider changes

The publisher may add, replace, or remove a provider when the deployment architecture changes. This page will be updated before or when a material provider change is introduced. Users should review the effective date and contact [t.dealer01@dsg.pics](mailto:t.dealer01@dsg.pics) with questions.

## Scope and limitation

This list describes service-level processors for the DSG Verified Execution deployment. GitHub, Azure, and Stripe may use their own affiliates and subprocessors under their respective terms and privacy documentation. The publisher does not claim that this list is a regulatory certification or an independent audit of any provider.

## Provider references

- [Microsoft Azure Trust Center](https://learn.microsoft.com/en-us/compliance/)
- [GitHub Privacy Statement](https://docs.github.com/en/site-policy/privacy-policies/github-privacy-statement)
- [Stripe Privacy Center](https://stripe.com/privacy-center/legal)
