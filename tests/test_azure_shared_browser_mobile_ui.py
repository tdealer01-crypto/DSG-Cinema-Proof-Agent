from api_v1.browserbase_live_ui import _azure_view_page


def _html() -> str:
    return _azure_view_page("viewer-test-token").body.decode("utf-8")


def test_azure_shared_browser_mobile_keyboard_controls_are_present() -> None:
    page = _html()
    assert 'id="kbd"' in page
    assert 'id="send"' in page
    assert 'data-key="Enter"' in page
    assert 'data-key="Tab"' in page
    assert 'data-key="Backspace"' in page
    assert "act('type',{text})" in page


def test_azure_shared_browser_uses_pointer_and_touch_input() -> None:
    page = _html()
    assert "addEventListener('pointerup'" in page
    assert "addEventListener('touchstart'" in page
    assert "addEventListener('touchend'" in page
    assert "act('click',p)" in page
    assert "act('scroll'" in page
