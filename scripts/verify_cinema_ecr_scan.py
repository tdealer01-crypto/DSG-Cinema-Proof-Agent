#!/usr/bin/env python3
"""Fail closed on HIGH/CRITICAL findings for an exact ECR Cinema image.

Read-only CI validator; does not deploy, approve, mutate AWS or grant authority.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")


class ScanNotReady(ValueError):
    pass


class ScanInvalid(ValueError):
    pass


def assess(scan: Any, *, digest: str, repository: str) -> dict[str, Any]:
    if not DIGEST.fullmatch(digest):
        raise ScanInvalid("INVALID_EXPECTED_DIGEST")
    if not isinstance(repository, str) or not repository.strip():
        raise ScanInvalid("INVALID_EXPECTED_REPOSITORY")
    if not isinstance(scan, dict):
        raise ScanInvalid("SCAN_NOT_OBJECT")
    identity = scan.get("imageId")
    if (not isinstance(identity, dict) or identity.get("imageDigest") != digest
            or scan.get("repositoryName") != repository):
        raise ScanInvalid("SCAN_IMAGE_IDENTITY_MISMATCH")
    status = scan.get("imageScanStatus")
    if not isinstance(status, dict) or status.get("status") != "COMPLETE":
        raise ScanNotReady("SCAN_NOT_COMPLETE")
    findings = scan.get("imageScanFindings")
    if not isinstance(findings, dict):
        raise ScanInvalid("SCAN_FINDINGS_MISSING")
    counts = findings.get("findingSeverityCounts")
    if not isinstance(counts, dict):
        raise ScanInvalid("SCAN_COUNTS_MISSING")
    if any(not isinstance(k, str) or type(v) is not int or v < 0
           for k, v in counts.items()):
        raise ScanInvalid("SCAN_COUNTS_INVALID")
    severity = {name: counts.get(name, 0) for name in SEVERITIES}
    if severity["CRITICAL"]:
        return {"verdict": "BLOCKED", "reason": "CRITICAL_FINDINGS", "counts": severity}
    if severity["HIGH"]:
        return {"verdict": "BLOCKED", "reason": "HIGH_FINDINGS_UNREVIEWED", "counts": severity}
    return {"verdict": "SCAN_GATE_PASS", "reason": "NO_CRITICAL_OR_HIGH", "counts": severity}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--digest", required=True)
    parser.add_argument("--repository", required=True)
    args = parser.parse_args(argv)
    try:
        payload = json.load(sys.stdin)
        result = assess(payload, digest=args.digest, repository=args.repository)
    except json.JSONDecodeError:
        print("READINESS=BLOCKED reason=SCAN_JSON_INVALID")
        return 27
    except ScanNotReady as exc:
        print(f"READINESS=BLOCKED reason={exc}")
        return 26
    except ScanInvalid as exc:
        print(f"READINESS=BLOCKED reason={exc}")
        return 28
    counts = result["counts"]
    print("AWS_CINEMA_ECR_SCAN " + " ".join(f"{k.lower()}={counts[k]}" for k in SEVERITIES))
    if result["verdict"] == "BLOCKED":
        print(f"READINESS=BLOCKED reason={result['reason']}")
        print("nextAction=Review exact ECR findings and Debian package fixes, "
              "rebuild a new immutable image, then rerun the scan. "
              "Do not claim unresolved HIGH findings are fixed or waived.")
        return 25 if result["reason"] == "CRITICAL_FINDINGS" else 29
    print("AWS_CINEMA_ECR_SCAN_GATE=PASS")
    print("CINEMA_IMAGE_DEPLOYMENT=NOT_VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
