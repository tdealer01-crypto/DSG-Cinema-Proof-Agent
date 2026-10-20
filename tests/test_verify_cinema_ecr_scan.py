"""Hermetic regression tests for Cinema ECR scan policy; no AWS calls."""
import importlib.util
from pathlib import Path
import json
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_cinema_ecr_scan.py"
DIGEST = "sha256:" + "a" * 64
REPO = "dsg-cinema-prod"

spec = importlib.util.spec_from_file_location("ecr_verify", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def scan(**counts):
    return {"repositoryName": REPO, "imageId": {"imageDigest": DIGEST},
            "imageScanStatus": {"status": "COMPLETE"},
            "imageScanFindings": {"findingSeverityCounts": counts}}


class ScanGateTests(unittest.TestCase):
    def cli(self, payload):
        return subprocess.run([sys.executable, str(SCRIPT), "--digest", DIGEST,
                               "--repository", REPO],
                              input=json.dumps(payload), text=True, capture_output=True)

    def test_empty_findings_do_not_imply_deployment(self):
        p = self.cli(scan())
        self.assertEqual(p.returncode, 0)
        self.assertIn("AWS_CINEMA_ECR_SCAN_GATE=PASS", p.stdout)
        self.assertIn("CINEMA_IMAGE_DEPLOYMENT=NOT_VERIFIED", p.stdout)

    def test_current_cinema_candidate_with_ten_high_fails_closed(self):
        p = self.cli(scan(HIGH=10, MEDIUM=22, LOW=11))
        self.assertEqual(p.returncode, 29)
        self.assertIn("HIGH_FINDINGS_UNREVIEWED", p.stdout)
        self.assertNotIn("SCAN_GATE=PASS", p.stdout)

    def test_critical_blocks_even_if_high_zero(self):
        p = self.cli(scan(CRITICAL=1, HIGH=0))
        self.assertEqual(p.returncode, 25)
        self.assertIn("CRITICAL_FINDINGS", p.stdout)

    def test_medium_does_not_automatically_block_existing_policy(self):
        self.assertEqual(self.cli(scan(MEDIUM=22, LOW=11)).returncode, 0)

    def test_digest_binding_prevents_replay_from_another_image(self):
        fake = scan()
        fake["imageId"]["imageDigest"] = "sha256:" + "b" * 64
        self.assertEqual(self.cli(fake).returncode, 28)

    def test_repository_binding_prevents_cross_repository_scan(self):
        fake = scan()
        fake["repositoryName"] = "other-repo"
        self.assertEqual(self.cli(fake).returncode, 28)

    def test_scan_must_be_complete(self):
        fake = scan()
        fake["imageScanStatus"]["status"] = "IN_PROGRESS"
        self.assertEqual(self.cli(fake).returncode, 26)

    def test_missing_findings_is_not_zero_findings(self):
        fake = scan()
        fake.pop("imageScanFindings")
        self.assertEqual(self.cli(fake).returncode, 28)

    def test_incomplete_counts_are_rejected(self):
        fake = scan()
        fake["imageScanFindings"].pop("findingSeverityCounts")
        self.assertEqual(self.cli(fake).returncode, 28)

    def test_bool_and_negative_counts_are_invalid(self):
        for count in (True, -1, "0"):
            with self.subTest(count=count):
                self.assertEqual(self.cli(scan(HIGH=count)).returncode, 28)

    def test_unknown_non_severity_fields_still_require_nonnegative_counts(self):
        self.assertEqual(self.cli(scan(UNDEFINED=1)).returncode, 0)


if __name__ == "__main__":
    unittest.main()
