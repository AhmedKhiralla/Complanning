"""Unit conversion: same dimension by factor, mass <-> volume by item density,
count units by item-specific pack conversions."""
from __future__ import annotations

from decimal import Decimal

from .api import ApiError


class UnitBook:
    """Loads units and item conversions once per request."""

    def __init__(self, tx):
        self.tx = tx
        self.uoms = {str(u["id"]): u for u in tx.q("SELECT id, code, dimension, factor_to_base FROM uoms")}
        self._items: dict[str, dict] = {}

    def item(self, item_id: str) -> dict:
        key = str(item_id)
        if key not in self._items:
            it = self.tx.one("SELECT id, code, stock_uom_id, density_kg_per_l FROM items WHERE id = %s::uuid", key)
            if not it:
                raise ApiError(404, "not_found", "Item was not found.")
            it["packs"] = {str(r["uom_id"]): Decimal(r["factor"]) for r in self.tx.q(
                "SELECT uom_id, factor FROM item_uom_conversions WHERE item_id = %s::uuid", key)}
            self._items[key] = it
        return self._items[key]

    def to_stock(self, item_id: str, qty: Decimal, uom_id: str) -> Decimal:
        it = self.item(item_id)
        return self.convert(it, Decimal(qty), str(uom_id), str(it["stock_uom_id"]))

    def convert(self, it: dict, qty: Decimal, from_id: str, to_id: str) -> Decimal:
        """Convert via the item's stock unit: pack conversions first, then physical units."""
        if from_id == to_id:
            return qty
        stock = str(it["stock_uom_id"])
        if from_id == stock:
            in_stock = qty
        elif from_id in it["packs"]:
            in_stock = qty * it["packs"][from_id]
        else:
            in_stock = self._physical(it, qty, from_id, stock)
        if to_id == stock:
            return in_stock
        if to_id in it["packs"]:
            return in_stock / it["packs"][to_id]
        return self._physical(it, in_stock, stock, to_id)

    def _physical(self, it: dict, qty: Decimal, from_id: str, to_id: str) -> Decimal:
        f, t = self.uoms.get(from_id), self.uoms.get(to_id)
        if not f or not t:
            raise ApiError(422, "invalid_unit", "Unknown unit of measure.")
        if from_id == to_id:
            return qty
        if "count" in (f["dimension"], t["dimension"]) and f["dimension"] != t["dimension"] or \
                (f["dimension"] == "count" and t["dimension"] == "count"):
            raise ApiError(422, "no_conversion",
                           f"Item {it['code']} has no conversion from {f['code']} to {t['code']}. Add it under the item's unit conversions.")
        base = qty * Decimal(f["factor_to_base"])
        if f["dimension"] == t["dimension"]:
            return base / Decimal(t["factor_to_base"])
        if {f["dimension"], t["dimension"]} == {"mass", "volume"}:
            dens = it.get("density_kg_per_l")
            if not dens:
                raise ApiError(422, "no_density",
                               f"Item {it['code']} needs a density (kg/L) to convert between {f['code']} and {t['code']}.")
            dens = Decimal(dens)
            return (base / dens if f["dimension"] == "mass" else base * dens) / Decimal(t["factor_to_base"])
        raise ApiError(422, "no_conversion", f"Cannot convert {f['code']} to {t['code']}.")
