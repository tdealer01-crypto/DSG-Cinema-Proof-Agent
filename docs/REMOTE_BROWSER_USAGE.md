# DSG Remote Browser Usage

## Canonical architecture

`Human / Agent / CLI -> DSG Cinema governance -> Azure shared Chromium -> Evidence`

Production provider: `azure_container_apps`.

The shared browser is account-scoped and persistent. A mobile viewer, an approved agent executor, and an agent verifier can operate on the same browser profile, tabs, cookies, login state, URL, and DOM.

Do not create a second browser stack for a task that can use this shared browser.

## Canonical product CLI

The supported CLI entry point is:

```bash
bash scripts/install_dsg_browser.sh
dsg-browser --help
```

The CLI is a thin client over the production remote-browser REST contract. It does not contain embedded credentials and does not grant authority by itself.

Authentication is provided at runtime:

```bash
export DSG_API_KEY='...'
# or, for agent use:
export DSG_PAIRING_TOKEN='dsg_pair_...'
```

`DSG_PAIRING_TOKEN` is preferred for agent commands. `DSG_API_KEY` is required to create a human viewer URL because the viewer belongs to the account owner.

Optional config file: `~/.config/dsg-browser/config.json`. If it contains credentials it must be mode `0600` or stricter.

## Human shared viewer

```bash
dsg-browser status
dsg-browser view
dsg-browser view --open
```

`view` returns a short-lived viewer URL. Opening a new viewer URL does not create a new browser profile; it attaches to the same account-scoped Azure browser session.

The mobile viewer supports touch/click, swipe/scroll, URL navigation, text input, Enter, Tab, and Backspace.

## Agent connection

Agent mutation authority is plan-bound:

```bash
dsg-browser connect \
  --plan-id plan_... \
  --step-id browser-step \
  --agent-identity my-agent
```

The approved plan must authorize the browser step and target origins. `connect` stores only the short-lived remote session token in `~/.config/dsg-browser/session.json` with mode `0600`.

Disconnect agent authority without closing the human browser:

```bash
dsg-browser disconnect
```

## Read and verify

Verifier actions are read-only:

```bash
dsg-browser extract
dsg-browser screenshot
dsg-browser screenshot --full-page
```

The CLI automatically uses `agent_verifier` for these commands.

## In-scope browser mutations

```bash
dsg-browser navigate 'https://example.com'
dsg-browser click 'button[type=submit]'
dsg-browser type 'input[name=display_name]' 'DSG ONE'
dsg-browser select 'select[name=role]' 'developer'
dsg-browser scroll --y 700
dsg-browser press Enter
```

These commands use `agent_executor` and remain subject to the approved plan, origin allowlist, remote-enabled state, and Cinema governance checks.

## Upload and download

Approved artifacts use symbolic references, never arbitrary local filesystem paths:

```bash
dsg-browser upload 'input[type=file]' 'artifact://approved/profile.png'
dsg-browser download 'a.download'
```

Downloads go to the Cinema quarantine path and are not auto-executed.

## Identity and secret boundary

The generic CLI must not type plaintext passwords, API keys, private keys, OTPs, MFA codes, or passkeys.

Sensitive identity controls remain direct-user-only unless the approved plan explicitly includes the user-controller delegation contract. Delegated secret/OTP flows use opaque references inside the trusted runtime; plaintext values must never enter the model prompt, CLI arguments, evidence, or ordinary logs.

CAPTCHA and passkey remain direct-user-only.

## Approval model

Approval is task-level, not click-level. Once a browser task is approved, ordinary in-scope navigation/click/type/select operations may continue without asking for approval on every action.

Re-approval is required when scope expands into a high-risk boundary such as payment, destructive deletion, credential/permission changes, production mutation outside the approved plan, or external publication outside the approved plan.

## Startup sequence for agents

1. Read `AGENTS.md`.
2. Read `docs/REMOTE_BROWSER_USAGE.md`.
3. Verify production provider/status.
4. Reuse the existing shared Azure browser.
5. Connect under an approved plan.
6. Execute in-scope actions continuously.
7. Verify evidence.
8. Disconnect agent authority when finished; do not destroy the user's persistent browser profile.

## Required invariants

- Production browser provider is Azure.
- Human and agent share one account-scoped persistent browser context.
- Agent mutations are plan-bound and fail closed.
- Verifier remains read-only.
- No direct model-to-browser secret injection.
- No automatic execution of downloaded files.
- No second browser stack unless the canonical provider is unavailable and an explicit architecture change is approved.
