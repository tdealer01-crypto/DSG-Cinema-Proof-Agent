from __future__ import annotations

from fastapi.testclient import TestClient

import cinema_main


client = TestClient(cinema_main.app)


def test_app_loads_one_click_free_evaluation_controller():
    response = client.get("/app")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert '<script src="/app-free-evaluation.js"></script>' in response.text


def test_free_evaluation_controller_is_session_only_and_auto_activates():
    response = client.get("/app-free-evaluation.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    script = response.text

    assert 'const FREE_KEY = "dsg-one-free-session-key"' in script
    assert 'sessionStorage.setItem(FREE_KEY, key)' in script
    assert 'sessionStorage.getItem(FREE_KEY)' in script
    assert 'localStorage.setItem' not in script
    assert '/billing/activate' in script
    assert '/billing/usage' in script
    assert 'byId("btnRun")' in script
    assert 'activateFreeEvaluation({ retryRun: true })' in script
    assert 'X-DSG-API-Key' in script


def test_free_evaluation_controller_hides_raw_unknown_key_from_normal_flow():
    script = client.get("/app-free-evaluation.js").text
    assert 'jsonErrorCode(payload) === "UNKNOWN_KEY"' in script
    assert 'FREE_EVALUATION_REQUIRED' in script
    assert 'Free Evaluation is not active for this browser session' in script
    assert 'No payment card is required' in script


def test_developer_key_flow_remains_available_and_copy_is_corrected():
    script = client.get("/app-free-evaluation.js").text
    assert 'X-DSG-API-Key (Developer mode)' in script
    assert 'first Run activates Free Evaluation automatically' in script
    assert 'paid, marketplace, or developer-managed key' in script
    assert 'manualKeyPresent() || freeKey()' in script


def test_session_key_is_only_attached_to_dsg_api_surfaces():
    script = client.get("/app-free-evaluation.js").text
    assert 'target.origin !== base.origin' in script
    assert 'target.pathname.startsWith("/api/v1/")' in script
    assert 'target.pathname.startsWith("/billing/")' in script
    assert '!headers.has("X-DSG-API-Key")' in script


def test_console_exposes_explicit_plan_approval_control():
    script = client.get("/app-free-evaluation.js").text
    assert 'approve.id = "btnApprovePlan"' in script
    assert 'approve.textContent = "✓ Approve Plan"' in script
    assert 'keyedJson("/api/v1/plans"' in script
    assert '/approve`' in script
    assert 'plan_hash: created.plan_hash' in script
    assert 'approved?.status !== "APPROVED"' in script
    assert 'const APPROVED_PLAN = "dsg-one-approved-plan-session"' in script
    assert 'sessionStorage.setItem(APPROVED_PLAN' in script
    assert 'Run full flow will reuse this real approval' in script


def test_console_exposes_same_origin_shared_browser_viewer():
    script = client.get("/app-free-evaluation.js").text
    assert 'browser.id = "btnSharedBrowser"' in script
    assert 'browser.textContent = "▣ Shared Browser"' in script
    assert 'keyedJson("/remote-browser/browserbase/live-frame"' in script
    assert 'live?.connected !== true || !live?.embed_url' in script
    assert 'new URL(live.embed_url, configuredBase()).toString()' in script
    assert 'dsgSharedBrowserFrame' in script
    assert 'same managed session shared with the agent' in script
