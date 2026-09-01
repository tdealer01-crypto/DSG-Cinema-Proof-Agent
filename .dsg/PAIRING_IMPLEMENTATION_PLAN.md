# Agent Pairing + API Key UX implementation plan

Approved implementation target from user conversation:

1. Keep existing API-key activation flow.
2. Add Show/Hide and Copy controls for the browser-held API key.
3. Do not send the master API key into model prompts.
4. Add an agent pairing flow that uses a short-lived pairing/session token and binds the agent to the existing Cinema MCP endpoint.
5. Preserve DSG plan-bound governance for remote browser actions.
6. Add tests before claiming completion.

This file is temporary implementation evidence and may be removed before merge if the final PR description and tests fully capture the plan.
