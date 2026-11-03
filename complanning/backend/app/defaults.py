"""Default feature toggles and terminology for new companies."""

# Feature toggles, grouped for the settings screen. Pharma-specific features can
# be switched off for other industries.
FEATURES: dict[str, dict] = {
    # Materials and stock
    "lot_stock":             {"group": "materials", "pharma": True, "general": False},
    "assay_compensation":    {"group": "materials", "pharma": True, "general": False},
    "overage":               {"group": "materials", "pharma": True, "general": False},
    "compensating_material": {"group": "materials", "pharma": True, "general": False},
    "use_stock_wip":         {"group": "materials", "pharma": True, "general": True},
    "use_stock_semi":        {"group": "materials", "pharma": True, "general": True},
    "use_stock_fg":          {"group": "materials", "pharma": True, "general": True},
    # Quality
    "qc_lead_times":         {"group": "quality", "pharma": True, "general": False},
    "release_at_risk":       {"group": "quality", "pharma": True, "general": False},
    "cleaning_verification": {"group": "quality", "pharma": True, "general": False},
    "equipment_hold_times":  {"group": "quality", "pharma": True, "general": False},
    # Production
    "holding_times":         {"group": "production", "pharma": True, "general": True},
    "campaign_limits":       {"group": "production", "pharma": True, "general": True},
    "sales_plan":            {"group": "production", "pharma": True, "general": True},
    "holiday_import":        {"group": "production", "pharma": True, "general": True},
    # Costs
    "costs":                 {"group": "costs", "pharma": False, "general": False},
}


def feature_preset(preset: str) -> dict[str, bool]:
    key = "general" if preset == "general" else "pharma"
    return {name: meta[key] for name, meta in FEATURES.items()}


def effective_features(stored: dict | None) -> dict[str, bool]:
    base = feature_preset("pharma")
    for k, v in (stored or {}).items():
        if k in base and isinstance(v, bool):
            base[k] = v
    return base


# Renamable terms. Each company can change the words used across the app.
TERMS: dict[str, dict[str, str]] = {
    "batch":            {"en": "Batch", "ar": "تشغيلة"},
    "wip":              {"en": "Work in process", "ar": "منتج تحت التشغيل"},
    "semi_finished":    {"en": "Semi-finished product", "ar": "منتج نصف مصنع"},
    "finished_product": {"en": "Finished product", "ar": "منتج تام"},
    "qc_release":       {"en": "QC release", "ar": "إفراج الجودة"},
    "campaign":         {"en": "Campaign", "ar": "حملة إنتاج"},
    "machine":          {"en": "Machine", "ar": "ماكينة"},
}


def effective_terms(stored: dict | None) -> dict[str, dict[str, str]]:
    out = {k: dict(v) for k, v in TERMS.items()}
    for key, langs in (stored or {}).items():
        if key in out and isinstance(langs, dict):
            for lang in ("en", "ar"):
                val = langs.get(lang)
                if isinstance(val, str) and val.strip():
                    out[key][lang] = val.strip()[:60]
    return out
