# JetBrains Marketplace — Plugin Offer Pack

## Product concept

**Plugin name:** DSG Verified Execution

**Purpose:** Add a familiar IDE surface for sending bounded execution facts to the Cinema `/verify/evaluate` API and displaying the resulting Proof Receipt.

## UX

Keep the plugin thin and familiar to JetBrains users:

- tool window named **DSG Proof**
- one primary action: **Verify execution**
- status badge: ALLOW / REVIEW / BLOCK
- expandable sections: Plan alignment, Z3 verification, Replay, Evidence, Cost
- copy buttons for `proof_hash`, `context_hash`, and `execution_id`
- no Z3 backend credential stored in the IDE plugin

## Marketplace listing copy

**Short description:** Deterministic Z3 proof receipts for AI and automated actions from your JetBrains IDE.

**Long description:** DSG Verified Execution sends bounded execution facts to a Cinema verification service, verifies plan alignment and deterministic constraints with exact Z3 proof, and renders a replayable Proof Receipt with authorization, replay, evidence, and hash details.

## Review requirements to satisfy before upload

- original plugin name and branding
- 40x40 SVG plugin icon that does not resemble JetBrains product marks
- plugin compatibility verification against supported IDE builds
- signed/buildable plugin ZIP
- privacy/terms links appropriate to the distribution model
- trader/non-trader declaration for EEA consumer rules as required by JetBrains Marketplace

## Status

`PLUGIN_SPEC_PREPARED` — no plugin ZIP is claimed to be uploaded or approved yet. A new plugin and later updates are subject to JetBrains Marketplace verification/review.
