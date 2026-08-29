from api_v1 import mcp
from api_v1.sheet import ASSIGNED_CELLS, compose, get_cell, install_mcp_tools, sheet_snapshot


def test_sheet_has_exactly_100_stable_cells():
    snapshot = sheet_snapshot()
    assert snapshot["status"] == "PASSED"
    assert snapshot["sheet_size"] == 100
    assert len(snapshot["cells"]) == 100
    assert [cell["cell_id"] for cell in snapshot["cells"]] == list(range(1, 101))
    assert snapshot["occupied_count"] == len(ASSIGNED_CELLS)
    assert snapshot["empty_count"] == 100 - len(ASSIGNED_CELLS)


def test_neon_is_memory_cell_11():
    result = get_cell(11)
    assert result["cell"]["occupied"] is True
    assert result["cell"]["slug"] == "neon-postgres"
    assert "memory" in result["cell"]["capabilities"]


def test_empty_cell_is_explicit_not_invented():
    result = get_cell(100)
    assert result["cell"] == {
        "cell_id": 100,
        "occupied": False,
        "slug": None,
        "name": None,
        "kind": "empty",
        "provider": None,
        "capabilities": [],
    }


def test_composition_resolves_memory_source_payment_deterministically():
    first = compose("global store", ["payment", "memory", "source"])
    second = compose("global store", ["source", "payment", "memory", "payment"])

    assert first["status"] == "PASSED"
    assert second["status"] == "PASSED"
    assert [cell["cell_id"] for cell in first["selected_cells"]] == [11, 12, 13]
    assert first["required_capabilities"] == second["required_capabilities"]
    assert first["selected_cells"] == second["selected_cells"]


def test_missing_capability_fails_closed():
    result = compose("unknown system", ["memory", "teleportation"])
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "MISSING_CAPABILITY"
    assert result["missing_capabilities"] == ["teleportation"]
    assert [cell["cell_id"] for cell in result["selected_cells"]] == [11]


def test_mcp_sheet_tools_install_once():
    before = tuple(tool.name for tool in mcp.TOOLS)
    install_mcp_tools()
    once = tuple(tool.name for tool in mcp.TOOLS)
    install_mcp_tools()
    twice = tuple(tool.name for tool in mcp.TOOLS)

    assert once == twice
    assert set(once) >= {"dsg_sheet_list", "dsg_sheet_get", "dsg_sheet_compose"}
    assert len(once) == len(set(once))
    assert set(before).issubset(set(once))
