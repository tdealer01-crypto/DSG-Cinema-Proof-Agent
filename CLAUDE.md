# CLAUDE.md

The agent guide for this repository is **[AGENTS.md](AGENTS.md)**. Read it
before changing anything — it is short, and every rule in it is one CI already
enforces.

The four that cost the most time when missed:

- `landing/index.html` and `azure-landing/index.html` must stay **byte-identical**.
- Nothing under `marketplace/` may contain a retired Control Plane URL — including
  a diff line that *removes* one.
- `checkout_status` takes only `LINKED` or `NOT_VERIFIED_NOT_LINKED`.
  `LINKED_VERIFIED` is `stripe.link_state`, a different field.
- The `launch-manifest.json` truth-boundary guards are deliberate. Raising a
  claim there is the owner's decision, not a side effect of another change.

Run `python3 -m pytest -q` from the repo root before any push. Fetch
`/openapi.json` from production before asserting that a route exists.
