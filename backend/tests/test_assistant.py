"""AI assistant: tool loop against a stand-in AI service, permissions, limits and settings."""
import datetime as dt

import pytest

from conftest import sign_in_first_time


@pytest.fixture(scope="module")
def co(server, platform):
    status, body, _ = platform.post("/api/platform/tenants", {
        "code": "ASSIST", "name": "Assist Pharma", "admin": {"email": "admin@assist.test", "full_name": "Aya Admin"}})
    assert status == 200, body
    admin = sign_in_first_time(server, "admin@assist.test", body["temporary_password"], "Assist#Admin2026")
    assert admin.post("/api/sample-data")[0] == 200
    _, sites, _ = admin.get("/api/sites")
    sid = sites["items"][0]["id"]
    start = dt.date.today()
    status, plan, _ = admin.post(f"/api/sites/{sid}/plans", {"horizon_start": start.isoformat(),
                                                             "horizon_end": (start + dt.timedelta(days=40)).isoformat(),
                                                             "material_constraints": False})
    assert status == 200, plan
    return {"admin": admin, "sid": sid, "plan": plan["id"], "server": server}


def ask(client, text, **ctx):
    return client.post("/api/assistant/chat", {"messages": [{"role": "user", "content": text}], **ctx})


def test_status_and_me(co):
    status, s, _ = co["admin"].get("/api/assistant/status")
    assert status == 200 and s["available"] and s["model"] == "qwen-plus" and s["daily_limit"] == 12
    _, me, _ = co["admin"].get("/api/auth/me")
    assert me["tenant"]["assistant"] is True


def test_answers_from_plan_data(co, fake_ai):
    fake_ai.requests.clear()
    status, r, _ = ask(co["admin"], "Why is the Egypt delivery late?", site_id=co["sid"], plan_id=co["plan"], page=f"/plans/{co['plan']}")
    assert status == 200, r
    # The tool result reached the model and its answer came back: the delivery rows of FG-PCM-20-EG with their batches.
    assert r["answer"].startswith("ANSWER") and "FG-PCM-20-EG" in r["answer"] and "deliveries" in r["answer"]
    assert any(u["kind"] == "plan" for u in r["used"]) and r["remaining"] == 11
    first = fake_ai.requests[0]
    assert first["path"] == "/v1/chat/completions" and first["auth"] == "Bearer test-key"
    assert first["body"]["model"] == "qwen-plus" and {t["function"]["name"] for t in first["body"]["tools"]} >= {"explain_delivery", "search_help"}
    system = first["body"]["messages"][0]["content"]
    assert "Assist Pharma" in system and "Africa/Cairo" in system and "Never invent numbers" in system


def test_manual_setup_and_plans(co):
    _, r, _ = ask(co["admin"], "How do I add a Ramadan shift?", site_id=co["sid"])
    assert "Working calendar" in r["answer"] or "calendar" in r["answer"].lower()
    _, r, _ = ask(co["admin"], "Is my setup complete?", site_id=co["sid"])
    assert "checklist" in r["answer"]
    _, r, _ = ask(co["admin"], "Which plans do we have?", site_id=co["sid"])
    assert co["plan"] in r["answer"]


def test_bad_tool_input_does_not_break(co):
    status, r, _ = ask(co["admin"], "bogus plan please", site_id=co["sid"])
    assert status == 200 and "error" in r["answer"]
    # The request's transaction is still usable afterwards: the usage counter was written.
    _, s, _ = co["admin"].get("/api/assistant/status")
    assert s["used_today"] >= 5


def test_other_company_cannot_see_plan(co, platform):
    status, body, _ = platform.post("/api/platform/tenants", {
        "code": "OTHERAI", "name": "Other Pharma", "admin": {"email": "admin@otherai.test", "full_name": "Omar Other"}})
    other = sign_in_first_time(co["server"], "admin@otherai.test", body["temporary_password"], "Other#Admin2026")
    status, r, _ = ask(other, "Why is it late?", plan_id=co["plan"])
    assert status == 200 and "not found" in r["answer"].lower() and "FG-PCM" not in r["answer"]


def test_switch_off_limit_and_admin_tools(co, platform):
    a = co["admin"]
    status, t, _ = a.post("/api/assistant/test")
    assert status == 200 and t["reply"] == "OK" and t["model"] == "qwen-plus"
    _, u, _ = a.get("/api/assistant/usage")
    assert u["days"] and u["days"][0]["questions"] >= 5
    assert a.put("/api/settings/features", {"features": {"ai_assistant": False}})[0] == 200
    status, err, _ = ask(a, "hello")
    assert status == 403 and err["error"]["code"] == "ai_off"
    _, me, _ = a.get("/api/auth/me")
    assert me["tenant"]["assistant"] is False
    a.put("/api/settings/features", {"features": {"ai_assistant": True}})
    for _ in range(20):
        status, r, _ = ask(a, "hello")
        if status != 200:
            break
    assert status == 429 and r["error"]["code"] == "ai_limit"
    # Questions are not stored, and nothing about them goes to the audit trail.
    _, audit, _ = a.get("/api/audit?page_size=50")
    assert not any("assistant" in (e.get("entity") or "") or "ai_usage" in (e.get("entity") or "") for e in audit["items"])
