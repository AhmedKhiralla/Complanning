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

export interface Column { key: string; label: string | null; machines: string[]; unused?: boolean }

export interface Model {
  t0: number; t1: number; batches: SimBatch[]; byId: Map<string, SimBatch>; events: number[];
  opsByMachine: Map<string, POp[]>; columns: Column[]; flows: [string, string][]; unscheduled: number;
}

const stageOf = (b: PBatch): Stage => (b.type === "wip" || b.type === "semi_finished" ? b.type : "finished");

export function buildModel(plan: PlanFull): Model {
  const machineCode = new Map(plan.machines.map((m) => [m.id, m.code]));
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

  // Machine-to-machine flow: consecutive steps of a batch, and the last step of a supplier batch
  // to the first step of the batch that uses it.
  const flowSet = new Set<string>();
  for (const x of batches) {
    const runs = x.segs.filter((s) => s.kind === "run");
    for (let i = 1; i < runs.length; i++) if (runs[i - 1].machine !== runs[i].machine) flowSet.add(`${runs[i - 1].machine}>${runs[i].machine}`);
    for (const sid of x.suppliers) {
      const sup = plan.operations.filter((o) => o.batch_id === sid).sort((a, c) => c.seq - a.seq)[0];
      if (sup && runs[0] && sup.resource_id !== runs[0].machine) flowSet.add(`${sup.resource_id}>${runs[0].machine}`);
    }
  }
  const flows = Array.from(flowSet).map((s) => s.split(">") as [string, string]);

  // Automatic layout as a process flow: one column per process step, from left to right in the order
  // products move. Machines that can do the same step (alternatives) share a column.
  const level = new Map(plan.batches.map((b) => [b.id, b.level]));
  const maxLevel = Math.max(0, ...plan.batches.map((b) => b.level));
  const order = new Map<string, number[]>();
  for (const o of plan.operations) {
    const k = (maxLevel - (level.get(o.batch_id) ?? 0)) * 100 + o.seq;
    order.set(o.resource_id, [...(order.get(o.resource_id) ?? []), k]);
  }
  // Alternatives: machines listed for the same routing step join one group.
  const parent = new Map<string, string>(plan.machines.map((m) => [m.id, m.id]));
  const find = (id: string): string => { const p = parent.get(id) ?? id; if (p === id) return id; const r = find(p); parent.set(id, r); return r; };
  const unite = (a: string, b: string) => { if (!parent.has(a) || !parent.has(b)) return; const ra = find(a), rb = find(b); if (ra !== rb) parent.set(rb, ra); };
  for (const o of plan.operations) for (const e of o.eligible ?? []) unite(o.resource_id, e);
  const groups = new Map<string, string[]>();
  for (const m of plan.machines) groups.set(find(m.id), [...(groups.get(find(m.id)) ?? []), m.id]);
  const gKey = new Map<string, number>();
  for (const [g, ids] of groups) {
    const ks = ids.flatMap((id) => order.get(id) ?? []);
    gKey.set(g, ks.length ? ks.reduce((a, c) => a + c, 0) / ks.length : Infinity);
  }
  // Rank = longest path through the flow, using only edges that go forward in the process (no loops).
  const gEdges = new Map<string, Set<string>>();
  for (const [a, b] of flows) {
    const ga = find(a), gb = find(b);
    if (ga === gb || !(gKey.get(ga)! < gKey.get(gb)!)) continue;
    gEdges.set(ga, (gEdges.get(ga) ?? new Set()).add(gb));
  }
  const rank = new Map<string, number>();
  const used = Array.from(groups.keys()).filter((g) => gKey.get(g) !== Infinity).sort((a, b) => gKey.get(a)! - gKey.get(b)!);
  for (const g of used) rank.set(g, 0);
  for (const g of used) for (const n of gEdges.get(g) ?? []) rank.set(n, Math.max(rank.get(n) ?? 0, rank.get(g)! + 1));
  const nCols = used.length ? Math.max(...used.map((g) => rank.get(g)!)) + 1 : 0;
  const colGroups: string[][] = Array.from({ length: nCols }, () => []);
  for (const g of used) colGroups[rank.get(g)!].push(g);
  // Inside a column, keep each group near the machines that feed it (fewer crossing arrows).
  const yOf = new Map<string, number>();
  const preds = new Map<string, string[]>();
  for (const [a, b] of flows) preds.set(b, [...(preds.get(b) ?? []), a]);
  const stepName = new Map<string, string[]>();
  for (const o of plan.operations) stepName.set(o.resource_id, [...(stepName.get(o.resource_id) ?? []), o.step_name]);
  const cols: Column[] = [];
  colGroups.forEach((gs, ci) => {
    const bary = (g: string) => {
      const ys = groups.get(g)!.flatMap((id) => (preds.get(id) ?? []).map((p) => yOf.get(p)).filter((v): v is number => v !== undefined));
      return ys.length ? ys.reduce((a, c) => a + c, 0) / ys.length : gKey.get(g)!;
    };
    gs.sort((a, b) => bary(a) - bary(b) || gKey.get(a)! - gKey.get(b)!);
    const ids = gs.flatMap((g) => groups.get(g)!.slice().sort((a, b) => (machineCode.get(a) ?? "").localeCompare(machineCode.get(b) ?? "")));
    ids.forEach((id, i) => yOf.set(id, i));
    const names = ids.flatMap((id) => stepName.get(id) ?? []);
    const count = new Map<string, number>();
    for (const n of names) count.set(n, (count.get(n) ?? 0) + 1);
    const top = Array.from(count.entries()).sort((a, b) => b[1] - a[1]).map(([n]) => n);
    cols.push({ key: `c${ci}`, label: top.slice(0, 2).join(" · ") || null, machines: ids });
  });
  const idle = Array.from(groups.keys()).filter((g) => gKey.get(g) === Infinity).flatMap((g) => groups.get(g)!);
  if (idle.length) cols.push({ key: "unused", label: "", machines: idle, unused: true });

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
