import { useEffect, useMemo, useState } from "react";
import { LuCalendarPlus, LuChevronLeft, LuChevronRight, LuCopy, LuDownload, LuPlus, LuTrash2, LuX } from "react-icons/lu";
import { Badge, Button, Confirm, LoadError, Notice, PageHead, TextField, errorText, fieldErrors, useLoad, useToast } from "../../components/ui";
import { ReadOnlyNote } from "../../components/master";
import { del, get, patch, post, put, qs } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { usePerms } from "../../lib/session";
import type { CalendarData, Holiday, Period, Shift } from "../../lib/types";

const WEEK_SAT = ["SA", "EG", "AE", "KW", "QA", "BH", "OM", "JO", "IQ", "SY", "LY", "SD", "YE", "DZ"];
interface DayHours { date: string; hours: number; holiday: string | null; holiday_confirmed: boolean; period: string | null; }
type EditShift = { key: string; weekday: number; name: string; start_time: string; end_time: string };
let k = 0;

const hoursOf = (s: string, e: string) => {
  const [sh, sm] = s.split(":").map(Number), [eh, em] = e.split(":").map(Number);
  let a = sh * 60 + sm, b = eh * 60 + em;
  if (b <= a) b += 1440;
  return (b - a) / 60;
};

function ShiftEditor({ siteId, period, shifts, order, canEdit, onSaved }: {
  siteId: string; period: Period | null; shifts: Shift[]; order: number[]; canEdit: boolean; onSaved: (d: CalendarData) => void;
}) {
  const { t, qty } = useI18n();
  const toast = useToast();
  const days = t("calendar.weekdaysLong").split(",");
  const initial = () => shifts.filter((s) => s.period_id === (period?.id ?? null))
    .map((s) => ({ key: `s${++k}`, weekday: s.weekday, name: s.name, start_time: s.start_time, end_time: s.end_time }));
  const [rows, setRows] = useState<EditShift[]>(initial);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setRows(initial()); }, [shifts, period?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (key: string, p: Partial<EditShift>) => setRows((r) => r.map((x) => (x.key === key ? { ...x, ...p } : x)));
  const copyFrom = (day: number) => {
    const src = rows.filter((r) => r.weekday === day);
    const workDays = Array.from(new Set(rows.map((r) => r.weekday))).filter((d) => d !== day);
    setRows([...rows.filter((r) => !workDays.includes(r.weekday)),
      ...workDays.flatMap((d) => src.map((s) => ({ ...s, key: `s${++k}`, weekday: d })))]);
  };
  const save = async () => {
    setBusy(true); setErr(null);
    try {
      const d = await put<CalendarData>(`/api/sites/${siteId}/calendar/shifts`, { period_id: period?.id ?? null,
        shifts: rows.map(({ weekday, name, start_time, end_time }) => ({ weekday, name: name || "Shift", start_time, end_time })) });
      onSaved(d); toast(t("calendar.savedToast"));
    } catch (e) { setErr(errorText(e, t)); } finally { setBusy(false); }
  };
  return (
    <div className="stack" style={{ gap: 0 }}>
      {err && <div className="panel-body"><Notice tone="danger">{err}</Notice></div>}
      {order.map((day) => {
        const list = rows.filter((r) => r.weekday === day);
        const total = list.reduce((a, s) => a + hoursOf(s.start_time, s.end_time), 0);
        return (
          <div className={`week-row ${list.length ? "" : "off"}`} key={day}>
            <div className="week-day"><strong>{days[day - 1]}</strong><span className="small muted num">{list.length ? t("calendar.hours", { h: qty(total, 1) }) : t("calendar.dayOff")}</span></div>
            <div className="week-shifts">
              {list.map((s) => (
                <div className="shift-chip" key={s.key}>
                  <input className="input sname" value={s.name} disabled={!canEdit} aria-label={t("calendar.shift")} maxLength={40} onChange={(e) => set(s.key, { name: e.target.value })} />
                  <input className="input num" type="time" value={s.start_time} disabled={!canEdit} aria-label={t("calendar.start")} onChange={(e) => set(s.key, { start_time: e.target.value })} />
                  <span className="subtle" aria-hidden>–</span>
                  <input className="input num" type="time" value={s.end_time} disabled={!canEdit} aria-label={t("calendar.end")} onChange={(e) => set(s.key, { end_time: e.target.value })} />
                  {s.end_time <= s.start_time && <span className="small subtle">{t("calendar.overnight")}</span>}
                  {canEdit && <button type="button" className="icon-btn" aria-label={t("common.remove")} onClick={() => setRows(rows.filter((x) => x.key !== s.key))}><LuX /></button>}
                </div>
              ))}
              {canEdit && <div className="row">
                <Button size="sm" variant="ghost" icon={<LuPlus />} onClick={() => setRows([...rows, { key: `s${++k}`, weekday: day, name: list.length ? "Evening" : "Morning", start_time: list.length ? "15:00" : "07:00", end_time: list.length ? "23:00" : "15:00" }])}>{t("calendar.addShift")}</Button>
                {list.length > 0 && <Button size="sm" variant="ghost" icon={<LuCopy />} onClick={() => copyFrom(day)}>{t("calendar.copyDay")}</Button>}
              </div>}
            </div>
          </div>
        );
      })}
      {canEdit && <div className="panel-body"><Button variant="primary" size="sm" busy={busy} onClick={save}>{t("calendar.saveShifts")}</Button></div>}
    </div>
  );
}

export function CalendarPage() {
  const { t, qty, date, lang } = useI18n();
  const toast = useToast();
  const { siteId, site, editSite } = usePerms();
  const canEdit = editSite(siteId);
  const today = new Date();
  const [month, setMonth] = useState(`${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`);
  const [year, setYear] = useState(today.getFullYear());
  const cal = useLoad(() => (siteId ? get<CalendarData>(`/api/sites/${siteId}/calendar${qs({ year })}`) : Promise.resolve(null)), [siteId, year]);
  const hours = useLoad(() => (siteId ? get<{ days: DayHours[]; total_hours: number }>(`/api/sites/${siteId}/calendar/hours${qs({ month })}`) : Promise.resolve(null)),
    [siteId, month, cal.data]);
  const [patternFor, setPatternFor] = useState<string | null>(null);
  const [newPeriod, setNewPeriod] = useState<{ name: string; start_date: string; end_date: string } | null>(null);
  const [newDay, setNewDay] = useState<{ date: string; name: string } | null>(null);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const [removePeriod, setRemovePeriod] = useState<Period | null>(null);
  const [removeDay, setRemoveDay] = useState<Holiday | null>(null);
  const [importing, setImporting] = useState(false);

  const weekStartsSat = WEEK_SAT.includes(site?.country ?? "EG");
  const order = weekStartsSat ? [6, 7, 1, 2, 3, 4, 5] : [1, 2, 3, 4, 5, 6, 7];
  const short = t("calendar.weekdays").split(",");
  const monthLabel = useMemo(() => new Intl.DateTimeFormat(lang === "ar" ? "ar-EG-u-nu-latn" : "en-GB", { month: "long", year: "numeric" })
    .format(new Date(`${month}-01T12:00:00`)), [month, lang]);
  const shiftMonth = (delta: number) => {
    const d = new Date(`${month}-01T12:00:00`); d.setMonth(d.getMonth() + delta);
    const m = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    setMonth(m); if (d.getFullYear() !== year) setYear(d.getFullYear());
  };

  if (!siteId) return <><PageHead title={t("calendar.title")} /><Notice>{t("common.noSite")}</Notice></>;
  const c = cal.data;
  const maxH = Math.max(16, ...(hours.data?.days.map((d) => d.hours) ?? [0]));
  const firstIso = hours.data ? new Date(`${hours.data.days[0].date}T12:00:00`).getDay() : 1;  // 0 Sunday
  const firstIsoWeekday = firstIso === 0 ? 7 : firstIso;
  const lead = order.indexOf(firstIsoWeekday);
  const period = c?.periods.find((p) => p.id === patternFor) ?? null;
  const fail = (e: unknown) => { setErrs(fieldErrors(e)); setGeneral(errorText(e, t)); };

  return (
    <>
      <PageHead title={t("calendar.title")} lead={t("calendar.lead", { site: site?.name ?? "" })} />
      <ReadOnlyNote show={!canEdit} />
      {general && <div style={{ marginBottom: 12 }}><Notice tone="danger">{general}</Notice></div>}

      <section className="panel" aria-labelledby="cal-h">
        <div className="panel-head">
          <h2 id="cal-h">{t("calendar.month")}</h2>
          <div className="row">
            <Button size="sm" variant="ghost" iconOnly aria-label={t("calendar.prev")} icon={<LuChevronLeft className="flip-rtl" />} onClick={() => shiftMonth(-1)} />
            <strong className="month-label">{monthLabel}</strong>
            <Button size="sm" variant="ghost" iconOnly aria-label={t("calendar.next")} icon={<LuChevronRight className="flip-rtl" />} onClick={() => shiftMonth(1)} />
          </div>
          <span className="spacer" />
          {hours.data && <span className="small muted num">{t("calendar.total", { h: qty(hours.data.total_hours, 1) })}</span>}
        </div>
        {hours.error ? <LoadError error={hours.error} onRetry={hours.reload} /> : (
          <div className="month-grid" role="grid" aria-label={monthLabel}>
            {order.map((d) => <div key={d} className="mg-head" role="columnheader">{short[d - 1]}</div>)}
            {hours.data && Array.from({ length: lead }).map((_, i) => <div key={`b${i}`} className="mg-blank" />)}
            {hours.data?.days.map((d) => {
              const level = d.hours === 0 ? 0 : Math.max(1, Math.round((d.hours / maxH) * 4));
              const isToday = d.date === today.toISOString().slice(0, 10);
              return (
                <div key={d.date} role="gridcell" className={`mg-day lvl-${level} ${isToday ? "today" : ""} ${d.holiday ? (d.holiday_confirmed ? "hol" : "hol-proposed") : ""}`}
                  title={[d.holiday, d.period].filter(Boolean).join(" · ") || undefined}>
                  <span className="mg-date num">{Number(d.date.slice(8))}</span>
                  <span className="mg-hours num">{d.hours ? t("calendar.hours", { h: qty(d.hours, 1) }) : d.holiday ? "" : "—"}</span>
                  {d.holiday && <span className="mg-note">{d.holiday}{!d.holiday_confirmed && ` · ${t("calendar.proposed")}`}</span>}
                  {!d.holiday && d.period && <span className="mg-note period">{d.period}</span>}
                </div>
              );
            })}
          </div>
        )}
      </section>

      {cal.error ? <div className="panel" style={{ marginTop: 16 }}><LoadError error={cal.error} onRetry={cal.reload} /></div> : c && (
        <div className="cal-grid">
          <section className="panel" aria-labelledby="wk-h">
            <div className="panel-head">
              <div><h2 id="wk-h">{period ? t("calendar.periodPattern", { name: period.name }) : t("calendar.weekly")}</h2>
                <p className="small muted">{period ? t("calendar.periodLead", { from: date(period.start_date), to: date(period.end_date) }) : t("calendar.weeklyLead")}</p></div>
              <span className="spacer" />
              {period && <Button size="sm" onClick={() => setPatternFor(null)}>{t("calendar.weekly")}</Button>}
            </div>
            <ShiftEditor key={period?.id ?? "default"} siteId={siteId} period={period} shifts={c.shifts} order={order} canEdit={canEdit} onSaved={(d) => cal.setData(d)} />
          </section>

          <div className="stack">
            <section className="panel" aria-labelledby="per-h">
              <div className="panel-head">
                <div><h2 id="per-h">{t("calendar.periods")}</h2><p className="small muted">{t("calendar.periodsLead")}</p></div>
                <span className="spacer" />
                {canEdit && !newPeriod && <Button size="sm" icon={<LuPlus />} onClick={() => setNewPeriod({ name: "", start_date: "", end_date: "" })}>{t("calendar.newPeriod")}</Button>}
              </div>
              {newPeriod && (
                <div className="panel-body stack" style={{ borderBottom: "1px solid var(--line)" }}>
                  <TextField label={t("calendar.periodName")} value={newPeriod.name} onChange={(v) => setNewPeriod({ ...newPeriod, name: v })} error={errs.name} />
                  <div className="grid-2">
                    <TextField label={t("calendar.from")} type="date" value={newPeriod.start_date} onChange={(v) => setNewPeriod({ ...newPeriod, start_date: v })} error={errs.start_date} />
                    <TextField label={t("calendar.to")} type="date" value={newPeriod.end_date} onChange={(v) => setNewPeriod({ ...newPeriod, end_date: v })} error={errs.end_date} />
                  </div>
                  <div className="row">
                    <Button size="sm" variant="primary" disabled={!newPeriod.name || !newPeriod.start_date || !newPeriod.end_date} onClick={async () => {
                      setErrs({}); setGeneral(null);
                      try { const d = await post<CalendarData>(`/api/sites/${siteId}/calendar/periods`, newPeriod); setNewPeriod(null); setYear(Number(newPeriod.start_date.slice(0, 4))); cal.setData(d); }
                      catch (e) { fail(e); }
                    }}>{t("common.create")}</Button>
                    <Button size="sm" onClick={() => setNewPeriod(null)}>{t("common.cancel")}</Button>
                  </div>
                </div>
              )}
              {c.periods.length === 0 ? <div className="panel-body small subtle">{t("calendar.noPeriods")}</div> : (
                <ul className="plain-list">
                  {c.periods.map((p) => {
                    const n = c.shifts.filter((s) => s.period_id === p.id).length;
                    return (
                      <li key={p.id} className={patternFor === p.id ? "selected" : ""}>
                        <div><strong>{p.name}</strong><div className="small muted num">{date(p.start_date)} – {date(p.end_date)} · {n} × {t("calendar.shift").toLowerCase()}</div></div>
                        <div className="row">
                          <Button size="sm" onClick={() => setPatternFor(p.id)}>{t("calendar.editPattern")}</Button>
                          {canEdit && <Button size="sm" variant="ghost" iconOnly aria-label={t("common.remove")} icon={<LuTrash2 />} onClick={() => setRemovePeriod(p)} />}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>

            <section className="panel" aria-labelledby="hol-h">
              <div className="panel-head">
                <div><h2 id="hol-h">{t("calendar.holidays", { year })}</h2><p className="small muted">{t("calendar.holidaysLead")}</p></div>
              </div>
              <div className="panel-body row wrap" style={{ borderBottom: "1px solid var(--line)" }}>
                <div className="row">
                  <Button size="sm" variant="ghost" iconOnly aria-label={t("calendar.prev")} icon={<LuChevronLeft className="flip-rtl" />} onClick={() => setYear(year - 1)} />
                  <strong className="num">{year}</strong>
                  <Button size="sm" variant="ghost" iconOnly aria-label={t("calendar.next")} icon={<LuChevronRight className="flip-rtl" />} onClick={() => setYear(year + 1)} />
                </div>
                <span className="spacer" />
                {canEdit && <>
                  <Button size="sm" icon={<LuDownload />} busy={importing} onClick={async () => {
                    setImporting(true); setGeneral(null);
                    try { const d = await post<CalendarData>(`/api/sites/${siteId}/holidays/import`, { year }); cal.setData(d);
                      toast(d.imported?.added ? t("calendar.importDone", { n: d.imported.added }) : t("calendar.importNone")); }
                    catch (e) { fail(e); } finally { setImporting(false); }
                  }}>{t("calendar.import")}</Button>
                  <Button size="sm" icon={<LuCalendarPlus />} onClick={() => setNewDay({ date: `${year}-01-01`, name: "" })}>{t("calendar.addDayOff")}</Button>
                </>}
              </div>
              {newDay && (
                <div className="panel-body stack" style={{ borderBottom: "1px solid var(--line)" }}>
                  <div className="grid-2">
                    <TextField label={t("calendar.date")} type="date" value={newDay.date} onChange={(v) => setNewDay({ ...newDay, date: v })} error={errs.date} />
                    <TextField label={t("calendar.name")} value={newDay.name} onChange={(v) => setNewDay({ ...newDay, name: v })} />
                  </div>
                  <div className="row">
                    <Button size="sm" variant="primary" disabled={!newDay.date || !newDay.name} onClick={async () => {
                      setErrs({}); setGeneral(null);
                      try { const d = await post<CalendarData>(`/api/sites/${siteId}/holidays`, newDay); setNewDay(null); cal.setData(d); }
                      catch (e) { fail(e); }
                    }}>{t("calendar.addDayOff")}</Button>
                    <Button size="sm" onClick={() => setNewDay(null)}>{t("common.cancel")}</Button>
                  </div>
                </div>
              )}
              {c.holidays.length === 0 ? <div className="panel-body small subtle">{t("calendar.noHolidays", { year })}</div> : (
                <ul className="plain-list">
                  {c.holidays.map((h) => (
                    <li key={h.id} className={h.confirmed ? "" : "proposed"}>
                      <div className="hol-date num">{date(h.date)}</div>
                      <div className="hol-name">{h.name}{h.estimated && <span className="small subtle"> · {t("calendar.estimated")}</span>}</div>
                      <div className="row">
                        {h.confirmed ? <Badge tone="ok" dot>{t("calendar.confirmed")}</Badge>
                          : canEdit ? <Button size="sm" variant="primary" onClick={async () => { cal.setData(await patch<CalendarData>(`/api/holidays/${h.id}`, { confirmed: true })); }}>{t("calendar.confirm")}</Button>
                            : <Badge tone="warn">{t("calendar.proposed")}</Badge>}
                        {canEdit && <Button size="sm" variant="ghost" iconOnly aria-label={t("common.remove")} icon={<LuTrash2 />} onClick={() => setRemoveDay(h)} />}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </div>
      )}
      {removePeriod && <Confirm danger title={t("calendar.removePeriodTitle", { name: removePeriod.name })} body={t("calendar.removePeriodBody")}
        confirmLabel={t("common.remove")} onClose={() => setRemovePeriod(null)}
        onConfirm={async () => { const d = await del<CalendarData>(`/api/calendar/periods/${removePeriod.id}`); if (patternFor === removePeriod.id) setPatternFor(null); cal.setData(d); }} />}
      {removeDay && <Confirm danger title={t("calendar.removeDayTitle", { name: removeDay.name })} body={t("calendar.removeDayBody")}
        confirmLabel={t("common.remove")} onClose={() => setRemoveDay(null)}
        onConfirm={async () => { cal.setData(await del<CalendarData>(`/api/holidays/${removeDay.id}`)); }} />}
    </>
  );
}
