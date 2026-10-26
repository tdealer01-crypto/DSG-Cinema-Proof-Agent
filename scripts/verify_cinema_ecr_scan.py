#!/usr/bin/env python3
"""Fail-closed AWS Cinema ECR scan gate. Accepts the raw ECR response on stdin.

A successful build or an uploaded ECR image is not an approved production release.
Only a completed scan with zero reported CRITICAL/HIGH is eligible for later gates.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any


def decide(payload: Any, *, digest: str, repository: str) -> tuple[bool, str, dict[str, int]]:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest) or not repository:
        return False, "INVALID_EXPECTED_IMAGE_ID", {}
    if not isinstance(payload, dict):
        return False, "INVALID_SCAN_RESPONSE", {}
    # An ECR response must attest this *same* digest and repository, rather
    # than an unrelated successful scan or a stale source-bound image.
    if (payload.get("repositoryName") != repository
            or not isinstance(payload.get("imageId"), dict)
            or payload["imageId"].get("imageDigest") != digest):
        return False, "IMAGE_IDENTITY_MISMATCH", {}
    status = payload.get("imageScanStatus")
    if not isinstance(status, dict) or status.get("status") != "COMPLETE":
        return False, "SCAN_NOT_COMPLETE", {}
    findings = payload.get("imageScanFindings")
    if not isinstance(findings, dict):
        return False, "MISSING_FINDINGS", {}
    severities = findings.get("findingSeverityCounts")
    if not isinstance(severities, dict):
        return False, "MISSING_SEVERITY_COUNTS", {}

    result: dict[str, int] = {}
    for severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        count = severities.get(severity, 0)
        if type(count) is not int or count < 0:
            return False, "INVALID_" + severity + "_COUNT", {}
        result[severity] = count

    if result["CRITICAL"] != 0 or result["HIGH"] != 0:
        return False, "UNRESOLVED_CRITICAL_OR_HIGH", result
    return True, "PASS", result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--digest", required=True)
    parser.add_argument("--repository", required=True)
    args = parser.parse_args()
    try:
        data = json.load(sys.stdin)
    except (ValueError, UnicodeError):
        print("READINESS=BLOCKED reason=INVALID_SCAN_JSON", flush=True)
        return 25
    allowed, reason, counts = decide(data, digest=args.digest, repository=args.repository)
    if counts:
        print(
            "AWS_CINEMA_ECR_SCAN status=COMPLETE"
            f" critical={counts['CRITICAL']} high={counts['HIGH']}"
            f" medium={counts['MEDIUM']} low={counts['LOW']}",
            flush=True,
        )
    if not allowed:
        print("READINESS=BLOCKED reason=" + reason, flush=True)
        print(
            "nextAction=Remediate affected signed OS packages, build a new "
            "immutable Cinema image, and independently verify ECR findings.",
            flush=True,
        )
        return 25
    print("AWS_CINEMA_ECR_SCAN_GATE=PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
