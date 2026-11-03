import { useEffect, useMemo, useState, type DragEvent } from "react";
import { LuArrowLeft, LuArrowRight, LuGripVertical, LuPlus, LuSearch, LuStar, LuTrash2, LuWorkflow, LuX } from "react-icons/lu";
import { Badge, Button, Empty, LoadError, LoadingRows, Notice, PageHead, errorText, fieldErrors, useLoad, useToast } from "../../components/ui";
import { PickProducedItem, ReadOnlyNote, TypeBadge, str } from "../../components/master";
import { get, put } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { Link, navigate } from "../../lib/router";
import { usePerms } from "../../lib/session";
import { nameOf, type ItemType, type Resource, type Step } from "../../lib/types";

interface RoutingRow {
  item_id: string; code: string; name_en: string; name_ar: string | null; type: ItemType; routing_id: string | null;
  step_count: number; machines: string[];
}

export function Routings() {
  const { t, lang } = useI18n();
  const { siteId, site, editSite, editCompany } = usePerms();
  const list = useLoad(() => (siteId ? get<{ items: RoutingRow[] }>(`/api/sites/${siteId}/routings`) : Promise.resolve(null)), [siteId]);
  const [picking, setPicking] = useState(false);
  if (!siteId) return <><PageHead title={t("routings.title")} /><Notice>{t("common.noSite")}</Notice></>;
  const rows = list.data?.items ?? [];
  const options = [...rows].sort((a, b) => Number(a.step_count > 0) - Number(b.step_count > 0)).map((r) => ({
    id: r.item_id, label: `${r.code} · ${nameOf(r, lang)}`, group: t(`type.${r.type}` as never),
    note: r.step_count ? t("pick.stepsDefined", { n: r.step_count }) : t("pick.noneYet") }));
  return (
    <>
      <PageHead title={t("routings.title")} lead={t("routings.lead", { site: site?.name ?? "" })}
        actions={editSite(siteId) ? <Button variant="primary" icon={<LuPlus />} onClick={() => setPicking(true)}>{t("routings.new")}</Button> : undefined} />
      {picking && <PickProducedItem title={t("routings.new")} lead={t("routings.newLead", { site: site?.name ?? "" })} options={options}
        canCreateItem={editCompany} onClose={() => setPicking(false)} onPick={(id) => navigate(`/master/routings/${id}`)} />}
      {list.error ? <div className="panel"><LoadError error={list.error} onRetry={list.reload} /></div> : list.data && rows.length === 0 ? (
        <div className="panel"><Empty icon={<LuWorkflow />} title={t("routings.empty")} body={t("boms.emptyBody")} /></div>
      ) : (
        <div className="panel table-wrap">
          <table className="table">
            <thead><tr><th>{t("common.code")}</th><th>{t("common.name")}</th><th>{t("items.f.type")}</th><th className="num">{t("routings.steps")}</th><th>{t("routings.machines")}</th></tr></thead>
            {!list.data ? <LoadingRows cols={5} rows={7} /> : (
              <tbody>
                {rows.map((r) => (
                  <tr key={r.item_id} className="clickable" tabIndex={0} onClick={() => navigate(`/master/routings/${r.item_id}`)}
                    onKeyDown={(e) => { if (e.key === "Enter") navigate(`/master/routings/${r.item_id}`); }}>
                    <td className="mono-id cell-main" dir="ltr" style={{ textAlign: "start" }}>{r.code}</td>
                    <td>{nameOf(r, lang)}</td>
                    <td><TypeBadge type={r.type} /></td>
                    <td className="num">{r.step_count || <span className="subtle">—</span>}</td>
                    <td>{r.machines.length ? <div className="chip-row">{r.machines.map((m) => <span key={m} className="mchip">{m}</span>)}</div>
                      : <span className="subtle small">{t("routings.notDefined")}</span>}</td>
                  </tr>
                ))}
              </tbody>
            )}
          </table>
        </div>
      )}
    </>
  );
}

// ------------------------------------------------------------------ editor
interface RoutingData {
  item: { id: string; code: string; name_en: string; name_ar: string | null; type: ItemType; stock_uom: string };
  routing: { id: string; notes: string | null } | null;
  steps: (Step & { id: string })[];
  active_batch: { batch_size: number; batch_uom: string } | null;
}
type EStep = Step & { key: string };
let seq = 0;
const nk = () => `k${++seq}`;
const MACHINE = "application/x-cp-machine";
const STEP = "application/x-cp-step";

export function RoutingEditor({ itemId }: { itemId: string }) {
  const { t, lang, qty } = useI18n();
  const toast = useToast();
  const { siteId, editSite } = usePerms();
  const data = useLoad(() => (siteId ? get<RoutingData>(`/api/sites/${siteId}/routings/${itemId}`) : Promise.resolve(null)), [siteId, itemId]);
  const res = useLoad(() => (siteId ? get<{ items: Resource[] }>(`/api/sites/${siteId}/resources`) : Promise.resolve(null)), [siteId]);
  const [steps, setSteps] = useState<EStep[]>([]);
  const [original, setOriginal] = useState("");
  const [q, setQ] = useState("");
  const [over, setOver] = useState<string | null>(null);
  const [dragStep, setDragStep] = useState<number | null>(null);
  const [justAdded, setJustAdded] = useState<string | null>(null);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const canEdit = editSite(siteId);

  useEffect(() => {
    if (!data.data) return;
    const s = data.data.steps.map((x) => ({ ...x, key: x.id ?? nk(), resources: x.resources.map((r) => ({ ...r })) }));
    setSteps(s); setOriginal(JSON.stringify(strip(s)));
  }, [data.data]);

  const machines = (res.data?.items ?? []).filter((m) => m.active);
  const byId = useMemo(() => new Map(machines.map((m) => [m.id, m])), [machines]);
  const dirty = JSON.stringify(strip(steps)) !== original;
  const filtered = machines.filter((m) => !q.trim() || [m.code, m.name_en, m.name_ar ?? "", m.area ?? ""].some((s) => s.toLowerCase().includes(q.trim().toLowerCase())));
  const areas = Array.from(new Set(filtered.map((m) => m.area ?? ""))).sort();

  const update = (key: string, fn: (s: EStep) => EStep) => setSteps((all) => all.map((s) => (s.key === key ? fn(s) : s)));
  const addMachine = (key: string, resourceId: string) => {
    update(key, (s) => s.resources.some((r) => r.resource_id === resourceId) ? s
      : { ...s, resources: [...s.resources, { resource_id: resourceId, preferred: s.resources.length === 0 }] });
    setJustAdded(`${key}:${resourceId}`);
    setTimeout(() => setJustAdded(null), 700);
  };
  const move = (from: number, to: number) => {
    if (to < 0 || to >= steps.length || from === to) return;
    setSteps((all) => { const next = [...all]; const [x] = next.splice(from, 1); next.splice(to, 0, x); return next; });
  };

  const onDropStep = (e: DragEvent, key: string, index: number) => {
    e.preventDefault(); setOver(null);
    const m = e.dataTransfer.getData(MACHINE);
    if (m) { addMachine(key, m); return; }
    const from = e.dataTransfer.getData(STEP);
    if (from !== "") move(Number(from), index);
    setDragStep(null);
  };

  const save = async () => {
    setBusy(true); setErrs({}); setGeneral(null);
    try {
      const d = await put<RoutingData>(`/api/sites/${siteId}/routings/${itemId}`, { steps: strip(steps) });
      data.setData(d); toast(t("routings.savedToast"));
    } catch (e) { setErrs(fieldErrors(e)); setGeneral(errorText(e, t)); }
    finally { setBusy(false); }
  };

  if (!siteId) return <Notice>{t("common.noSite")}</Notice>;
  if (data.error) return <div className="panel"><LoadError error={data.error} onRetry={data.reload} /></div>;
  const d = data.data;
  const batch = d?.active_batch;
  const stepHours = (s: EStep) => {
    const pref = s.resources.find((r) => r.preferred) ?? s.resources[0];
    const m = pref ? byId.get(pref.resource_id) : undefined;
    if (!m) return null;
    const eff = Number(m.efficiency_pct) / 100;
    const setup = Number(s.setup_minutes || 0) / 60;
    if (s.time_model === "fixed") {
      const min = Number(pref?.fixed_minutes || s.fixed_minutes || 0);
      return min ? { h: min / 60 / eff + setup, code: m.code } : null;
    }
    const rate = Number(pref?.rate_per_hour || s.rate_per_hour || 0);
    if (!rate || !batch || batch.batch_uom !== d?.item.stock_uom) return null;
    return { h: Number(batch.batch_size) / rate / eff + setup, code: m.code };
  };

  return (
    <>
      <Link to="/master/routings" className="back-link"><LuArrowLeft />{t("routings.back")}</Link>
      <PageHead title={d ? nameOf(d.item, lang) : t("app.loading")}
        lead={d ? <span className="row wrap"><span className="mono-id">{d.item.code}</span><TypeBadge type={d.item.type} />
          <span className="small muted">{batch ? t("routings.batchInfo", { qty: qty(batch.batch_size), uom: batch.batch_uom }) : t("routings.noBatch")}</span></span> : undefined}
        actions={canEdit ? <>
          {dirty && <Badge tone="warn" dot>{t("common.unsaved")}</Badge>}
          {dirty && <Button variant="ghost" onClick={() => data.data && setSteps(data.data.steps.map((x) => ({ ...x, key: x.id ?? nk() })))}>{t("common.discardChanges")}</Button>}
          <Button variant="primary" busy={busy} disabled={!dirty} onClick={save}>{t("routings.save")}</Button>
        </> : undefined} />
      <ReadOnlyNote show={!canEdit} />
      {canEdit && <p className="muted small" style={{ marginBottom: 12 }}>{t("routings.editorLead")}</p>}
      {general && <div style={{ marginBottom: 12 }}><Notice tone="danger">{general}</Notice></div>}

      <div className={`flow-layout ${canEdit ? "" : "readonly"}`}>
        {canEdit && (
          <aside className="palette panel" aria-label={t("routings.palette")}>
            <div className="panel-head"><h3>{t("routings.palette")}</h3></div>
            <div className="palette-search"><LuSearch aria-hidden />
              <input className="input" type="search" placeholder={t("routings.find")} aria-label={t("routings.find")} value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            {machines.length === 0 ? <p className="small subtle" style={{ padding: "0 14px 14px" }}>{t("routings.noMachines")}</p> : (
              <div className="palette-list">
                {areas.map((a) => (
                  <div key={a || "none"} className="palette-group">
                    <div className="palette-area">{a || t("machines.noArea")}</div>
                    {filtered.filter((m) => (m.area ?? "") === a).map((m) => (
                      <div key={m.id} className="pchip" draggable title={nameOf(m, lang)}
                        onDragStart={(e) => { e.dataTransfer.setData(MACHINE, m.id); e.dataTransfer.effectAllowed = "copy"; }}>
                        <LuGripVertical aria-hidden className="grip" />
                        <span className="mono-id">{m.code}</span>
                        <span className="pname">{nameOf(m, lang)}</span>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            )}
            <p className="small subtle palette-hint">{t("routings.dragHint")}</p>
          </aside>
        )}

        <div className="flow-board" aria-busy={!d}>
          {!d ? <div className="skeleton" style={{ width: "40%" }} /> : (
            <div className="flow-track">
              {steps.map((s, i) => {
                const err = errs[`steps.${i}`];
                const est = stepHours(s);
                return (
                  <div className="flow-item" key={s.key}>
                    <article className={`step-card ${over === s.key ? "over" : ""} ${err ? "invalid" : ""} ${dragStep === i ? "dragging" : ""}`}
                      onDragOver={(e) => { if (!canEdit) return; e.preventDefault(); setOver(s.key); }}
                      onDragLeave={() => setOver((o) => (o === s.key ? null : o))}
                      onDrop={(e) => canEdit && onDropStep(e, s.key, i)}
                      aria-label={t("routings.step", { n: i + 1 })}>
                      <header className="step-head">
                        {canEdit && <span className="drag-handle" draggable aria-hidden
                          onDragStart={(e) => { e.dataTransfer.setData(STEP, String(i)); e.dataTransfer.effectAllowed = "move"; setDragStep(i); }}
                          onDragEnd={() => setDragStep(null)}><LuGripVertical /></span>}
                        <span className="step-no">{i + 1}</span>
                        <input className="step-name" value={s.name} disabled={!canEdit} aria-label={t("routings.stepName")} maxLength={80}
                          onChange={(e) => update(s.key, (x) => ({ ...x, name: e.target.value }))} />
                        {canEdit && <div className="step-tools">
                          <button type="button" className="icon-btn" aria-label={t("routings.moveEarlier")} disabled={i === 0} onClick={() => move(i, i - 1)}><LuArrowLeft className="flip-rtl" /></button>
                          <button type="button" className="icon-btn" aria-label={t("routings.moveLater")} disabled={i === steps.length - 1} onClick={() => move(i, i + 1)}><LuArrowRight className="flip-rtl" /></button>
                          <button type="button" className="icon-btn" aria-label={t("routings.removeStep")} onClick={() => setSteps(steps.filter((x) => x.key !== s.key))}><LuTrash2 /></button>
                        </div>}
                      </header>

                      <div className="step-time">
                        <div className="seg" role="group" aria-label={t("routings.time")}>
                          <button type="button" disabled={!canEdit} aria-pressed={s.time_model === "fixed"} onClick={() => update(s.key, (x) => ({ ...x, time_model: "fixed" }))}>{t("routings.fixed")}</button>
                          <button type="button" disabled={!canEdit} aria-pressed={s.time_model === "rate"} onClick={() => update(s.key, (x) => ({ ...x, time_model: "rate" }))}>{t("routings.rate")}</button>
                        </div>
                        <label className="mini">
                          <span>{s.time_model === "fixed" ? t("routings.minutes") : t("routings.ratePer", { uom: d.item.stock_uom })}</span>
                          <input className="input num" type="number" min="0" step="any" disabled={!canEdit}
                            value={str(s.time_model === "fixed" ? s.fixed_minutes : s.rate_per_hour)}
                            onChange={(e) => update(s.key, (x) => s.time_model === "fixed"
                              ? { ...x, fixed_minutes: e.target.value === "" ? null : Number(e.target.value) }
                              : { ...x, rate_per_hour: e.target.value === "" ? null : Number(e.target.value) })} />
                        </label>
                        <label className="mini">
                          <span>{t("routings.setup")}</span>
                          <input className="input num" type="number" min="0" step="any" disabled={!canEdit} value={str(s.setup_minutes)}
                            onChange={(e) => update(s.key, (x) => ({ ...x, setup_minutes: Number(e.target.value || 0) }))} />
                        </label>
                      </div>

                      <div className={`dropzone ${s.resources.length ? "" : "empty"}`}>
                        {s.resources.length === 0 && <span className="drop-hint">{t("routings.dropHere")}</span>}
                        {s.resources.map((r) => {
                          const m = byId.get(r.resource_id);
                          const ownKey = s.time_model === "fixed" ? "fixed_minutes" : "rate_per_hour";
                          return (
                            <div key={r.resource_id} className={`mslot ${r.preferred ? "preferred" : ""} ${justAdded === `${s.key}:${r.resource_id}` ? "pop" : ""}`}>
                              <button type="button" className="star" disabled={!canEdit} aria-pressed={r.preferred}
                                aria-label={r.preferred ? t("routings.preferred") : t("routings.makePreferred", { code: m?.code ?? "" })}
                                onClick={() => update(s.key, (x) => ({ ...x, resources: x.resources.map((y) => ({ ...y, preferred: y.resource_id === r.resource_id })) }))}>
                                <LuStar />
                              </button>
                              <span className="mslot-name"><span className="mono-id">{m?.code ?? "?"}</span><span className="pname">{m ? nameOf(m, lang) : ""}</span></span>
                              <input className="input num own" type="number" min="0" step="any" dir="ltr" disabled={!canEdit}
                                placeholder={s.time_model === "fixed" ? "min" : "/h"}
                                title={s.time_model === "fixed" ? t("routings.ownMinutes") : t("routings.ownSpeed")}
                                aria-label={`${m?.code ?? ""} ${s.time_model === "fixed" ? t("routings.ownMinutes") : t("routings.ownSpeed")}`}
                                value={str(r[ownKey])}
                                onChange={(e) => update(s.key, (x) => ({ ...x, resources: x.resources.map((y) => y.resource_id === r.resource_id
                                  ? { ...y, [ownKey]: e.target.value === "" ? null : Number(e.target.value) } : y) }))} />
                              {canEdit && <button type="button" className="icon-btn" aria-label={t("routings.removeMachine", { code: m?.code ?? "" })}
                                onClick={() => update(s.key, (x) => {
                                  const rest = x.resources.filter((y) => y.resource_id !== r.resource_id);
                                  if (r.preferred && rest.length) rest[0] = { ...rest[0], preferred: true };
                                  return { ...x, resources: rest };
                                })}><LuX /></button>}
                            </div>
                          );
                        })}
                        {canEdit && (
                          <select className="select add-machine" value="" aria-label={t("routings.addMachine")} onChange={(e) => e.target.value && addMachine(s.key, e.target.value)}>
                            <option value="">+ {t("routings.addMachine")}</option>
                            {machines.filter((m) => !s.resources.some((r) => r.resource_id === m.id)).map((m) => <option key={m.id} value={m.id}>{m.code} · {nameOf(m, lang)}</option>)}
                          </select>
                        )}
                      </div>
                      {est && <footer className="step-foot num">{t("routings.stepTime", { h: qty(est.h, 1), code: est.code })}</footer>}
                      {err && <div className="step-error" role="alert">{err}</div>}
                    </article>
                    {i < steps.length - 1 && <FlowLink />}
                  </div>
                );
              })}
              {canEdit && (
                <div className="flow-item">
                  {steps.length > 0 && <FlowLink faint />}
                  <button type="button" className="step-add" onClick={() => setSteps([...steps, { key: nk(), name: t("routings.newStep"), time_model: "fixed", fixed_minutes: 60, rate_per_hour: null, setup_minutes: 0, resources: [] }])}>
                    <LuPlus />{t("routings.addStep")}
                  </button>
                </div>
              )}
              {!canEdit && steps.length === 0 && <p className="subtle">{t("routings.notDefined")}</p>}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function FlowLink({ faint }: { faint?: boolean }) {
  return (
    <svg className={`flow-link ${faint ? "faint" : ""}`} viewBox="0 0 48 24" aria-hidden>
      <line x1="2" y1="12" x2="40" y2="12" className="flow-dash" />
      <path d="M38 6 L46 12 L38 18" className="flow-head" />
    </svg>
  );
}

function strip(steps: EStep[]) {
  return steps.map(({ id, name, time_model, fixed_minutes, rate_per_hour, setup_minutes, resources }) => ({
    id, name, time_model, fixed_minutes: time_model === "fixed" ? fixed_minutes : null, rate_per_hour: time_model === "rate" ? rate_per_hour : null,
    setup_minutes: Number(setup_minutes || 0),
    resources: resources.map((r) => ({ resource_id: r.resource_id, preferred: r.preferred,
      fixed_minutes: time_model === "fixed" ? r.fixed_minutes ?? null : null, rate_per_hour: time_model === "rate" ? r.rate_per_hour ?? null : null })),
  }));
}
