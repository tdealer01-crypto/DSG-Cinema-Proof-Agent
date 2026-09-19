"""Verified task loop over the canonical Cinema CLI. No browser or approval bypass.

The connected DSG agent supplies a bounded task proposal from inspect_context().
Cinema remains the authority for every action. This module never approves plans.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import os
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ALLOWED = {"browser.navigate", "browser.click", "browser.type", "browser.select",
           "browser.upload", "browser.scroll", "browser.extract"}
FIELDS = {"text", "checked", "disabled", "required", "tag", "type"}
SENSITIVE = {"password", "otp", "passcode", "secret", "token", "api_key", "session_token"}
LABELS = {"PASS": "ผ่าน", "FAILED": "ไม่ผ่าน", "NEED_USER": "ต้องให้คุณช่วย",
          "RUNNING": "กำลังทำงาน", "VERIFYING": "กำลังตรวจผล"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def safe_url(value):
    try:
        p = urlsplit(str(value))
        if p.scheme not in {"https", "http"} or not p.hostname:
            return ""
        return urlunsplit((p.scheme, p.hostname + (":" + str(p.port) if p.port else ""),
                           p.path, "", ""))
    except ValueError:
        return ""


def origin(value):
    p = urlsplit(safe_url(value))
    return p.scheme + "://" + p.netloc if p.netloc else ""


def page_context(result, goal):
    response = result.get("response", result)
    if not isinstance(response, dict) or response.get("ok") is not True:
        raise ValueError("READ_RESULT_NOT_VERIFIED")
    if not isinstance(response.get("controls"), list):
        raise ValueError("PAGE_CONTEXT_UNAVAILABLE")
    controls = []
    for raw in response["controls"][:400]:
        if not isinstance(raw, dict):
            continue
        control = {k: raw.get(k) for k in (
            "selector", "tag", "type", "label", "aria_label", "required",
            "disabled", "checked", "sensitive", "text")}
        if control["sensitive"]:
            control["text"] = "[redacted]"
        controls.append(control)
    sensitive = any(c["sensitive"] for c in controls)
    fields = [c for c in controls if c["tag"] in {"input", "textarea", "select"}]
    data = {
        "url": safe_url(response.get("url", "")), "controls": controls,
        "user_goal": goal, "observed_at": time.time(),
        "page_purpose_hint": "identity_input" if sensitive else ("form" if fields else "navigation"),
        "purpose_is_inference": True, "authority": "page_data_only",
        "limitations": ["Main document controls only; no raw DOM, field values, frames or network proof.",
                        "A page text assertion proves the observed UI state only."],
        "truncated": len(response["controls"]) >= 400,
        "provider_evidence": {k: result.get(k) for k in
                              ("event_id", "evidence_hash", "response_sha256", "plan_id")},
    }
    data["observation_id"] = digest(data)
    return data


def check(context, condition):
    if condition["kind"] == "url":
        return context["url"] == condition["equals"]
    candidates = [c for c in context["controls"] if c.get("selector") == condition["selector"]]
    if len(candidates) != 1 or candidates[0].get("sensitive"):
        return False
    return candidates[0].get(condition["field"]) == condition["equals"]


def validate(task):
    if task.get("schema") != "dsg.browser-task.v1":
        raise ValueError("INVALID_TASK_SCHEMA")
    for key in ("goal", "plan_id", "step_id"):
        if not isinstance(task.get(key), str) or not task[key].strip():
            raise ValueError("MISSING_" + key.upper())
    origins = task.get("allowed_origins")
    if not isinstance(origins, list) or not origins or any(
            not isinstance(x, str) or not x.startswith("https://") or origin(x) != x for x in origins):
        raise ValueError("EXACT_HTTPS_ORIGINS_REQUIRED")
    steps = task.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 32:
        raise ValueError("STEP_BUDGET_EXCEEDED")
    if any(not isinstance(s, dict) for s in steps):
        raise ValueError("INVALID_STEP")
    for key in ("verify_seconds", "budget_seconds"):
        value = task.get(key, 3 if key == "verify_seconds" else 120)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("INVALID_BUDGET")
    ids = [s.get("id") for s in steps]
    if any(not isinstance(x, str) or not x for x in ids) or len(set(ids)) != len(ids):
        raise ValueError("UNIQUE_STEP_IDS_REQUIRED")
    if not isinstance(task.get("success"), list) or not task["success"]:
        raise ValueError("FINAL_ASSERTION_REQUIRED")
    assertions = list(task["success"])
    for step in steps:
        action = step.get("action", {})
        if not isinstance(action, dict) or action.get("kind") not in ALLOWED or not isinstance(action.get("parameters", {}), dict):
            raise ValueError("UNSUPPORTED_ACTION")
        params = action.get("parameters", {})
        if any(k.lower() in SENSITIVE for k in params):
            raise ValueError("PLAINTEXT_SECRET_FORBIDDEN")
        if action["kind"] == "browser.navigate" and origin(params.get("url", "")) not in origins:
            raise ValueError("OUT_OF_SCOPE_NAVIGATION")
        if action["kind"] == "browser.upload" and not str(params.get("file_ref", "")).startswith("artifact://"):
            raise ValueError("APPROVED_ARTIFACT_REQUIRED")
        if not isinstance(step.get("expect", []), list):
            raise ValueError("INVALID_ASSERTION_LIST")
        assertions.extend(step.get("expect", []))
    for a in assertions:
        if not isinstance(a, dict) or a.get("kind") not in {"url", "control"} or "equals" not in a:
            raise ValueError("INVALID_ASSERTION")
        if a["kind"] == "url":
            if not isinstance(a["equals"], str) or safe_url(a["equals"]) != a["equals"]:
                raise ValueError("SANITIZED_URL_ASSERTION_REQUIRED")
        elif not a.get("selector") or a.get("field") not in FIELDS:
            raise ValueError("INVALID_CONTROL_ASSERTION")


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(value, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


@contextmanager
def lease(path):
    import fcntl
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("SESSION_BUSY")
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


class TaskRunner:
    def __init__(self, cli, output):
        self.cli = cli
        self.root = Path(output)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "checkpoint.json"

    def save(self):
        atomic_json(self.path, self.state)
        atomic_json(self.root / "result.json", self.state)
        self.report()

    def event(self, kind, **data):
        records = self.state["events"]
        record = {"index": len(records), "kind": kind, "time": time.time(),
                  "previous_hash": records[-1]["hash"] if records else None,
                  **data}
        record["hash"] = digest(record)
        records.append(record)
        self.save()

    def report(self):
        s = self.state
        esc = lambda x: html.escape(str(x))
        rows = "".join("<tr><td>" + esc(e["index"]) + "</td><td>" + esc(e["kind"]) +
                       "</td><td>" + esc(e.get("step_id", "")) + "</td><td>" +
                       esc(e.get("reason", e.get("matched", ""))) + "</td></tr>" for e in s["events"])
        content = '<!doctype html><html lang="th"><meta charset="utf-8"><meta name="viewport" content="width=device-width">' +             '<title>DSG Browser Task Evidence</title><style>body{font:18px system-ui;max-width:960px;margin:24px auto;padding:16px;background:#101827;color:#e4eaf5}a{color:#8bccff}table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #43516a;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>' +             "<h1>" + esc(LABELS.get(s["status"], s["status"])) + "</h1><p>" + esc(s["goal"]) +             "</p><p>" + esc(s.get("reason", "")) + "</p><p>" + esc(s.get("next_action", "")) +             '</p><p><a href="result.json">เปิดหลักฐาน JSON</a></p><table><tr><th>ลำดับ</th><th>เหตุการณ์</th><th>ขั้นตอน</th><th>ผล</th></tr>' +             rows + "</table><details><summary>ดูหลักฐานย้อนหลัง</summary><pre>" +             esc(json.dumps(s, ensure_ascii=False, indent=2)) + "</pre></details></html>"
        (self.root / "report.html").write_text(content, encoding="utf-8")

    def finish(self, status, reason, next_action=""):
        self.state.update(status=status, reason=reason, next_action=next_action)
        self.save()
        return self.state

    def read(self, task):
        result = self.cli._action("browser.extract", {}, controller="agent_verifier")
        context = page_context(result, task["goal"])
        self.event("OBSERVATION", context=context)
        return context

    def verify(self, task, conditions):
        # Retry observations only. Browser mutations are NEVER automatically retried.
        end = time.monotonic() + min(max(float(task.get("verify_seconds", 3)), 0), 15)
        while True:
            context = self.read(task)
            matched = all(check(context, c) for c in conditions)
            if matched or time.monotonic() >= end:
                return matched, context
            time.sleep(0.3)

    def run(self, task, resume=False):
        validate(task)
        session = self.cli._load_session()
        if any(session.get(k) != task[k] for k in ("plan_id", "step_id")):
            raise ValueError("SESSION_PLAN_MISMATCH")
        session_key = digest({k: session.get(k) for k in ("session_token", "plan_id", "step_id")})
        # Local coordinator lease; Cinema still governs/serializes remote actions.
        lock = self.cli._session_path().parent / ("task-" + session_key + ".lock")
        with lease(lock):
            return self._run(task, resume)

    def _run(self, task, resume):
        if self.path.exists():
            if not resume:
                raise ValueError("CHECKPOINT_EXISTS_USE_RESUME")
            self.state = json.loads(self.path.read_text())
            if self.state["task_hash"] != digest(task):
                raise ValueError("RESUME_SCOPE_CHANGED")
            previous = None
            for e in self.state["events"]:
                if e.get("previous_hash") != previous or e.get("hash") != digest({k:v for k,v in e.items() if k != "hash"}):
                    raise ValueError("EVIDENCE_CHAIN_INVALID")
                previous = e["hash"]
            if self.state["status"] == "PASS":
                return {**self.state, "cached_completed_result": True}
        else:
            self.state = {"schema": "dsg.browser-task.result.v1", "goal": task["goal"],
                          "task_hash": digest(task), "plan_id": task["plan_id"],
                          "status": "RUNNING", "cursor": 0, "pending": None, "events": [],
                          "proof_scope": "Canonical Cinema action receipts and observed UI assertions.",
                          "not_claimed": ["backend persistence", "independent audit", "immutable storage",
                                          "distributed lease", "automatic LLM planning"]}
            self.save()
        budget = min(max(float(task.get("budget_seconds", 120)), 1), 600)
        started = time.monotonic()
        try:
            for index in range(self.state["cursor"], len(task["steps"])):
                step = task["steps"][index]
                conditions = step.get("expect", [])
                if self.state["pending"] is not None:
                    if self.state["pending"] != step["id"]:
                        return self.finish("FAILED", "CHECKPOINT_INCONSISTENT")
                    if conditions:
                        matched, _ = self.verify(task, conditions)
                        if matched:
                            self.state.update(cursor=index + 1, pending=None)
                            self.event("RECONCILED_WITHOUT_REPLAY", step_id=step["id"])
                            continue
                    return self.finish("NEED_USER", "ACTION_OUTCOME_UNKNOWN",
                                       "ตรวจผลบนหน้าเว็บก่อน ห้ามส่งซ้ำ; หลักฐานยังไม่ยืนยันผลของขั้นตอนนี้")
                if time.monotonic() - started >= budget:
                    return self.finish("FAILED", "TIME_BUDGET_EXCEEDED", "ตรวจหลักฐานและ resume งานเดิม")
                context = self.read(task)
                action = step["action"]
                kind, params = action["kind"], action.get("parameters", {})
                if kind != "browser.navigate" and origin(context["url"]) not in task["allowed_origins"]:
                    return self.finish("NEED_USER", "CURRENT_ORIGIN_OUT_OF_SCOPE", "เปิดหน้าที่อยู่ในขอบเขตแผนแล้ว resume")
                if context["truncated"] and kind != "browser.navigate":
                    return self.finish("NEED_USER", "PAGE_CONTEXT_TRUNCATED", "ต้องอ่านบริบทเป้าหมายให้ครบก่อนดำเนินการ")
                selector = params.get("selector")
                if kind in {"browser.click", "browser.type", "browser.select", "browser.upload"}:
                    targets = [c for c in context["controls"] if c.get("selector") == selector]
                    if len(targets) != 1:
                        return self.finish("NEED_USER", "TARGET_NOT_UNIQUE", "อ่านหน้าใหม่และปรับข้อเสนอขั้นตอนให้ตรงกับหน้าจริง")
                    if targets[0].get("sensitive"):
                        return self.finish("NEED_USER", "DIRECT_USER_INPUT_REQUIRED", "กรอกข้อมูลยืนยันตัวตนใน Azure viewer ด้วยตัวคุณ")
                    if targets[0].get("disabled"):
                        return self.finish("NEED_USER", "TARGET_DISABLED", "แก้เงื่อนไขบนหน้าเว็บแล้ว resume")
                self.state["pending"] = step["id"]
                self.event("ACTION_INTENT", step_id=step["id"], action_kind=kind,
                           parameters_hash=digest(params), observation_id=context["observation_id"])
                try:
                    result = self.cli._action(kind, params)
                except Exception as exc:
                    self.event("TRANSPORT_UNCERTAIN", step_id=step["id"], error_type=type(exc).__name__)
                    if conditions:
                        matched, _ = self.verify(task, conditions)
                        if matched:
                            self.state.update(cursor=index + 1, pending=None)
                            self.event("RECONCILED_WITHOUT_REPLAY", step_id=step["id"])
                            continue
                    return self.finish("NEED_USER", "ACTION_OUTCOME_UNKNOWN", "ตรวจผลจริงก่อนดำเนินการต่อ ระบบจะไม่กดส่งซ้ำ")
                self.event("ACTION_RECEIPT", step_id=step["id"],
                           receipt={k:result.get(k) for k in ("ok", "remote_status", "event_id", "evidence_hash", "response_sha256")})
                if result.get("ok") is not True or result.get("response", {}).get("ok") is False:
                    return self.finish("FAILED", "REMOTE_ACTION_REJECTED", "ตรวจ action receipt และแก้สาเหตุ; ผลกระทบยังไม่ยืนยัน")
                self.state["status"] = "VERIFYING"
                matched, _ = self.verify(task, conditions)
                self.event("STEP_OBSERVATION", step_id=step["id"], matched=matched,
                           assertion_count=len(conditions))
                if not matched:
                    return self.finish("FAILED", "STEP_POSTCONDITION_FAILED", "ตรวจหลักฐานหลังทำงาน; resume จะตรวจผลก่อนและไม่ทำ action ซ้ำ")
                self.state.update(cursor=index + 1, pending=None, status="RUNNING")
                self.save()
            matched, _ = self.verify(task, task["success"])
            self.event("TASK_VERIFICATION", matched=matched, assertion_count=len(task["success"]))
            return self.finish("PASS" if matched else "FAILED",
                               "ALL_TASK_ASSERTIONS_MATCHED" if matched else "TASK_POSTCONDITION_FAILED")
        except Exception as exc:
            self.event("OBSERVATION_ERROR", error_type=type(exc).__name__)
            return self.finish("NEED_USER", "READ_OR_SESSION_UNAVAILABLE",
                               "ตรวจ Remote ON และ session ของแผนนี้ แล้ว resume จาก checkpoint เดิม")
