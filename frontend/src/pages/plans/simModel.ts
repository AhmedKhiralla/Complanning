// Plan simulation model: where every batch is and what every machine does at any moment of the plan.
// Pure functions over the stored plan; the plan is played back, nothing is simulated at random.
import type { PBatch, PlanFull, POp } from "./PlanView";

export const HOUR = 3600_000;
const ms = (s: string | null | undefined) => (s ? Date.parse(s) : NaN);
const startOf = (o: POp) => ms(o.changeover_start ?? o.start_at);

export type Stage = "wip" | "semi_finished" | "finished";
export type LocKind = "planned" | "queue" | "run" | "qc" | "stored" | "shipped" | "used";
export interface Seg { from: number; to: number; kind: LocKind; machine?: string; op?: POp }
export interface SimBatch { b: PBatch; stage: Stage; segs: Seg[]; first: number; consumers: string[]; suppliers: string[] }
export interface Where { kind: LocKind; machine?: string; op?: POp; seg?: Seg }

export interface SimMaterialData {
  available: boolean;
  pools: Record<string, { released: number; quarantine: number; quarantine_ready: string | null; arrival: string | null; has_lead: boolean; unlimited: boolean }>;
  items: Record<string, { code: string; name_en: string; name_ar: string | null; type: string; uom: string }>;
  materials: { batch_id: string; item_id: string; quantity: number }[];
}

export interface Column { key: string; label: string | null; machines: string[] }

export interface Model {
  t0: number; t1: number; batches: SimBatch[]; byId: Map<string, SimBatch>; events: number[];
  opsByMachine: Map<string, POp[]>; columns: Column[]; flows: [string, string][]; unscheduled: number;
}

const stageOf = (b: PBatch): Stage => (b.type === "wip" || b.type === "semi_finished" ? b.type : "finished");

export function buildModel(plan: PlanFull): Model {
  const opsBy = new Map<string, POp[]>();
  for (const o of plan.operations) {
    const l = opsBy.get(o.batch_id) ?? [];
    l.push(o);
    opsBy.set(o.batch_id, l);
  }
  const consumersOf = new Map<string, string[]>(), suppliersOf = new Map<string, string[]>();
  for (const l of plan.links) {
    consumersOf.set(l.supplier_id, [...(consumersOf.get(l.supplier_id) ?? []), l.consumer_id]);
    suppliersOf.set(l.consumer_id, [...(suppliersOf.get(l.consumer_id) ?? []), l.supplier_id]);
  }
  // A batch starts when its first step starts; cleaning before it belongs to the machine, not the batch.
  const firstStart = new Map<string, number>();
  for (const [bid, ops] of opsBy) firstStart.set(bid, Math.min(...ops.map((o) => ms(o.start_at))));

  const batches: SimBatch[] = [];
  let unscheduled = 0;
  for (const b of plan.batches) {
    const ops = (opsBy.get(b.id) ?? []).slice().sort((a, c) => a.seq - c.seq || ms(a.start_at) - ms(c.start_at));
    if (b.status !== "scheduled" || !ops.length) { unscheduled++; continue; }
    const segs: Seg[] = [];
    const first = firstStart.get(b.id)!;
    let t = first;
    for (const o of ops) {
      const s = ms(o.start_at), e = ms(o.end_at);
      if (s > t) segs.push({ from: t, to: s, kind: "queue", machine: o.resource_id, op: o });
      segs.push({ from: Math.min(s, Math.max(t, s)), to: e, kind: "run", machine: o.resource_id, op: o });
      t = Math.max(t, e);
    }
    const avail = Number.isNaN(ms(b.available_at)) ? t : Math.max(t, ms(b.available_at));
    if (avail > t) segs.push({ from: t, to: avail, kind: "qc" });
    const consumers = consumersOf.get(b.id) ?? [];
    const stage = stageOf(b);
    if (consumers.length) {
      const used = Math.max(avail, ...consumers.map((c) => firstStart.get(c) ?? avail));
      if (used > avail) segs.push({ from: avail, to: used, kind: "stored" });
      segs.push({ from: used, to: Infinity, kind: "used" });
    } else if (stage === "finished" && !Number.isNaN(ms(b.ship_at))) {
      const ship = Math.max(avail, ms(b.ship_at));
      if (ship > avail) segs.push({ from: avail, to: ship, kind: "stored" });
      segs.push({ from: ship, to: Infinity, kind: "shipped" });
    } else {
      segs.push({ from: avail, to: Infinity, kind: "stored" });
    }
    batches.push({ b, stage, segs, first, consumers, suppliers: suppliersOf.get(b.id) ?? [] });
  }

  const starts = batches.map((x) => x.first);
  const ends = batches.flatMap((x) => x.segs.map((s) => (s.to === Infinity ? s.from : s.to)));
  const planStart = ms(plan.starts_at);
  const t0 = Math.min(Number.isNaN(planStart) ? Infinity : planStart, ...starts);
  const t1 = Math.max(t0 + 24 * HOUR, ...ends) + 12 * HOUR;

  const ev = new Set<number>();
  for (const x of batches) for (const s of x.segs) { ev.add(s.from); if (s.to !== Infinity) ev.add(s.to); }
  for (const o of plan.operations) if (o.changeover_start) ev.add(ms(o.changeover_start));
  const events = Array.from(ev).filter((v) => v >= t0 && v <= t1).sort((a, c) => a - c);

  const opsByMachine = new Map<string, POp[]>();
  for (const o of plan.operations) {
    const l = opsByMachine.get(o.resource_id) ?? [];
    l.push(o);
    opsByMachine.set(o.resource_id, l);
  }
  for (const l of opsByMachine.values()) l.sort((a, c) => startOf(a) - startOf(c));

  // Automatic layout: machines in columns by area, areas ordered by where they come in the process
  // (bulk steps first, then semi-finished, then finished; by step number inside each level).
  const level = new Map(plan.batches.map((b) => [b.id, b.level]));
  const maxLevel = Math.max(0, ...plan.batches.map((b) => b.level));
  const order = new Map<string, number[]>();
  for (const o of plan.operations) {
    const k = (maxLevel - (level.get(o.batch_id) ?? 0)) * 100 + o.seq;
    order.set(o.resource_id, [...(order.get(o.resource_id) ?? []), k]);
  }
  const mKey = (id: string) => { const l = order.get(id); return l?.length ? l.reduce((a, c) => a + c, 0) / l.length : Infinity; };
  const areas = new Map<string, string[]>();
  for (const m of plan.machines) {
    const a = (m.area ?? "").trim();
    areas.set(a, [...(areas.get(a) ?? []), m.id]);
  }
  const columns: Column[] = Array.from(areas.entries()).map(([a, ids]) => {
    const sorted = ids.slice().sort((x, y) => mKey(x) - mKey(y));
    const used = sorted.map(mKey).filter((v) => v !== Infinity);
    return { key: a || "~", label: a || null, machines: sorted, k: used.length ? Math.min(...used) : Infinity };
  }).sort((x, y) => x.k - y.k || x.key.localeCompare(y.key)).map(({ key, label, machines }) => ({ key, label, machines }));
  // Split very tall columns so the floor stays readable.
  const cols: Column[] = [];
  for (const c of columns) {
    for (let i = 0; i < c.machines.length; i += 5) cols.push({ key: `${c.key}#${i}`, label: i === 0 ? c.label : null, machines: c.machines.slice(i, i + 5) });
  }

  const flowSet = new Set<string>();
  for (const x of batches) {
    const runs = x.segs.filter((s) => s.kind === "run");
    for (let i = 1; i < runs.length; i++) if (runs[i - 1].machine !== runs[i].machine) flowSet.add(`${runs[i - 1].machine}>${runs[i].machine}`);
    // Supplier batches feed the first machine of this batch.
    for (const sid of x.suppliers) {
      const sup = plan.operations.filter((o) => o.batch_id === sid).sort((a, c) => c.seq - a.seq)[0];
      if (sup && runs[0] && sup.resource_id !== runs[0].machine) flowSet.add(`${sup.resource_id}>${runs[0].machine}`);
    }
  }
  const flows = Array.from(flowSet).map((s) => s.split(">") as [string, string]);

  return { t0, t1, batches, byId: new Map(batches.map((x) => [x.b.id, x])), events, opsByMachine, columns: cols, flows, unscheduled };
}

export function whereAt(x: SimBatch, t: number): Where {
  if (t < x.first) return { kind: "planned" };
  // Several runs can overlap (steps that run together): the latest one that has started wins.
  let found: Seg | undefined;
  for (const s of x.segs) if (t >= s.from && t < s.to) found = s;
  if (!found) found = x.segs[x.segs.length - 1];
  return { kind: found.kind, machine: found.machine, op: found.op, seg: found };
}

export type MState = "running" | "changeover" | "down" | "idle";
export interface MachineNow { state: MState; op?: POp; progress?: number; next?: POp }

export function machineAt(model: Model, plan: PlanFull, id: string, t: number): MachineNow {
  const ops = model.opsByMachine.get(id) ?? [];
  for (const o of ops) {
    const s = ms(o.start_at), e = ms(o.end_at);
    if (t >= s && t < e) return { state: "running", op: o, progress: (t - s) / Math.max(1, e - s), next: ops.find((n) => startOf(n) >= e && n !== o) };
    if (o.changeover_start && t >= ms(o.changeover_start) && t < ms(o.changeover_end ?? o.start_at)) return { state: "changeover", op: o, next: o };
  }
  const down = plan.downtime.some((d) => d.resource_id === id && t >= ms(d.starts_at) && t < ms(d.ends_at));
  return { state: down ? "down" : "idle", next: ops.find((o) => startOf(o) > t) };
}

/** Hours a batch spent in each kind of wait, up to time t (Infinity for the whole plan). */
export function waits(x: SimBatch, t: number) {
  const out = { between: 0, qc: 0, stored: 0 };
  for (const s of x.segs) {
    if (s.to === Infinity) continue;
    const a = Math.max(s.from, x.first), e = Math.min(s.to, t);
    if (e <= a) continue;
    const h = (e - a) / HOUR;
    if (s.kind === "queue") out.between += h;
    else if (s.kind === "qc") out.qc += h;
    else if (s.kind === "stored") out.stored += h;
  }
  return out;
}

export function busyHours(model: Model, id: string, from: number, t: number): number {
  let h = 0;
  const add = (s: number, e: number) => { const a = Math.max(from, s), b = Math.min(t, e); if (b > a) h += (b - a) / HOUR; };
  for (const o of model.opsByMachine.get(id) ?? []) {
    if (o.changeover_start && o.changeover_end) add(ms(o.changeover_start), ms(o.changeover_end));
    add(ms(o.start_at), ms(o.end_at));
  }
  return h;
}
