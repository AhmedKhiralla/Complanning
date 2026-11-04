"""End-to-end checks for Phase 4: sales plan, stock and net requirements."""
import datetime as dt
import io

import pytest

from conftest import sign_in_first_time
from test_master_data import _upload


@pytest.fixture(scope="module")
def co(server, platform):
    status, body, _ = platform.post("/api/platform/tenants", {
        "code": "DEMAND", "name": "Demand Pharma", "admin": {"email": "admin@demand.test", "full_name": "Dina Admin"}})
    assert status == 200, body
    admin = sign_in_first_time(server, "admin@demand.test", body["temporary_password"], "Demand#Admin2026")
    assert admin.post("/api/sample-data")[0] == 200
    _, sites, _ = admin.get("/api/sites")
    sid = sites["items"][0]["id"]
    _, items, _ = admin.get("/api/items")
    _, markets, _ = admin.get("/api/markets")
    return {"admin": admin, "sid": sid, "server": server, "items": {i["code"]: i["id"] for i in items["items"]},
            "markets": {m["code"]: m["id"] for m in markets["items"]}}


def this_month():
    t = dt.date.today()
    first = t.replace(day=1)
    end = (first.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    return first, end


def test_sample_demand_and_stock(co):
    status, grid, _ = co["admin"].get(f"/api/sites/{co['sid']}/demand?months=6")
    assert status == 200, grid
    assert len(grid["months"]) == 6 and len(grid["rows"]) == 4
    pcm = next(r for r in grid["rows"] if r["code"] == "FG-PCM-20-EG" and r["market"] == "LOCAL")
    assert float(pcm["cells"][grid["months"][0]]["quantity"]) == 48000
    assert float(pcm["price"]) == 32.00                           # price valid today
    _, stock, _ = co["admin"].get(f"/api/sites/{co['sid']}/stock")
    assert stock["as_of"] and len(stock["items"]) > 30
    # Loading the sample demand twice is refused.
    assert co["admin"].post(f"/api/sites/{co['sid']}/sample-demand")[0] == 409


def test_save_demand(co):
    a, sid, i, m = co["admin"], co["sid"], co["items"], co["markets"]
    month = dt.date.today().replace(day=1)
    nxt = (month.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    key = nxt.strftime("%Y-%m")
    status, r, _ = a.put(f"/api/sites/{sid}/demand", {"lines": [
        {"item_id": i["FG-PCM-20-SA"], "market_id": m["KSA"], "month": key, "quantity": 19000, "due_date": nxt.replace(day=12).isoformat()},
        {"item_id": i["FG-VITC-120-EG"], "market_id": m["LOCAL"], "month": key, "quantity": 0}]})
    assert status == 200 and r == {"saved": 1, "removed": 1}, r
    _, grid, _ = a.get(f"/api/sites/{sid}/demand?start={key}&months=1")
    ksa = next(x for x in grid["rows"] if x["market"] == "KSA")
    assert float(ksa["cells"][key]["quantity"]) == 19000 and ksa["cells"][key]["due_date"] == nxt.replace(day=12).isoformat()
    vitc = next(x for x in grid["rows"] if x["code"] == "FG-VITC-120-EG")
    assert key not in vitc["cells"]
    # Product not sold in that market, and a due date outside the month, are refused.
    status, err, _ = a.put(f"/api/sites/{sid}/demand", {"lines": [
        {"item_id": i["FG-VITC-120-EG"], "market_id": m["KSA"], "month": key, "quantity": 10}]})
    assert status == 422 and "lines.0" in err["error"]["fields"]
    status, err, _ = a.put(f"/api/sites/{sid}/demand", {"lines": [
        {"item_id": i["FG-PCM-20-SA"], "market_id": m["KSA"], "month": key, "quantity": 10, "due_date": month.isoformat()}]})
    assert status == 422
    # The change is in the audit trail with a readable label.
    _, audit, _ = a.get("/api/audit?entity=demand_lines&page_size=20")
    assert any(e["record_label"] == f"FG-PCM-20-SA / KSA / {key}" and e["action"] == "UPDATE" for e in audit["items"])


def test_net_requirements(co):
    a, sid = co["admin"], co["sid"]
    first, end = this_month()
    status, r, _ = a.get(f"/api/sites/{sid}/requirements?start={first}&end={end}")
    assert status == 200, r
    p = {x["code"]: x for x in r["produced"]}
    # 48,000 + 24,000 demand - 18,500 released = 53,500; batches of 23,880 (yield 99.5%), partial last batch >= 50%.
    eg = p["FG-PCM-20-EG"]
    assert float(eg["net"]) == 53500 and eg["batches"] == 3
    assert [round(float(x)) for x in eg["batch_sizes"]] == [23880, 23880, 11940]
    # 16,000 - 6,200 = 9,800 is below the minimum batch, so one batch at the minimum (50% of 23,880).
    assert p["FG-PCM-20-SA"]["batches"] == 1 and round(float(p["FG-PCM-20-SA"]["planned"])) == 11940
    # Blisters: 120,000 + 24,000 needed - 31,000 in stock = 113,000 -> 3 fixed batches of 48,020.
    bls = p["SF-PCM-BLS"]
    assert round(float(bls["dependent"])) == 144000 and bls["batches"] == 3
    assert {u["code"] for u in bls["used_by"]} == {"FG-PCM-20-EG", "FG-PCM-20-SA"}
    assert p["WIP-PCM-BLEND"]["batches"] == 3
    mats = {x["code"]: x for x in r["materials"]}
    api = mats["RM-PCM"]
    # 750 kg in the formula, raised by the potency of the stock: assay 99.6 % on the dried substance, LOD 0.3 %.
    assert abs(float(api["required"]) - 750 * 100 / 99.6 * 100 / 99.7) < 0.01 and round(float(api["shortage"])) == 155
    # Suggested order: shortage plus safety stock (800 kg), at least the minimum order (500 kg).
    assert round(float(api["order_qty"])) == 955
    assert api["quarantine_would_cover"] and api["late"]           # 120 days lead time
    assert mats["RM-PW"]["not_stock_controlled"] and float(mats["RM-PW"]["shortage"]) == 0
    assert "PM-ALU-250" in mats and float(mats["PM-ALU-250"]["released"]) == 250   # rejected lot not counted
    assert r["sales_value"] and r["totals"]["batches"] >= 8
    # Counting quarantine stock: finished goods awaiting QC reduce the batches, and the API shortage goes away.
    _, q, _ = a.get(f"/api/sites/{sid}/requirements?start={first}&end={end}&quarantine=1")
    qp = {x["code"]: x for x in q["produced"]}
    assert qp["FG-PCM-20-EG"]["batches"] == 2
    assert float({x["code"]: x for x in q["materials"]}["RM-PCM"]["shortage"]) == 0


def test_stock_lines_and_permissions(co, platform):
    a, sid, i = co["admin"], co["sid"], co["items"]
    body = {"item_id": i["RM-TALC"], "lot_no": "TL-TEST-1", "status": "quarantine", "quantity": 12.5,
            "manufactured_on": "2026-10-01", "expires_on": "2029-09-30"}
    status, line, _ = a.post(f"/api/sites/{sid}/stock", body)
    assert status == 200 and line["code"] == "RM-TALC"
    assert a.post(f"/api/sites/{sid}/stock", body)[0] == 409                 # same lot and status
    status, err, _ = a.put(f"/api/stock/{line['id']}", {**body, "expires_on": "2026-09-01"})
    assert status == 422 and "expires_on" in err["error"]["fields"]
    status, upd, _ = a.put(f"/api/stock/{line['id']}", {**body, "status": "released", "quantity": 12})
    assert status == 200 and upd["status"] == "released"
    # A viewer can read but not change; a planner can change.
    for email, role in (("viewer@demand.test", "viewer"), ("planner@demand.test", "planner")):
        status, u, _ = a.post("/api/users", {"email": email, "full_name": role.title(), "roles": [{"site_id": sid, "role": role}]})
        assert status == 200, u
        c = sign_in_first_time(co["server"], email, u["temporary_password"], "Demand#User2026")
        assert c.get(f"/api/sites/{sid}/stock")[0] == 200
        expected = 200 if role == "planner" else 403
        assert c.put(f"/api/stock/{line['id']}", {**body, "status": "released", "quantity": 11})[0] == expected
    assert a.call("DELETE", f"/api/stock/{line['id']}")[0] == 200


def test_excel_round_trip(co):
    from openpyxl import Workbook, load_workbook
    a, sid = co["admin"], co["sid"]
    status, data, _ = a.get(f"/api/master/export?entity=demand&site_id={sid}", raw=True)
    assert status == 200
    wb = load_workbook(io.BytesIO(data))
    assert "Export info" in wb.sheetnames
    assert wb["Export info"]["B1"].value.startswith("Dina Admin")
    status, summary = _upload(a, f"/api/master/import?entity=demand&site_id={sid}&commit=0", data)
    assert status == 200 and summary["error_count"] == 0 and summary["update"] == summary["rows"]

    status, tpl, _ = a.get("/api/master/template?entity=stock", raw=True)
    head = [c.value for c in load_workbook(io.BytesIO(tpl)).active[1]]
    wb = Workbook()
    ws = wb.active
    ws.append(head)
    ws.append(["RM-PCM", "API-NEW-1", "Released", 900, "2026-09-01", "2030-08-31", 99.8, 0.2, None])
    ws.append(["FG-PCM-20-EG", "PE-NEW-1", "Quarantine", 1000, None, None, None, None, None])
    ws.append(["NO-SUCH", None, "Lost", "x", None, None, None, None, None])
    buf = io.BytesIO(); wb.save(buf)
    status, summary = _upload(a, f"/api/master/import?entity=stock&site_id={sid}&commit=1", buf.getvalue())
    assert status == 200 and not summary["committed"] and summary["errors"][0]["row"] == 4
    assert len(summary["errors"][0]["problems"]) == 3
    ws.delete_rows(4)
    buf = io.BytesIO(); wb.save(buf)
    status, summary = _upload(a, f"/api/master/import?entity=stock&site_id={sid}&commit=1", buf.getvalue())
    assert status == 200 and summary["committed"] and summary["create"] == 2 and summary["remove"] > 30
    _, stock, _ = a.get(f"/api/sites/{sid}/stock")
    assert len(stock["items"]) == 2                                   # import replaces the site's stock
