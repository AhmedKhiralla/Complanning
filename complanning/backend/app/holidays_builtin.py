"""Built-in national holidays, used when the online holiday service has no data for a country.

Dates of Islamic holidays depend on the moon sighting and are announced late, and Egypt often
moves holidays to a Thursday or Sunday. They are therefore marked as estimates: they arrive
in the calendar as proposals for the planner to confirm or move.
"""
import datetime as dt

D = dt.date

_EG_FIXED = [
    (1, 7, "Coptic Christmas", "عيد الميلاد المجيد"),
    (1, 25, "Revolution Day and Police Day", "عيد ثورة 25 يناير وعيد الشرطة"),
    (4, 25, "Sinai Liberation Day", "عيد تحرير سيناء"),
    (5, 1, "Labour Day", "عيد العمال"),
    (6, 30, "June 30 Revolution Day", "ذكرى ثورة 30 يونيو"),
    (7, 23, "Revolution Day", "عيد ثورة 23 يوليو"),
    (10, 6, "Armed Forces Day", "عيد القوات المسلحة"),
]

# Estimates: Islamic calendar dates and Sham El-Nessim (Monday after Orthodox Easter).
_EG_MOVABLE = {
    2026: [
        (D(2026, 3, 20), "Eid al-Fitr (day 1)"), (D(2026, 3, 21), "Eid al-Fitr (day 2)"), (D(2026, 3, 22), "Eid al-Fitr (day 3)"),
        (D(2026, 4, 13), "Sham El-Nessim"),
        (D(2026, 5, 26), "Arafat Day"), (D(2026, 5, 27), "Eid al-Adha (day 1)"), (D(2026, 5, 28), "Eid al-Adha (day 2)"),
        (D(2026, 5, 29), "Eid al-Adha (day 3)"),
        (D(2026, 6, 16), "Islamic New Year"),
        (D(2026, 8, 25), "Prophet's Birthday"),
    ],
    2027: [
        (D(2027, 3, 9), "Eid al-Fitr (day 1)"), (D(2027, 3, 10), "Eid al-Fitr (day 2)"), (D(2027, 3, 11), "Eid al-Fitr (day 3)"),
        (D(2027, 5, 3), "Sham El-Nessim"),
        (D(2027, 5, 15), "Arafat Day"), (D(2027, 5, 16), "Eid al-Adha (day 1)"), (D(2027, 5, 17), "Eid al-Adha (day 2)"),
        (D(2027, 5, 18), "Eid al-Adha (day 3)"),
        (D(2027, 6, 6), "Islamic New Year"),
        (D(2027, 8, 14), "Prophet's Birthday"),
    ],
}


def builtin_holidays(country: str, year: int) -> list[dict]:
    if country != "EG":
        return []
    out = [{"date": D(year, m, d), "name": en, "estimated": False} for m, d, en, _ar in _EG_FIXED]
    out += [{"date": day, "name": name, "estimated": True} for day, name in _EG_MOVABLE.get(year, [])]
    return sorted(out, key=lambda h: h["date"])
