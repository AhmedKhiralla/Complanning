"""End-to-end checks for Phase 3 planning rules."""
import psycopg
import pytest

from conftest import sign_in_first_time


@pytest.fixture(scope="module")
def co(server, platform):
    status, body, _ = platform.post("/api/platform/tenants", {
        "code": "RULES", "name": "Rules Pharma", "admin": {"email": "admin@rules.test", "full_name": "Rana Admin"}})
    assert status == 200, body
    admin = sign_in_first_time(server, "admin@rules.test", body["temporary_password"], "Rules#Admin2026")
    assert admin.post("/api/sample-data")[0] == 200
    _, sites, _ = admin.get("/api/sites")
    sid = sites["items"][0]["id"]
    _, items, _ = admin.get("/api/items")
    _, res, _ = admin.get(f"/api/sites/{sid}/resources")
    return {"admin": admin, "sid": sid, "items": {i["code"]: i["id"] for i in items["items"]},
            "machines": {m["code"]: m["id"] for m in res["items"]}}


def resolve(co, machine, a, b):
    m = f"&resource_id={co['machines'][machine]}" if machine else ""
    status, r, _ = co["admin"].get(f"/api/sites/{co['sid']}/changeovers/resolve?from_item_id={co['items'][a]}&to_item_id={co['items'][b]}{m}")
    assert status == 200, r
    return r


def test_sample_rules_loaded(co):
    _, rules, _ = co["admin"].get(f"/api/sites/{co['sid']}/changeovers")
    assert len(rules["items"]) == 9
    _, groups, _ = co["admin"].get("/api/cleaning-groups")
    assert {g["code"] for g in groups["items"]} == {"PCM", "VITC"}
    # Loading sample rules again is refused.
    assert co["admin"].post(f"/api/sites/{co['sid']}/sample-rules")[0] == 409


def test_resolution_order(co):
    same = resolve(co, "TP-01", "SF-PCM-BLS", "SF-PCM-BLS")
    assert same["source"] == "same_product" and float(same["total_minutes"]) == 30
    cross = resolve(co, "TP-01", "WIP-PCM-BLEND", "WIP-VITC-BULK")
    assert cross["source"] == "group_to_group" and cross["verification"] == "swab" and float(cross["total_minutes"]) == 240 + 1440
    back = resolve(co, None, "WIP-VITC-BULK", "WIP-PCM-BLEND")
    assert float(back["total_minutes"]) == 300 + 1440       # direction matters
    within = resolve(co, "TP-01", "FG-PCM-20-EG", "FG-PCM-20-SA")
    assert within["source"] == "same_group" and within["scope"] == "site"
    machine = resolve(co, "BLS-01", "FG-PCM-20-EG", "FG-PCM-20-SA")
    assert machine["source"] == "same_group" and machine["scope"] == "machine" and float(machine["format_minutes"]) == 45
    pair = resolve(co, "CRT-01", "FG-PCM-20-EG", "FG-PCM-20-SA")
    assert pair["source"] == "product_pair" and float(pair["total_minutes"]) == 35


def test_matrix(co):
    _, m, _ = co["admin"].get(f"/api/sites/{co['sid']}/changeovers/matrix?resource_id={co['machines']['BLS-01']}")
    codes = [g["code"] for g in m["groups"]]
    pcm, vitc = codes.index("PCM"), codes.index("VITC")
    cell = m["matrix"][pcm][pcm]                      # BLS-01's own within-group rule (not group-specific)
    assert float(cell["total_minutes"]) == 150 and cell["scope"] == "machine" and cell["specific"] is False
    cross = m["matrix"][pcm][vitc]                    # the site's PCM -> VITC rule
    assert float(cross["total_minutes"]) == 1680 and cross["scope"] == "site" and cross["specific"] is True


def test_rule_crud_and_validation(co):
    a = co["admin"]
    status, err, _ = a.post(f"/api/sites/{co['sid']}/changeovers", {"kind": "group_to_group", "from_group": "PCM", "to_group": "PCM"})
    assert status == 422
    status, err, _ = a.post(f"/api/sites/{co['sid']}/changeovers", {"kind": "default", "cleaning_minutes": 10})
    assert status == 409   # a site default already exists
    status, rule, _ = a.post(f"/api/sites/{co['sid']}/changeovers", {"kind": "same_product", "resource_id": co["machines"]["FIL-01"],
                                                                    "cleaning_minutes": 45, "verification": "visual"})
    assert status == 200, rule
    assert float(resolve(co, "FIL-01", "SF-VITC-120", "SF-VITC-120")["total_minutes"]) == 45
    status, upd, _ = a.patch(f"/api/changeovers/{rule['id']}", {"cleaning_minutes": 50, "verification": "visual"})
    assert status == 200 and float(upd["total_minutes"]) == 50
    assert a.call("DELETE", f"/api/changeovers/{rule['id']}")[0] == 200
    _, audit, _ = a.get("/api/audit?entity=changeover_rules&action=DELETE")
    assert audit["items"][0]["record_label"] == "FIL-01: same product"


def test_campaigns_holds_and_times(co):
    a = co["admin"]
    _, camps, _ = a.get(f"/api/sites/{co['sid']}/campaigns")
    assert len(camps["items"]) == 4
    status, err, _ = a.post(f"/api/sites/{co['sid']}/campaigns", {"item_id": co["items"]["SF-PCM-BLS"], "resource_id": co["machines"]["TP-01"], "max_batches": 3})
    assert status == 409
    status, err, _ = a.post(f"/api/sites/{co['sid']}/campaigns", {"item_id": co["items"]["SF-PCM-BLS"], "min_batches": 5, "max_batches": 2})
    assert status == 422
    _, holds, _ = a.get(f"/api/sites/{co['sid']}/equipment-holds")
    fbd = next(h for h in holds["items"] if h["code"] == "FBD-01")
    assert float(fbd["clean_hold_hours"]) == 48
    _, times, _ = a.get("/api/item-times")
    blend = next(t for t in times["items"] if t["code"] == "WIP-PCM-BLEND")
    assert float(blend["hold_max_hours"]) == 72 and blend["release_at_risk_allowed"] is True
    row = {"item_id": blend["id"], "cleaning_group": "PCM", "hold_min_hours": 80, "hold_max_hours": 72,
           "release_lead_days": 2, "release_at_risk_allowed": True}
    status, err, _ = a.put("/api/item-times", {"rows": [row]})
    assert status == 422
    row["hold_min_hours"] = 4
    status, out, _ = a.put("/api/item-times", {"rows": [row]})
    assert status == 200
    status, err, _ = a.patch(f"/api/items/{blend['id']}", {"cleaning_group": "NOPE"})
    assert status == 422 and "cleaning_group" in err["error"]["fields"]


def test_group_delete_guard(co):
    a = co["admin"]
    _, groups, _ = a.get("/api/cleaning-groups")
    pcm = next(g for g in groups["items"] if g["code"] == "PCM")
    assert a.call("DELETE", f"/api/cleaning-groups/{pcm['id']}")[0] == 409
    status, g, _ = a.post("/api/cleaning-groups", {"code": "HORM", "name_en": "Hormones"})
    assert status == 200
    assert a.call("DELETE", f"/api/cleaning-groups/{g['id']}")[0] == 200


def test_rules_isolated(db_url, co):
    conn = psycopg.connect(db_url)
    conn.execute("SET LOCAL ROLE cp_app")
    conn.execute("SELECT set_config('app.is_platform', 'true', true)")
    assert conn.execute("SELECT count(*) FROM changeover_rules").fetchone()[0] == 0
    conn.rollback(); conn.close()
