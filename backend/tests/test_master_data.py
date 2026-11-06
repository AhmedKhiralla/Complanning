"""End-to-end checks for Phase 2 master data."""
import io
import urllib.error
import urllib.request
from decimal import Decimal

import psycopg
import pytest

from conftest import Client, sign_in_first_time


@pytest.fixture(scope="module")
def pharma(server, platform):
    status, body, _ = platform.post("/api/platform/tenants", {
        "code": "SAMPLE", "name": "Sample Pharma", "admin": {"email": "admin@sample.test", "full_name": "Sara Admin"}})
    assert status == 200, body
    admin = sign_in_first_time(server, "admin@sample.test", body["temporary_password"], "Sample#Admin2026")
    status, res, _ = admin.post("/api/sample-data")
    assert status == 200, res
    _, sites, _ = admin.get("/api/sites")
    site_id = sites["items"][0]["id"]
    _, items, _ = admin.get("/api/items")
    code = {i["code"]: i for i in items["items"]}
    return {"admin": admin, "site_id": site_id, "items": code, "tenant": body["tenant"]}


def _bom_id(admin, item):
    _, d, _ = admin.get("/api/boms")
    row = next(i for i in d["items"] if i["code"] == item)
    return next(v["id"] for v in row["versions"] if v["status"] == "active")


def test_sample_loaded(pharma):
    admin = pharma["admin"]
    assert len(pharma["items"]) == 36
    _, units, _ = admin.get("/api/uoms")
    assert {"KG", "L", "BLS", "CTN"} <= {u["code"] for u in units["items"]}
    _, res, _ = admin.get(f"/api/sites/{pharma['site_id']}/resources")
    assert len(res["items"]) == 20
    status, again, _ = admin.post("/api/sample-data")
    assert status == 409  # only into an empty company


def test_explosion_three_levels_with_yield(pharma):
    admin = pharma["admin"]
    bid = _bom_id(admin, "FG-PCM-20-EG")
    status, tree, _ = admin.get(f"/api/boms/{bid}/explode")
    assert status == 200, tree
    sf = next(c for c in tree["children"] if c["code"] == "SF-PCM-BLS")
    assert Decimal(str(sf["quantity"])).quantize(Decimal("0.1")) == Decimal("48241.2")  # 48000 / 99.5%
    wip = next(c for c in sf["children"] if c["code"] == "WIP-PCM-BLEND")
    api = next(c for c in wip["children"] if c["code"] == "RM-PCM")
    assert api["assay_compensated"] is True
    assert 249 < float(api["quantity"]) < 251
    assert wip["bom_version"] == 1


def test_liquid_kg_dispensed_in_litres_and_overage(pharma):
    admin = pharma["admin"]
    bid = _bom_id(admin, "WIP-VITC-BULK")
    _, tree, _ = admin.get(f"/api/boms/{bid}/explode")
    by = {c["code"]: c for c in tree["children"]}
    assert by["RM-SORB"]["uom"] == "KG"
    assert abs(float(by["RM-SORB"]["quantity"]) - 150 * 1.29 / 0.98) < 0.01   # 150 L x density / yield
    assert abs(float(by["RM-ASC"]["quantity"]) - 20 * 1.08 / 0.98) < 0.01     # 8 % overage
    assert by["RM-PW"]["is_compensating"] is True


def test_price_history_never_overwritten(pharma, db_url):
    admin = pharma["admin"]
    item = pharma["items"]["FG-VITC-120-EG"]
    _, detail, _ = admin.get(f"/api/items/{item['id']}")
    local = next(m for m in detail["markets"] if m["market"] == "LOCAL")
    status, after, _ = admin.post(f"/api/items/{item['id']}/prices",
                                  {"market_id": local["market_id"], "price": 49.5, "valid_from": "2026-12-01"})
    assert status == 200, after
    local_prices = [p for p in after["prices"] if p["market"] == "LOCAL"]
    assert local_prices[0]["valid_from"] == "2026-12-01" and local_prices[0]["valid_to"] is None
    assert local_prices[1]["valid_to"] == "2026-11-30"   # previous price ended, not overwritten
    status, err, _ = admin.post(f"/api/items/{item['id']}/prices",
                                {"market_id": local["market_id"], "price": 50, "valid_from": "2026-10-01"})
    assert status == 422
    conn = psycopg.connect(db_url)
    with pytest.raises(psycopg.Error):
        conn.execute("UPDATE prices SET price = 1 WHERE item_id = %s", (item["id"],))
    conn.rollback()
    conn.close()


def test_active_bom_frozen_and_new_version(pharma, db_url):
    admin = pharma["admin"]
    bid = _bom_id(admin, "WIP-PCM-BLEND")
    status, err, _ = admin.put(f"/api/boms/{bid}/lines", {"lines": []})
    assert status == 422 and err["error"]["code"] == "not_draft"
    conn = psycopg.connect(db_url)
    with pytest.raises(psycopg.Error):
        conn.execute("UPDATE bom_lines SET quantity = 1 WHERE bom_id = %s", (bid,))
    conn.rollback()
    conn.close()
    item = pharma["items"]["WIP-PCM-BLEND"]
    _, blend, _ = admin.get(f"/api/boms/{bid}")
    status, draft, _ = admin.post(f"/api/items/{item['id']}/boms",
                                  {"batch_size": 300, "batch_uom_id": blend["batch_uom_id"]})
    assert status == 200 and draft["version"] == 2 and draft["status"] == "draft"
    assert len(draft["lines"]) == len(blend["lines"])   # copied from the active version
    # A loop is refused: the finished product cannot go into its own blend.
    fg = pharma["items"]["FG-PCM-20-EG"]
    lines = [{k: l[k] for k in ("id", "component_item_id", "quantity", "uom_id", "assay_compensated", "overage_pct", "is_compensating")}
             for l in draft["lines"]]
    lines.append({"component_item_id": fg["id"], "quantity": 1, "uom_id": fg["stock_uom_id"]})
    status, err, _ = admin.put(f"/api/boms/{draft['id']}/lines", {"lines": lines})
    assert status == 422 and any("loop" in v for v in err["error"]["fields"].values())
    # Change a quantity, activate, and the old version is archived.
    lines.pop()
    lines[1]["quantity"] = 26
    status, saved, _ = admin.put(f"/api/boms/{draft['id']}/lines", {"lines": lines})
    assert status == 200, saved
    status, active, _ = admin.post(f"/api/boms/{draft['id']}/activate", {"valid_from": "2027-01-01"})
    assert status == 200 and active["status"] == "active"
    _, old, _ = admin.get(f"/api/boms/{bid}")
    assert old["status"] == "archived" and old["valid_to"] == "2026-12-31"
    _, audit, _ = admin.get(f"/api/audit?entity=bom_lines&action=UPDATE")
    change = next(e for e in audit["items"] if e["new_values"].get("quantity") == 26)
    assert change["old_values"]["quantity"] == 25
    # A third version may start the same day as the current one (it replaces it); an earlier day is refused.
    status, v3, _ = admin.post(f"/api/items/{item['id']}/boms", {"batch_size": 300, "batch_uom_id": blend["batch_uom_id"]})
    assert status == 200 and v3["version"] == 3
    status, err, _ = admin.post(f"/api/boms/{v3['id']}/activate", {"valid_from": "2026-12-31"})
    assert status == 422 and "valid_from" in err["error"]["fields"] and "2027-01-01" in err["error"]["message"]
    status, act3, _ = admin.post(f"/api/boms/{v3['id']}/activate", {"valid_from": "2027-01-01"})
    assert status == 200 and act3["status"] == "active"
    _, v2, _ = admin.get(f"/api/boms/{draft['id']}")
    assert v2["status"] == "archived" and v2["valid_to"] == "2027-01-01"


def test_routing_save_and_single_preferred(pharma):
    admin, sid = pharma["admin"], pharma["site_id"]
    item = pharma["items"]["SF-VITC-120"]
    _, r, _ = admin.get(f"/api/sites/{sid}/routings/{item['id']}")
    _, res, _ = admin.get(f"/api/sites/{sid}/resources")
    m = {x["code"]: x["id"] for x in res["items"]}
    steps = [{"id": s["id"], "name": s["name"], "time_model": s["time_model"], "fixed_minutes": s["fixed_minutes"],
              "rate_per_hour": s["rate_per_hour"], "setup_minutes": s["setup_minutes"],
              "resources": [{"resource_id": x["resource_id"], "preferred": x["preferred"]} for x in s["resources"]]}
             for s in r["steps"]]
    steps.insert(1, {"name": "Leak test", "time_model": "fixed", "fixed_minutes": 30,
                     "resources": [{"resource_id": m["FIL-01"], "preferred": True}, {"resource_id": m["LBL-01"], "preferred": True}]})
    status, saved, _ = admin.put(f"/api/sites/{sid}/routings/{item['id']}", {"steps": steps})
    assert status == 200, saved
    assert [s["name"] for s in saved["steps"]] == ["Filling and capping", "Leak test", "Labelling"]
    assert sum(1 for x in saved["steps"][1]["resources"] if x["preferred"]) == 1
    steps[2]["resources"] = []
    status, err, _ = admin.put(f"/api/sites/{sid}/routings/{item['id']}", {"steps": steps})
    assert status == 422


def test_calendar_hours_and_holiday_import(pharma):
    admin, sid = pharma["admin"], pharma["site_id"]
    _, hours, _ = admin.get(f"/api/sites/{sid}/calendar/hours?month=2026-11")
    days = {d["date"]: d for d in hours["days"]}
    assert days["2026-11-06"]["hours"] == 0          # Friday off
    assert days["2026-11-07"]["hours"] == 16         # Saturday, two 8-hour shifts
    _, ram, _ = admin.get(f"/api/sites/{sid}/calendar/hours?month=2026-03")
    assert {d["date"]: d for d in ram["days"]}["2026-03-01"]["hours"] == 12   # Ramadan pattern
    status, imp, _ = admin.post(f"/api/sites/{sid}/holidays/import", {"year": 2027})
    assert status == 200
    assert imp["imported"]["added"] == 0             # sample already holds 2027 holidays; no duplicates
    status, err, _ = admin.post(f"/api/sites/{sid}/holidays", {"date": "2027-01-07", "name": "Duplicate"})
    assert status == 409


def test_roles_and_isolation(server, pharma, db_url, platform):
    admin, sid = pharma["admin"], pharma["site_id"]
    status, body, _ = admin.post("/api/users", {"email": "viewer@sample.test", "full_name": "Vera Viewer",
                                                "roles": [{"site_id": sid, "role": "viewer"}]})
    viewer = sign_in_first_time(server, "viewer@sample.test", body["temporary_password"], "Viewer#2026xy")
    assert viewer.get("/api/items")[0] == 200
    item = pharma["items"]["RM-TALC"]
    status, _, _ = viewer.patch(f"/api/items/{item['id']}", {"name_en": "Changed"})
    assert status == 403
    status, _, _ = viewer.post(f"/api/sites/{sid}/resources", {"code": "X-1", "name_en": "X"})
    assert status == 403
    # Editor at another site cannot touch this site's machines.
    _, other, _ = admin.post("/api/sites", {"code": "ALX", "name": "Alexandria"})
    status, body, _ = admin.post("/api/users", {"email": "editor@sample.test", "full_name": "Eddy Editor",
                                                "roles": [{"site_id": other["id"], "role": "master_data_editor"}]})
    editor = sign_in_first_time(server, "editor@sample.test", body["temporary_password"], "Editor#2026xy")
    assert editor.patch(f"/api/items/{item['id']}", {"grade": "USP"})[0] == 200   # company data: any editor
    assert editor.get(f"/api/sites/{sid}/resources")[0] == 403
    assert editor.post(f"/api/sites/{other['id']}/resources", {"code": "TP-9", "name_en": "Press"})[0] == 200
    # Platform administrators do not see company business data, even in the database.
    assert platform.get("/api/items")[0] == 403
    conn = psycopg.connect(db_url)
    conn.execute("SET LOCAL ROLE cp_app")
    conn.execute("SELECT set_config('app.is_platform', 'true', true)")
    assert conn.execute("SELECT count(*) FROM items").fetchone()[0] == 0
    conn.rollback()
    conn.close()


def _upload(client, path, data: bytes):
    req = urllib.request.Request(client.base + path, data=data, method="POST")
    req.add_header("X-Requested-With", "complanning")
    req.add_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    import json
    try:
        with client.opener.open(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_excel_import_all_or_nothing(pharma):
    from openpyxl import Workbook, load_workbook
    admin = pharma["admin"]
    status, data, _ = admin.get("/api/master/template?entity=items", raw=True)
    assert status == 200
    ws_head = [c.value for c in load_workbook(io.BytesIO(data)).active[1]]
    wb = Workbook()
    ws = wb.active
    ws.append(ws_head)
    ws.append(["RM-NEW-1", "Raw material", "New excipient", None, "KG"] + [None] * 17)
    ws.append(["RM-TALC", "Raw material", "Purified talc (updated)", None, "KG"] + [None] * 17)
    ws.append(["RM-BAD", "Unknown type", "Bad row", None, "XX"] + [None] * 17)
    buf = io.BytesIO(); wb.save(buf)
    status, summary = _upload(admin, "/api/master/import?entity=items&commit=1", buf.getvalue())
    assert status == 200 and summary["committed"] is False and summary["error_count"] == 1
    assert summary["errors"][0]["row"] == 4
    ws.delete_rows(4)
    buf = io.BytesIO(); wb.save(buf)
    status, summary = _upload(admin, "/api/master/import?entity=items&commit=1", buf.getvalue())
    assert status == 200 and summary["committed"] and summary["create"] == 1 and summary["update"] == 1
    _, items, _ = admin.get("/api/items?q=RM-NEW-1")
    assert items["items"][0]["name_en"] == "New excipient"
    status, data, _ = admin.get(f"/api/master/export?site_id={pharma['site_id']}", raw=True)
    assert status == 200
    assert {"Items", "Bills of materials", "Machines", "Routings"} <= set(load_workbook(io.BytesIO(data)).sheetnames)
