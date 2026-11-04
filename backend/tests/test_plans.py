"""End-to-end checks for Phase 5: the planning engine and stored plans."""
import datetime as dt
import io
from collections import defaultdict
from zoneinfo import ZoneInfo

import pytest

from conftest import sign_in_first_time

CAIRO = ZoneInfo("Africa/Cairo")


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


@pytest.fixture(scope="module")
def co(server, platform):
    status, body, _ = platform.post("/api/platform/tenants", {
        "code": "PLANS", "name": "Plans Pharma", "admin": {"email": "admin@plans.test", "full_name": "Pia Admin"}})
    assert status == 200, body
    admin = sign_in_first_time(server, "admin@plans.test", body["temporary_password"], "Plans#Admin2026")
    assert admin.post("/api/sample-data")[0] == 200
    _, sites, _ = admin.get("/api/sites")
    return {"admin": admin, "sid": sites["items"][0]["id"], "server": server}


def month_bounds():
    t = dt.date.today()
    nxt = (t.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return t, nxt + dt.timedelta(days=(nxt.replace(day=28) + dt.timedelta(days=4)).replace(day=1).day - 1) - dt.timedelta(days=1)


@pytest.fixture(scope="module")
def plan(co):
    start = dt.date.today()
    end = start + dt.timedelta(days=45)
    status, p, _ = co["admin"].post(f"/api/sites/{co['sid']}/plans", {
        "objective": "on_time", "horizon_start": start.isoformat(), "horizon_end": end.isoformat(), "material_constraints": False})
    assert status == 200, p
    status, full, _ = co["admin"].get(f"/api/plans/{p['id']}")
    assert status == 200
    return full


def test_plan_kpis(plan):
    k = plan["kpis"]
    assert k["batches"] > 0 and k["scheduled"] == k["batches"] and k["unscheduled"] == 0
    assert k["demand_lines"] >= 4 and k["on_time"] + k["late"] + k["unfilled"] == k["demand_lines"]
    assert k["engine"].startswith("complanning") and k["runs"] >= 1
    assert plan["name"].startswith("On-time delivery")
    assert {b["status"] for b in plan["batches"]} == {"scheduled"}
    assert all(b["batch_no"].startswith("B") for b in plan["batches"])


def test_machines_never_overlap(plan):
    by_machine = defaultdict(list)
    for o in plan["operations"]:
        start = ts(o["changeover_start"]) or ts(o["start_at"])
        by_machine[o["resource_id"]].append((start, ts(o["end_at"]), o))
    for ops in by_machine.values():
        ops.sort(key=lambda x: x[0])
        for (a_s, a_e, _), (b_s, b_e, o) in zip(ops, ops[1:]):
            assert b_s >= a_e, f"overlap on machine at {b_s}"


def test_steps_in_order_and_materials_flow(plan):
    ops = defaultdict(list)
    for o in plan["operations"]:
        ops[o["batch_id"]].append(o)
    for batch_ops in ops.values():
        batch_ops.sort(key=lambda o: o["seq"])
        for a, b in zip(batch_ops, batch_ops[1:]):
            assert ts(b["start_at"]) >= ts(a["end_at"])
    batches = {b["id"]: b for b in plan["batches"]}
    for link in plan["links"]:
        sup, con = batches[link["supplier_id"]], batches[link["consumer_id"]]
        # The consumer starts only after the supplier is released (QC release and holding time).
        assert ts(con["start_at"]) >= ts(sup["available_at"]) - dt.timedelta(seconds=1)


def test_working_time_only(plan):
    # The sample site works Saturday to Thursday, 07:00-23:00 (Ramadan: 09:00-15:00 and 20:00-02:00); Friday is off.
    for o in plan["operations"]:
        s = ts(o["start_at"]).astimezone(CAIRO)
        assert s.isoweekday() != 5 or s.hour < 2, f"operation starts on a Friday: {s}"
        assert not (2 <= s.hour < 7), f"operation starts outside shifts: {s}"


def test_changeovers_and_verification(plan):
    swabs = [o for o in plan["operations"] if o["verification"] == "swab"]
    for o in swabs:
        assert float(o["wait_minutes"]) == 1440 and o["changeover_kind"] == "group_to_group"
        assert ts(o["start_at"]) >= ts(o["changeover_end"])
    assert all(float(o["changeover_minutes"]) >= 0 for o in plan["operations"])


def test_deliveries(plan):
    for d in plan["demand"]:
        if d["before_rounding"] is None:
            assert float(d["quantity"]) <= float(d["requested"])
        else:
            # Rounded up to full shippers: a whole number of shippers, less than one shipper above the request.
            ups = d["units_per_shipper"]
            assert float(d["quantity"]) % ups == 0 and float(d["quantity"]) - float(d["before_rounding"]) < ups
        if d["on_time"]:
            assert d["available_at"] and ts(d["available_at"]).astimezone(CAIRO).date() <= dt.date.fromisoformat(d["due_date"])


def test_material_shortage_delays_batches(co):
    start = dt.date.today()
    status, p, _ = co["admin"].post(f"/api/sites/{co['sid']}/plans", {
        "objective": "sales_value", "horizon_start": start.isoformat(), "horizon_end": (start + dt.timedelta(days=29)).isoformat()})
    assert status == 200, p
    warnings = p["kpis"]["warnings"]
    shorts = [w for w in warnings if w["kind"] == "material_short"]
    assert {w["code"] for w in shorts} >= {"RM-PCM"}
    _, full, _ = co["admin"].get(f"/api/plans/{p['id']}")
    api = next(w for w in shorts if w["code"] == "RM-PCM")
    waiting = [b for b in full["batches"] if b["code"] == "WIP-PCM-BLEND" and b["start_at"] and ts(b["start_at"]) >= ts(api["arrival"])]
    assert waiting, "a blend batch waits for the paracetamol delivery"


def test_plan_permissions_edit_export_delete(co, plan):
    a, sid = co["admin"], co["sid"]
    status, upd, _ = a.patch(f"/api/plans/{plan['id']}", {"name": "November plan", "status": "archived"})
    assert status == 200 and upd["name"] == "November plan" and upd["status"] == "archived"
    _, lst, _ = a.get(f"/api/sites/{sid}/plans")
    assert any(x["id"] == plan["id"] for x in lst["items"])
    status, u, _ = a.post("/api/users", {"email": "viewer@plans.test", "full_name": "Viewer", "roles": [{"site_id": sid, "role": "viewer"}]})
    viewer = sign_in_first_time(co["server"], "viewer@plans.test", u["temporary_password"], "Plans#Viewer2026")
    assert viewer.get(f"/api/plans/{plan['id']}")[0] == 200
    assert viewer.post(f"/api/sites/{sid}/plans", {})[0] == 403
    from openpyxl import load_workbook
    status, data, _ = a.get(f"/api/plans/{plan['id']}/export", raw=True)
    assert status == 200
    wb = load_workbook(io.BytesIO(data))
    assert {"Plan", "Batches", "Machine schedule", "Deliveries", "Export info"} <= set(wb.sheetnames)
    assert wb["Batches"].max_row == len(plan["batches"]) + 1
    _, audit, _ = a.get("/api/audit?entity=plans&page_size=20")
    assert any(e["action"] == "UPDATE" and e["record_label"] == "November plan" for e in audit["items"])
    assert a.call("DELETE", f"/api/plans/{plan['id']}")[0] == 200
    assert a.get(f"/api/plans/{plan['id']}")[0] == 404
    # A horizon that has passed is refused.
    assert a.post(f"/api/sites/{sid}/plans", {"horizon_start": "2020-01-01", "horizon_end": "2020-01-31"})[0] == 422


def test_uninterrupted_steps_never_pause(plan):
    # In the sample, wet granulation, drying, final blending and syrup preparation must not pause.
    names = {"Wet granulation", "Drying", "Final blending", "Syrup preparation"}
    checked = 0
    for o in plan["operations"]:
        if o["step_name"] in names:
            elapsed = (ts(o["end_at"]) - ts(o["start_at"])).total_seconds() / 60
            assert abs(elapsed - float(o["work_minutes"])) < 0.5, f"{o['step_name']} paused"
            checked += 1
    assert checked > 0


def test_uninterrupted_flag_in_routing(co):
    a, sid = co["admin"], co["sid"]
    _, items, _ = a.get("/api/items")
    blend = next(i["id"] for i in items["items"] if i["code"] == "WIP-PCM-BLEND")
    _, r, _ = a.get(f"/api/sites/{sid}/routings/{blend}")
    flags = {s["name"]: s["uninterrupted"] for s in r["steps"]}
    assert flags["Wet granulation"] is True and flags["Dispensing"] is False
    steps = [{**s, "uninterrupted": not s["uninterrupted"] if s["name"] == "Dispensing" else s["uninterrupted"]} for s in r["steps"]]
    status, saved, _ = a.put(f"/api/sites/{sid}/routings/{blend}", {"steps": steps})
    assert status == 200, saved
    assert {s["name"]: s["uninterrupted"] for s in saved["steps"]}["Dispensing"] is True
