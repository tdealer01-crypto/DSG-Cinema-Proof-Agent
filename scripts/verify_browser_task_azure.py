#!/usr/bin/env python3
"""Real Azure acceptance against a dedicated synthetic Cinema test account.

Never consumes the operator's account credentials. Does not deploy or launch
a local browser. Approval is fixture authority, not an owner/business approval.
"""
import argparse
import copy
import hashlib
import json
import os
import tempfile
import urllib.request
import uuid
from pathlib import Path
from types import SimpleNamespace
import dsg_browser as cli
from browser_task import TaskRunner

BASE = cli.DEFAULT_BASE_URL


def run(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Use a new empty evidence output directory")
    original = {k:os.environ.get(k) for k in
                ("DSG_API_KEY","DSG_PAIRING_TOKEN","DSG_CINEMA_BASE_URL",
                 "DSG_BROWSER_CONFIG","DSG_BROWSER_SESSION_FILE")}
    key = None
    enabled = False

    def request(path, body):
        headers = {"Content-Type":"application/json"}
        if key:
            headers["X-DSG-API-Key"] = key
        req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.load(response)

    with tempfile.TemporaryDirectory(prefix="dsg-browser-test-credentials-") as secret_dir:
        secret_dir = Path(secret_dir)
        try:
            for name in original:
                os.environ.pop(name, None)
            activation = request("/billing/activate", {
                "channel":"azure_browser_e2e",
                "activation_id":"browser-task-" + uuid.uuid4().hex,
                "display_name":"DSG Browser Task SANDBOX E2E"})
            key = activation["api_key"]
            config = secret_dir/"config.json"
            config.write_text(json.dumps({"base_url":BASE,"api_key":key}))
            config.chmod(0o600)
            os.environ["DSG_BROWSER_CONFIG"] = str(config)
            os.environ["DSG_BROWSER_SESSION_FILE"] = str(secret_dir/"session.json")
            url = BASE + "/remote-browser/smoke"
            plan = request("/api/v1/plans", {
                "title":"SANDBOX: synthetic input/apply/upload on DSG smoke fixture only",
                "agent_identity":"dsg-browser-task-e2e", "channel":"api",
                "steps":[{"step_id":"smoke-workflow","action":"browser_workflow",
                          "target":url, "parameters":{"browser_allowed_origins":BASE},
                          "requires_evidence":True}],
                "metadata":{"environment":"sandbox-e2e","business_data":False}})
            approved = request("/api/v1/plans/"+plan["plan_id"]+"/approve", {
                "approver":"sandbox-e2e-harness", "plan_hash":plan["plan_hash"],
                "approval_note":"Synthetic test account and built-in fixture; no owner/business approval."})
            assert approved["status"] == "APPROVED"
            remote = request("/remote-browser/enable", {})
            enabled = True
            assert remote["shared_browser"]["provider"] == "azure_container_apps"
            assert remote["shared_browser"]["connected"] is True
            session = request("/chatgpt-actions/remote-browser/connect", {
                "plan_id":plan["plan_id"],"step_id":"smoke-workflow",
                "agent_identity":"dsg-browser-task-e2e","ttl_seconds":900})
            cli._save_session({k:session.get(k) for k in
                               ("session_token","plan_id","step_id","agent_identity")})
            provider = session.get("shared_browser",{}).get("provider")
            assert provider == "azure_container_apps"
            assertion = lambda sel,val:{"kind":"control","selector":sel,"field":"text","equals":val}
            message = "DSG-AZURE-VERIFIED-" + uuid.uuid4().hex[:8]
            applied = assertion("#status","applied:"+message)
            uploaded = assertion("#upload-status","uploaded:remote_browser_smoke_fixture.txt")
            task = {
                "schema":"dsg.browser-task.v1", "goal":"Azure synthetic form/input/upload verification",
                "plan_id":plan["plan_id"], "step_id":"smoke-workflow",
                "allowed_origins":[BASE], "verify_seconds":2, "budget_seconds":180,
                "steps":[
                    {"id":"navigate","action":{"kind":"browser.navigate","parameters":{"url":url}},
                     "expect":[{"kind":"url","equals":url}]},
                    {"id":"type","action":{"kind":"browser.type","parameters":{"selector":"#message","value":message}}},
                    {"id":"apply","action":{"kind":"browser.click","parameters":{"selector":"#apply"}},"expect":[applied]},
                    {"id":"upload","action":{"kind":"browser.upload","parameters":{
                        "selector":"#upload","file_ref":"artifact://api_v1/remote_browser_smoke_fixture.txt"}},
                     "expect":[uploaded]}], "success":[applied,uploaded]}
            (output/"task.json").write_text(json.dumps(task,indent=2))
            result = TaskRunner(cli,output/"positive").run(task)
            assert result["status"] == "PASS", result["reason"]
            frame = cli._request("GET","/remote-browser/browserbase/live-frame",require_api_key=True)
            assert frame["provider"] == "azure_container_apps"
            with urllib.request.urlopen(BASE + frame["embed_url"] + "/snapshot",timeout=40) as f:
                png = f.read()
            assert png.startswith(b"\x89PNG\r\n\x1a\n")
            (output/"positive/azure-screenshot.png").write_bytes(png)
            summary = {
                "provider":provider, "scope":"Synthetic account on real Azure shared Chromium; UI assertions only",
                "positive":{"status":result["status"],"steps":4,"assertions":2,"events":len(result["events"])},
                "screenshot_sha256":hashlib.sha256(png).hexdigest(),
                "test_plan_id":plan["plan_id"], "test_plan_hash":plan["plan_hash"],
                "source_sha256":{name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                 for name in ("browser_task.py","dsg_browser.py","verify_browser_task_azure.py")}}
            print("Azure positive: PASS",flush=True)
            negative = copy.deepcopy(task)
            negative["steps"] = negative["steps"][:1]
            negative["success"] = [assertion("#status","THIS_RESULT_DID_NOT_HAPPEN")]
            negative["verify_seconds"] = 0
            result = TaskRunner(cli,output/"negative").run(negative)
            assert result["status"] == "FAILED"
            summary["negative"] = {"status":result["status"],"reason":result["reason"]}
            need = copy.deepcopy(task)
            need["steps"] = [{"id":"disabled","action":{"kind":"browser.click","parameters":{"selector":"#status"}}}]
            result = TaskRunner(cli,output/"need-user").run(need)
            assert result["status"] == "NEED_USER"
            assert not any(e["kind"] == "ACTION_INTENT" for e in result["events"])
            summary["need_user"] = {"status":result["status"],"reason":result["reason"]}
            timeout = copy.deepcopy(task)
            timeout["steps"] = timeout["steps"][:3]
            timeout["success"] = [applied]
            counter = {"clicks":0}
            def fault(kind,params,controller="agent_executor"):
                reply = cli._action(kind,params,controller)
                if kind == "browser.click":
                    counter["clicks"] += 1
                    raise TimeoutError("Injected client timeout AFTER real Azure click")
                return reply
            adapter = SimpleNamespace(_action=fault,_load_session=cli._load_session,
                                      _session_path=cli._session_path)
            result = TaskRunner(adapter,output/"timeout-recovery").run(timeout)
            assert result["status"] == "PASS" and counter["clicks"] == 1
            TaskRunner(adapter,output/"timeout-recovery").run(timeout,resume=True)
            assert counter["clicks"] == 1
            summary["timeout_recovery"] = {
                "status":"PASS","actual_clicks":1,"replayed_mutations":0,
                "fault":"Client exception injected after real Azure click; not a natural provider outage"}
            denied = False
            try:
                cli._action("browser.navigate",{"url":"https://example.com"})
            except cli.BrowserCliError as exc:
                denied = "HTTP 403" in str(exc)
            assert denied, "Native Cinema must reject the outside-plan origin"
            summary["native_scope_gate"] = {"passed":denied,"http_status":403}
            summary["all_cases_passed"] = True
            (output/"azure-e2e-summary.json").write_text(json.dumps(summary,indent=2))
            print(json.dumps(summary,indent=2),flush=True)
            return summary
        finally:
            if key and enabled:
                try:
                    request("/remote-browser/disable",{})
                    print("Synthetic test authority revoked; user account unchanged",flush=True)
                except Exception:
                    print("Cleanup failed: synthetic account remote authority may remain enabled",flush=True)
            for name,value in original.items():
                if value is None:
                    os.environ.pop(name,None)
                else:
                    os.environ[name] = value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True)
    args = parser.parse_args()
    run(args.output)
