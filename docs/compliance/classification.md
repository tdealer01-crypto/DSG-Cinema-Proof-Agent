# DSG Cinema — EU AI Act Classification Record

**Status:** Preliminary internal classification; not an external legal opinion or certification.

## Intended purpose

DSG Cinema is a hosted governance and verification runtime for existing AI agents, MCP clients, automations, and API workflows. It enforces plan-bound execution, permission/capability checks, evidence capture, deterministic postconditions, and proof generation.

## Core decision mechanism

Cinema's governance core uses deterministic policy/authorization logic and formal verification components. The product documentation must not assume that deterministic governance logic is an AI system merely because it governs AI agents.

## Classification procedure

For every deployment or regulated use case, evaluate in order:

1. Does the relevant Cinema component meet the EU AI Act definition of an AI system based on its actual technical behavior and intended purpose?
2. If yes, does the intended purpose fall within a prohibited practice or high-risk category?
3. If high-risk is asserted, identify the exact Annex I or Annex III category and explain why it applies.
4. Identify the economic-operator role for DSG and the customer: provider, deployer, importer, distributor, authorised representative, or another role as applicable.
5. Record jurisdiction, intended users, affected persons, and whether substantial modification changes the classification.

## Current preliminary position

- The Cinema governance gate itself is primarily deterministic and rule/formal-proof driven.
- Controlling payment, deployment, browser, or API actions does **not by itself** establish Annex III high-risk classification.
- A customer's downstream AI use case may independently be high-risk (for example where an Annex III use case applies).
- Cinema may support high-risk systems without itself automatically becoming the regulated high-risk AI system in every deployment.

Therefore the repository must not state `Annex III high-risk` as a universal Cinema classification without a use-case-specific assessment.

## Required evidence per assessment

- Product/version/commit
- Intended purpose
- Decision/inference architecture
- Inputs and outputs
- Human oversight path
- Target sector/use case
- Annex category, if any
- Provider/deployer role analysis
- Reviewer and review date

## Public-claim rule

Allowed language:

> DSG Cinema provides technical controls and evidence that can support EU AI Act governance and conformity work where applicable.

Disallowed without external/legal basis:

> DSG Cinema is EU-certified.

> DSG Cinema is automatically an Annex III high-risk AI system.

> Z3 proof is an Article 43 conformity assessment.
