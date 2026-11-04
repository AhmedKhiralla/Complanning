"""End-to-end checks for Phase 6: moving, locking, re-planning and releasing plans."""
import datetime as dt
from collections import defaultdict

import pytest

from conftest import sign_in_first_time


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


@pytest.fixture(scope="module")
def co(server, platform):
    status, body, _ = platform.post("/api/platform/tenants", {
        "code": "EDIT", "name": "Edit Pharma", "admin": {"email": "admin@edit.test", "full_name": "Eman Admin"}})
    assert status == 200, body
    admin = sign_in_first_time(server, "admin@edit.test", body["temporary_password"], "Edit#Admin2026")
    assert admin.post("/api/sample-data")[0] == 200
    _, sites, _ = admin.get("/api/sites")
    return {"admin": admin, "sid": sites["items"][0]["id"]}


def make_plan(co, **kw):
    start = dt.date.today()
    body = {"objective": "on_time", "horizon_start": start.isoformat(), "horizon_end": (start + dt.timedelta(days=40)).isoformat(),
            "material_constraints": False, **kw}
    status, p, _ = co["admin"].post(f"/api/sites/{co['sid']}/plans", body)
    assert status == 200, p
    return co["admin"].get(f"/api/plans/{p['id']}")[1]


def no_overlaps(plan):
    by_m = defaultdict(list)
    for o in plan["operations"]:
        by_m[o["resource_id"]].append((ts(o["changeover_start"]) or ts(o["start_at"]), ts(o["end_at"])))
    for spans in by_m.values():
        spans.sort()
        for (_, a_end), (b_start, _) in zip(spans, spans[1:]):
            assert b_start >= a_end - dt.timedelta(seconds=1)


def test_move_locks_and_replans(co):
    a = co["admin"]
    plan = make_plan(co)
    fg = next(b for b in plan["batches"] if b["code"] == "FG-PCM-20-EG" and b["status"] == "scheduled")
    op = min((o for o in plan["operations"] if o["batch_id"] == fg["id"]), key=lambda o: o["seq"])
    target = ts(op["start_at"]) + dt.timedelta(days=3)
    status, moved, _ = a.post(f"/api/plans/{plan['id']}/move", {
        "batch_id": fg["id"], "seq": op["seq"], "resource_id": op["resource_id"], "start_at": target.isoformat()})
    assert status == 200, moved
    assert len(moved["locks"]) == 1 and moved["replanned_at"]
    full = a.get(f"/api/plans/{plan['id']}")[1]
    focus = next(b for b in full["batches"] if b["id"] == moved["focus"])
    assert focus["locked"] and focus["code"] == "FG-PCM-20-EG"
    first = min((o for o in full["operations"] if o["batch_id"] == focus["id"]), key=lambda o: o["seq"])
    assert first["locked"] and ts(first["start_at"]) >= target - dt.timedelta(seconds=1)
    assert ts(first["start_at"]) - target < dt.timedelta(days=2)         # the next working time after the drop point
    no_overlaps(full)
    # The rest of the plan is still complete.
    assert full["kpis"]["scheduled"] == full["kpis"]["batches"]
    # The move is in the audit trail as a change of the plan's locks.
    _, audit, _ = a.get("/api/audit?entity=plans&page_size=20")
    assert any(e["action"] == "UPDATE" and "locks" in (e["new_values"] or {}) for e in audit["items"])
    co["plan"] = full


def test_move_rules(co):
    a, plan = co["admin"], co["plan"]
    b = next(x for x in plan["batches"] if x["code"] == "WIP-PCM-BLEND" and x["status"] == "scheduled")
    op = next(o for o in plan["operations"] if o["batch_id"] == b["id"] and o["step_name"] == "Wet granulation")
    other = next(m for m in plan["machines"] if m["code"] == "CRT-01")
    status, err, _ = a.post(f"/api/plans/{plan['id']}/move", {"batch_id": b["id"], "seq": op["seq"], "resource_id": other["id"],
                                                               "start_at": op["start_at"]})
    assert status == 422 and err["error"]["code"] == "not_qualified"
    status, err, _ = a.post(f"/api/plans/{plan['id']}/move", {"batch_id": b["id"], "seq": op["seq"], "resource_id": op["resource_id"],
                                                               "start_at": "2020-01-01T08:00:00Z"})
    assert status == 422 and err["error"]["code"] == "in_past"


def test_lock_unlock_and_replan(co):
    a, plan = co["admin"], co["plan"]
    free = next(b for b in plan["batches"] if not b["locked"] and b["status"] == "scheduled")
    status, locked, _ = a.post(f"/api/plans/{plan['id']}/lock", {"batch_id": free["id"], "locked": True})
    assert status == 200 and len(locked["locks"]) == 2
    full = a.get(f"/api/plans/{plan['id']}")[1]
    assert next(b for b in full["batches"] if b["id"] == free["id"])["locked"]
    status, rp, _ = a.post(f"/api/plans/{plan['id']}/replan")
    assert status == 200 and len(rp["locks"]) == 2
    full = a.get(f"/api/plans/{plan['id']}")[1]
    assert sum(1 for b in full["batches"] if b["locked"]) == 2
    no_overlaps(full)
    target = next(b for b in full["batches"] if b["locked"])
    status, un, _ = a.post(f"/api/plans/{plan['id']}/lock", {"batch_id": target["id"], "locked": False})
    assert status == 200 and len(un["locks"]) == 1


def test_release(co):
    a, plan = co["admin"], co["plan"]
    status, r, _ = a.post(f"/api/plans/{plan['id']}/release")
    assert status == 200 and r["status"] == "released" and r["released_by_name"] == "Eman Admin"
    b = plan["batches"][0]
    assert a.post(f"/api/plans/{plan['id']}/lock", {"batch_id": b["id"], "locked": True})[0] == 409
    second = make_plan(co, objective="utilization")
    assert a.post(f"/api/plans/{second['id']}/release")[1]["status"] == "released"
    assert a.get(f"/api/plans/{plan['id']}")[1]["status"] == "draft"          # only one released plan per site
    status, back, _ = a.patch(f"/api/plans/{second['id']}", {"status": "draft"})
    assert status == 200 and back["status"] == "draft" and back["released_at"] is None
