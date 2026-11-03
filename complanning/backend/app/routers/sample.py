"""Loads a realistic pharmaceutical sample dataset into an empty company.

Two product families, three levels each:
  Paracetamol 500 mg tablets: final blend (WIP) -> blisters (semi-finished) -> cartons for Egypt and Saudi Arabia
  Vitamin C 100 mg/5 mL syrup: syrup bulk in litres (WIP) -> filled bottles (semi-finished) -> cartons
It shows assay compensation, overage, a compensating filler, q.s. water, liquids received in kg
and dispensed in litres, pack conversions, markets with price history, machines with alternatives,
routings, a shift pattern with a Ramadan period, holidays and planned downtime.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal as D

from ..api import ApiError, Call, endpoint
from ..holidays_builtin import builtin_holidays

MARKETS = [
    ("LOCAL", "Egypt – private market", "مصر – السوق الخاص", "EGP"),
    ("MOH", "Egypt – Ministry of Health tender", "مصر – مناقصة وزارة الصحة", "EGP"),
    ("KSA", "Saudi Arabia – export", "السعودية – تصدير", "USD"),
]

# code, name_en, name_ar, type, stock uom, extra fields
ITEMS = [
    # Active ingredients and excipients (tablets)
    ("RM-PCM", "Paracetamol BP (API)", "باراسيتامول (مادة فعالة)", "raw_material", "KG",
     dict(grade="BP", lead_time_days=120, moq=D(500), safety_stock=D(800), qc_release_days=D(10))),
    ("RM-MAIZE", "Maize starch BP", "نشا الذرة", "raw_material", "KG", dict(grade="BP", lead_time_days=45, qc_release_days=D(5))),
    ("RM-PVP", "Povidone K30", "بوفيدون K30", "raw_material", "KG", dict(grade="Ph. Eur.", lead_time_days=60, qc_release_days=D(5))),
    ("RM-MCC", "Microcrystalline cellulose PH102", "ميكروكريستالين سليلوز PH102", "raw_material", "KG",
     dict(grade="Ph. Eur.", lead_time_days=60, qc_release_days=D(5))),
    ("RM-SSG", "Sodium starch glycolate", "جليكولات نشا الصوديوم", "raw_material", "KG", dict(lead_time_days=60, qc_release_days=D(5))),
    ("RM-MGST", "Magnesium stearate", "ستيرات الماغنسيوم", "raw_material", "KG", dict(lead_time_days=60, qc_release_days=D(5))),
    ("RM-TALC", "Purified talc", "تلك منقى", "raw_material", "KG", dict(lead_time_days=45, qc_release_days=D(5))),
    # Syrup ingredients (liquids received in kg, dispensed in litres)
    ("RM-ASC", "Ascorbic acid (API)", "حمض الأسكوربيك (مادة فعالة)", "raw_material", "KG",
     dict(grade="USP", lead_time_days=90, moq=D(100), qc_release_days=D(10))),
    ("RM-SUC", "Sucrose", "سكروز", "raw_material", "KG", dict(lead_time_days=30, qc_release_days=D(4))),
    ("RM-SORB", "Sorbitol 70% solution", "محلول سوربيتول 70%", "raw_material", "KG",
     dict(dispensing="L", density_kg_per_l=D("1.29"), lead_time_days=45, qc_release_days=D(5))),
    ("RM-GLY", "Glycerin", "جلسرين", "raw_material", "KG",
     dict(dispensing="L", density_kg_per_l=D("1.26"), lead_time_days=45, qc_release_days=D(5))),
    ("RM-NABZ", "Sodium benzoate", "بنزوات الصوديوم", "raw_material", "KG", dict(lead_time_days=45, qc_release_days=D(4))),
    ("RM-CIT", "Citric acid monohydrate", "حمض الستريك", "raw_material", "KG", dict(lead_time_days=45, qc_release_days=D(4))),
    ("RM-FLV-ORG", "Orange flavour", "نكهة برتقال", "raw_material", "KG",
     dict(dispensing="L", density_kg_per_l=D("0.85"), lead_time_days=60, qc_release_days=D(4))),
    ("RM-PW", "Purified water", "ماء منقى", "raw_material", "L", dict(description="Produced on site; no stock limit")),
    # Packaging
    ("PM-PVC-250", "PVC film 250 mm, clear", "رقائق PVC عرض 250 مم", "packaging", "KG", dict(lead_time_days=30)),
    ("PM-ALU-250", "Blister lidding foil 250 mm, printed", "رقائق ألومنيوم مطبوعة 250 مم", "packaging", "KG", dict(lead_time_days=45)),
    ("PM-CTN-PCM-EG", "Carton – Paracetamol 500 mg 20s (Egypt)", "علبة باراسيتامول 500 مجم 20 قرص – مصر", "packaging", "EA", dict(lead_time_days=30)),
    ("PM-CTN-PCM-SA", "Carton – Paracetamol 500 mg 20s (KSA)", "علبة باراسيتامول 500 مجم 20 قرص – السعودية", "packaging", "EA", dict(lead_time_days=30)),
    ("PM-LEAF-PCM-EG", "Leaflet – Paracetamol (Egypt)", "نشرة باراسيتامول – مصر", "packaging", "EA", dict(lead_time_days=30)),
    ("PM-LEAF-PCM-SA", "Leaflet – Paracetamol (KSA)", "نشرة باراسيتامول – السعودية", "packaging", "EA", dict(lead_time_days=30)),
    ("PM-SHP-100", "Shipper box for 100 cartons", "كرتونة شحن 100 علبة", "packaging", "EA", dict(lead_time_days=20)),
    ("PM-BTL-120", "Amber PET bottle 120 mL", "زجاجة PET عسلي 120 مل", "packaging", "EA", dict(lead_time_days=45)),
    ("PM-CAP-28", "Child-resistant cap 28 mm", "غطاء آمن للأطفال 28 مم", "packaging", "EA", dict(lead_time_days=45)),
    ("PM-LBL-VITC", "Label – Vitamin C syrup", "ملصق شراب فيتامين سي", "packaging", "EA", dict(lead_time_days=30)),
    ("PM-CTN-VITC", "Carton – Vitamin C syrup 120 mL", "علبة شراب فيتامين سي 120 مل", "packaging", "EA", dict(lead_time_days=30)),
    ("PM-LEAF-VITC", "Leaflet – Vitamin C syrup", "نشرة شراب فيتامين سي", "packaging", "EA", dict(lead_time_days=30)),
    ("PM-CUP-10", "Dosing cup 10 mL", "كوب جرعات 10 مل", "packaging", "EA", dict(lead_time_days=45)),
    ("PM-SHP-60", "Shipper box for 60 cartons", "كرتونة شحن 60 علبة", "packaging", "EA", dict(lead_time_days=20)),
    # Produced items
    ("WIP-PCM-BLEND", "Paracetamol 500 mg final blend", "خليط باراسيتامول 500 مجم النهائي", "wip", "KG",
     dict(dosage_form="Tablet", cleaning_group="PCM", release_lead_days=D(2))),
    ("SF-PCM-BLS", "Paracetamol 500 mg tablets – blister of 10", "أقراص باراسيتامول 500 مجم – شريط 10", "semi_finished", "BLS",
     dict(dosage_form="Tablet", cleaning_group="PCM", release_lead_days=D(3))),
    ("FG-PCM-20-EG", "Paracetamol 500 mg 20 tablets – Egypt", "باراسيتامول 500 مجم 20 قرص – مصر", "finished", "CTN",
     dict(dosage_form="Tablet", cleaning_group="PCM", shelf_life_months=36, pack_size=D(20), units_per_shipper=100,
          standard_cost=D("14.20"), test_before_sale=True, release_lead_days=D(7))),
    ("FG-PCM-20-SA", "Paracetamol 500 mg 20 tablets – Saudi Arabia", "باراسيتامول 500 مجم 20 قرص – السعودية", "finished", "CTN",
     dict(dosage_form="Tablet", cleaning_group="PCM", shelf_life_months=36, pack_size=D(20), units_per_shipper=100,
          standard_cost=D("15.10"), test_before_sale=True, release_lead_days=D(7))),
    ("WIP-VITC-BULK", "Vitamin C 100 mg/5 mL syrup – bulk", "شراب فيتامين سي 100 مجم/5 مل – سائب", "wip", "L",
     dict(dosage_form="Syrup", cleaning_group="VITC", release_lead_days=D(1), density_kg_per_l=D("1.18"))),
    ("SF-VITC-120", "Vitamin C syrup 120 mL – filled bottle", "شراب فيتامين سي 120 مل – زجاجة معبأة", "semi_finished", "BTL",
     dict(dosage_form="Syrup", cleaning_group="VITC", release_lead_days=D(2))),
    ("FG-VITC-120-EG", "Vitamin C 100 mg/5 mL syrup 120 mL – Egypt", "شراب فيتامين سي 100 مجم/5 مل 120 مل – مصر", "finished", "CTN",
     dict(dosage_form="Syrup", cleaning_group="VITC", shelf_life_months=24, pack_size=D(1), units_per_shipper=60,
          standard_cost=D("21.40"), test_before_sale=True, release_lead_days=D(10))),
]

# Pack conversions: item, uom, factor (1 uom = factor stock units)
CONVERSIONS = [
    ("SF-PCM-BLS", "TAB", D("0.1")),
    ("FG-PCM-20-EG", "BLS", D("0.5")), ("FG-PCM-20-EG", "BOX", D(100)),
    ("FG-PCM-20-SA", "BLS", D("0.5")), ("FG-PCM-20-SA", "BOX", D(100)),
    ("FG-VITC-120-EG", "BTL", D(1)), ("FG-VITC-120-EG", "BOX", D(60)),
]

# BOMs: item, batch size, batch uom, yield %, mode, min %, lines(component, qty, uom, assay, overage %, compensating)
BOMS = [
    ("WIP-PCM-BLEND", D(300), "KG", D("98.5"), "fixed", None, [
        ("RM-PCM", D(250), "KG", True, D(0), False),
        ("RM-MAIZE", D(25), "KG", False, D(0), False),
        ("RM-PVP", D("7.5"), "KG", False, D(0), False),
        ("RM-SSG", D(6), "KG", False, D(0), False),
        ("RM-MGST", D("1.5"), "KG", False, D(0), False),
        ("RM-TALC", D(3), "KG", False, D(0), False),
        ("RM-MCC", D(7), "KG", False, D(0), True),
    ]),
    ("SF-PCM-BLS", D(49000), "BLS", D(98), "fixed", None, [
        ("WIP-PCM-BLEND", D(294), "KG", False, D(0), False),
        ("PM-PVC-250", D(54), "KG", False, D(0), False),
        ("PM-ALU-250", D(30), "KG", False, D(0), False),
    ]),
    ("FG-PCM-20-EG", D(24000), "CTN", D("99.5"), "partial", D(50), [
        ("SF-PCM-BLS", D(48000), "BLS", False, D(0), False),
        ("PM-CTN-PCM-EG", D(24000), "EA", False, D(0), False),
        ("PM-LEAF-PCM-EG", D(24000), "EA", False, D(0), False),
        ("PM-SHP-100", D(240), "EA", False, D(0), False),
    ]),
    ("FG-PCM-20-SA", D(24000), "CTN", D("99.5"), "partial", D(50), [
        ("SF-PCM-BLS", D(48000), "BLS", False, D(0), False),
        ("PM-CTN-PCM-SA", D(24000), "EA", False, D(0), False),
        ("PM-LEAF-PCM-SA", D(24000), "EA", False, D(0), False),
        ("PM-SHP-100", D(240), "EA", False, D(0), False),
    ]),
    ("WIP-VITC-BULK", D(1000), "L", D(98), "fixed", None, [
        ("RM-ASC", D(20), "KG", True, D(8), False),
        ("RM-SUC", D(450), "KG", False, D(0), False),
        ("RM-SORB", D(150), "L", False, D(0), False),
        ("RM-GLY", D(50), "L", False, D(0), False),
        ("RM-NABZ", D(1), "KG", False, D(0), False),
        ("RM-CIT", D(3), "KG", False, D(0), False),
        ("RM-FLV-ORG", D(2), "L", False, D(0), False),
        ("RM-PW", D(520), "L", False, D(0), True),
    ]),
    ("SF-VITC-120", D(8100), "BTL", D(99), "fixed", None, [
        ("WIP-VITC-BULK", D(972), "L", False, D(0), False),
        ("PM-BTL-120", D(8100), "EA", False, D(0), False),
        ("PM-CAP-28", D(8100), "EA", False, D(0), False),
        ("PM-LBL-VITC", D(8100), "EA", False, D(0), False),
    ]),
    ("FG-VITC-120-EG", D(8000), "CTN", D("99.5"), "partial", D(25), [
        ("SF-VITC-120", D(8000), "BTL", False, D(0), False),
        ("PM-CTN-VITC", D(8000), "EA", False, D(0), False),
        ("PM-LEAF-VITC", D(8000), "EA", False, D(0), False),
        ("PM-CUP-10", D(8000), "EA", False, D(0), False),
        ("PM-SHP-60", D(134), "EA", False, D(0), False),
    ]),
]

ITEM_MARKETS = [
    ("FG-PCM-20-EG", "LOCAL", D(60000), D(60)), ("FG-PCM-20-EG", "MOH", D(40000), D(75)),
    ("FG-PCM-20-SA", "KSA", D(20000), D(75)),
    ("FG-VITC-120-EG", "LOCAL", D(30000), D(60)),
]

# item, market, price, valid_from, valid_to
PRICES = [
    ("FG-PCM-20-EG", "LOCAL", D("28.00"), "2026-01-01", "2026-06-30"),
    ("FG-PCM-20-EG", "LOCAL", D("32.00"), "2026-07-01", None),
    ("FG-PCM-20-EG", "MOH", D("21.50"), "2026-01-01", None),
    ("FG-PCM-20-SA", "KSA", D("1.75"), "2026-01-01", None),
    ("FG-VITC-120-EG", "LOCAL", D("38.00"), "2026-01-01", "2026-08-31"),
    ("FG-VITC-120-EG", "LOCAL", D("45.00"), "2026-09-01", None),
]

# code, name_en, name_ar, area, efficiency %
MACHINES = [
    ("DSP-01", "Dispensing booth 1", "كابينة وزن 1", "Dispensing", D(100)),
    ("DSP-02", "Dispensing booth 2", "كابينة وزن 2", "Dispensing", D(100)),
    ("GR-01", "High-shear granulator 600 L", "خلاط تحبيب عالي القص 600 لتر", "Granulation", D(90)),
    ("FBD-01", "Fluid bed dryer 300 kg", "مجفف بالهواء المميع 300 كجم", "Granulation", D(90)),
    ("ML-01", "Cone mill", "طاحونة مخروطية", "Granulation", D(95)),
    ("BL-01", "Bin blender 1200 L", "خلاط حاويات 1200 لتر", "Granulation", D(95)),
    ("BL-02", "Bin blender 600 L", "خلاط حاويات 600 لتر", "Granulation", D(95)),
    ("TP-01", "Rotary tablet press 45 stations", "ماكينة كبس دوارة 45 محطة", "Compression", D(85)),
    ("TP-02", "Rotary tablet press 37 stations", "ماكينة كبس دوارة 37 محطة", "Compression", D(85)),
    ("CT-01", "Tablet coater 150 kg", "ماكينة تغليف أقراص 150 كجم", "Coating", D(85)),
    ("BLS-01", "Blister line 1", "خط بليستر 1", "Primary packaging", D(80)),
    ("BLS-02", "Blister line 2", "خط بليستر 2", "Primary packaging", D(80)),
    ("MX-01", "Syrup vessel 1000 L", "خزان تحضير شراب 1000 لتر", "Liquids", D(95)),
    ("MX-02", "Syrup vessel 1000 L (B)", "خزان تحضير شراب 1000 لتر (ب)", "Liquids", D(95)),
    ("FIL-01", "Liquid filling and capping line", "خط تعبئة وتغطية السوائل", "Liquids", D(80)),
    ("LBL-01", "Labelling machine", "ماكينة لصق الملصقات", "Liquids", D(85)),
    ("CRT-01", "Cartoner 1", "ماكينة تعبئة علب 1", "Secondary packaging", D(80)),
    ("CRT-02", "Cartoner 2", "ماكينة تعبئة علب 2", "Secondary packaging", D(80)),
    ("CHK-01", "Checkweigher and serialisation", "ميزان تحقق وترقيم تسلسلي", "Secondary packaging", D(90)),
]
QC_RESOURCES = [("QC-HPLC", "HPLC laboratory", "معمل HPLC", "Quality control")]

# item: steps (name, model, minutes or rate per hour, setup minutes, [(machine, preferred, own value)])
ROUTINGS = {
    "WIP-PCM-BLEND": [
        ("Dispensing", "fixed", D(120), D(0), [("DSP-01", True, None), ("DSP-02", False, None)]),
        ("Wet granulation", "fixed", D(90), D(30), [("GR-01", True, None)]),
        ("Drying", "fixed", D(150), D(0), [("FBD-01", True, None)]),
        ("Dry milling", "fixed", D(60), D(15), [("ML-01", True, None)]),
        ("Final blending", "fixed", D(45), D(15), [("BL-01", True, None), ("BL-02", False, D(60))]),
    ],
    "SF-PCM-BLS": [
        ("Compression", "rate", D(18000), D(45), [("TP-01", True, None), ("TP-02", False, D(14500))]),
        ("Blistering", "rate", D(12000), D(30), [("BLS-01", True, None), ("BLS-02", False, D(10000))]),
    ],
    "FG-PCM-20-EG": [
        ("Cartoning", "rate", D(6000), D(20), [("CRT-01", True, None), ("CRT-02", False, D(5000))]),
        ("Checkweighing and serialisation", "rate", D(9000), D(10), [("CHK-01", True, None)]),
    ],
    "FG-PCM-20-SA": [
        ("Cartoning", "rate", D(6000), D(20), [("CRT-01", True, None), ("CRT-02", False, D(5000))]),
        ("Checkweighing and serialisation", "rate", D(9000), D(10), [("CHK-01", True, None)]),
    ],
    "WIP-VITC-BULK": [
        ("Dispensing", "fixed", D(90), D(0), [("DSP-02", True, None), ("DSP-01", False, None)]),
        ("Syrup preparation", "fixed", D(360), D(30), [("MX-01", True, None), ("MX-02", False, None)]),
    ],
    "SF-VITC-120": [
        ("Filling and capping", "rate", D(3000), D(45), [("FIL-01", True, None)]),
        ("Labelling", "rate", D(4000), D(15), [("LBL-01", True, None)]),
    ],
    "FG-VITC-120-EG": [
        ("Cartoning", "rate", D(3500), D(20), [("CRT-02", True, None), ("CRT-01", False, D(3200))]),
    ],
}


GROUPS = [("PCM", "Paracetamol solids", "أقراص الباراسيتامول", "Low-potency oral solids"),
          ("VITC", "Vitamin C liquids", "سوائل فيتامين سي", "Oral liquids, sugar based")]

# kind, machine (None = all machines at the site), from, to, cleaning min, format min, verification, wait min, notes
CHANGEOVERS = [
    ("same_product", None, None, None, D(30), D(0), "visual", D(0), "Batch-to-batch line clearance"),
    ("same_group", None, None, None, D(120), D(0), "visual", D(30), "Product change within a cleaning group"),
    ("default", None, None, None, D(240), D(0), "rinse", D(240), "Any other product change"),
    ("group_to_group", None, "PCM", "VITC", D(240), D(0), "swab", D(1440), "Swab results needed before the next product"),
    ("group_to_group", None, "VITC", "PCM", D(300), D(0), "swab", D(1440), "Sugar residue: full wet clean and swab"),
    ("same_group", "BLS-01", None, None, D(90), D(45), "visual", D(15), "Change parts for blister format"),
    ("same_group", "BLS-02", None, None, D(90), D(45), "visual", D(15), "Change parts for blister format"),
    ("product_pair", "CRT-01", "FG-PCM-20-EG", "FG-PCM-20-SA", D(15), D(20), "visual", D(0), "Artwork and leaflet change only"),
    ("product_pair", "CRT-01", "FG-PCM-20-SA", "FG-PCM-20-EG", D(15), D(20), "visual", D(0), "Artwork and leaflet change only"),
]

# item, machine, max batches, max days, min batches
CAMPAIGNS = [
    ("WIP-PCM-BLEND", "GR-01", 6, D(5), None),
    ("SF-PCM-BLS", "TP-01", 10, D(7), 2),
    ("WIP-VITC-BULK", "MX-01", 3, D(3), None),
    ("SF-VITC-120", "FIL-01", 4, D(4), None),
]

# item: hold min hours, hold max hours, release at risk allowed
ITEM_TIMES = {
    "WIP-PCM-BLEND": (D(0), D(72), True),
    "SF-PCM-BLS": (D(0), D(720), False),
    "WIP-VITC-BULK": (D(2), D(48), False),
    "SF-VITC-120": (D(0), D(336), False),
}

# machine: dirty hold hours, clean hold hours (all other machines: 24 h dirty, 72 h clean)
HOLDS = {"FBD-01": (D(12), D(48)), "MX-01": (D(8), D(48)), "MX-02": (D(8), D(48)), "FIL-01": (D(8), D(48))}


def apply_sample_rules(call: Call, site_id: str) -> dict:
    """Add the sample rules for the sample products that exist in this company."""
    tx, tenant = call.tx, call.tenant_id
    items = {r["code"]: str(r["id"]) for r in tx.q("SELECT id, code FROM items")}
    machines = {r["code"]: str(r["id"]) for r in tx.q("SELECT id, code FROM resources WHERE site_id = %s::uuid", site_id)}
    needed = {"WIP-PCM-BLEND", "SF-PCM-BLS", "FG-PCM-20-EG", "WIP-VITC-BULK"}
    if not needed <= set(items) or "GR-01" not in machines:
        raise ApiError(409, "no_sample", "The sample products and machines were not found at this site. Load the sample data first.")
    if tx.val("SELECT count(*) FROM changeover_rules WHERE site_id = %s::uuid", site_id):
        raise ApiError(409, "not_empty", "This site already has changeover rules. Sample rules are only added to a site without rules.")
    for i, (code, en, ar, notes) in enumerate(GROUPS):
        tx.x("INSERT INTO cleaning_groups (tenant_id, code, name_en, name_ar, notes, sort_order) VALUES (%s, %s, %s, %s, %s, %s)"
             " ON CONFLICT (tenant_id, code) DO UPDATE SET name_en = EXCLUDED.name_en, name_ar = EXCLUDED.name_ar, notes = EXCLUDED.notes",
             tenant, code, en, ar, notes, (i + 1) * 10)
    for kind, mcode, frm, to, clean, fmt, ver, wait, notes in CHANGEOVERS:
        if mcode and mcode not in machines:
            continue
        pair = kind == "product_pair"
        if pair and (frm not in items or to not in items):
            continue
        tx.x("INSERT INTO changeover_rules (tenant_id, site_id, resource_id, kind, from_group, to_group, from_item_id, to_item_id,"
             " cleaning_minutes, format_minutes, verification, verification_wait_minutes, notes)"
             " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
             tenant, site_id, machines.get(mcode) if mcode else None, kind,
             None if pair else frm, None if pair else to, items.get(frm) if pair else None, items.get(to) if pair else None,
             clean, fmt, ver, wait, notes)
    for code, mcode, mx, days, mn in CAMPAIGNS:
        if code in items and mcode in machines:
            tx.x("INSERT INTO campaign_rules (tenant_id, site_id, item_id, resource_id, max_batches, max_days, min_batches)"
                 " VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING", tenant, site_id, items[code], machines[mcode], mx, days, mn)
    for code, (mn, mx, risk) in ITEM_TIMES.items():
        if code in items:
            tx.x("UPDATE items SET hold_min_hours = %s, hold_max_hours = %s, release_at_risk_allowed = %s WHERE id = %s",
                 mn, mx, risk, items[code])
    for code, mid in machines.items():
        dirty, clean = HOLDS.get(code, (D(24), D(72)))
        tx.x("UPDATE resources SET dirty_hold_hours = %s, clean_hold_hours = %s WHERE id = %s AND type = 'machine'", dirty, clean, mid)
    return {"changeovers": tx.val("SELECT count(*) FROM changeover_rules WHERE site_id = %s::uuid", site_id),
            "campaigns": tx.val("SELECT count(*) FROM campaign_rules WHERE site_id = %s::uuid", site_id)}


@endpoint(auth="tenant_admin")
def load_sample_rules(call: Call):
    site_id = call.path["site_id"]
    if not call.tx.val("SELECT 1 FROM sites WHERE id = %s::uuid", site_id):
        raise ApiError(404, "not_found", "Site was not found.")
    out = apply_sample_rules(call, site_id)
    call.tx.event("SAMPLE_DATA", "changeover_rules", None, "Sample planning rules", out)
    return {"ok": True, **out}


def _uuid(call: Call, sql: str, *args):
    return str(call.tx.val(sql, *args))


@endpoint(auth="tenant_admin")
def load_sample(call: Call):
    tx, tenant = call.tx, call.tenant_id
    if tx.val("SELECT count(*) FROM items"):
        raise ApiError(409, "not_empty", "Sample data can only be loaded into a company with no items yet.")
    tx.x("SELECT cp_seed_uoms(%s::uuid)", tenant)
    uom = {r["code"]: str(r["id"]) for r in tx.q("SELECT id, code FROM uoms")}

    # Site: use the first active site, or create one.
    site = tx.one("SELECT id, country FROM sites WHERE active ORDER BY created_at LIMIT 1")
    if not site:
        site = tx.one("INSERT INTO sites (tenant_id, code, name, address) VALUES (%s, 'OCT-1', '6th of October plant',"
                      " 'Industrial Zone 3, 6th of October City') RETURNING id, country", tenant)
    site_id = str(site["id"])

    markets = {}
    for code, en, ar, cur in MARKETS:
        markets[code] = _uuid(call, "INSERT INTO markets (tenant_id, code, name_en, name_ar, currency) VALUES (%s, %s, %s, %s, %s)"
                                    " RETURNING id", tenant, code, en, ar, cur)

    items = {}
    for code, en, ar, typ, stock, extra in ITEMS:
        extra = dict(extra)
        disp = extra.pop("dispensing", None)
        cols = ["tenant_id", "code", "name_en", "name_ar", "type", "stock_uom_id", "dispensing_uom_id"] + list(extra)
        vals = [tenant, code, en, ar, typ, uom[stock], uom[disp] if disp else None] + list(extra.values())
        items[code] = _uuid(call, f"INSERT INTO items ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING id", *vals)

    for code, u, f in CONVERSIONS:
        tx.x("INSERT INTO item_uom_conversions (tenant_id, item_id, uom_id, factor) VALUES (%s, %s, %s, %s)",
             tenant, items[code], uom[u], f)

    today = tx.val("SELECT current_date")
    for code, size, bu, yld, mode, minp, lines in BOMS:
        bom_id = _uuid(call, "INSERT INTO boms (tenant_id, item_id, version, batch_size, batch_uom_id, yield_pct, batch_mode, min_batch_pct)"
                             " VALUES (%s, %s, 1, %s, %s, %s, %s, %s) RETURNING id", tenant, items[code], size, uom[bu], yld, mode, minp)
        for n, (comp, qty, lu, assay, over, compensating) in enumerate(lines, start=1):
            tx.x("INSERT INTO bom_lines (tenant_id, bom_id, line_no, component_item_id, quantity, uom_id, assay_compensated,"
                 " overage_pct, is_compensating) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                 tenant, bom_id, n, items[comp], qty, uom[lu], assay, over, compensating)
        tx.x("UPDATE boms SET status = 'active', valid_from = %s WHERE id = %s", dt.date(today.year, 1, 1), bom_id)

    for code, mk, max_qty, shelf in ITEM_MARKETS:
        tx.x("INSERT INTO item_markets (tenant_id, item_id, market_id, max_sellable_per_month, min_remaining_shelf_pct)"
             " VALUES (%s, %s, %s, %s, %s)", tenant, items[code], markets[mk], max_qty, shelf)
    currency = {c: cur for c, _e, _a, cur in MARKETS}
    for code, mk, price, start, end in PRICES:
        tx.x("INSERT INTO prices (tenant_id, item_id, market_id, price, currency, valid_from, valid_to) VALUES (%s, %s, %s, %s, %s, %s, %s)",
             tenant, items[code], markets[mk], price, currency[mk], dt.date.fromisoformat(start),
             dt.date.fromisoformat(end) if end else None)

    machines = {}
    for code, en, ar, area, eff in MACHINES:
        machines[code] = _uuid(call, "INSERT INTO resources (tenant_id, site_id, code, name_en, name_ar, type, area, efficiency_pct)"
                                     " VALUES (%s, %s, %s, %s, %s, 'machine', %s, %s) RETURNING id", tenant, site_id, code, en, ar, area, eff)
    for code, en, ar, area in QC_RESOURCES:
        machines[code] = _uuid(call, "INSERT INTO resources (tenant_id, site_id, code, name_en, name_ar, type, area)"
                                     " VALUES (%s, %s, %s, %s, %s, 'qc_lab', %s) RETURNING id", tenant, site_id, code, en, ar, area)

    for item_code, steps in ROUTINGS.items():
        rt = _uuid(call, "INSERT INTO routings (tenant_id, site_id, item_id) VALUES (%s, %s, %s) RETURNING id", tenant, site_id, items[item_code])
        for seq, (name, model, value, setup, res) in enumerate(steps, start=1):
            step = _uuid(call, "INSERT INTO routing_steps (tenant_id, routing_id, seq, name, time_model, fixed_minutes, rate_per_hour, setup_minutes)"
                               " VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id", tenant, rt, seq, name, model,
                         value if model == "fixed" else None, value if model == "rate" else None, setup)
            for mcode, pref, own in res:
                tx.x("INSERT INTO routing_step_resources (tenant_id, step_id, resource_id, preferred, fixed_minutes, rate_per_hour)"
                     " VALUES (%s, %s, %s, %s, %s, %s)", tenant, step, machines[mcode], pref,
                     own if model == "fixed" else None, own if model == "rate" else None)

    # Calendar: Saturday to Thursday, two 8-hour shifts; Friday off. Ramadan: shorter shifts.
    for weekday in (6, 7, 1, 2, 3, 4):
        for name, s, e in (("Morning", "07:00", "15:00"), ("Evening", "15:00", "23:00")):
            tx.x("INSERT INTO shifts (tenant_id, site_id, weekday, name, start_time, end_time) VALUES (%s, %s, %s, %s, %s, %s)",
                 tenant, site_id, weekday, name, s, e)
    for year, start, end in ((2026, "2026-02-18", "2026-03-19"), (2027, "2027-02-08", "2027-03-09")):
        pid = _uuid(call, "INSERT INTO calendar_periods (tenant_id, site_id, name, start_date, end_date) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                    tenant, site_id, f"Ramadan {year} (estimated)", dt.date.fromisoformat(start), dt.date.fromisoformat(end))
        for weekday in (6, 7, 1, 2, 3, 4):
            for name, s, e in (("Day", "09:00", "15:00"), ("Night", "20:00", "02:00")):
                tx.x("INSERT INTO shifts (tenant_id, site_id, period_id, weekday, name, start_time, end_time) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                     tenant, site_id, pid, weekday, name, s, e)
    for year in (today.year, today.year + 1):
        for h in builtin_holidays((site["country"] or "EG").strip().upper(), year):
            tx.x("INSERT INTO holidays (tenant_id, site_id, date, name, source, estimated, confirmed) VALUES (%s, %s, %s, %s, 'imported', %s, %s)"
                 " ON CONFLICT (site_id, date) DO NOTHING", tenant, site_id, h["date"], h["name"], h["estimated"], not h["estimated"])

    # Planned downtime next week.
    monday = today + dt.timedelta(days=(7 - today.weekday()))
    tx.x("INSERT INTO resource_exceptions (tenant_id, site_id, resource_id, starts_at, ends_at, reason, notes)"
         " VALUES (%s, %s, %s, %s, %s, 'maintenance', 'Preventive maintenance: punches and turret')",
         tenant, site_id, machines["TP-02"], dt.datetime.combine(monday, dt.time(7, 0), dt.timezone.utc),
         dt.datetime.combine(monday + dt.timedelta(days=1), dt.time(23, 0), dt.timezone.utc))
    tx.x("INSERT INTO resource_exceptions (tenant_id, site_id, resource_id, starts_at, ends_at, reason, notes)"
         " VALUES (%s, %s, %s, %s, %s, 'calibration', 'Sealing temperature and checkweigher calibration')",
         tenant, site_id, machines["BLS-01"], dt.datetime.combine(monday + dt.timedelta(days=2), dt.time(7, 0), dt.timezone.utc),
         dt.datetime.combine(monday + dt.timedelta(days=2), dt.time(13, 0), dt.timezone.utc))

    apply_sample_rules(call, site_id)
    tx.event("SAMPLE_DATA", "items", None, "Pharmaceutical sample dataset",
             {"items": len(items), "boms": len(BOMS), "machines": len(machines)})
    return {"ok": True, "site_id": site_id, "items": len(items), "boms": len(BOMS), "machines": len(machines),
            "markets": len(markets)}
