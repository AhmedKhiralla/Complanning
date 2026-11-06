import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import {
  LuArchive, LuArchiveRestore, LuArrowLeft, LuSprayCan, LuLock, LuLockOpen, LuRefreshCw, LuSend, LuUndo2, LuChartGantt, LuCircleAlert, LuCircleCheck, LuEllipsis, LuFileSpreadsheet, LuPencil, LuReceipt, LuTarget, LuTrash2, LuX,
} from "react-icons/lu";
import {
  Badge, Button, Confirm, Dialog, Empty, LoadError, Menu, MenuItem, Notice, TextField, errorText, useLoad, useToast,
} from "../../components/ui";
import { TypeBadge } from "../../components/master";
import { useDuration } from "../../components/rules";
import { del, get, patch, post } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { Link, navigate } from "../../lib/router";
import { usePerms, useSession } from "../../lib/session";
import { nameOf, type ItemType } from "../../lib/types";
import { OBJ_ICON, type PlanRow, type Warning } from "./Plans";

interface PBatch {
  id: string; batch_no: string; item_id: string; code: string; name_en: string; name_ar: string | null; type: ItemType;
  cleaning_group: string | null; uom: string; level: number; quantity: number; bom_version: number | null; need_by: string | null;
  start_at: string | null; end_at: string | null; available_at: string | null; ship_at: string | null;
  status: "scheduled" | "unscheduled"; problem: string | null; value: number | null; currency: string | null;
  ordinal: number; locked: boolean; expires_on: string | null; material_cost: number | null;
}
interface POp {
  id: string; batch_id: string; seq: number; step_name: string; resource_id: string; changeover_start: string | null;
  changeover_end: string | null; changeover_minutes: number; wait_minutes: number; changeover_kind: string | null;
  verification: string | null; reclean_minutes: number; start_at: string; end_at: string; work_minutes: number;
  locked: boolean; eligible: string[];
}
interface PDemand {
  id: string; item_id: string; code: string; name_en: string; name_ar: string | null; uom: string; market: string; month: string;
  due_date: string; requested: number; quantity: number; from_stock: number; batches: string | null; available_at: string | null;
  late_hours: number | null; on_time: boolean; before_rounding: number | null; units_per_shipper: number | null; pack_size: number | null;
  on_time_qty: number | null;
}
interface PlanFull extends PlanRow {
  batches: PBatch[]; operations: POp[]; links: { supplier_id: string; consumer_id: string; quantity: number }[];
  demand: PDemand[]; machines: { id: string; code: string; name_en: string; name_ar: string | null; area: string | null }[];
  downtime: { resource_id: string; starts_at: string; ends_at: string; reason: string }[];
}

const HOUR = 3600_000;
const ZOOM = { month: 1.4, week: 6, day: 26 } as const;
type Zoom = keyof typeof ZOOM;
const ms = (s: string | null | undefined) => (s ? Date.parse(s) : NaN);

/** Minutes east of UTC for the given instant in a time zone. */
function tzOffset(at: number, tz: string): number {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit" }).formatToParts(new Date(at));
  const v = (k: string) => Number(parts.find((p) => p.type === k)?.value);
  return (Date.UTC(v("year"), v("month") - 1, v("day"), v("hour"), v("minute"), v("second")) - at) / 60000;
}
/** Local midnights (as UTC ms) from the day containing a to the day after b. */
function midnights(a: number, b: number, tz: string): number[] {
  const out: number[] = [];
  const off = tzOffset(a, tz);
  const local = new Date(a + off * 60000);
  let y = local.getUTCFullYear(), m = local.getUTCMonth(), d = local.getUTCDate();
  for (let i = 0; i < 400; i++) {
    const guess = Date.UTC(y, m, d);
    const t = guess - tzOffset(guess, tz) * 60000;
    out.push(t);
    if (t > b) break;
    const nx = new Date(Date.UTC(y, m, d + 1));
    y = nx.getUTCFullYear(); m = nx.getUTCMonth(); d = nx.getUTCDate();
  }
  return out;
}

interface Drag { op: POp; dx: number; rowId: string; }

function Gantt({ plan, tz, selected, onSelect, editable, onMove }: {
  plan: PlanFull; tz: string; selected: string | null; onSelect: (id: string | null) => void;
  editable: boolean; onMove: (op: POp, resourceId: string, startIso: string) => void;
}) {
  const { t, lang, dateTime } = useI18n();
  const dur = useDuration();
  const [zoom, setZoom] = useState<Zoom>("week");
  const scroller = useRef<HTMLDivElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const pointer = useRef<{ op: POp; x0: number; y0: number; moved: boolean } | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const batches = useMemo(() => new Map(plan.batches.map((b) => [b.id, b])), [plan.batches]);
  const groups = useMemo(() => {
    const gs = Array.from(new Set(plan.batches.map((b) => b.cleaning_group ?? "").filter(Boolean))).sort();
    return new Map(gs.map((g, i) => [g, i % 6]));
  }, [plan.batches]);
  const chain = useMemo(() => {
    if (!selected) return null;
    const set = new Set([selected]);
    const up = (id: string) => plan.links.filter((l) => l.consumer_id === id).forEach((l) => { if (!set.has(l.supplier_id)) { set.add(l.supplier_id); up(l.supplier_id); } });
    const down = (id: string) => plan.links.filter((l) => l.supplier_id === id).forEach((l) => { if (!set.has(l.consumer_id)) { set.add(l.consumer_id); down(l.consumer_id); } });
    up(selected); down(selected);
    return set;
  }, [selected, plan.links]);

  const starts = plan.operations.map((o) => ms(o.changeover_start ?? o.start_at));
  const t0raw = Math.min(ms(plan.starts_at), ...starts);
  const hEnd = Date.parse(plan.horizon_end + "T23:59:59Z");
  const t1raw = Math.max(hEnd, ...plan.operations.map((o) => ms(o.end_at)));
  const days = midnights(t0raw, t1raw, tz);
  const t0 = days[0], t1 = days[days.length - 1];
  const px = ZOOM[zoom];
  const x = (v: number) => ((v - t0) / HOUR) * px;
  const width = x(t1);
  const now = Date.now();
  const areas = Array.from(new Set(plan.machines.map((m) => m.area ?? "")));
  const dayFmt = new Intl.DateTimeFormat(lang === "ar" ? "ar-EG-u-nu-latn" : "en-GB", { timeZone: tz, weekday: zoom === "month" ? undefined : "short", day: "numeric" });
  const monFmt = new Intl.DateTimeFormat(lang === "ar" ? "ar-EG-u-nu-latn" : "en-GB", { timeZone: tz, month: "long", year: "numeric" });
  const months: { left: number; label: string }[] = [];
  days.slice(0, -1).forEach((d, i) => {
    const label = monFmt.format(new Date(d + 12 * HOUR));
    if (i === 0 || months[months.length - 1].label !== label) months.push({ left: x(d), label });
  });
  const isFriSat = (d: number) => { const wd = new Date(d + 12 * HOUR + tzOffset(d, tz) * 60000).getUTCDay(); return wd === 5; };

  // Row positions inside the chart body: area header rows are 24 px, machine rows 36 px.
  const rows: { id: string | null; top: number; h: number }[] = [];
  let y = 0;
  for (const a of areas) {
    rows.push({ id: null, top: y, h: 24 }); y += 24;
    for (const m of plan.machines.filter((mm) => (mm.area ?? "") === a)) { rows.push({ id: m.id, top: y, h: 36 }); y += 36; }
  }
  const rowAt = (clientY: number) => {
    const top = body.current?.getBoundingClientRect().top ?? 0;
    const yy = clientY - top;
    return rows.find((r) => r.id && yy >= r.top && yy < r.top + r.h)?.id ?? null;
  };
  const rowTop = (id: string) => rows.find((r) => r.id === id)?.top ?? 0;
  const dropStart = (d: Drag) => {
    const raw = ms(d.op.start_at) + (d.dx / px) * HOUR;
    return Math.round(raw / (15 * 60000)) * 15 * 60000;
  };

  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollLeft = Math.max(0, x(Math.max(now, t0)) - 80);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zoom]);

  const tip = (o: POp, b: PBatch) => [
    `${b.batch_no} · ${b.code}`, `${o.seq}. ${o.step_name}`,
    `${dateTime(o.start_at, tz)} → ${dateTime(o.end_at, tz)}`,
    o.changeover_start ? `${t("pv.changeover")}: ${t(`pv.co.${o.changeover_kind}` as never)} ${dur(Number(o.changeover_minutes))}` +
      (Number(o.wait_minutes) ? ` + ${t("pv.wait", { d: dur(Number(o.wait_minutes)) })}` : "") : "",
  ].filter(Boolean).join("\n");

  return (
    <div className="gantt-wrap">
      <div className="gantt-bar">
        <div className="seg" role="group" aria-label={t("pv.zoom")}>
          {(Object.keys(ZOOM) as Zoom[]).map((z) => <button key={z} type="button" aria-pressed={zoom === z} onClick={() => setZoom(z)}>{t(`pv.zoom.${z}` as never)}</button>)}
        </div>
        <div className="legend small">
          <span><i className="lg co" />{t("pv.legend.co")}</span>
          <span><i className="lg wait" />{t("pv.legend.wait")}</span>
          <span><i className="lg down" />{t("pv.legend.down")}</span>
          {Array.from(groups.entries()).map(([g, i]) => <span key={g}><i className={`lg tone-${i}`} />{g}</span>)}
        </div>
        <span className="spacer" />
        <span className="small subtle">{editable ? t("pv.dragHint") : selected ? "" : t("pv.selectHint")} {t("pv.timesIn", { tz })}</span>
      </div>
      <div className="gantt" dir="ltr">
        <div className="g-names">
          <div className="g-head" />
          {areas.map((a) => (
            <Fragment key={a || "none"}>
              <div className="g-area">{a || "—"}</div>
              {plan.machines.filter((m) => (m.area ?? "") === a).map((m) => (
                <div key={m.id} className="g-name" title={nameOf(m, lang)}><strong>{m.code}</strong><span>{nameOf(m, lang)}</span></div>
              ))}
            </Fragment>
          ))}
        </div>
        <div className="g-scroll" ref={scroller}>
          <div className="g-canvas" style={{ width }}>
            <div className="g-head">
              <div className="g-months">{months.map((mo, i) => <span key={i} style={{ left: mo.left }}>{mo.label}</span>)}</div>
              <div className="g-days">
                {days.slice(0, -1).map((d, i) => (
                  <span key={d} className={isFriSat(d) ? "off" : ""} style={{ left: x(d), width: x(days[i + 1]) - x(d) }}>
                    {zoom !== "month" || px * 24 > 20 ? dayFmt.format(new Date(d + 12 * HOUR)) : ""}
                  </span>
                ))}
              </div>
            </div>
            <div className={`g-body ${drag ? "dragging" : ""}`} ref={body} onClick={(e) => { if (e.target === e.currentTarget) onSelect(null); }}>
              {days.slice(0, -1).map((d, i) => isFriSat(d) && <div key={d} className="g-off" style={{ left: x(d), width: x(days[i + 1]) - x(d) }} />)}
              {days.map((d) => <div key={"l" + d} className="g-line" style={{ left: x(d) }} />)}
              {now > t0 && now < t1 && <div className="g-now" style={{ left: x(now) }}><span>{t("pv.today")}</span></div>}
              <div className="g-hend" style={{ left: x(hEnd) }}><span>{t("pv.horizonEnd")}</span></div>
              {areas.map((a) => (
                <Fragment key={a || "none"}>
                  <div className="g-row area" />
                  {plan.machines.filter((m) => (m.area ?? "") === a).map((m) => (
                    <div key={m.id} className={`g-row ${drag ? (drag.op.eligible.includes(m.id) ? "drop-ok" : "drop-no") : ""} ${drag?.rowId === m.id ? "hover" : ""}`}>
                      {plan.downtime.filter((dt) => dt.resource_id === m.id).map((dt, i) => (
                        <div key={i} className="g-down" style={{ left: x(ms(dt.starts_at)), width: Math.max(2, x(ms(dt.ends_at)) - x(ms(dt.starts_at))) }}
                          title={`${t(`reason.${dt.reason}` as never)}: ${dateTime(dt.starts_at, tz)} → ${dateTime(dt.ends_at, tz)}`} />
                      ))}
                      {plan.operations.filter((o) => o.resource_id === m.id).map((o) => {
                        const b = batches.get(o.batch_id)!;
                        const dim = chain && !chain.has(b.id);
                        const tone = b.cleaning_group && groups.has(b.cleaning_group) ? `tone-${groups.get(b.cleaning_group)}` : "tone-x";
                        const cs = ms(o.changeover_start), ce = ms(o.changeover_end), wait = Number(o.wait_minutes) * 60000;
                        const w = x(ms(o.end_at)) - x(ms(o.start_at));
                        return (
                          <Fragment key={o.id}>
                            {o.changeover_start && <>
                              <div className={`g-co ${dim ? "dim" : ""}`} style={{ left: x(cs), width: Math.max(1, x(ce - wait) - x(cs)) }} title={tip(o, b)} />
                              {wait > 0 && <div className={`g-wait ${dim ? "dim" : ""}`} style={{ left: x(ce - wait), width: Math.max(1, x(ce) - x(ce - wait)) }} title={tip(o, b)} />}
                            </>}
                            <button type="button" className={`g-op ${tone} lvl-${Math.min(b.level, 3)} ${dim ? "dim" : ""} ${selected === b.id ? "sel" : ""} ${b.locked ? "locked" : ""} ${editable ? "movable" : ""} ${drag?.op.id === o.id ? "origin" : ""}`}
                              style={{ left: x(ms(o.start_at)), width: Math.max(3, w) }} title={tip(o, b) + (b.locked ? `\n${t("pv.locked")}` : "")}
                              onPointerDown={(e) => {
                                if (e.button !== 0) return;
                                pointer.current = { op: o, x0: e.clientX, y0: e.clientY, moved: false };
                                if (editable) e.currentTarget.setPointerCapture(e.pointerId);
                              }}
                              onPointerMove={(e) => {
                                const pt = pointer.current;
                                if (!pt || pt.op.id !== o.id || !editable) return;
                                const dx = e.clientX - pt.x0, dy = e.clientY - pt.y0;
                                if (!pt.moved && Math.hypot(dx, dy) < 5) return;
                                pt.moved = true;
                                setDrag({ op: o, dx, rowId: rowAt(e.clientY) ?? o.resource_id });
                              }}
                              onPointerUp={(e) => {
                                const pt = pointer.current;
                                pointer.current = null;
                                e.stopPropagation();
                                if (pt?.moved && drag) {
                                  const d = drag;
                                  setDrag(null);
                                  if (d.op.eligible.includes(d.rowId)) onMove(d.op, d.rowId, new Date(dropStart(d)).toISOString());
                                  return;
                                }
                                setDrag(null);
                                onSelect(selected === b.id ? null : b.id);
                              }}
                              onPointerCancel={() => { pointer.current = null; setDrag(null); }}
                              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(selected === b.id ? null : b.id); } }}>
                              {b.locked && w > 16 && <LuLock className="lk" aria-hidden />}
                              {w > 46 && <span>{b.batch_no}{w > 120 ? ` · ${b.code}` : ""}</span>}
                            </button>
                          </Fragment>
                        );
                      })}
                    </div>
                  ))}
                </Fragment>
              ))}
              {drag && (() => {
                const b = batches.get(drag.op.batch_id)!;
                const ok = drag.op.eligible.includes(drag.rowId);
                const st = dropStart(drag);
                const w = x(ms(drag.op.end_at)) - x(ms(drag.op.start_at));
                return (
                  <div className={`g-ghost ${ok ? "" : "bad"}`} style={{ left: x(st), top: rowTop(drag.rowId) + 6, width: Math.max(3, w) }}>
                    <span>{b.batch_no} · {ok ? dateTime(new Date(st).toISOString(), tz) : t("pv.notQualified")}</span>
                  </div>
                );
              })()}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function BatchDetail({ plan, id, tz, onSelect, editable, onLock }: {
  plan: PlanFull; id: string; tz: string; onSelect: (id: string | null) => void; editable: boolean; onLock: (id: string, locked: boolean) => void;
}) {
  const { t, lang, qty, dateTime, date } = useI18n();
  const dur = useDuration();
  const b = plan.batches.find((x) => x.id === id);
  if (!b) return null;
  const byId = new Map(plan.batches.map((x) => [x.id, x]));
  const machines = new Map(plan.machines.map((m) => [m.id, m]));
  const ops = plan.operations.filter((o) => o.batch_id === id).sort((a, c) => a.seq - c.seq);
  const sup = plan.links.filter((l) => l.consumer_id === id);
  const con = plan.links.filter((l) => l.supplier_id === id);
  const serves = plan.demand.filter((d) => (d.batches ?? "").split(", ").includes(b.batch_no));
  const chip = (bid: string, q: number) => {
    const x = byId.get(bid)!;
    return <button key={bid} type="button" className="bchip link" onClick={() => onSelect(bid)}>{x.batch_no} · {x.code} · {qty(q, 1)} {x.uom}</button>;
  };
  return (
    <div className="panel batch-detail">
      <div className="panel-head">
        <div className="titles">
          <div className="row wrap" style={{ gap: 8 }}><strong className="mono-id">{b.batch_no}</strong><span className="mono-id">{b.code}</span><TypeBadge type={b.type} /></div>
          <span className="small muted">{nameOf(b, lang)} · {qty(b.quantity, 1)} {b.uom}{b.bom_version ? ` · BOM v${b.bom_version}` : ""}</span>
        </div>
        <span className="spacer" />
        {b.locked && <Badge tone="brand"><LuLock /> {t("pv.locked")}</Badge>}
        {editable && b.status === "scheduled" && (b.locked
          ? <Button size="sm" icon={<LuLockOpen />} onClick={() => onLock(b.id, false)}>{t("pv.unlock")}</Button>
          : <Button size="sm" icon={<LuLock />} onClick={() => onLock(b.id, true)} title={t("pv.lockedHint")}>{t("pv.lock")}</Button>)}
        <Button size="sm" variant="ghost" iconOnly icon={<LuX />} aria-label={t("pv.close")} onClick={() => onSelect(null)} />
      </div>
      <div className="panel-body bd-grid">
        <div className="bd-times">
          <div><span>{t("pv.start")}</span><strong>{dateTime(b.start_at, tz)}</strong></div>
          <div><span>{t("pv.end")}</span><strong>{dateTime(b.end_at, tz)}</strong></div>
          <div><span>{b.type === "finished" ? t("pv.ship") : t("pv.available")}</span><strong>{dateTime(b.type === "finished" ? b.ship_at : b.available_at, tz)}</strong></div>
          {b.expires_on && <div><span>{t("pv.expires")}</span><strong>{date(b.expires_on, "UTC")}</strong></div>}
          {b.material_cost !== null && b.material_cost !== undefined && <div><span>{t("pv.matCost")}</span>
            <strong>{qty(b.material_cost, 0)} {plan.kpis?.cost?.currency ?? ""}</strong></div>}
        </div>
        <table className="table compact">
          <thead><tr><th>{t("pv.step")}</th><th>{t("pv.machine")}</th><th>{t("pv.changeover")}</th><th>{t("pv.start")}</th><th>{t("pv.end")}</th></tr></thead>
          <tbody>{ops.map((o) => (
            <tr key={o.id}>
              <td>{o.seq}. {o.step_name}</td>
              <td className="mono-id">{machines.get(o.resource_id)?.code}</td>
              <td className="small">{o.changeover_kind ? <>{t(`pv.co.${o.changeover_kind}` as never)} · {dur(Number(o.changeover_minutes))}
                {Number(o.wait_minutes) > 0 && <> + {t("pv.wait", { d: dur(Number(o.wait_minutes)) })}</>}</> : <span className="subtle">—</span>}
                {Number(o.reclean_minutes) > 0 && <div className="subtle">{t("pv.reclean", { m: qty(o.reclean_minutes, 0) })}</div>}</td>
              <td className="small num">{dateTime(o.start_at, tz)}</td>
              <td className="small num">{dateTime(o.end_at, tz)}</td>
            </tr>
          ))}</tbody>
        </table>
        <div className="bd-links">
          {sup.length > 0 && <div><span className="small muted">{t("pv.suppliers")}</span><div className="chip-row">{sup.map((l) => chip(l.supplier_id, l.quantity))}</div></div>}
          {con.length > 0 && <div><span className="small muted">{t("pv.consumers")}</span><div className="chip-row">{con.map((l) => chip(l.consumer_id, l.quantity))}</div></div>}
          {serves.length > 0 && <div><span className="small muted">{t("pv.serves")}</span><div className="chip-row">{serves.map((d) => (
            <span key={d.id} className="bchip">{d.market} · {qty(d.quantity, 0)} · {d.due_date}</span>))}</div></div>}
        </div>
      </div>
    </div>
  );
}

function warnText(w: Warning, t: ReturnType<typeof useI18n>["t"], qty: ReturnType<typeof useI18n>["qty"], date: (s: string) => string) {
  const n = (v: unknown, d = 0) => qty(Number(v), d);
  switch (w.kind) {
    case "capped": return t("pv.w.capped", { code: String(w.code), market: String(w.market), month: String(w.month), requested: n(w.requested), quantity: n(w.quantity) });
    case "hold_exceeded": return t("pv.w.hold_exceeded", { code: String(w.code), consumer: String(w.consumer), hours: n(w.hours), limit: n(w.limit), qty: `${n(w.quantity, 1)} ${w.uom ?? ""}` });
    case "material_short": return w.no_lead_time ? t("pv.w.material_short_nolead", { code: String(w.code), short: n(w.short, 1), batch: String(w.batch) })
      : t("pv.w.material_short", { code: String(w.code), short: n(w.short, 1), batch: String(w.batch), arrival: date(String(w.arrival)) });
    case "unscheduled": return t("pv.w.unscheduled", { code: String(w.code), reason: t(`pv.problem.${w.reason}` as never) });
    case "after_horizon": return t("pv.w.after_horizon", { n: String(w.count) });
    case "no_shifts": return t("pv.w.no_shifts");
    case "lock_overlap": return t("pv.w.lock_overlap", { code: String(w.code), machine: String(w.machine), other: String(w.other) });
    case "lock_no_changeover": return t("pv.w.lock_no_changeover", { code: String(w.code), machine: String(w.machine), minutes: n(w.minutes) });
    case "lock_inputs_late": return t("pv.w.lock_inputs_late", { code: String(w.code), input: String(w.input), hours: n(w.hours) });
    case "lock_lost": return t("pv.w.lock_lost", { code: String(w.code) });
    case "short_shelf_life": return t("pv.w.short_shelf_life", { code: String(w.code), market: String(w.market), qty: `${n(w.quantity)} ${w.uom ?? ""}` });
    case "shelf_life_short": return t("pv.w.shelf_life_short", { code: String(w.code), market: String(w.market), min: n(w.min), expires: String(w.expires) });
    case "campaign_short": return t("pv.w.campaign_short", { code: String(w.code), machine: String(w.machine), n: String(w.batches), min: String(w.min) });
    case "compensation_negative": return t("pv.w.compensation_negative", { code: String(w.code), item: String(w.item) });
    case "inactive_item": return t("pv.w.inactive_item", { code: String(w.code), item: String(w.item) });
    case "compensation_unit": return t("pv.w.compensation_unit", { code: String(w.code), item: String(w.item) });
    default: return w.kind;
  }
}

export function PlanView({ planId }: { planId: string }) {
  const { t, lang, qty, date, dateTime } = useI18n();
  const { planSite } = usePerms();
  const { me } = useSession();
  const toast = useToast();
  const dur = useDuration();
  const data = useLoad(() => get<PlanFull>(`/api/plans/${planId}`), [planId]);
  const [tab, setTab] = useState<"gantt" | "deliveries" | "batches" | "warnings" | "machines">("gantt");
  const [selected, setSelected] = useState<string | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [name, setName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [releasing, setReleasing] = useState(false);
  if (data.error) return <>
    <Link to="/plans" className="back-link"><LuArrowLeft /> {t("pv.back")}</Link>
    {(data.error as { status?: number }).status === 404
      ? <div className="panel"><Empty icon={<LuChartGantt />} title={t("pv.notFound")} /></div>
      : <LoadError error={data.error} onRetry={data.reload} />}
  </>;
  const p = data.data;
  if (!p) return <div className="panel"><div className="panel-body"><div className="skeleton" style={{ height: 300 }} /></div></div>;
  const tz = me?.sites.find((x) => x.id === p.site_id)?.timezone ?? "UTC";
  const k = p.kpis!;
  const canEdit = planSite(p.site_id);
  const editable = canEdit && p.status === "draft";
  const act = async (fn: () => Promise<{ focus?: string | null } | unknown>, done: string) => {
    setBusy(true); setErr(null);
    try {
      const r = (await fn()) as { focus?: string | null } | undefined;
      await data.reload();
      if (r && r.focus) setSelected(r.focus);
      toast(t(done as never));
    } catch (e) { setErr(errorText(e, t)); }
    setBusy(false);
  };
  const move = (op: POp, resourceId: string, startIso: string) =>
    act(() => post(`/api/plans/${p.id}/move`, { batch_id: op.batch_id, seq: op.seq, resource_id: resourceId, start_at: startIso }), "pv.replanned");
  const lock = (batchId: string, locked: boolean) => act(() => post(`/api/plans/${p.id}/lock`, { batch_id: batchId, locked }), "pv.replanned");
  const save = async (body: Record<string, unknown>) => {
    try { const r = await patch<PlanRow>(`/api/plans/${p.id}`, body); data.setData({ ...p, ...r }); toast(t("pv.saved")); }
    catch (e) { setErr(errorText(e, t)); }
  };
  const warnings = k.warnings ?? [];
  const otif = otifOf(p.demand);
  const lateLabel = (h: number) => t("pv.st.late", { d: h >= 24 ? t("pv.nDays", { n: qty(h / 24, 1) }) : t("pv.nHours", { n: qty(h, 0) }) });

  return (
    <>
      <Link to="/plans" className="back-link"><LuArrowLeft className="flip-rtl" /> {t("pv.back")}</Link>
      <div className="page-head">
        <div className="titles">
          <h1 className="row" style={{ gap: 10 }}><span className={`obj obj-${p.objective}`}>{OBJ_ICON[p.objective]}</span>{p.name}
            {p.status === "archived" ? <Badge>{t("plans.archived")}</Badge> : p.status === "released"
              ? <Badge tone="ok" dot>{t("pv.st.released")}</Badge> : <Badge>{t("pv.st.draft")}</Badge>}
            {(p.locks?.length ?? 0) > 0 && <Badge tone="brand"><LuLock /> {t("pv.locks", { n: p.locks.length })}</Badge>}</h1>
          <p>{t("pv.meta", { objective: t(`obj.${p.objective}` as never), from: date(p.horizon_start, "UTC"), to: date(p.horizon_end, "UTC"), date: date(p.plan_date, "UTC") })}
            <br /><span className="small subtle">{t("pv.createdBy", { name: p.created_by_name ?? "—", when: dateTime(p.created_at, tz) })}
              {" · "}{t("pv.kpi.runtime", { s: qty(k.runtime_ms / 1000, 1), n: k.runs })}
              {p.status === "released" && p.released_at && <><br />{t("pv.releasedBy", { name: p.released_by_name ?? "—", when: dateTime(p.released_at, tz) })}</>}</span></p>
        </div>
        <div className="actions">
          {editable && <Button icon={<LuRefreshCw />} busy={busy} title={t("pv.replanHint")}
            onClick={() => act(() => post(`/api/plans/${p.id}/replan`), "pv.replanned")}>{t("pv.replan")}</Button>}
          {canEdit && p.status === "draft" && <Button variant="primary" icon={<LuSend />} onClick={() => setReleasing(true)}>{t("pv.release")}</Button>}
          {canEdit && p.status === "released" && <Button icon={<LuUndo2 />} onClick={() => save({ status: "draft" })}>{t("pv.reopen")}</Button>}
          <a className="btn" href={`/api/plans/${p.id}/export`}><LuFileSpreadsheet />{t("pv.export")}</a>
          {canEdit && <Menu trigger={(pr) => <Button iconOnly icon={<LuEllipsis />} aria-label={t("common.actions")} {...pr} />}>
            {(close) => <>
              <MenuItem icon={<LuPencil />} onClick={() => { close(); setName(p.name); setRenaming(true); }}>{t("pv.rename")}</MenuItem>
              {p.status === "archived"
                ? <MenuItem icon={<LuArchiveRestore />} onClick={() => { close(); save({ status: "draft" }); }}>{t("pv.restore")}</MenuItem>
                : <MenuItem icon={<LuArchive />} onClick={() => { close(); save({ status: "archived" }); }}>{t("pv.archive")}</MenuItem>}
              <div className="menu-sep" />
              <MenuItem danger icon={<LuTrash2 />} onClick={() => { close(); setDeleting(true); }}>{t("pv.delete")}</MenuItem>
            </>}
          </Menu>}
        </div>
      </div>
      {err && <Notice tone="danger">{err}</Notice>}
      {p.notes && <Notice>{p.notes}</Notice>}

      <div className="kpis" style={{ marginTop: 0 }}>
        <div className={`kpi ${k.late + k.unfilled ? "bad" : "good"}`}><span className="icon"><LuCircleCheck /></span><span className="k">{t("pv.kpi.onTime")}</span>
          <strong>{k.on_time} / {k.demand_lines}</strong><span className="small subtle">{k.on_time_pct !== null ? `${qty(k.on_time_pct, 0)}%` : ""}</span></div>
        {otif && <div className={`kpi ${otif.pct === 100 ? "good" : "bad"}`}><span className="icon"><LuTarget /></span><span className="k">{t("pv.kpi.otif")}</span>
          <strong>{otif.pct === null ? "—" : `${qty(otif.pct, 0)}%`}</strong>
          <span className="small subtle">{t("pv.kpi.otifSub", { n: otif.otif, of: otif.lines, q: otif.qtyPct === null ? "—" : qty(otif.qtyPct, 1) })}</span></div>}
        <div className={`kpi ${k.unscheduled ? "bad" : ""}`}><span className="icon"><LuChartGantt /></span><span className="k">{t("pv.kpi.batches")}</span>
          <strong>{k.scheduled}</strong>{k.unscheduled > 0 && <span className="small text-danger">{t("pv.kpi.unscheduled", { n: k.unscheduled })}</span>}</div>
        <div className="kpi"><span className="icon"><LuSprayCan /></span><span className="k">{t("pv.kpi.co")}</span>
          <strong>{dur(k.changeover_hours * 60)}</strong><span className="small subtle">{t("pv.kpi.coSub", { n: k.changeovers })}</span></div>
        <div className="kpi"><span className="icon">{OBJ_ICON.sales_value}</span><span className="k">{t("pv.kpi.value")}</span>
          <div className="money">{k.value.length ? k.value.map((v) => <strong key={v.currency}>{qty(v.on_time, 0)} <small>{v.currency} {t("pv.kpi.valueOf", { v: qty(v.requested, 0) })}</small></strong>) : <strong>—</strong>}</div></div>
        <div className="kpi"><span className="icon">{OBJ_ICON.on_time}</span><span className="k">{t("pv.kpi.finish")}</span>
          <strong className="date-kpi">{k.finish ? dateTime(k.finish, tz) : "—"}</strong></div>
        {k.cost && <div className="kpi"><span className="icon"><LuReceipt /></span><span className="k">{t("pv.kpi.margin")}</span>
          <div className="money"><strong>{qty(k.cost.margin, 0)} <small>{k.cost.currency}</small></strong></div>
          <span className="small subtle">{t("pv.kpi.costSub", { m: qty(k.cost.materials, 0), d: qty(k.cost.deliveries, 0), cur: k.cost.currency })}</span></div>}
      </div>

      <div className="tabs" role="tablist" style={{ marginTop: 20 }}>
        {(["gantt", "deliveries", "batches", "warnings", "machines"] as const).map((x) => (
          <button key={x} type="button" role="tab" className="tab" aria-selected={tab === x} onClick={() => setTab(x)}>
            {t(`pv.tab.${x}` as never)}{x === "warnings" && warnings.length > 0 && <Badge tone="warn"> {warnings.length}</Badge>}
          </button>
        ))}
      </div>

      {tab === "gantt" && <>
        {canEdit && p.status === "released" && <Notice>{t("pv.readonlyHint", { status: t("pv.st.released").toLowerCase() })}</Notice>}
        <div className="panel gantt-panel">
          <Gantt plan={p} tz={tz} selected={selected} onSelect={setSelected} editable={editable && !busy} onMove={move} />
          {busy && <div className="replanning"><span className="spinner" aria-hidden />{t("pv.replanning")}</div>}
        </div>
        {selected && <BatchDetail plan={p} id={selected} tz={tz} onSelect={setSelected} editable={editable && !busy} onLock={lock} />}
      </>}

      {tab === "deliveries" && <>
        {otif?.unknown ? <Notice>{t("pv.otifOld")}</Notice> : null}
        <div className="panel"><div className="table-wrap"><table className="table deliveries">
        <thead><tr><th>{t("pv.product")}</th><th>{t("pv.market")}</th><th>{t("pv.due")}</th><th className="num">{t("pv.requested")}</th>
          <th className="num">{t("pv.planned")}</th><th className="num">{t("pv.onTimeQty")}</th><th>{t("pv.batchesCol")}</th><th>{t("pv.availableCol")}</th><th>{t("pv.status")}</th>
          <th>{t("pv.otif")}</th></tr></thead>
        <tbody>{p.demand.map((d) => {
          const req = Number(d.requested), planned = Number(d.quantity);
          const otq = d.on_time_qty === null ? null : Number(d.on_time_qty);
          const pct = otq === null || req <= 0 ? null : Math.min(100, (Math.min(otq, req) / req) * 100);
          const full = otq !== null && req > 0 && otq >= req - 0.001;
          return (
          <tr key={d.id}>
            <td><span className="mono-id cell-main">{d.code}</span><div className="small muted">{nameOf(d, lang)}</div></td>
            <td><Badge tone="brand">{d.market}</Badge></td>
            <td className="small num">{date(d.due_date, "UTC")}</td>
            <td className="num">{qty(req, 0)} <span className="subtle small">{d.uom}</span></td>
            <td className="num">{qty(planned, 0)}
              {d.before_rounding !== null ? <div className="small subtle">{t("pv.rounded", { q: qty(d.before_rounding, 0) })}</div>
                : planned < req && <div className="small text-warn">{t("pv.capped")}</div>}
              {d.units_per_shipper ? <div className="small subtle">{t("pv.shippers", { n: qty(planned / Number(d.units_per_shipper), 1) })}</div> : null}
              {Number(d.from_stock) > 0 && <div className="small subtle">{t("pv.fromStockN", { q: qty(d.from_stock, 0) })}</div>}</td>
            <td className="num">{otq === null ? <span className="subtle">—</span> : <>
              {qty(otq, 0)}
              <div className="fill" title={t("pv.fillHint")}><span className="fill-bar"><i style={{ width: `${pct ?? 0}%` }} className={full ? "ok" : (pct ?? 0) > 0 ? "part" : "none"} /></span>
                <span className="small">{pct === null ? "—" : `${qty(pct, pct >= 99.95 || pct < 1 ? 0 : 1)}%`}</span></div>
              {planned - otq > 0.5 && <div className="small text-danger">{t("pv.lateN", { q: qty(planned - otq, 0) })}</div>}</>}</td>
            <td className="small mono-id">{d.batches ?? "—"}</td>
            <td className="small num">{d.available_at ? dateTime(d.available_at, tz) : "—"}</td>
            <td>{d.on_time ? <Badge tone="ok" dot>{t("pv.st.onTime")}</Badge> : d.available_at && d.late_hours !== null
              ? <Badge tone="danger" dot>{lateLabel(Number(d.late_hours))}</Badge> : <Badge tone="danger">{t("pv.st.unfilled")}</Badge>}</td>
            <td>{otq === null ? <span className="subtle">—</span> : full ? <Badge tone="ok">{t("pv.otifYes")}</Badge>
              : <Badge tone="danger">{t(otq > 0 ? (d.on_time ? "pv.otifShort" : "pv.otifPart") : "pv.otifNo")}</Badge>}</td>
          </tr>);
        })}</tbody>
        {otif && otif.sameUom && <tfoot><tr>
          <td colSpan={3}><strong>{t("pv.total")}</strong></td>
          <td className="num"><strong>{qty(otif.requested, 0)}</strong> <span className="subtle small">{otif.sameUom}</span></td>
          <td className="num"><strong>{qty(otif.planned, 0)}</strong></td>
          <td className="num"><strong>{qty(otif.onTime, 0)}</strong><div className="small subtle">{otif.qtyPct === null ? "" : `${qty(otif.qtyPct, 1)}%`}</div>
            {otif.planned - otif.onTime > 0.5 && <div className="small text-danger">{t("pv.lateN", { q: qty(otif.planned - otif.onTime, 0) })}</div>}</td>
          <td colSpan={3} />
          <td><strong>{otif.otif} / {otif.lines}</strong></td>
        </tr></tfoot>}
      </table></div></div>
        <p className="small subtle" style={{ marginTop: 8 }}>{t("pv.otifNote")}</p>
      </>}

      {tab === "batches" && <div className="panel"><div className="table-wrap"><table className="table">
        <thead><tr><th>{t("pv.batch")}</th><th>{t("pv.item")}</th><th className="num">{t("pv.qty")}</th><th>{t("pv.start")}</th><th>{t("pv.end")}</th>
          <th>{t("pv.available")}</th><th>{t("pv.status")}</th></tr></thead>
        <tbody>{p.batches.map((b) => (
          <tr key={b.id} className="clickable" onClick={() => { setSelected(b.id); setTab("gantt"); }}>
            <td className="mono-id cell-main">{b.batch_no}</td>
            <td><span className="mono-id">{b.code}</span> <TypeBadge type={b.type} /></td>
            <td className="num">{qty(b.quantity, 1)} <span className="subtle small">{b.uom}</span></td>
            <td className="small num">{dateTime(b.start_at, tz)}</td>
            <td className="small num">{dateTime(b.end_at, tz)}</td>
            <td className="small num">{dateTime(b.type === "finished" ? b.ship_at : b.available_at, tz)}</td>
            <td>{b.status === "scheduled" ? <LuCircleCheck style={{ color: "var(--ok)" }} aria-hidden />
              : <Badge tone="danger">{t(`pv.problem.${b.problem}` as never)}</Badge>}</td>
          </tr>
        ))}</tbody>
      </table></div></div>}

      {tab === "warnings" && <div className="panel">
        {warnings.length === 0 ? <div className="panel-body row" style={{ gap: 8 }}><LuCircleCheck style={{ color: "var(--ok)" }} />{t("pv.noWarnings")}</div> : (
          <ul className="warn-list">{warnings.map((w, i) => (
            <li key={i} className={`w-${w.kind}`}>
              <LuCircleAlert />
              <span>{warnText(w, t, qty, (s) => dateTime(s, tz))}</span>
              {typeof w.key === "number" && <span className="spacer" />}
            </li>
          ))}</ul>
        )}
      </div>}

      {tab === "machines" && <div className="panel"><div className="panel-body util-list">
        <h3 className="small muted" style={{ margin: 0 }}>{t("pv.util")}</h3>
        {k.utilization.map((u) => {
          const busy = u.available_hours ? (u.busy_hours / u.available_hours) * 100 : 0;
          const co = u.available_hours ? (u.changeover_hours / u.available_hours) * 100 : 0;
          const mach = p.machines.find((x) => x.id === u.machine_id);
          return (
            <div key={u.machine_id} className="util-row">
              <span className="util-name"><span className="mono-id cell-main">{u.code}</span>
                {mach && <span className="small muted" title={nameOf(mach, lang)}>{nameOf(mach, lang)}</span>}</span>
              <div className="util-bar" title={t("pv.utilBusy", { busy: qty(u.busy_hours, 0), co: qty(u.changeover_hours, 0), avail: qty(u.available_hours, 0) })}>
                <span className="busy" style={{ width: `${Math.min(100, busy)}%` }} />
                <span className="co" style={{ width: `${Math.min(100 - Math.min(100, busy), co)}%` }} />
              </div>
              <strong className="num">{u.utilization !== null ? `${qty(u.utilization * 100, 0)}%` : "—"}</strong>
              <span className="small subtle">{t("pv.utilBusy", { busy: qty(u.busy_hours, 0), co: qty(u.changeover_hours, 0), avail: qty(u.available_hours, 0) })}</span>
            </div>
          );
        })}
      </div></div>}

      {renaming && <Dialog title={t("pv.renameTitle")} onClose={() => setRenaming(false)} footer={<>
        <Button onClick={() => setRenaming(false)}>{t("common.cancel")}</Button>
        <Button variant="primary" disabled={!name.trim()} onClick={async () => { await save({ name: name.trim() }); setRenaming(false); }}>{t("common.save")}</Button>
      </>}><TextField label={t("np.name")} value={name} maxLength={120} onChange={setName} /></Dialog>}
      {releasing && <Confirm title={t("pv.releaseTitle")} body={t("pv.releaseBody")} confirmLabel={t("pv.release")} onClose={() => setReleasing(false)}
        onConfirm={async () => { await post(`/api/plans/${p.id}/release`); await data.reload(); toast(t("pv.released")); }} />}
      {deleting && <Confirm danger title={t("pv.deleteTitle")} body={t("pv.deleteBody")} confirmLabel={t("pv.delete")} onClose={() => setDeleting(false)}
        onConfirm={async () => { await del(`/api/plans/${p.id}`); toast(t("pv.deleted")); navigate("/plans"); }} />}
    </>
  );
}


/** On time in full: lines complete by their due date, and the share of the requested quantity ready on time. */
function otifOf(rows: PDemand[]) {
  const lines = rows.filter((d) => Number(d.requested) > 0);
  if (!lines.length) return null;
  const known = lines.filter((d) => d.on_time_qty !== null);
  let requested = 0, planned = 0, onTime = 0, otif = 0;
  for (const d of known) {
    const req = Number(d.requested), otq = Number(d.on_time_qty);
    requested += req; planned += Number(d.quantity); onTime += Math.min(otq, req);
    if (otq >= req - 0.001) otif += 1;
  }
  const uoms = new Set(lines.map((d) => d.uom));
  return {
    lines: known.length, otif, unknown: lines.length - known.length,
    pct: known.length ? (otif / known.length) * 100 : null,
    qtyPct: requested > 0 ? (onTime / requested) * 100 : null,
    requested, planned, onTime, sameUom: uoms.size === 1 && known.length === lines.length ? [...uoms][0] : null,
  };
}
