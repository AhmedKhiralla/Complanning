import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  LuChartGantt, LuFlaskConical, LuPause, LuPlay, LuRewind, LuSkipBack, LuSkipForward, LuStepBack, LuStepForward, LuTruck,
  LuWarehouse, LuX,
} from "react-icons/lu";
import { Button, Empty, LoadError, Notice, useLoad } from "../../components/ui";
import { useDuration } from "../../components/rules";
import { get } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { nameOf } from "../../lib/types";
import type { PlanFull } from "./PlanView";
import {
  HOUR, buildModel, busyHours, machineAt, waits, whereAt, type LocKind, type SimBatch, type SimMaterialData, type Stage, type Where,
} from "./simModel";

// Floor geometry (px).
const CARD_W = 190, CARD_H = 104, COL_W = 222, CARD_GAP = 16, HEAD = 30, PAD = 16;
const TOK_W = 54, TOK_H = 20, BAND_H = 196;
const SPEEDS = [1, 4, 12, 24, 72] as const;
const STAGES: Stage[] = ["wip", "semi_finished", "finished"];
const ms = (s: string | null | undefined) => (s ? Date.parse(s) : NaN);

type Sel = { kind: "batch"; id: string } | { kind: "machine"; id: string } | null;
interface Pos { x: number; y: number; show: boolean }

export function PlanSimulation({ plan, tz, onShowBatch }: { plan: PlanFull; tz: string; onShowBatch: (id: string) => void }) {
  const { t, lang, qty, dateTime, date } = useI18n();
  const dur = useDuration();
  const mats = useLoad(() => get<SimMaterialData>(`/api/plans/${plan.id}/simulation`), [plan.id]);
  const model = useMemo(() => buildModel(plan), [plan]);
  const [now, setNow] = useState(model.t0);
  const [dir, setDir] = useState<0 | 1 | -1>(0);
  const [speed, setSpeed] = useState<number>(12);
  const [sel, setSel] = useState<Sel>(null);
  const [waitMode, setWaitMode] = useState<"now" | "plan">("now");
  const [allMats, setAllMats] = useState(false);
  const nowRef = useRef(now);
  nowRef.current = now;

  useEffect(() => { setNow(model.t0); setDir(0); }, [model.t0]);

  // Playback loop.
  useEffect(() => {
    if (!dir) return;
    let raf = 0, last = performance.now();
    const tick = (ts: number) => {
      const dt = (ts - last) / 1000;
      last = ts;
      let v = nowRef.current + dir * dt * speed * HOUR;
      if (v >= model.t1) { v = model.t1; setDir(0); }
      if (v <= model.t0) { v = model.t0; setDir(0); }
      setNow(v);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [dir, speed, model.t0, model.t1]);

  const jumpEvent = useCallback((d: 1 | -1) => {
    setDir(0);
    const ev = model.events;
    const cur = nowRef.current;
    const nx = d > 0 ? ev.find((v) => v > cur + 1000) : [...ev].reverse().find((v) => v < cur - 1000);
    setNow(nx ?? (d > 0 ? model.t1 : model.t0));
  }, [model]);

  const floorRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = floorRef.current?.closest(".sim") as HTMLElement | null;
    if (!el) return;
    const key = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      if (e.key === " ") { e.preventDefault(); setDir((d) => (d ? 0 : nowRef.current >= model.t1 ? 0 : 1)); }
      else if (e.key === "ArrowRight") { e.preventDefault(); jumpEvent(lang === "ar" ? -1 : 1); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); jumpEvent(lang === "ar" ? 1 : -1); }
    };
    el.addEventListener("keydown", key);
    return () => el.removeEventListener("keydown", key);
  }, [jumpEvent, model.t1, lang]);

  // ---- layout
  const machines = useMemo(() => new Map(plan.machines.map((m) => [m.id, m])), [plan.machines]);
  const rowsMax = Math.max(1, ...model.columns.map((c) => c.machines.length));
  const W = Math.max(model.columns.length * COL_W + PAD * 2 - (COL_W - CARD_W), 980);
  const bandY = PAD + HEAD + rowsMax * (CARD_H + CARD_GAP) + 26;
  const H = bandY + BAND_H + PAD;
  const rtl = lang === "ar";
  const X = (x: number, w: number) => (rtl ? W - x - w : x);
  const cardAt = useMemo(() => {
    const m = new Map<string, { x: number; y: number }>();
    // Centre each column on the tallest one, so a step with one machine sits between the machines it feeds.
    model.columns.forEach((c, ci) => {
      const off = c.unused ? 0 : ((rowsMax - c.machines.length) * (CARD_H + CARD_GAP)) / 2;
      c.machines.forEach((id, ri) => m.set(id, { x: PAD + ci * COL_W, y: PAD + HEAD + off + ri * (CARD_H + CARD_GAP) }));
    });
    return m;
  }, [model.columns, rowsMax]);
  const innerW = W - PAD * 2, gap = 16;
  const areaBox = {
    stored: { x: PAD, y: bandY, w: Math.round(innerW * 0.45), h: BAND_H },
    qc: { x: PAD + Math.round(innerW * 0.45) + gap, y: bandY, w: Math.round(innerW * 0.3) - gap, h: BAND_H },
    shipped: { x: PAD + Math.round(innerW * 0.75) + gap, y: bandY, w: innerW - Math.round(innerW * 0.75) - gap, h: BAND_H },
  };

  // ---- state at the clock
  const where = useMemo(() => new Map(model.batches.map((x) => [x.b.id, whereAt(x, now)])), [model, now]);
  const mNow = useMemo(() => new Map(plan.machines.map((m) => [m.id, machineAt(model, plan, m.id, now)])), [model, plan, now]);

  const layout = useMemo(() => {
    const pos = new Map<string, Pos>();
    const overflow: Record<string, number> = {};
    const queueOf = new Map<string, SimBatch[]>();
    const inArea: Record<"stored" | "qc" | "shipped", SimBatch[]> = { stored: [], qc: [], shipped: [] };
    for (const x of model.batches) {
      const w = where.get(x.b.id)!;
      if (w.kind === "queue" && w.machine) queueOf.set(w.machine, [...(queueOf.get(w.machine) ?? []), x]);
      else if (w.kind === "stored" || w.kind === "qc") inArea[w.kind].push(x);
      else if (w.kind === "shipped" && w.seg && now - w.seg.from < 48 * HOUR) inArea.shipped.push(x);
    }
    const door = { x: areaBox.stored.x + 14, y: areaBox.stored.y + 14 };
    for (const x of model.batches) {
      const w = where.get(x.b.id)!;
      if (w.kind === "run" && w.machine && cardAt.has(w.machine)) {
        const c = cardAt.get(w.machine)!;
        pos.set(x.b.id, { x: c.x + 10, y: c.y + 52, show: true });
      }
    }
    for (const [mid, list] of queueOf) {
      const c = cardAt.get(mid);
      if (!c) continue;
      list.sort((a, b) => ms(a.b.start_at) - ms(b.b.start_at));
      list.forEach((x, i) => {
        if (i < 3) pos.set(x.b.id, { x: c.x + 8 + i * (TOK_W + 4), y: c.y + CARD_H - TOK_H - 8, show: true });
        else pos.set(x.b.id, { x: c.x + 8 + 2 * (TOK_W + 4), y: c.y + CARD_H - TOK_H - 8, show: false });
      });
      if (list.length > 3) overflow[`m:${mid}`] = list.length - 2;
    }
    (Object.keys(inArea) as ("stored" | "qc" | "shipped")[]).forEach((k) => {
      const box = areaBox[k];
      const perRow = Math.max(1, Math.floor((box.w - 20) / (TOK_W + 6)));
      const rows = Math.max(1, Math.floor((box.h - 58) / (TOK_H + 6)));
      const cap = perRow * rows;
      const list = inArea[k].sort((a, b) => a.b.batch_no.localeCompare(b.b.batch_no));
      list.forEach((x, i) => {
        const j = Math.min(i, cap - 1);
        pos.set(x.b.id, { x: box.x + 10 + (j % perRow) * (TOK_W + 6), y: box.y + 50 + Math.floor(j / perRow) * (TOK_H + 6), show: i < cap - (list.length > cap ? 1 : 0) });
      });
      if (list.length > cap) overflow[k] = list.length - cap + 1;
    });
    // Hidden tokens: not started (at the warehouse door), used (move into the batch that uses them), shipped long ago.
    for (const x of model.batches) {
      if (pos.has(x.b.id)) continue;
      const w = where.get(x.b.id)!;
      if (w.kind === "used") {
        const c = x.consumers.map((id) => pos.get(id)).find(Boolean);
        pos.set(x.b.id, { x: c?.x ?? door.x, y: c?.y ?? door.y, show: false });
      } else if (w.kind === "shipped") {
        pos.set(x.b.id, { x: areaBox.shipped.x + areaBox.shipped.w - TOK_W - 10, y: areaBox.shipped.y + 14, show: false });
      } else {
        pos.set(x.b.id, { x: door.x, y: door.y, show: false });
      }
    }
    return { pos, overflow, queueOf, inArea };
  }, [model, where, cardAt, now, areaBox.stored.x, areaBox.stored.y, areaBox.stored.w, areaBox.qc.x, areaBox.qc.w, areaBox.shipped.x, areaBox.shipped.w, bandY]);

  const chain = useMemo(() => {
    if (sel?.kind !== "batch") return null;
    const set = new Set([sel.id]);
    const up = (id: string) => model.byId.get(id)?.suppliers.forEach((s) => { if (!set.has(s)) { set.add(s); up(s); } });
    const down = (id: string) => model.byId.get(id)?.consumers.forEach((s) => { if (!set.has(s)) { set.add(s); down(s); } });
    up(sel.id); down(sel.id);
    return set;
  }, [sel, model]);

  // ---- analysis
  const stageTable = useMemo(() => {
    const rows = STAGES.map((s) => ({ stage: s, planned: 0, making: 0, between: 0, qc: 0, stored: 0, done: 0, total: 0 }));
    for (const x of model.batches) {
      const r = rows[STAGES.indexOf(x.stage)];
      const k = where.get(x.b.id)!.kind;
      r.total++;
      if (k === "planned") r.planned++; else if (k === "run") r.making++; else if (k === "queue") r.between++;
      else if (k === "qc") r.qc++; else if (k === "stored") r.stored++; else r.done++;
    }
    return rows.filter((r) => r.total > 0);
  }, [model, where]);

  const waitTable = useMemo(() => STAGES.map((s) => {
    const list = model.batches.filter((x) => x.stage === s && (waitMode === "plan" || x.first <= now));
    const tot = { between: 0, qc: 0, stored: 0 };
    for (const x of list) { const w = waits(x, waitMode === "plan" ? Infinity : now); tot.between += w.between; tot.qc += w.qc; tot.stored += w.stored; }
    const n = Math.max(1, list.length);
    return { stage: s, n: list.length, between: tot.between / n, qc: tot.qc / n, stored: tot.stored / n };
  }).filter((r) => model.batches.some((x) => x.stage === r.stage)), [model, now, waitMode]);

  const deliveries = useMemo(() => {
    const lines = plan.demand.filter((d) => d.quantity > 0);
    const ready = lines.filter((d) => !Number.isNaN(ms(d.available_at)) && ms(d.available_at) <= now);
    return { total: lines.length, ready: ready.length, onTime: ready.filter((d) => d.on_time).length };
  }, [plan.demand, now]);

  const materials = useMemo(() => {
    const md = mats.data;
    if (!md || !md.available) return null;
    const used = new Map<string, number>();
    for (const m of md.materials) {
      const x = model.byId.get(m.batch_id);
      if (x && x.first <= now) used.set(m.item_id, (used.get(m.item_id) ?? 0) + m.quantity);
    }
    const rows = Object.entries(md.pools).map(([iid, p]) => {
      const u = used.get(iid) ?? 0;
      const it = md.items[iid];
      const left = p.released + p.quarantine - u;
      const status = p.unlimited ? "unlimited" : left < -1e-6 ? "short" : u > p.released + 1e-6 ? "quarantine" : "ok";
      return { iid, it, p, used: u, left, status, ratio: p.unlimited ? 9 : (p.released + p.quarantine) > 0 ? left / (p.released + p.quarantine) : left < 0 ? -1 : 9 };
    }).filter((r) => r.it && r.used > 0);
    const rank = { short: 0, quarantine: 1, ok: 2, unlimited: 3 } as const;
    rows.sort((a, b) => rank[a.status] - rank[b.status] || a.ratio - b.ratio || a.it.code.localeCompare(b.it.code));
    return rows;
  }, [mats.data, model, now]);

  if (!model.batches.length) return <div className="panel"><Empty icon={<LuChartGantt />} title={t("sim.empty")} /></div>;

  const iso = (v: number) => new Date(v).toISOString();
  const shortFmt = new Intl.DateTimeFormat(lang === "ar" ? "ar-EG-u-nu-latn" : "en-GB", { timeZone: tz, day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const shortDT = (v: string) => shortFmt.format(new Date(v));
  const dayN = Math.floor((now - model.t0) / (24 * HOUR)) + 1;
  const dayOf = Math.ceil((model.t1 - model.t0) / (24 * HOUR));
  const speedLabel = (n: number) => t("sim.speedOpt", { n: n === 1 ? t("sim.hour") : n < 24 ? t("sim.hours", { n }) : n === 24 ? t("sim.day") : t("sim.days", { n: n / 24 }) });
  const label = (x: SimBatch) => x.b.lot_no || x.b.batch_no;
  const stName = (s: Stage) => t(`sim.legend.${s}` as never);
  const hrs = (h: number) => dur(h * 60);
  const tokenClass = (x: SimBatch) => `sim-tok st-${x.stage}${sel?.kind === "batch" && sel.id === x.b.id ? " sel" : ""}${chain && !chain.has(x.b.id) ? " dim" : ""}`;

  const locText = (w: Where) => {
    const m = w.machine ? machines.get(w.machine)?.code ?? "" : "";
    return ({ planned: t("sim.loc.planned"), queue: t("sim.loc.queue", { m }), run: t("sim.loc.run", { m }), qc: t("sim.loc.qc"),
      stored: t("sim.loc.stored"), shipped: t("sim.loc.shipped"), used: t("sim.loc.used") } as Record<LocKind, string>)[w.kind];
  };

  // Flow connectors between machine cards.
  const flowPaths = model.flows.map(([a, b]) => {
    const A = cardAt.get(a), B = cardAt.get(b);
    if (!A || !B) return null;
    const ax = X(A.x, CARD_W) + (rtl ? 0 : CARD_W), ay = A.y + CARD_H / 2;
    const bx = X(B.x, CARD_W) + (rtl ? CARD_W : 0), by = B.y + CARD_H / 2;
    const fwd = rtl ? bx < ax : bx > ax;
    const d = fwd
      ? `M${ax},${ay} C${(ax + bx) / 2},${ay} ${(ax + bx) / 2},${by} ${bx},${by}`
      : `M${ax},${ay} C${ax + (rtl ? -40 : 40)},${ay + 70} ${bx + (rtl ? 40 : -40)},${by + 70} ${bx},${by}`;
    return <path key={`${a}>${b}`} d={d} className="sim-flow" markerEnd="url(#sim-arrow)" />;
  });

  const selBatch = sel?.kind === "batch" ? model.byId.get(sel.id) : undefined;
  const selMachine = sel?.kind === "machine" ? machines.get(sel.id) : undefined;

  return (
    <div className="sim" tabIndex={-1}>
      <p className="small subtle" style={{ margin: "0 0 10px" }}>{t("sim.lead")}</p>
      <div className="panel sim-bar">
        <div className="sim-clock">
          <strong>{dateTime(iso(now), tz)}</strong>
          <span className="small subtle">{t("sim.dayOf", { n: Math.min(dayN, dayOf), of: dayOf })}</span>
        </div>
        <div className="sim-controls" dir="ltr">
          <Button iconOnly icon={<LuSkipBack />} aria-label={t("sim.toStart")} title={t("sim.toStart")} onClick={() => { setDir(0); setNow(model.t0); }} />
          <Button iconOnly icon={<LuStepBack />} aria-label={t("sim.prevEvent")} title={t("sim.prevEvent")} onClick={() => jumpEvent(-1)} />
          <Button iconOnly icon={<LuRewind />} aria-label={t("sim.back")} title={t("sim.back")} aria-pressed={dir === -1}
            onClick={() => setDir(dir === -1 ? 0 : -1)} />
          <Button variant="primary" iconOnly icon={dir === 1 ? <LuPause /> : <LuPlay />} aria-label={dir === 1 ? t("sim.pause") : t("sim.play")}
            title={dir === 1 ? t("sim.pause") : t("sim.play")}
            onClick={() => { if (dir === 1) setDir(0); else { if (now >= model.t1) setNow(model.t0); setDir(1); } }} />
          <Button iconOnly icon={<LuStepForward />} aria-label={t("sim.nextEvent")} title={t("sim.nextEvent")} onClick={() => jumpEvent(1)} />
          <Button iconOnly icon={<LuSkipForward />} aria-label={t("sim.toEnd")} title={t("sim.toEnd")} onClick={() => { setDir(0); setNow(model.t1); }} />
        </div>
        <label className="sim-speed small">{t("sim.speed")}
          <select className="input" value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
            {SPEEDS.map((n) => <option key={n} value={n}>{speedLabel(n)}</option>)}
          </select>
        </label>
        <input className="sim-slider" type="range" min={model.t0} max={model.t1} step={15 * 60_000} value={now} dir="ltr"
          aria-label={t("sim.dayOf", { n: dayN, of: dayOf })}
          onChange={(e) => { setDir(0); setNow(Number(e.target.value)); }} />
        <span className="small subtle sim-keys">{t("sim.keys")}</span>
      </div>
      {model.unscheduled > 0 && <Notice tone="warn">{t("sim.unscheduled", { n: model.unscheduled })}</Notice>}

      <div className="sim-main">
        <div className="panel sim-floor-wrap">
          <div className="sim-legend small">
            {STAGES.map((s) => <span key={s}><i className={`sim-dot st-${s}`} />{stName(s)}</span>)}
            <span><i className="sim-dot m-running" />{t("sim.st.running")}</span>
            <span><i className="sim-dot m-changeover" />{t("sim.st.changeover")}</span>
            <span><i className="sim-dot m-down" />{t("sim.st.down")}</span>
            <span><i className="sim-dot m-idle" />{t("sim.st.idle")}</span>
          </div>
          <div className="sim-floor" ref={floorRef} style={{ width: W, height: H }} onClick={(e) => { if (e.target === e.currentTarget) setSel(null); }}>
            <svg className="sim-lines" width={W} height={H} aria-hidden>
              <defs><marker id="sim-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0,0 L10,5 L0,10 z" /></marker></defs>
              {flowPaths}
            </svg>
            {model.columns.map((c, ci) => (c.label !== null || c.unused) && (
              <div key={c.key} className="sim-colhead small" style={{ left: X(PAD + ci * COL_W, CARD_W), top: PAD, width: CARD_W }}>{c.unused ? t("sim.unused") : c.label || t("sim.other")}</div>
            ))}
            {Array.from(cardAt.entries()).map(([id, c]) => {
              const m = machines.get(id)!;
              const st = mNow.get(id)!;
              const q = layout.queueOf.get(id)?.length ?? 0;
              const runB = st.op ? model.byId.get(st.op.batch_id) : undefined;
              return (
                <button key={id} type="button" className={`sim-card m-${st.state}${sel?.kind === "machine" && sel.id === id ? " sel" : ""}`}
                  style={{ left: X(c.x, CARD_W), top: c.y, width: CARD_W, height: CARD_H }}
                  onClick={() => setSel({ kind: "machine", id })} title={nameOf(m, lang)}>
                  <span className="sim-card-head"><strong>{m.code}</strong><span className="sim-state">{t(`sim.st.${st.state}` as never)}</span></span>
                  <span className="sim-card-name small subtle">{nameOf(m, lang)}</span>
                  {st.state === "running" && <span className="sim-prog"><span style={{ width: `${Math.round((st.progress ?? 0) * 100)}%` }} /></span>}
                  {st.state === "changeover" && runB && <span className="sim-co small">→ {label(runB)} · {runB.b.code}</span>}
                  {st.state !== "running" && st.state !== "changeover" && st.next && model.byId.get(st.next.batch_id) && q === 0 &&
                    <span className="sim-co sim-nextline small">{t("sim.next", { b: label(model.byId.get(st.next.batch_id)!), t: shortDT(st.next.changeover_start ?? st.next.start_at) })}</span>}
                  {layout.overflow[`m:${id}`] && <span className="sim-more small" style={{ insetInlineStart: 8 + 2 * (TOK_W + 4) }}>{t("sim.more", { n: layout.overflow[`m:${id}`] })}</span>}
                </button>
              );
            })}
            {(["stored", "qc", "shipped"] as const).map((k) => {
              const b = areaBox[k];
              const shippedAll = k === "shipped" ? model.batches.filter((x) => where.get(x.b.id)!.kind === "shipped").length : 0;
              return (
                <div key={k} className={`sim-area a-${k}`} style={{ left: X(b.x, b.w), top: b.y, width: b.w, height: b.h }}>
                  <div className="sim-area-head">
                    {k === "stored" ? <LuWarehouse /> : k === "qc" ? <LuFlaskConical /> : <LuTruck />}
                    <strong>{t(k === "stored" ? "sim.warehouse" : k === "qc" ? "sim.qc" : "sim.dispatch")}</strong>
                    <span className="sim-count">{k === "shipped" ? shippedAll : layout.inArea[k].length}</span>
                  </div>
                  <div className="small subtle sim-area-sub">{t(k === "stored" ? "sim.warehouseSub" : k === "qc" ? "sim.qcSub" : "sim.dispatchSub")}</div>
                  {layout.overflow[k] && <span className="sim-more small" style={{ bottom: 8, insetInlineEnd: 10 }}>{t("sim.more", { n: layout.overflow[k] })}</span>}
                </div>
              );
            })}
            {model.batches.map((x) => {
              const p = layout.pos.get(x.b.id)!;
              return (
                <button key={x.b.id} type="button" className={tokenClass(x)} tabIndex={p.show ? 0 : -1} aria-hidden={!p.show}
                  style={{ transform: `translate(${X(p.x, TOK_W)}px, ${p.y}px)`, opacity: p.show ? (chain && !chain.has(x.b.id) ? 0.35 : 1) : 0, pointerEvents: p.show ? undefined : "none" }}
                  title={`${label(x)} · ${x.b.code}`} onClick={() => setSel({ kind: "batch", id: x.b.id })}>{label(x)}</button>
              );
            })}
          </div>
        </div>
        {sel && <aside className="sim-overlay">
          {selBatch && <div className="panel sim-detail">
            <div className="sim-detail-head">
              <strong>{t("sim.batch", { b: label(selBatch) })}</strong>
              <Button iconOnly size="sm" icon={<LuX />} aria-label={t("sim.close")} onClick={() => setSel(null)} />
            </div>
            <div className="small">{selBatch.b.code} · {nameOf(selBatch.b, lang)}</div>
            <div className="small subtle">{stName(selBatch.stage)} · {qty(selBatch.b.quantity)} {selBatch.b.uom}</div>
            <div className="sim-kv"><span>{t("sim.where")}</span><strong>{locText(where.get(selBatch.b.id)!)}</strong></div>
            <h4>{t("sim.journey")}</h4>
            <ol className="sim-journey small">
              {selBatch.segs.filter((s) => s.kind !== "used" && s.kind !== "shipped").map((s, i) => (
                <li key={i} className={now >= s.from && now < s.to ? "cur" : now >= s.to ? "past" : ""}>
                  <span>{locText({ kind: s.kind, machine: s.machine })}{s.op && s.kind === "run" ? ` · ${s.op.step_name}` : ""}</span>
                  <span className="subtle">{dateTime(iso(s.from), tz)} · {hrs((s.to - s.from) / HOUR)}</span>
                </li>
              ))}
              {(() => { const last = selBatch.segs[selBatch.segs.length - 1]; return (last.kind === "used" || last.kind === "shipped") && (
                <li className={now >= last.from ? "past" : ""}><span>{locText({ kind: last.kind })}</span><span className="subtle">{dateTime(iso(last.from), tz)}</span></li>); })()}
            </ol>
            {selBatch.suppliers.length > 0 && <div className="sim-kv small"><span>{t("sim.fedBy")}</span>
              <span>{selBatch.suppliers.map((id) => model.byId.get(id)).filter(Boolean).map((s) => (
                <button key={s!.b.id} type="button" className="link-btn" onClick={() => setSel({ kind: "batch", id: s!.b.id })}>{label(s!)}</button>))}</span></div>}
            {selBatch.consumers.length > 0 && <div className="sim-kv small"><span>{t("sim.feeds")}</span>
              <span>{selBatch.consumers.map((id) => model.byId.get(id)).filter(Boolean).map((s) => (
                <button key={s!.b.id} type="button" className="link-btn" onClick={() => setSel({ kind: "batch", id: s!.b.id })}>{label(s!)}</button>))}</span></div>}
            <Button size="sm" icon={<LuChartGantt />} onClick={() => onShowBatch(selBatch.b.id)}>{t("sim.showGantt")}</Button>
          </div>}

          {selMachine && (() => {
            const st = mNow.get(selMachine.id)!;
            const cur = st.op ? model.byId.get(st.op.batch_id) : undefined;
            const elapsed = (now - model.t0) / HOUR;
            const busy = busyHours(model, selMachine.id, model.t0, now);
            const nextOps = (model.opsByMachine.get(selMachine.id) ?? []).filter((o) => ms(o.changeover_start ?? o.start_at) > now).slice(0, 4);
            return <div className="panel sim-detail">
              <div className="sim-detail-head">
                <strong>{t("sim.machine", { m: selMachine.code })}</strong>
                <Button iconOnly size="sm" icon={<LuX />} aria-label={t("sim.close")} onClick={() => setSel(null)} />
              </div>
              <div className="small subtle">{nameOf(selMachine, lang)}</div>
              <div className="sim-kv"><span>{t("sim.where")}</span><strong>{t(`sim.st.${st.state}` as never)}</strong></div>
              <div className="sim-kv"><span>{t("sim.nowOn")}</span><span>{cur ? `${label(cur)} · ${cur.b.code}` : t("sim.nothing")}</span></div>
              <div className="sim-kv"><span>{t("sim.util")}</span><span>{elapsed > 0 ? t("sim.utilVal", { p: qty((busy / elapsed) * 100, 0) }) : "—"}</span></div>
              {(layout.queueOf.get(selMachine.id)?.length ?? 0) > 0 && <div className="sim-kv"><span>{t("sim.waitingHere")}</span>
                <span>{layout.queueOf.get(selMachine.id)!.map((x) => label(x)).join(", ")}</span></div>}
              {nextOps.length > 0 && <><h4>{t("sim.nextOps")}</h4><ul className="sim-journey small">
                {nextOps.map((o) => { const b = model.byId.get(o.batch_id); return b && <li key={o.id}><span>{label(b)} · {b.b.code}</span>
                  <span className="subtle">{dateTime(o.changeover_start ?? o.start_at, tz)}</span></li>; })}
              </ul></>}
            </div>;
          })()}
        </aside>}
      </div>

      <div className="sim-analysis">
          <div className="panel sim-panel">
            <h4>{t("sim.stages")}</h4>
            <div className="table-wrap"><table className="table sim-table">
              <thead><tr><th>{t("sim.col.type")}</th><th className="num">{t("sim.col.planned")}</th><th className="num">{t("sim.col.making")}</th>
                <th className="num">{t("sim.col.between")}</th><th className="num">{t("sim.col.qc")}</th><th className="num">{t("sim.col.stored")}</th>
                <th className="num">{t("sim.col.done")}</th></tr></thead>
              <tbody>{stageTable.map((r) => <tr key={r.stage}><td><i className={`sim-dot st-${r.stage}`} />{stName(r.stage)}</td>
                <td className="num">{r.planned}</td><td className="num">{r.making}</td><td className="num">{r.between}</td>
                <td className="num">{r.qc}</td><td className="num">{r.stored}</td><td className="num">{r.done}</td></tr>)}</tbody>
            </table></div>
          </div>

          <div className="panel sim-panel">
            <h4>{t("sim.deliveries")}</h4>
            <div>{t("sim.shipped", { n: deliveries.ready, of: deliveries.total })}</div>
            <div className="small"><span className="text-ok">{t("sim.onTime", { n: deliveries.onTime })}</span>
              {deliveries.ready - deliveries.onTime > 0 && <> · <span className="text-danger">{t("sim.late", { n: deliveries.ready - deliveries.onTime })}</span></>}</div>
          </div>

          <div className="panel sim-panel">
            <div className="sim-panel-head"><h4>{t("sim.waits")}</h4>
              <div className="seg small" role="group">
                <button type="button" aria-pressed={waitMode === "now"} onClick={() => setWaitMode("now")}>{t("sim.w.now")}</button>
                <button type="button" aria-pressed={waitMode === "plan"} onClick={() => setWaitMode("plan")}>{t("sim.w.plan")}</button>
              </div></div>
            <p className="small subtle">{t("sim.waitsHint")}</p>
            <div className="table-wrap"><table className="table sim-table">
              <thead><tr><th>{t("sim.col.type")}</th><th className="num">{t("sim.w.between")}</th><th className="num">{t("sim.w.qc")}</th>
                <th className="num">{t("sim.col.stored")}</th></tr></thead>
              <tbody>{waitTable.map((r) => <tr key={r.stage}><td><i className={`sim-dot st-${r.stage}`} />{stName(r.stage)}</td>
                <td className="num">{r.n ? hrs(r.between) : "—"}</td><td className="num">{r.n ? hrs(r.qc) : "—"}</td>
                <td className="num">{r.n ? hrs(r.stored) : "—"}</td></tr>)}</tbody>
            </table></div>
          </div>

          <div className="panel sim-panel">
            <h4>{t("sim.materials")}</h4>
            <p className="small subtle">{t("sim.materialsHint")}</p>
            {mats.error ? <LoadError error={mats.error} onRetry={mats.reload} />
              : !mats.data ? <div className="skeleton" style={{ height: 80 }} />
              : !materials ? <Notice>{t("sim.mat.old")}</Notice>
              : !materials.length ? <p className="small subtle">{t("sim.mat.none")}</p>
              : <>
                {(plan.options as { material_constraints?: boolean } | null)?.material_constraints === false
                  && materials.some((r) => r.status === "short") && <p className="small text-warn">{t("sim.mat.ignored")}</p>}
                <div className="table-wrap"><table className="table sim-table">
                  <thead><tr><th>{t("sim.mat.item")}</th><th className="num">{t("sim.mat.used")}</th><th className="num">{t("sim.mat.left")}</th></tr></thead>
                  <tbody>{(allMats ? materials : materials.slice(0, 8)).map((r) => <tr key={r.iid} className={`mat-${r.status}`}>
                    <td><strong>{r.it.code}</strong><div className="small subtle">{nameOf(r.it, lang)}</div>
                      {r.status === "short" && <div className="small text-danger">{t("sim.mat.short", { q: `${qty(-r.left)} ${r.it.uom}` })}
                        {r.p.arrival ? ` · ${t("sim.mat.arrives", { d: date(r.p.arrival, tz) })}` : ""}</div>}
                      {r.status === "quarantine" && <div className="small text-warn">{t("sim.mat.quarantine")}</div>}
                      {r.status === "unlimited" && <div className="small subtle">{t("sim.mat.unlimited")}</div>}</td>
                    <td className="num">{qty(r.used)} <span className="subtle">{r.it.uom}</span></td>
                    <td className="num">{r.status === "unlimited" ? "—" : <>{qty(Math.max(0, r.left))} <span className="subtle">{r.it.uom}</span></>}</td>
                  </tr>)}</tbody>
                </table></div>
                {materials.length > 8 && <button type="button" className="link-btn small" onClick={() => setAllMats(!allMats)}>
                  {allMats ? t("sim.mat.less") : t("sim.mat.all", { n: materials.length })}</button>}
              </>}
          </div>
      </div>
    </div>
  );
}
