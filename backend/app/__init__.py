"""DSG Cinema Proof Agent backend package.

Google ADK discovers ``root_agent`` from ``app.agent``. Keeping package import light lets
non-agent modules (for example audit/auth tests) run without creating external clients.
"""
