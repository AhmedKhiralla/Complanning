"""Working time per machine: site shifts (with special periods such as Ramadan), confirmed holidays
and planned downtime, as sorted UTC intervals. Times inside the engine are naive UTC datetimes."""
from __future__ import annotations

import bisect
import datetime as dt
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc


def to_naive_utc(t: dt.datetime) -> dt.datetime:
    return t.astimezone(UTC).replace(tzinfo=None) if t.tzinfo else t


class WorkCalendar:
    """Sorted, non-overlapping working intervals with fast 'add working minutes' arithmetic."""

    def __init__(self, intervals: list[tuple[dt.datetime, dt.datetime]]):
        merged: list[list[dt.datetime]] = []
        for s, e in sorted(intervals):
            if e <= s:
                continue
            if merged and s <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        self.starts = [m[0] for m in merged]
        self.ends = [m[1] for m in merged]

    def _idx(self, t: dt.datetime) -> int:
        """Index of the first interval that ends after t."""
        return bisect.bisect_right(self.ends, t)

    def next_work(self, t: dt.datetime) -> dt.datetime | None:
        i = self._idx(t)
        if i >= len(self.starts):
            return None
        return max(t, self.starts[i])

    def add_work(self, t: dt.datetime, minutes: float) -> dt.datetime | None:
        """End time after working `minutes` from t; work pauses outside working time.
        None when the calendar runs out."""
        if minutes <= 0:
            return t
        need = dt.timedelta(minutes=minutes)
        i = self._idx(t)
        while i < len(self.starts):
            s = max(t, self.starts[i])
            room = self.ends[i] - s
            if room >= need:
                return s + need
            need -= room
            i += 1
        return None

    def fit(self, t: dt.datetime, minutes: float) -> dt.datetime | None:
        """Earliest start at or after t where `minutes` fit inside one block of working time without a pause."""
        need = dt.timedelta(minutes=max(minutes, 0))
        i = self._idx(t)
        while i < len(self.starts):
            s = max(t, self.starts[i])
            if self.ends[i] - s >= need:
                return s
            i += 1
        return None

    def longest(self) -> float:
        """Longest block of working time, in minutes."""
        return max(((e - s).total_seconds() / 60 for s, e in zip(self.starts, self.ends)), default=0.0)

    def work_minutes(self, a: dt.datetime, b: dt.datetime) -> float:
        """Working minutes between a and b."""
        if b <= a:
            return 0.0
        total = dt.timedelta()
        i = self._idx(a)
        while i < len(self.starts) and self.starts[i] < b:
            s, e = max(a, self.starts[i]), min(b, self.ends[i])
            if e > s:
                total += e - s
            i += 1
        return total.total_seconds() / 60

    def minus(self, blocks: list[tuple[dt.datetime, dt.datetime]]) -> "WorkCalendar":
        """A copy with the given periods removed (downtime)."""
        if not blocks:
            return self
        out = []
        blocks = sorted(blocks)
        for s, e in zip(self.starts, self.ends):
            cur = s
            for bs, be in blocks:
                if be <= cur or bs >= e:
                    continue
                if bs > cur:
                    out.append((cur, bs))
                cur = max(cur, be)
                if cur >= e:
                    break
            if cur < e:
                out.append((cur, e))
        return WorkCalendar(out)


def site_calendar(tx, site_id: str, tz_name: str, first: dt.date, last: dt.date) -> tuple[WorkCalendar, bool]:
    """Working intervals for the site from `first` to `last` (local dates). Returns (calendar, has_shifts).
    A site without any shifts is treated as working around the clock."""
    try:
        tz = ZoneInfo(tz_name or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    periods = tx.q("SELECT id, start_date, end_date FROM calendar_periods WHERE site_id = %s::uuid", site_id)
    shifts = tx.q("SELECT period_id, weekday, start_time, end_time FROM shifts WHERE site_id = %s::uuid", site_id)
    holidays = {r["date"] for r in tx.q("SELECT date FROM holidays WHERE site_id = %s::uuid AND confirmed AND date BETWEEN %s AND %s",
                                         site_id, first - dt.timedelta(days=1), last)}
    if not shifts:
        start = dt.datetime.combine(first, dt.time(0), tz)
        end = dt.datetime.combine(last + dt.timedelta(days=1), dt.time(0), tz)
        return WorkCalendar([(to_naive_utc(start), to_naive_utc(end))]), False
    with_shifts = {s["period_id"] for s in shifts}
    by_key: dict[tuple, list] = {}
    for s in shifts:
        by_key.setdefault((s["period_id"], s["weekday"]), []).append(s)
    out = []
    d = first - dt.timedelta(days=1)          # a night shift from the day before can reach into `first`
    while d <= last:
        if d not in holidays:
            period = next((p for p in periods if p["start_date"] <= d <= p["end_date"]), None)
            pid = period["id"] if period and period["id"] in with_shifts else None
            for s in by_key.get((pid, d.isoweekday()), []):
                a = dt.datetime.combine(d, s["start_time"], tz)
                end_day = d if s["end_time"] > s["start_time"] else d + dt.timedelta(days=1)
                b = dt.datetime.combine(end_day, s["end_time"], tz)
                out.append((to_naive_utc(a), to_naive_utc(b)))
        d += dt.timedelta(days=1)
    return WorkCalendar(out), True
