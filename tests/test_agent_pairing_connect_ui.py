from __future__ import annotations

from api_v1 import agent_pairing


def test_connect_agent_page_runs_one_click_plumbing() -> None:
    html = agent_pairing._CONNECT_HTML

    assert "Connect Agent" in html
    assert "/billing/activate" in html
    assert "channel:'remote_browser'" in html
    assert "/remote-browser/enable" in html
    assert "/remote-browser/agent-pair" in html
    assert "remote_status" in html
    assert "if(new URLSearchParams(location.search).get('auto')==='1')connectAgent()" in html


def test_connect_agent_page_keeps_master_key_tab_scoped() -> None:
    html = agent_pairing._CONNECT_HTML

    assert "sessionStorage" in html
    assert "localStorage" not in html
    assert "master DSG key stays in this browser tab" in html
    assert "short-lived pairing token only" in html
    assert "master_key_exposed_to_agent:false" in html


def test_connect_agent_page_preserves_explicit_plan_approval_boundary() -> None:
    html = agent_pairing._CONNECT_HTML

    assert "Plan approval is never skipped" in html
    assert "plan_approval_required:true" in html
    assert "after APPROVED the agent binds to that exact step automatically" in html
