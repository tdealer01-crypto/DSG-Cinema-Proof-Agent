from __future__ import annotations

from api_v1 import agent_pairing


def test_connect_agent_page_restores_visible_free_key_activation() -> None:
    html = agent_pairing._CONNECT_HTML

    assert "Activate Free Key" in html
    assert "/billing/activate" in html
    assert "channel:'remote_browser'" in html
    assert "if(!key)key=await activateKey()" in html


def test_connect_agent_page_keeps_master_key_tab_scoped() -> None:
    html = agent_pairing._CONNECT_HTML

    assert "sessionStorage" in html
    assert "localStorage" not in html
    assert "master DSG key stays in this browser tab" in html
    assert "pairing token only" in html
