# Verification Infrastructure for Independent Evaluation

**Status:** Public evidence document  
**Date:** 2026-09-21  
**Inspected source baseline:** `5b099918b12c248533f52c740c53a6ff4655774b`

## Purpose

This document describes the parts of DSG ONE / Cinema that can support independent technical evaluation of governed AI-agent execution.

It makes two different claims, and keeps them separate:

1. **Verified implementation claim:** DSG ONE contains code paths that independently compute plan alignment, evidence integrity, replay consistency, authorization state, and deterministic solver proofs instead of accepting an agent's own verdict.
2. **External evaluation claim:** DSG ONE has **not** been independently audited, certified, or endorsed by Anthropic, Accenture, or another third-party evaluator unless a separate external artifact explicitly proves that event.

The intended evaluator workflow is therefore:

```text
approved plan
    +
observed action trace
    +
content-bearing evidence
    +
execution / proof receipts
        |
        v
DSG verification boundary
  - recompute plan alignment
  - recompute hashes
  - reject evidence mismatch
  - distinguish content-verified evidence from hash-only claims
  - compare replay outputs
  - run deterministic solver proof obligations
        |
        v
inspectable findings + hashes + receipts
        |
        v
independent evaluator / auditor / operator
```

DSG ONE is verification infrastructure that can expose inspectable evidence to an evaluator. That is not the same as claiming that an independent evaluator has already audited DSG ONE.

## Publicly inspectable implementation evidence

| Control | What the implementation does | Public source |
|---|---|---|
| Independent plan alignment | Computes alignment from the approved plan and observed action trace. It does not ask whether the agent believes it stayed inside the plan. | [`api_v1/alignment.py`](https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/blob/5b099918b12c248533f52c740c53a6ff4655774b/api_v1/alignment.py) |
| Canonical plan/action hashes | Canonical hashes bind the approved plan and the observed trace used by the alignment decision. | [`api_v1/alignment.py`](https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/blob/5b099918b12c248533f52c740c53a6ff4655774b/api_v1/alignment.py) |
| Evidence bytes are verified | When artifact bytes are supplied, DSG computes SHA-256 itself. A conflicting declared digest is rejected with `EVIDENCE_HASH_MISMATCH`. | [`api_v1/evidence.py`](https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/blob/5b099918b12c248533f52c740c53a6ff4655774b/api_v1/evidence.py) |
| Hash-only is not treated as verified content | Evidence without bytes is explicitly marked `HASH_ONLY` and does not count as independently content-verified evidence when content evidence is required. | [`api_v1/evidence.py`](https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/blob/5b099918b12c248533f52c740c53a6ff4655774b/api_v1/evidence.py) |
| Replay comparison is computed | Replay matching is derived by comparing declared action output digests with digests of content-verified artifacts. | [`api_v1/evidence.py`](https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/blob/5b099918b12c248533f52c740c53a6ff4655774b/api_v1/evidence.py) |
| Plan-bound execution authority | The Decision Core permits exact approved-plan work, blocks changed/out-of-plan actions, and keeps capability provisioning distinct from policy denial. | [`api_v1/decision_core.py`](https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/blob/5b099918b12c248533f52c740c53a6ff4655774b/api_v1/decision_core.py) |
| Mutation path re-checks authority | State-changing execution re-runs the Decision Core. `WAITING_PERMISSION` and `BLOCK` do not write an authorized-looking mutation record. | [`api_v1/mutation.py`](https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/blob/5b099918b12c248533f52c740c53a6ff4655774b/api_v1/mutation.py) |
| Storage read-back integrity | Guarded mutation evidence is read back from storage and its evidence hash is recomputed from the returned record. | [`api_v1/mutation.py`](https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/blob/5b099918b12c248533f52c740c53a6ff4655774b/api_v1/mutation.py) |
| QUBO optimum proof | The Z3 service performs an independent lower-bound proof obligation and returns `VERIFIED_GLOBAL_OPTIMUM` only when no lower-energy assignment exists. | [`z3_main.py`](https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/blob/5b099918b12c248533f52c740c53a6ff4655774b/z3_main.py) |
| Exact top-k proof | The verifier computes its own deterministic oracle and uses independent solver instances to refute both a better score and a better lexicographic tie-break. It does not accept a caller verdict. | [`z3_exact_topk.py`](https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/blob/5b099918b12c248533f52c740c53a6ff4655774b/z3_exact_topk.py) |

## Public test evidence

The repository test suite contains explicit checks for the same boundaries, including:

- rejection of `EVIDENCE_HASH_MISMATCH`;
- replay mismatch handling;
- plan parameter mismatch findings;
- verified global-optimum behavior;
- rejection of agent-supplied verdict semantics in the governed API path.

Representative test source:

- [`tests/test_api_v1.py`](https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/blob/5b099918b12c248533f52c740c53a6ff4655774b/tests/test_api_v1.py)
- [`tests/test_z3_main.py`](https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/blob/5b099918b12c248533f52c740c53a6ff4655774b/tests/test_z3_main.py)
- [`tests/test_guarded_mutation.py`](https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/blob/5b099918b12c248533f52c740c53a6ff4655774b/tests/test_guarded_mutation.py)

A test file demonstrates that a code path is exercised under the encoded test conditions. It is not, by itself, evidence that every production deployment or every external provider behaved correctly.

## What an independent evaluator can inspect

A technical evaluator can examine or request evidence at four distinct layers:

### 1. Authorization evidence

Relevant material can include:

- approved plan identifier and plan hash;
- approved agent identity;
- exact step/action/target/parameter scope;
- capability state;
- `ALLOW`, `WAITING_PERMISSION`, or `BLOCK` decision;
- control/alignment hashes.

The evaluator can compare the approved scope with the observed action trace rather than relying on a model-generated statement that execution was compliant.

### 2. Execution evidence

Relevant material can include:

- observed action records;
- content-bearing artifacts;
- computed artifact digests;
- evidence completeness findings;
- storage read-back evidence;
- idempotency/replay state.

The key distinction is that a declared hash is an attestation. Content supplied to DSG can be independently hashed and marked content-verified.

### 3. Deterministic proof evidence

For supported mathematical verification paths, relevant material can include:

- normalized solver request;
- deterministic seed/configuration;
- solver status;
- witness/result;
- request hash;
- proof hash;
- explicit proof obligation result.

The verifier's decision is separate from the candidate generator's claim.

### 4. Replay / consistency evidence

Where a workflow supplies replayable output digests and content-verified artifacts, DSG compares them and records mismatches instead of treating a declared replay result as proof.

## Independent evaluation boundary

For DSG ONE, **independent evaluation** should mean that the evaluator is not required to trust the candidate-generating agent's own statement about safety, alignment, completion, or correctness.

That can be implemented operationally by giving an evaluator access to:

```text
Plan / plan hash
Observed action trace
DSG-computed alignment
Evidence artifacts or redacted evidence package
Computed evidence hashes
Replay comparison
Z3 proof result where applicable
Execution / proof receipt
Source commit or immutable image identifier
Run-scoped deployment evidence
```

Access should remain least-privilege. Independent evaluation does not require exposing plaintext passwords, bearer tokens, private keys, OTPs, or other secrets.

## Industry context: embedded independent evaluation

On 18 September 2026, Anthropic announced a partnership with Accenture on independent embedded evaluation of frontier AI. Anthropic described embedded evaluators as having deeper access than conventional external evaluators so they can assess operations, verify safety commitments, identify blind spots, and report incidents. Anthropic also stated that independent embedded evaluators help make accountability more verifiable and noted that common standards for evaluator access and reporting do not yet exist.

Official source:

- Anthropic, **Partnering with Accenture on embedded evaluation**, 18 Sep 2026:  
  https://www.anthropic.com/news/accenture-embedded-evaluation

This reference is included as external industry context only.

**DSG ONE is not claiming a partnership with, endorsement by, certification from, or evaluation by Anthropic or Accenture.**

## What is verified vs. what is not

| Statement | Status |
|---|---|
| DSG computes plan alignment independently from the agent's self-assessment | **Verified in public source** |
| DSG can compute artifact hashes from supplied bytes and reject mismatches | **Verified in public source** |
| DSG distinguishes content-verified evidence from hash-only evidence | **Verified in public source** |
| DSG computes replay comparisons from verified digests | **Verified in public source** |
| DSG contains deterministic Z3 proof paths that do not accept caller verdicts as proof | **Verified in public source** |
| DSG provides an evidence structure suitable for inspection by an independent evaluator | **Supported by the inspected implementation** |
| A named third-party evaluator has audited DSG ONE | **Not claimed** |
| DSG ONE is independently certified | **Not claimed** |
| DSG ONE is affiliated with Anthropic or Accenture | **Not claimed** |
| A bounded proof receipt proves every real-world outcome of an AI system | **Not claimed** |

## Verification scope and limitations

This document proves only what can be traced to the public source baseline and its encoded tests.

It does **not** prove:

- legal or regulatory compliance;
- SOC 2, ISO, or other certification;
- correctness of every model output;
- correctness of an external system that was not observed;
- production success for a deployment merely because source tests pass;
- that an evaluator is organizationally independent merely because a verifier is technically separate;
- that a third party has reviewed DSG ONE.

A production or commercial claim should be tied to the exact run, source commit, image/revision, evidence package, and external status relevant to that claim.

## Public verification principle

```text
Agent assertion != evidence
Declared hash != content verification
Proposal != authority
Proof component != execution authority
Internal verification != independent third-party audit
Old PASS != proof for a later revision
```

DSG ONE's role is to make governed execution and its evidence more inspectable and independently verifiable, while keeping unsupported claims outside the verified boundary.
