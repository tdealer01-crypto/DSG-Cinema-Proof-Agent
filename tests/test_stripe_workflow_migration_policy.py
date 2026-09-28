from pathlib import Path

WORKFLOW = Path(".github/workflows/stripe-app-v2-7.yml").read_text(encoding="utf-8")


def test_azure_live_binding_is_manual_only_during_aws_migration():
    assert "package-production:" in WORKFLOW
    assert "if: github.event_name == 'workflow_dispatch'" in WORKFLOW
    assert "github.event_name == 'push' || github.event_name == 'workflow_dispatch'" not in WORKFLOW


def test_verification_still_runs_on_pull_request_and_push():
    assert "pull_request:" in WORKFLOW
    assert "push:" in WORKFLOW
    assert "name: Verify Stripe UI and Cinema policy proof" in WORKFLOW
