# Verified browser task loop

Status: implementation and acceptance scope must be read with the attached execution evidence. This client uses the existing Cinema/Azure browser and existing approval boundary.

## Use

Install with `bash scripts/install_dsg_browser.sh`. Connect the existing approved browser task using the canonical instructions in REMOTE_BROWSER_USAGE.md. The connected DSG agent reads `dsg-browser context --goal "your goal"`, proposes a JSON task from observed selectors, and runs `dsg-browser task task.json --output evidence/task-1`. Open `evidence/task-1/report.html` to see the Thai status, events and JSON evidence. Resume that same task with `--resume`.

The schema is `dsg.browser-task.v1`: goal, plan_id, step_id, allowed_origins, steps and non-empty success assertions. Each step has id, action {kind, parameters}, and optional expect assertions. Assertions are exact sanitized URL or exact unique control selector plus text/checked/disabled/required/tag/type equality. The connected session must match plan_id and step_id. The native Cinema API remains authoritative for each action; the client never creates approvals for normal tasks.

PASS requires the whole task's assertions. An accepted click alone is not task success. Every action is followed by a fresh read; before-dispatch intent is checkpointed. An uncertain mutation is never blindly replayed. If its postcondition can be established, resume advances without sending it again; otherwise the report asks for user input. A completed resume returns the historical result, not a new provider-state claim.

## Real Azure acceptance

Run `python scripts/verify_browser_task_azure.py --output /tmp/new-empty-evidence-directory`.

This explicitly provisions a synthetic test account on the existing Azure provider, gives the test harness fixture-only approval, enables that account's remote session, and exercises the built-in smoke page. It does not use the owner's browser credentials or deploy production code. Temporary credentials are outside the evidence output and test remote authority is revoked in finally. This test approval is not an owner/customer workflow approval.

The proof includes actual navigate, type, click and artifact upload; final DOM checks; a deliberately unmet final condition; disabled-target NEED_USER; a client timeout injected AFTER a real Azure click followed by read-only reconciliation; completed resume without replay; and native Cinema rejection of an out-of-scope origin. Evidence includes source file hashes, action receipts, chained local events and a real Azure PNG screenshot.

## Precise limitations

- The agent/planner supplies the task; this module does not call DSG-Agent-v0 or another LLM itself. The context purpose hint is an inference, never authority.
- The existing provider extracts main-document controls. Raw DOM, frames, form values and detailed page errors are not added by this client. Truncated context blocks further control mutation.
- UI assertions do not prove database persistence, business transaction completion, arbitrary website compatibility, select-option verification or secret-reference injection.
- The lease prevents concurrent instances of this local coordinator using the same session file. It is not a distributed account-wide lease and cannot prevent human edits between observation and dispatch.
- Local evidence hashes are not signatures, immutable storage, certification or independent audit.
- Secret input remains on the canonical direct-user/opaque-reference path. This client deliberately excludes identity injection and arbitrary code execution.

Existing native CLI commands keep their behavior. Server API, production browser provider, approvals and persistent customer profiles are unchanged by installing the client.
