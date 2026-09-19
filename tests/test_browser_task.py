"""Unit fault-injection only. Real Azure E2E is recorded separately."""
import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("browser_task", ROOT / "scripts/browser_task.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class CinemaDouble:
    def __init__(self, tmp_path):
        self.path = tmp_path / "session.json"
        self.actions = []
        self.text = "idle"
        self.secret = False
        self.disabled = False
        self.fail_after_effect = False
        self.reject = False
        self.url = "https://example.com/smoke"

    def _load_session(self):
        return {"plan_id":"p1","step_id":"s1","session_token":"unit-session"}

    def _session_path(self):
        return self.path

    def _action(self, kind, params, controller="agent_executor"):
        if kind == "browser.extract":
            assert controller == "agent_verifier"
            return {"ok":True, "event_id":"unit-observation", "response":{
                "ok":True,"url":self.url, "controls":[
                    {"selector":"#apply","tag":"button","text":"Apply","sensitive":self.secret,"disabled":self.disabled},
                    {"selector":"#status","tag":"button","text":self.text,"sensitive":False}]}}
        self.actions.append(kind)
        if self.reject:
            return {"ok":False, "remote_status":403, "response":{"ok":False}}
        self.text = "applied"
        if self.fail_after_effect:
            raise TimeoutError("injected transport timeout AFTER effect")
        return {"ok":True,"event_id":"unit-action","response":{"ok":True}}


def task():
    expected={"kind":"control","selector":"#status","field":"text","equals":"applied"}
    return {"schema":"dsg.browser-task.v1","goal":"Apply unit fixture","plan_id":"p1",
            "step_id":"s1","allowed_origins":["https://example.com"],"verify_seconds":0,
            "steps":[{"id":"apply","action":{"kind":"browser.click","parameters":{"selector":"#apply"}},
                      "expect":[expected]}],"success":[expected]}


def test_success_requires_final_assertion_and_emits_report(tmp_path):
    api=CinemaDouble(tmp_path);runner=mod.TaskRunner(api,tmp_path/"out")
    result=runner.run(task())
    assert result["status"]=="PASS" and api.actions==["browser.click"]
    assert (tmp_path/"out/report.html").is_file()
    assert all("unit-session" not in json.dumps(e) for e in result["events"])


def test_one_success_does_not_mask_failed_final_goal(tmp_path):
    api=CinemaDouble(tmp_path);t=task();t["success"][0]=dict(t["success"][0],equals="never happened")
    result=mod.TaskRunner(api,tmp_path/"out").run(t)
    assert result["status"]=="FAILED" and result["reason"]=="TASK_POSTCONDITION_FAILED"


def test_rejected_action_is_never_pass(tmp_path):
    api=CinemaDouble(tmp_path);api.reject=True
    result=mod.TaskRunner(api,tmp_path/"out").run(task())
    assert result["status"]=="FAILED"


def test_timeout_after_effect_reconciles_without_second_click(tmp_path):
    api=CinemaDouble(tmp_path);api.fail_after_effect=True
    result=mod.TaskRunner(api,tmp_path/"out").run(task())
    assert result["status"]=="PASS" and len(api.actions)==1
    assert any(e["kind"]=="RECONCILED_WITHOUT_REPLAY" for e in result["events"])


def test_unknown_outcome_survives_resume_without_replay(tmp_path):
    api=CinemaDouble(tmp_path);api.fail_after_effect=True
    t=task();t["steps"][0]["expect"]=[];runner=mod.TaskRunner(api,tmp_path/"out")
    result=runner.run(t)
    assert result["status"]=="NEED_USER"
    result=mod.TaskRunner(api,tmp_path/"out").run(t,resume=True)
    assert result["status"]=="NEED_USER" and len(api.actions)==1


@pytest.mark.parametrize("attr,reason",[("secret","DIRECT_USER_INPUT_REQUIRED"),("disabled","TARGET_DISABLED")])
def test_user_interrupt_precedes_mutation(tmp_path,attr,reason):
    api=CinemaDouble(tmp_path);setattr(api,attr,True)
    result=mod.TaskRunner(api,tmp_path/"out").run(task())
    assert result["status"]=="NEED_USER" and result["reason"]==reason and not api.actions


def test_origin_change_is_not_authorized(tmp_path):
    api=CinemaDouble(tmp_path);api.url="https://outside.example/"
    result=mod.TaskRunner(api,tmp_path/"out").run(task())
    assert result["reason"]=="CURRENT_ORIGIN_OUT_OF_SCOPE" and not api.actions


def test_task_and_session_plan_must_match(tmp_path):
    api=CinemaDouble(tmp_path);t=task();t["plan_id"]="different"
    with pytest.raises(ValueError,match="SESSION_PLAN_MISMATCH"):
        mod.TaskRunner(api,tmp_path/"out").run(t)
    assert not api.actions


def test_resume_does_not_accept_changed_scope(tmp_path):
    api=CinemaDouble(tmp_path);t=task();mod.TaskRunner(api,tmp_path/"out").run(t)
    t["goal"]="new scope"
    with pytest.raises(ValueError,match="RESUME_SCOPE_CHANGED"):
        mod.TaskRunner(api,tmp_path/"out").run(t,resume=True)


def test_resume_detects_corrupted_event(tmp_path):
    api=CinemaDouble(tmp_path);mod.TaskRunner(api,tmp_path/"out").run(task())
    path=tmp_path/"out/checkpoint.json";state=json.loads(path.read_text())
    state["events"][0]["kind"]="tampered";path.write_text(json.dumps(state))
    with pytest.raises(ValueError,match="EVIDENCE_CHAIN_INVALID"):
        mod.TaskRunner(api,tmp_path/"out").run(task(),resume=True)


@pytest.mark.parametrize("alter,reason",[
    (lambda t:t.update(success=[]),"FINAL_ASSERTION_REQUIRED"),
    (lambda t:t["steps"][0]["action"].update(kind="shell.execute"),"UNSUPPORTED_ACTION"),
    (lambda t:t["steps"][0]["action"].update(parameters={"password":"never print"}),"PLAINTEXT_SECRET_FORBIDDEN"),
    (lambda t:t["steps"][0].update(action={"kind":"browser.navigate","parameters":{"url":"http://127.0.0.1/"}}),"OUT_OF_SCOPE_NAVIGATION"),
])
def test_invalid_tasks_fail_before_transport(tmp_path,alter,reason):
    api=CinemaDouble(tmp_path);t=task();alter(t)
    with pytest.raises(ValueError,match=reason):
        mod.TaskRunner(api,tmp_path/"out").run(t)
    assert not api.actions


def test_context_strips_url_tokens_and_sensitive_text():
    context=mod.page_context({"ok":True,"url":"https://example.com/path?token=SECRET#SECRET",
        "controls":[{"selector":"#password","sensitive":True,"text":"SECRET","tag":"input"}]}, "user goal")
    assert "SECRET" not in json.dumps(context)
    assert context["user_goal"]=="user goal" and context["authority"]=="page_data_only"


def test_lock_rejects_concurrent_local_runner(tmp_path):
    with mod.lease(tmp_path/"lock"):
        with pytest.raises(ValueError,match="SESSION_BUSY"):
            with mod.lease(tmp_path/"lock"): pass
