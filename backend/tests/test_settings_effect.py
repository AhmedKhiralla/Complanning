"""Version 0.7: every company setting and item field changes planning."""
import datetime as dt
from collections import defaultdict

import pytest

from conftest import sign_in_first_time


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


@pytest.fixture(scope="module")
def co(server, platform):
    status, body, _ = platform.post("/api/platform/tenants", {
        "code": "EFFECT", "name": "Effect Pharma", "admin": {"email": "admin@effect.test", "full_name": "Efe Admin"}})
    assert status == 200, body
    admin = sign_in_first_time(server, "admin@effect.test", body["temporary_password"], "Effect#Admin2026")
    assert admin.post("/api/sample-data")[0] == 200
    _, sites, _ = admin.get("/api/sites")
    _, items, _ = admin.get("/api/items?page_size=200")
    return {"admin": admin, "sid": sites["items"][0]["id"], "items": {i["code"]: i["id"] for i in items["items"]}}


def features(co, **kw):
    status, s, _ = co["admin"].put("/api/settings/features", {"features": kw})
    assert status == 200, s


def month():
    first = dt.date.today().replace(day=1)
    end = (first.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    return first, end


def reqs(co):
    first, end = month()
    status, r, _ = co["admin"].get(f"/api/sites/{co['sid']}/requirements?start={first}&end={end}")
    assert status == 200, r
    return r, {m["code"]: m for m in r["materials"]}, {p["code"]: p for p in r["produced"]}


def plan(co, days=40, **kw):
    start = dt.date.today()
    body = {"objective": "on_time", "horizon_start": start.isoformat(), "horizon_end": (start + dt.timedelta(days=days)).isoformat(),
            "material_constraints": False, **kw}
    status, p, _ = co["admin"].post(f"/api/sites/{co['sid']}/plans", body)
    assert status == 200, p
    return co["admin"].get(f"/api/plans/{p['id']}")[1]


def test_assay_overage_and_compensation(co):
    _, m, _ = reqs(co)
    factor = 100 / 99.6 * 100 / 99.7                       # paracetamol: assay on the dried substance, LOD 0.3 %
    pcm = float(m["RM-PCM"]["required"])
    assert abs(pcm - 750 * factor) < 0.01
    assert abs(float(m["RM-PCM"]["potency"]) - factor) < 1e-6
    # The compensating filler (MCC, 7 kg per batch) gives up the extra paracetamol weight.
    assert abs(float(m["RM-MCC"]["required"]) - (21 - (pcm - 750))) < 0.01
    asc_on = float(m["RM-ASC"]["required"])
    pw_on = float(m["RM-PW"]["required"])

    features(co, compensating_material=False)
    _, m, _ = reqs(co)
    assert abs(float(m["RM-MCC"]["required"]) - 21) < 0.01
    assert float(m["RM-PW"]["required"]) > pw_on

    features(co, assay_compensation=False)
    _, m, _ = reqs(co)
    assert abs(float(m["RM-PCM"]["required"]) - 750) < 0.01 and m["RM-PCM"]["potency"] is None
    asc_plain = float(m["RM-ASC"]["required"])
    assert abs(asc_on - asc_plain * 100 / 99.2) < 0.01     # ascorbic acid: assay 99.2 % as is

    features(co, overage=False)
    _, m, _ = reqs(co)
    assert abs(float(m["RM-ASC"]["required"]) - asc_plain / 1.08) < 0.01   # 8 % overage gone
    features(co, overage=True, assay_compensation=True, compensating_material=True)


def test_assay_basis_on_item(co):
    a, iid = co["admin"], co["items"]["RM-PCM"]
    status, it, _ = a.patch(f"/api/items/{iid}", {"assay_basis": "as_is"})
    assert status == 200 and it["assay_basis"] == "as_is"
    _, m, _ = reqs(co)
    assert abs(float(m["RM-PCM"]["required"]) - 750 * 100 / 99.6) < 0.01     # LOD no longer counted
    a.patch(f"/api/items/{iid}", {"assay_basis": "dried"})


def test_sales_plan_off_fills_sales_limits(co):
    features(co, sales_plan=False)
    r, _, p = reqs(co)
    # Each finished product at its monthly limit in every market: 60,000 + 40,000 for paracetamol in Egypt.
    assert float(p["FG-PCM-20-EG"]["demand"]) == 100000
    assert float(p["FG-VITC-120-EG"]["demand"]) == 30000
    assert r["options"]["sales_plan"] is False
    features(co, sales_plan=True)
    _, _, p = reqs(co)
    assert float(p["FG-PCM-20-EG"]["demand"]) < 100000


def test_holiday_import_switch(co):
    a, sid = co["admin"], co["sid"]
    features(co, holiday_import=False)
    status, err, _ = a.post(f"/api/sites/{sid}/holidays/import", {"year": dt.date.today().year + 1})
    assert status == 409 and err["error"]["code"] == "feature_off"
    features(co, holiday_import=True)


def test_shelf_life_and_shippers(co):
    p = plan(co)
    # A 30-month-old lot of paracetamol (36 months shelf life) has too little shelf life left for Egyptian markets.
    w = [x for x in p["kpis"]["warnings"] if x["kind"] == "short_shelf_life"]
    assert any(x["code"] == "FG-PCM-20-EG" and round(x["quantity"]) > 0 for x in w)
    # Planned batches expire at the end of production plus the shelf life.
    fg = next(b for b in p["batches"] if b["code"] == "FG-PCM-20-EG" and b["end_at"])
    end = ts(fg["end_at"]).date()
    assert dt.date.fromisoformat(fg["expires_on"]) >= end.replace(year=end.year + 3) - dt.timedelta(days=3)
    # Deliveries are whole shippers (100 cartons) unless switched off.
    for d in p["demand"]:
        if d["code"].startswith("FG-PCM") and float(d["quantity"]) > 0:
            assert float(d["quantity"]) % 100 == 0
    assert p["kpis"]["rounded"] >= 1
    q = plan(co, full_shippers=False)
    assert all(d["before_rounding"] is None for d in q["demand"]) and q["kpis"]["rounded"] == 0


def test_minimum_campaign(co):
    a, sid = co["admin"], co["sid"]
    _, camps, _ = a.get(f"/api/sites/{sid}/campaigns")
    bls = next(c for c in camps["items"] if c["item_code"] == "SF-PCM-BLS")
    assert a.patch(f"/api/campaigns/{bls['id']}", {"max_batches": 10, "max_days": 7, "min_batches": 3})[0] == 200
    p = plan(co, days=60)
    tp = next(m for m in p["machines"] if m["code"] == "TP-01")
    batch_item = {b["id"]: b["code"] for b in p["batches"]}
    ops = sorted((o for o in p["operations"] if o["resource_id"] == tp["id"]), key=lambda o: o["start_at"])
    n_bls = sum(1 for b in p["batches"] if b["code"] == "SF-PCM-BLS")
    seq = [batch_item[o["batch_id"]] for o in ops]
    groups = []
    for code in seq:
        if code == "SF-PCM-BLS":
            if groups and groups[-1][0] == "run":
                groups[-1][1] += 1
            else:
                groups.append(["run", 1])
        else:
            groups.append(["other", 1])
    bls_runs = [g[1] for g in groups if g[0] == "run"]
    assert n_bls >= 3 and bls_runs
    # Every run is a full minimum campaign, except a last short one when the batches do not divide evenly.
    assert all(n >= 3 for n in bls_runs[:-1])
    short = [w for w in p["kpis"]["warnings"] if w["kind"] == "campaign_short"]
    assert all(w["batches"] < w["min"] for w in short)


def test_costs(co):
    p0 = plan(co)
    assert p0["kpis"]["cost"] is None
    features(co, costs=True)
    status, s, _ = co["admin"].patch("/api/settings/company", {"cost_currency": "egp"})
    assert status == 200 and s["company"]["cost_currency"] == "EGP"
    r, m, _ = reqs(co)
    assert r["cost"]["currency"] == "EGP" and float(r["cost"]["materials"]) > 0
    assert float(m["RM-PCM"]["unit_cost"]) == 310
    p = plan(co)
    c = p["kpis"]["cost"]
    assert c["currency"] == "EGP" and c["materials"] > 0 and c["deliveries"] > 0 and c["margin"] > 0
    assert any(b["material_cost"] for b in p["batches"])
    features(co, costs=False)
