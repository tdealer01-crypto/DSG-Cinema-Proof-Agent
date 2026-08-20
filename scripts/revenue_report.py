#!/usr/bin/env python3
"""Reconcile the DSG revenue ledger and render an evidence-backed report.

The script is deliberately dumb about money: it reports only what the live
service returns, and prints UNAVAILABLE where it could not read anything. It
never estimates, projects, or fills a gap with a plausible number.

Usage:
    python3 scripts/revenue_report.py --base-url https://cinema.example \\
        --admin-secret "$DSG_REVENUE_ADMIN_SECRET" --output revenue-report.md

Exit codes:
    0  every required probe returned validated evidence
    1  usage error
    2  a reachable service returned a broken ledger chain
    3  one or more required probes were unavailable or malformed
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

UNAVAILABLE = "UNAVAILABLE"
DEFAULT_TIMEOUT = 20


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def micros_to_usd(micros: int) -> str:
    sign = "-" if micros < 0 else ""
    whole, fraction = divmod(abs(micros), 1_000_000)
    return f"{sign}${whole}.{fraction:06d}"


def probe(
    base_url: str,
    path: str,
    admin_secret: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """GET one endpoint and return a structured outcome, never raising."""
    url = f"{base_url.rstrip('/')}{path}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    if admin_secret:
        request.add_header("Authorization", f"Bearer {admin_secret}")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            status = response.status
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "error": f"HTTP {exc.code}", "path": path}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "status": None, "error": f"unreachable: {exc}", "path": path}

    try:
        payload = json.loads(body)
    except ValueError:
        return {"ok": False, "status": status, "error": "response is not JSON", "path": path}

    return {"ok": status == 200, "status": status, "body": payload, "path": path}


def load_local_report(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return {"ok": True, "status": 200, "body": json.load(handle), "path": path}


def render(
    base_url: str,
    health: dict,
    status: dict,
    report: dict,
    chain: dict,
) -> str:
    lines: list[str] = []
    lines.append("# DSG Verified Execution — Revenue Reconciliation")
    lines.append("")
    lines.append(f"- Generated: `{utc_now()}`")
    lines.append(f"- Target: `{base_url}`")
    lines.append("")
    lines.append("## Service state")
    lines.append("")
    lines.append("| Probe | Result |")
    lines.append("|---|---|")

    health_state = (
        health["body"].get("status", UNAVAILABLE) if health.get("ok") else UNAVAILABLE
    )
    lines.append(f"| `/health` | {health_state} |")

    if status.get("ok"):
        body = status["body"]
        checkout = body.get("checkout_status", UNAVAILABLE)
        enforced = body.get("metering_enforced", UNAVAILABLE)
        charges = body.get("stripe", {}).get("charges_enabled", UNAVAILABLE)
        ledger_entries = body.get("ledger", {}).get("entries", UNAVAILABLE)
        lines.append("| `/billing/status` | reachable |")
        lines.append(f"| Checkout | {checkout} |")
        lines.append(f"| Metering enforced | {enforced} |")
        lines.append(f"| Stripe charges enabled | {charges} |")
        lines.append(f"| Ledger entries | {ledger_entries} |")
    else:
        lines.append(f"| `/billing/status` | {UNAVAILABLE} — {status.get('error')} |")

    lines.append("")
    lines.append("## Ledger integrity")
    lines.append("")
    if chain.get("ok"):
        body = chain["body"]
        lines.append(f"- Chain verified: **{body.get('verified')}**")
        lines.append(f"- Entries: `{body.get('entries')}`")
        lines.append(f"- Head hash: `{body.get('head_hash')}`")
    else:
        lines.append(
            f"- {UNAVAILABLE} — {chain.get('error')}. "
            "No integrity claim is made for this run."
        )

    lines.append("")
    lines.append("## Recognized usage")
    lines.append("")
    if report.get("ok"):
        body = report["body"]
        lines.append(f"- Billing period: `{body.get('period')}`")
        lines.append(
            f"- Accounts with activity: `{body.get('accounts_with_activity')}`"
        )
        lines.append(f"- Accounts with paid invoices: `{body.get('accounts_billed')}`")
        lines.append(f"- Billable units: `{body.get('billable_units')}`")
        recorded = body.get("recorded_usage_amount_micros")
        if isinstance(recorded, int):
            lines.append(f"- Recorded usage amount: **{micros_to_usd(recorded)}**")
        else:
            lines.append(f"- Recorded usage amount: {UNAVAILABLE}")
        recognized = body.get("recognized_amount_micros")
        if isinstance(recognized, int):
            lines.append(f"- Recognized amount: **{micros_to_usd(recognized)}**")
        else:
            lines.append(f"- Recognized amount: {UNAVAILABLE}")
        lines.append("")

        accounts = body.get("accounts") or []
        if accounts:
            lines.append("| Account | Plan | Units | Recorded usage | Paid invoices |")
            lines.append("|---|---|---:|---:|---:|")
            for item in accounts:
                account = item.get("account", {})
                lines.append(
                    f"| `{account.get('account_id')}` | {account.get('plan')} "
                    f"| {item.get('units')} "
                    f"| {micros_to_usd(item.get('usage_amount_micros', 0))} "
                    f"| {micros_to_usd(item.get('recognized_amount_micros', 0))} |"
                )
        else:
            lines.append("No account recorded billable usage in this period.")
    else:
        lines.append(
            f"- {UNAVAILABLE} — {report.get('error')}. "
            "Revenue figures are not reported for this run."
        )

    lines.append("")
    lines.append("## Truth boundary")
    lines.append("")
    lines.append(
        "- Recorded usage is the service's proof ledger, not an invoice. "
        "Recognized amount is limited to scoped USD invoice.paid amounts; "
        "neither figure is an independent financial audit."
    )
    lines.append(
        "- A row marked UNAVAILABLE means the probe failed. It does not mean "
        "the value is zero."
    )
    lines.append(
        "- A working self-serve charge path is claimed only where "
        "`Stripe charges enabled` is true."
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("DSG_CINEMA_BASE_URL", ""))
    parser.add_argument("--admin-secret", default=os.getenv("DSG_REVENUE_ADMIN_SECRET", ""))
    parser.add_argument("--period", default=None)
    parser.add_argument("--local-report", default=None, help="Read a report JSON instead of probing")
    parser.add_argument("--output", default=None)
    parser.add_argument("--json-output", default=None)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = parser.parse_args(argv)

    if not args.base_url and not args.local_report:
        parser.error("--base-url or --local-report is required")

    base_url = args.base_url or "local"
    suffix = f"?period={args.period}" if args.period else ""

    if args.local_report:
        health = {"ok": False, "error": "local report mode", "path": "/health"}
        status = {"ok": False, "error": "local report mode", "path": "/billing/status"}
        report = load_local_report(args.local_report)
        chain = {"ok": False, "error": "local report mode", "path": "/billing/ledger/verify"}
        embedded = report["body"].get("ledger")
        if isinstance(embedded, dict):
            chain = {"ok": True, "status": 200, "body": embedded, "path": "embedded"}
    else:
        health = probe(base_url, "/health", timeout=args.timeout)
        status = probe(base_url, "/billing/status", timeout=args.timeout)
        secret = args.admin_secret or None
        report = (
            probe(base_url, f"/billing/report{suffix}", secret, args.timeout)
            if secret
            else {"ok": False, "error": "no admin secret supplied", "path": "/billing/report"}
        )
        chain = (
            probe(base_url, "/billing/ledger/verify", secret, args.timeout)
            if secret
            else {"ok": False, "error": "no admin secret supplied", "path": "/billing/ledger/verify"}
        )

    markdown = render(base_url, health, status, report, chain)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(markdown)
    else:
        sys.stdout.write(markdown)

    if args.json_output:
        with open(args.json_output, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "generated_at": utc_now(),
                    "base_url": base_url,
                    "health": health,
                    "status": status,
                    "report": report,
                    "chain": chain,
                },
                handle,
                indent=2,
                sort_keys=True,
            )

    if chain.get("ok") and chain["body"].get("verified") is not True:
        print("ledger chain did not verify", file=sys.stderr)
        return 2

    required = [report, chain] if args.local_report else [health, status, report, chain]
    unavailable = [item.get("path", "unknown") for item in required if not item.get("ok")]
    if unavailable:
        print(
            f"required revenue probes unavailable: {', '.join(unavailable)}",
            file=sys.stderr,
        )
        return 3

    if not args.local_report:
        if health["body"].get("status") not in {"ready", "ok"}:
            print("health probe did not report a ready service", file=sys.stderr)
            return 3
        status_body = status["body"]
        if not isinstance(status_body.get("metering_enforced"), bool):
            print("billing status omitted metering_enforced", file=sys.stderr)
            return 3

    report_body = report["body"]
    if not isinstance(report_body.get("recorded_usage_amount_micros"), int):
        print("billing report omitted an exact recorded usage amount", file=sys.stderr)
        return 3
    if not isinstance(report_body.get("recognized_amount_micros"), int):
        print("billing report omitted an exact recognized amount", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
