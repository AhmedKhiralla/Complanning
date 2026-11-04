"""Getting-started checklist and page tours."""
import datetime as dt

import pytest

from conftest import sign_in_first_time


@pytest.fixture(scope="module")
def co(server, platform):
    status, body, _ = platform.post("/api/platform/tenants", {
        "code": "GUIDE", "name": "Guide Pharma", "admin": {"email": "admin@guide.test", "full_name": "Gina Admin"}})
    assert status == 200, body
    admin = sign_in_first_time(server, "admin@guide.test", body["temporary_password"], "Guide#Admin2026")
    return {"admin": admin, "server": server}


def progress(co, sid=None):
    status, p, _ = co["admin"].get("/api/setup-progress" + (f"?site_id={sid}" if sid else ""))
    assert status == 200, p
    return p, {s["key"]: s for s in p["steps"]}


def test_new_company_has_nothing_done(co):
    p, s = progress(co)
    assert p["total"] == 12 and p["done"] == 0
    assert [x["key"] for x in p["steps"]] == ["company", "markets", "items", "boms", "routings", "calendar", "rules",
                                              "sales", "stock", "requirements", "plan", "release"]


def test_steps_follow_the_data(co):
    a = co["admin"]
    assert a.post("/api/sample-data")[0] == 200
    _, sites, _ = a.get("/api/sites")
    sid = sites["items"][0]["id"]
    co["sid"] = sid
    p, s = progress(co, sid)
    for key in ("company", "markets", "items", "boms", "routings", "calendar", "rules", "sales", "stock", "requirements"):
        assert s[key]["done"], key
    assert not s["plan"]["done"] and not s["release"]["done"]
    start = dt.date.today()
    status, plan, _ = a.post(f"/api/sites/{sid}/plans", {"horizon_start": start.isoformat(),
                                                         "horizon_end": (start + dt.timedelta(days=20)).isoformat()})
    assert status == 200
    _, s = progress(co, sid)
    assert s["plan"]["done"] and not s["release"]["done"]
    assert a.post(f"/api/plans/{plan['id']}/release")[0] == 200
    p, s = progress(co, sid)
    assert s["release"]["done"] and p["complete"]


def test_checklist_and_tours_are_remembered(co):
    a = co["admin"]
    status, r, _ = a.patch("/api/auth/preferences", {"checklist_hidden": True, "tour_seen": "items"})
    assert status == 200 and r["guide"] == {"checklist_hidden": True, "tours": ["items"]}
    a.patch("/api/auth/preferences", {"tour_seen": "plans"})
    a.patch("/api/auth/preferences", {"tour_seen": "items"})
    _, me, _ = a.get("/api/auth/me")
    assert me["user"]["guide"]["tours"] == ["items", "plans"] and me["user"]["guide"]["checklist_hidden"] is True
    a.patch("/api/auth/preferences", {"tours_reset": True, "checklist_hidden": False})
    _, me, _ = a.get("/api/auth/me")
    assert me["user"]["guide"] == {"checklist_hidden": False, "tours": []}
    assert a.patch("/api/auth/preferences", {"tour_seen": "bad name!"})[0] == 422
    # Display preferences are not recorded in the audit trail.
    _, audit, _ = a.get("/api/audit?entity=users&page_size=50")
    assert not any("guide" in (e["new_values"] or {}) for e in audit["items"])
