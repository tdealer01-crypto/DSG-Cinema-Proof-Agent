"""Validate the isolated Ubuntu Noble image's static provenance and release contract.

These tests do NOT establish a security pass; live CI image build and ECR scan
are required to make any promotion decision.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
DOCKER = ROOT / "Dockerfile.cinema.noble"
WORKFLOW = ROOT / ".github/workflows/validate-cinema-noble-candidate.yml"


class NobleCandidateSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = DOCKER.read_text(encoding="utf-8")
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_all_build_stages_use_ubuntu_noble(self):
        self.assertEqual(self.source.count("FROM ubuntu:24.04"), 3)
        self.assertNotIn("FROM python:3.11-slim-trixie", self.source)
        self.assertNotIn("snapshot.debian.org", self.source)

    def test_source_packages_signed_and_built_on_same_distro(self):
        self.assertEqual(self.source.count("Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg"), 2)
        self.assertIn("apt-get source git", self.source)
        self.assertIn("apt-get source cups", self.source)
        self.assertIn("NO_CURL=YesPlease", self.source)
        self.assertIn("--with-tls=openssl", self.source)
        self.assertIn("dpkg-deb --build", self.source)

    def test_exact_runtime_package_security_floor(self):
        self.assertIn("2.39-0ubuntu8.9", self.source)
        self.assertIn("2.9.14+dfsg-1.3ubuntu3.10", self.source)
        self.assertIn("libxml2", self.source)
        self.assertIn("zlib1g", self.source)

    def test_gnutls_absent_and_chromium_pipeline_preserved(self):
        self.assertIn("! dpkg-query -W libgnutls30t64", self.source)
        self.assertIn("! ldconfig -p | grep libgnutls", self.source)
        self.assertIn("python -m playwright install chromium", self.source)
        self.assertIn("GnuTLS not included", self.source)
        self.assertIn('DSG_BROWSER_PROVIDER=self_hosted', self.source)
        self.assertIn('DSG_PLATFORM_REQUIRE_AUTH=1', self.source)
        self.assertIn('RUN python market_ready_payload/reconstruct.py', self.source)

    def test_candidate_workflow_is_not_automatic_production_publisher(self):
        self.assertIn("Dockerfile.cinema.noble", self.workflow)
        self.assertIn("docker build", self.workflow)
        self.assertIn("docker run --rm -i", self.workflow)
        self.assertIn("CINEMA_NOBLE_CHROMIUM_SMOKE=PASS", self.workflow)
        self.assertIn("CINEMA_NOBLE_LOCAL_GIT_SMOKE=PASS", self.workflow)
        self.assertNotIn("aws ecr put-image", self.workflow)
        self.assertNotIn("docker push", self.workflow)
        self.assertNotIn("aws-actions/configure-aws-credentials", self.workflow)
        self.assertNotIn("workflow_dispatch", self.workflow)


if __name__ == "__main__":
    unittest.main()
