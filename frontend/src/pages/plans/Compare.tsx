import { useEffect, useState, type ReactNode } from "react";
import { LuArrowLeft, LuColumns3 } from "react-icons/lu";
import { Badge, Empty, LoadError, PageHead } from "../../components/ui";
import { useDuration } from "../../components/rules";
import { get } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { Link } from "../../lib/router";
import { useSession } from "../../lib/session";
import { OBJ_ICON, type PlanRow } from "./Plans";

interface Delivery { code: string; market: string; due_date: string; quantity: number; available_at: string | null; late_hours: number | null; on_time: boolean; }
type Full = PlanRow & { demand: Delivery[] };

export function ComparePlans() {
  const { t, qty, date, dateTime } = useI18n();
  const { me } = useSession();
  const dur = useDuration();
  const ids = (new URLSearchParams(window.location.search).get("ids") ?? "").split(",").filter(Boolean).slice(0, 3);
  const [plans, setPlans] = useState<Full[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    let live = true;
    Promise.all(ids.map((id) => get<Full>(`/api/plans/${id}`))).then((r) => live && setPlans(r)).catch((e) => live && setError(e));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids.join(",")]);
  const back = <Link to="/plans" className="back-link"><LuArrowLeft className="flip-rtl" /> {t("pv.back")}</Link>;
  if (ids.length < 2) return <>{back}<PageHead title={t("cmp.title")} /><div className="panel"><Empty icon={<LuColumns3 />} title={t("cmp.pick")} /></div></>;
  if (error) return <>{back}<LoadError error={error} onRetry={() => window.location.reload()} /></>;
  if (!plans) return <>{back}<PageHead title={t("cmp.title")} /><div className="panel"><div className="panel-body"><div className="skeleton" style={{ height: 240 }} /></div></div></>;
  const tz = (id: string) => me?.sites.find((s) => s.id === id)?.timezone ?? "UTC";
  const costCur = plans.find((p) => p.kpis?.cost)?.kpis?.cost?.currency ?? null;
  const currencies = Array.from(new Set(plans.flatMap((p) => (p.kpis?.value ?? []).map((v) => v.currency)))).sort();

  type Row = { label: string; values: (number | null)[]; show: (v: number | null, p: Full) => ReactNode; better: "high" | "low" | null };
  const rows: Row[] = [
    { label: t("pv.kpi.onTime"), values: plans.map((p) => p.kpis?.on_time ?? null), better: "high",
      show: (v, p) => v === null ? "—" : `${v} / ${p.kpis?.demand_lines}` },
    { label: t("pv.kpi.otif"), values: plans.map((p) => p.kpis?.otif?.pct ?? null), better: "high", show: (v) => v === null ? "—" : `${qty(v, 0)}%` },
    { label: t("cmp.otifQty"), values: plans.map((p) => p.kpis?.otif?.qty_pct ?? null), better: "high", show: (v) => v === null ? "—" : `${qty(v, 1)}%` },
    { label: t("cmp.late"), values: plans.map((p) => p.kpis?.late ?? null), better: "low", show: (v) => v ?? "—" },
    { label: t("cmp.unfilled"), values: plans.map((p) => p.kpis?.unfilled ?? null), better: "low", show: (v) => v ?? "—" },
    { label: t("pv.kpi.batches"), values: plans.map((p) => p.kpis?.scheduled ?? null), better: null, show: (v) => v ?? "—" },
    { label: t("pv.kpi.co"), values: plans.map((p) => p.kpis?.changeover_hours ?? null), better: "low", show: (v) => v === null ? "—" : dur(v * 60) },
    { label: t("cmp.changeovers"), values: plans.map((p) => p.kpis?.changeovers ?? null), better: "low", show: (v) => v ?? "—" },
    ...currencies.map((c): Row => ({
      label: `${t("pv.kpi.value")} (${c})`, better: "high",
      values: plans.map((p) => p.kpis?.value.find((v) => v.currency === c)?.on_time ?? null), show: (v) => v === null ? "—" : qty(v, 0),
    })),
    { label: t("pv.kpi.finish"), values: plans.map((p) => (p.kpis?.finish ? Date.parse(p.kpis.finish) : null)), better: "low",
      show: (v, p) => v === null ? "—" : dateTime(new Date(v).toISOString(), tz(p.site_id)) },
    { label: t("cmp.warnings"), values: plans.map((p) => p.kpis?.warnings.length ?? null), better: "low", show: (v) => v ?? "—" },
    ...(costCur ? [
      { label: `${t("pv.kpi.margin")} (${costCur})`, better: "high" as const, show: (v: number | null) => v === null ? "—" : qty(v, 0),
        values: plans.map((p) => (p.kpis?.cost?.currency === costCur ? p.kpis.cost.margin : null)) },
      { label: `${t("pv.matCost")} (${costCur})`, better: "low" as const, show: (v: number | null) => v === null ? "—" : qty(v, 0),
        values: plans.map((p) => (p.kpis?.cost?.currency === costCur ? p.kpis.cost.materials : null)) },
    ] : []),
  ];
  const best = (r: Row) => {
    const vs = r.values.filter((v): v is number => v !== null);
    if (!r.better || vs.length < 2 || vs.every((v) => v === vs[0])) return null;
    return r.better === "high" ? Math.max(...vs) : Math.min(...vs);
  };
  const keyOf = (d: Delivery) => `${d.code}|${d.market}|${d.due_date}`;
  const lines = Array.from(new Map(plans.flatMap((p) => p.demand.map((d) => [keyOf(d), d] as const))).values())
    .sort((a, b) => a.due_date.localeCompare(b.due_date) || a.code.localeCompare(b.code));
  const late = (h: number) => t("pv.st.late", { d: h >= 24 ? t("pv.nDays", { n: qty(h / 24, 1) }) : t("pv.nHours", { n: qty(h, 0) }) });

  return (
    <>
      {back}
      <PageHead title={t("cmp.title")} lead={t("cmp.lead")} />
      <div className="panel"><div className="table-wrap">
        <table className="table cmp-table">
          <thead><tr>
            <th>{t("cmp.kpi")}</th>
            {plans.map((p) => (
              <th key={p.id}>
                <Link to={`/plans/${p.id}`} className="cmp-head">
                  <span className={`obj obj-${p.objective}`}>{OBJ_ICON[p.objective]}</span>
                  <span><strong>{p.name}</strong><span className="small muted">{t(`obj.${p.objective}` as never)} · {date(p.horizon_start, "UTC")} – {date(p.horizon_end, "UTC")}</span></span>
                </Link>
                {p.status === "released" && <Badge tone="ok" dot>{t("pv.st.released")}</Badge>}
              </th>
            ))}
          </tr></thead>
          <tbody>{rows.map((r) => {
            const b = best(r);
            return (
              <tr key={r.label}>
                <th scope="row">{r.label}</th>
                {r.values.map((v, i) => <td key={i} className={`num ${b !== null && v === b ? "best" : ""}`}>{r.show(v, plans[i])}</td>)}
              </tr>
            );
          })}</tbody>
        </table>
      </div></div>

      <div className="section-head"><div className="titles"><h2>{t("cmp.deliveries")}</h2></div></div>
      <div className="panel"><div className="table-wrap">
        <table className="table cmp-table">
          <thead><tr><th>{t("pv.product")}</th><th>{t("pv.due")}</th>{plans.map((p) => <th key={p.id}>{p.name}</th>)}</tr></thead>
          <tbody>{lines.map((l) => (
            <tr key={keyOf(l)}>
              <td><span className="mono-id cell-main">{l.code}</span> <Badge tone="brand">{l.market}</Badge></td>
              <td className="small num">{date(l.due_date, "UTC")}</td>
              {plans.map((p) => {
                const d = p.demand.find((x) => keyOf(x) === keyOf(l));
                if (!d) return <td key={p.id} className="subtle">—</td>;
                return (
                  <td key={p.id}>
                    {d.on_time ? <Badge tone="ok" dot>{t("pv.st.onTime")}</Badge> : d.available_at && d.late_hours !== null
                      ? <Badge tone="danger" dot>{late(Number(d.late_hours))}</Badge> : <Badge tone="danger">{t("pv.st.unfilled")}</Badge>}
                    {d.available_at && <div className="small subtle num">{dateTime(d.available_at, tz(p.site_id))}</div>}
                  </td>
                );
              })}
            </tr>
          ))}</tbody>
        </table>
      </div></div>
    </>
  );
}
