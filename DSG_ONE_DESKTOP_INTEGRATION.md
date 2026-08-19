# DSG ONE + Trinity Integration

This package adds a DSG ONE pre-execution gate to the Unify desktop agent and bundles the Trinity DSG MCP bridge.

## Desktop execution path

`user task -> Magnitude plan -> DSG ONE /api/dsg/evaluate -> allow/block -> desktop action -> local JSONL evidence`

The gate is applied to `/nav`, each planned action inside `/act`, and `/execute-actions`.

Configuration is stored in `/opt/unify-desktop-assistant/agent-service/.env`:

- `DSG_ONE_API_URL` — DSG ONE deployment base URL. Empty means the remote gate is not configured.
- `DSG_ONE_TOKEN` — optional bearer token.
- `DSG_GATE_MODE` — `enforce` (default), `audit` (allow if verifier unavailable), or `off`.
- `DSG_GATE_PROFILE` — DSG evaluate profile, default `balanced`.
- `DSG_EVIDENCE_LOG` — local JSONL audit path.

When `DSG_ONE_API_URL` is set and `DSG_GATE_MODE=enforce`, verifier failure or a deny decision prevents the desktop action from executing.

## Trinity MCP

The bundled MCP bridge can be started by an MCP client with:

`/usr/local/bin/trinity-dsg-mcp`

The wrapper sources the same `.env` and points `TRINITY_API_URL` at `DSG_ONE_API_URL` when configured.

The MCP server remains stdio transport; it is not exposed as a network daemon by this package.
