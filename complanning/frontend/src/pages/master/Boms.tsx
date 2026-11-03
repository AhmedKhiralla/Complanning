import { Fragment, useEffect, useMemo, useState } from "react";
import { LuArrowLeft, LuCalculator, LuChevronDown, LuChevronRight, LuCirclePlay, LuCopyPlus, LuListTree, LuPlus, LuTrash2 } from "react-icons/lu";
import {
  Badge, Button, Confirm, Dialog, Empty, Field, LoadError, LoadingRows, Notice, PageHead, SelectField, TextField,
  errorText, fieldErrors, useLoad, useToast,
} from "../../components/ui";
import { NumberField, PickProducedItem, ReadOnlyNote, TypeBadge, numOrNull, str, useUoms } from "../../components/master";
import { ApiError, del, get, patch, post, put } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { Link, navigate } from "../../lib/router";
import { usePerms } from "../../lib/session";
import { nameOf, type Bom, type BomLine, type BomListRow, type ExplodeNode, type ItemDetail, type ItemRow, type ItemType, type Uom } from "../../lib/types";

const LEVELS: ItemType[] = ["finished", "semi_finished", "wip"];

export function Boms() {
  const { t, lang, qty } = useI18n();
  const { editCompany } = usePerms();
  const list = useLoad(() => get<{ items: BomListRow[] }>("/api/boms"));
  const rows = list.data?.items ?? [];
  const [picking, setPicking] = useState(false);
  // Items without any version first, then the rest.
  const options = [...rows].filter((r) => r.active)
    .sort((a, b) => Number(a.versions.length > 0) - Number(b.versions.length > 0))
    .map((r) => {
      const act = r.versions.find((v) => v.status === "active");
      const dr = r.versions.find((v) => v.status === "draft");
      return { id: r.id, label: `${r.code} · ${nameOf(r, lang)}`, group: t(`type.${r.type}` as never),
        note: dr ? t("boms.draft", { v: dr.version }) : act ? t("pick.newVersionOf", { v: act.version }) : t("pick.noneYet") };
    });
  return (
    <>
      <PageHead title={t("boms.title")} lead={t("boms.lead")}
        actions={editCompany ? <Button variant="primary" icon={<LuPlus />} onClick={() => setPicking(true)}>{t("boms.new")}</Button> : undefined} />
      {picking && <PickProducedItem title={t("boms.new")} lead={t("boms.newLead")} options={options} canCreateItem={editCompany}
        onClose={() => setPicking(false)} onPick={(id) => navigate(`/master/boms/${id}`)} />}
      {list.error ? <div className="panel"><LoadError error={list.error} onRetry={list.reload} /></div> : list.data && rows.length === 0 ? (
        <div className="panel"><Empty icon={<LuListTree />} title={t("boms.empty")} body={t("boms.emptyBody")}
          action={<Button onClick={() => navigate("/master/items")}>{t("nav.items")}</Button>} /></div>
      ) : (
        <div className="panel table-wrap">
          <table className="table">
            <thead><tr><th>{t("common.code")}</th><th>{t("common.name")}</th><th>{t("boms.active")}</th><th className="num">{t("boms.batch")}</th><th className="num">{t("boms.linesCol")}</th></tr></thead>
            {!list.data ? <LoadingRows cols={5} rows={7} /> : (
              <tbody>
                {LEVELS.map((lvl) => {
                  const group = rows.filter((r) => r.type === lvl);
                  if (!group.length) return null;
                  return (
                    <Fragment key={lvl}>
                      <tr className="group-row"><td colSpan={5}><TypeBadge type={lvl} /></td></tr>
                      {group.map((r) => {
                        const active = r.versions.find((v) => v.status === "active");
                        const draft = r.versions.find((v) => v.status === "draft");
                        return (
                          <tr key={r.id} className={`clickable ${r.active ? "" : "inactive"}`} tabIndex={0}
                            onClick={() => navigate(`/master/boms/${r.id}`)} onKeyDown={(e) => { if (e.key === "Enter") navigate(`/master/boms/${r.id}`); }}>
                            <td className="mono-id cell-main" dir="ltr" style={{ textAlign: "start" }}>{r.code}</td>
                            <td>{nameOf(r, lang)}</td>
                            <td>
                              {active ? <Badge tone="ok" dot>{t("boms.version", { v: active.version })}</Badge> : <span className="subtle small">{t("boms.noVersion")}</span>}
                              {draft && <> <Badge tone="warn">{t("boms.draft", { v: draft.version })}</Badge></>}
                            </td>
                            <td className="num small">{active ? `${qty(active.batch_size)} ${active.batch_uom}` : "—"}</td>
                            <td className="num small">{active ? active.lines : "—"}</td>
                          </tr>
                        );
                      })}
                    </Fragment>
                  );
                })}
              </tbody>
            )}
          </table>
        </div>
      )}
    </>
  );
}

// ------------------------------------------------------------------ editor
type EditLine = BomLine & { key: string };
let keySeq = 0;
const toEdit = (l: BomLine): EditLine => ({ ...l, key: l.id ?? `n${++keySeq}`, quantity: str(l.quantity), overage_pct: str(l.overage_pct) });

function Tree({ nodes, depth = 0 }: { nodes: ExplodeNode[]; depth?: number }) {
  const { t, lang, qty } = useI18n();
  const [closed, setClosed] = useState<Set<string>>(new Set());
  return (
    <>
      {nodes.map((n) => {
        const kids = n.children.length > 0;
        const isOpen = !closed.has(n.item_id);
        return (
          <Fragment key={n.item_id + depth}>
            <div className={`tree-row depth-${Math.min(depth, 4)}`} style={{ paddingInlineStart: 12 + depth * 22 }}>
              {kids ? (
                <button type="button" className="tree-toggle" aria-expanded={isOpen} aria-label={n.code}
                  onClick={() => setClosed((s) => { const x = new Set(s); x.has(n.item_id) ? x.delete(n.item_id) : x.add(n.item_id); return x; })}>
                  {isOpen ? <LuChevronDown /> : <LuChevronRight className="flip-rtl" />}
                </button>
              ) : <span className="tree-leaf" aria-hidden />}
              <span className="tree-name">
                {kids || ["wip", "semi_finished", "finished"].includes(n.type)
                  ? <Link to={`/master/boms/${n.item_id}`} className="mono-id">{n.code}</Link> : <span className="mono-id">{n.code}</span>}
                <span className="tree-label">{nameOf(n, lang)}</span>
              </span>
              <span className="tree-tags">
                {n.assay_compensated && <Badge tone="brand">{t("boms.tag.assay")}</Badge>}
                {Number(n.overage_pct) > 0 && <Badge tone="warn">{t("boms.tag.overage", { n: qty(n.overage_pct, 2) })}</Badge>}
                {n.is_compensating && <Badge tone="ok">{t("boms.tag.comp")}</Badge>}
                {n.batches !== null && <span className="small muted">{t("boms.batches", { n: qty(n.batches, 2) })} · {t("boms.levelBom", { v: n.bom_version ?? 0 })}</span>}
                {n.batches === null && ["wip", "semi_finished"].includes(n.type) && <span className="small warn-text">{t("boms.noSubBom")}</span>}
              </span>
              <span className="tree-qty num">{qty(n.quantity)} <span className="subtle">{n.uom}</span></span>
            </div>
            {kids && isOpen && <Tree nodes={n.children} depth={depth + 1} />}
          </Fragment>
        );
      })}
    </>
  );
}

function LotCheck({ bom, uoms }: { bom: Bom; uoms: Uom[] }) {
  const { t, qty } = useI18n();
  const assayLines = bom.lines.filter((l) => l.assay_compensated);
  const comp = bom.lines.find((l) => l.is_compensating);
  const [lineId, setLineId] = useState(assayLines[0]?.id ?? "");
  const [assay, setAssay] = useState("99.2");
  const [lod, setLod] = useState("0.5");
  const [basis, setBasis] = useState<"as_is" | "dried">("as_is");
  const line = assayLines.find((l) => l.id === lineId) ?? assayLines[0];
  if (!line) return <p className="small subtle">{t("boms.lotNoAssay")}</p>;
  const std = Number(line.quantity);
  const over = 1 + Number(line.overage_pct) / 100;
  const a = Number(assay), w = Number(lod);
  const valid = a > 0 && a <= 200 && w >= 0 && w < 100;
  const actual = valid ? std * (100 / a) * (basis === "dried" ? 100 / (100 - w) : 1) * over : NaN;
  const delta = actual - std * over;
  let compText: string | null = null;
  let compNeg = false;
  if (comp && valid) {
    const lu = uoms.find((u) => u.id === line.uom_id), cu = uoms.find((u) => u.id === comp.uom_id);
    if (lu && cu && lu.dimension === cu.dimension && lu.dimension !== "count") {
      const deltaInComp = (delta * lu.factor_to_base) / cu.factor_to_base;
      const newComp = Number(comp.quantity) - deltaInComp;
      compNeg = newComp < 0;
      compText = t("boms.lotComp", { code: comp.component_code ?? "", qty: qty(newComp), std: qty(comp.quantity), uom: comp.uom ?? "" });
    }
  }
  return (
    <div className="stack" style={{ gap: 12 }}>
      <div className="grid-4">
        <SelectField label={t("boms.lotLine")} value={line.id ?? ""} onChange={setLineId}
          options={assayLines.map((l) => ({ value: l.id ?? "", label: `${l.component_code}` }))} />
        <NumberField label={t("boms.lotAssay")} value={assay} onChange={setAssay} min={0} />
        <SelectField label={t("boms.lotBasis")} value={basis} onChange={(v) => setBasis(v as "as_is" | "dried")}
          options={[{ value: "as_is", label: t("boms.asIs") }, { value: "dried", label: t("boms.dried") }]} />
        <NumberField label={t("boms.lotLod")} value={lod} onChange={setLod} min={0} disabled={basis === "as_is"} />
      </div>
      {valid && <div className="lot-result">
        <strong className="num">{t("boms.lotResult", { qty: qty(actual), std: qty(std * over), uom: line.uom ?? "" })}</strong>
        {comp ? (compNeg ? <Notice tone="danger">{t("boms.lotCompNeg")}</Notice> : compText && <span className="num">{compText}</span>)
          : <span className="small muted">{t("boms.lotCompNone")}</span>}
        <span className="small subtle formula" dir="ltr">{t("boms.formula")}</span>
      </div>}
    </div>
  );
}

export function BomEditor({ itemId }: { itemId: string }) {
  const { t, lang, qty, date } = useI18n();
  const toast = useToast();
  const { editCompany } = usePerms();
  const uoms = useUoms();
  const item = useLoad(() => get<ItemDetail>(`/api/items/${itemId}`), [itemId]);
  const versions = useLoad(() => get<{ items: BomListRow[] }>("/api/boms").then((d) => d.items.find((r) => r.id === itemId)?.versions ?? []), [itemId]);
  const components = useLoad(() => get<{ items: ItemRow[] }>("/api/items?active=true"));
  const [bomId, setBomId] = useState<string | null>(null);
  const bom = useLoad(() => (bomId ? get<Bom>(`/api/boms/${bomId}`) : Promise.resolve(null)), [bomId]);
  const tree = useLoad(() => (bomId ? get<{ children: ExplodeNode[]; quantity: number; uom: string }>(`/api/boms/${bomId}/explode`) : Promise.resolve(null)), [bomId, bom.data?.updated_at]);
  const [lines, setLines] = useState<EditLine[]>([]);
  const [header, setHeader] = useState({ batch_size: "", batch_uom_id: "", yield_pct: "100", batch_mode: "fixed", min_batch_pct: "", notes: "" });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [activating, setActivating] = useState<string | null>(null);
  const [discarding, setDiscarding] = useState(false);
  const [dirty, setDirty] = useState(false);

  // Pick a version: draft first, then active, then the latest.
  useEffect(() => {
    const v = versions.data;
    if (!v) return;
    if (bomId && v.some((x) => x.id === bomId)) return;
    const pick = v.find((x) => x.status === "draft") ?? v.find((x) => x.status === "active") ?? v[0];
    setBomId(pick ? pick.id : null);
  }, [versions.data]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const b = bom.data;
    if (!b) return;
    setLines(b.lines.map(toEdit));
    setHeader({ batch_size: str(b.batch_size), batch_uom_id: b.batch_uom_id, yield_pct: str(b.yield_pct), batch_mode: b.batch_mode,
      min_batch_pct: str(b.min_batch_pct), notes: b.notes ?? "" });
    setDirty(false); setErrs({}); setGeneral(null);
  }, [bom.data]);

  useEffect(() => {
    if (item.data && !bomId && versions.data && versions.data.length === 0) {
      setHeader((h) => ({ ...h, batch_uom_id: h.batch_uom_id || item.data!.stock_uom_id }));
    }
  }, [item.data, versions.data, bomId]);

  const b = bom.data;
  const draft = b?.status === "draft";
  const canEdit = editCompany && draft;
  const hasDraft = (versions.data ?? []).some((v) => v.status === "draft");
  const uomList = uoms.data?.items.filter((u) => u.active) ?? [];
  const compOptions = useMemo(() => (components.data?.items ?? []).filter((c) => c.id !== itemId), [components.data, itemId]);

  const fail = (e: unknown) => { setErrs(fieldErrors(e)); setGeneral(e instanceof ApiError && e.code === "invalid" && Object.keys(e.fields).some((k) => k.startsWith("lines.")) ? e.message : errorText(e, t)); };
  const refreshAll = (newId?: string) => { if (newId) setBomId(newId); versions.reload(); bom.reload(); };

  const createVersion = async () => {
    setBusy("create"); setErrs({}); setGeneral(null);
    try {
      const nb = await post<Bom>(`/api/items/${itemId}/boms`, {
        batch_size: Number(header.batch_size), batch_uom_id: header.batch_uom_id, yield_pct: numOrNull(header.yield_pct) ?? 100,
        batch_mode: header.batch_mode, min_batch_pct: header.batch_mode === "partial" ? numOrNull(header.min_batch_pct) : null,
        notes: header.notes || null, copy_from: bomId,
      });
      toast(t("boms.savedToast")); setBomId(nb.id); versions.reload();
    } catch (e) { fail(e); } finally { setBusy(null); }
  };
  const saveHeader = async () => {
    if (!b) return;
    setBusy("header"); setErrs({}); setGeneral(null);
    try {
      await patch<Bom>(`/api/boms/${b.id}`, { batch_size: Number(header.batch_size), batch_uom_id: header.batch_uom_id,
        yield_pct: Number(header.yield_pct), batch_mode: header.batch_mode,
        min_batch_pct: header.batch_mode === "partial" ? numOrNull(header.min_batch_pct) : null, notes: header.notes || null });
      toast(t("boms.savedToast")); refreshAll();
    } catch (e) { fail(e); } finally { setBusy(null); }
  };
  const saveLines = async () => {
    if (!b) return;
    setBusy("lines"); setErrs({}); setGeneral(null);
    try {
      await put<Bom>(`/api/boms/${b.id}/lines`, { lines: lines.map((l) => ({
        id: l.id, component_item_id: l.component_item_id, quantity: Number(l.quantity), uom_id: l.uom_id,
        assay_compensated: l.assay_compensated, overage_pct: Number(l.overage_pct || 0), is_compensating: l.is_compensating, notes: l.notes || null,
      })) });
      toast(t("boms.savedToast")); refreshAll();
    } catch (e) { fail(e); } finally { setBusy(null); }
  };
  const setLine = (key: string, patchVals: Partial<EditLine>) => {
    setDirty(true);
    setLines((ls) => ls.map((l) => {
      if (l.key !== key) return patchVals.is_compensating ? { ...l, is_compensating: false } : l;
      const next = { ...l, ...patchVals };
      if (patchVals.component_item_id) {
        const c = compOptions.find((x) => x.id === patchVals.component_item_id);
        if (c) { next.uom_id = c.stock_uom_id; next.component_code = c.code; next.component_type = c.type; next.uom = c.stock_uom; }
      }
      if (next.is_compensating) next.assay_compensated = false;
      return next;
    }));
  };

  if (item.error) return <div className="panel"><LoadError error={item.error} onRetry={item.reload} /></div>;
  const it = item.data;
  const headerForm = (disabled: boolean) => (
    <div className="stack" style={{ gap: 14 }}>
      <div className="grid-4">
        <NumberField label={t("boms.batchSize")} value={header.batch_size} min={0} disabled={disabled} error={errs.batch_size}
          onChange={(v) => { setHeader({ ...header, batch_size: v }); setDirty(true); }} />
        <SelectField label={t("boms.batchUom")} value={header.batch_uom_id} disabled={disabled} error={errs.batch_uom_id}
          onChange={(v) => { setHeader({ ...header, batch_uom_id: v }); setDirty(true); }}
          options={uomList.map((u) => ({ value: u.id, label: u.code }))} />
        <NumberField label={t("boms.yield")} value={header.yield_pct} min={0} disabled={disabled} error={errs.yield_pct}
          onChange={(v) => { setHeader({ ...header, yield_pct: v }); setDirty(true); }} />
        <SelectField label={t("boms.batchMode")} value={header.batch_mode} disabled={disabled}
          onChange={(v) => { setHeader({ ...header, batch_mode: v }); setDirty(true); }}
          options={[{ value: "fixed", label: t("boms.fixed") }, { value: "partial", label: t("boms.partial") }]} />
      </div>
      {header.batch_mode === "partial" && <div className="grid-4">
        <NumberField label={t("boms.minBatch")} value={header.min_batch_pct} min={1} disabled={disabled} error={errs.min_batch_pct}
          onChange={(v) => { setHeader({ ...header, min_batch_pct: v }); setDirty(true); }} />
      </div>}
      <Field label={t("boms.notes")}>{(id) => <textarea id={id} className="textarea" style={{ minHeight: 56 }} value={header.notes} disabled={disabled}
        maxLength={1000} onChange={(e) => { setHeader({ ...header, notes: e.target.value }); setDirty(true); }} />}</Field>
    </div>
  );

  return (
    <>
      <Link to="/master/boms" className="back-link"><LuArrowLeft />{t("boms.back")}</Link>
      <PageHead title={it ? nameOf(it, lang) : t("app.loading")} lead={it ? <span className="row wrap"><span className="mono-id">{it.code}</span><TypeBadge type={it.type} /></span> : undefined}
        actions={b && editCompany ? <>
          {!hasDraft && <Button icon={<LuCopyPlus />} busy={busy === "create"} onClick={createVersion}>{t("boms.newVersion")}</Button>}
          {draft && <Button variant="ghost" icon={<LuTrash2 />} onClick={() => setDiscarding(true)}>{t("boms.discard")}</Button>}
          {draft && <Button variant="primary" icon={<LuCirclePlay />} disabled={dirty || lines.length === 0}
            onClick={() => setActivating(new Date().toISOString().slice(0, 10))}>{t("boms.activate")}</Button>}
        </> : undefined} />
      <ReadOnlyNote show={!editCompany} />

      {versions.data && versions.data.length > 0 && (
        <div className="version-strip" role="tablist" aria-label={t("boms.version", { v: "" })}>
          {versions.data.map((v) => (
            <button key={v.id} type="button" role="tab" aria-selected={v.id === bomId} className="version-chip" onClick={() => setBomId(v.id)}>
              <strong>{t("boms.version", { v: v.version })}</strong>
              <span className={`status ${v.status}`}>{t(`boms.status.${v.status}` as never)}</span>
              {v.valid_from && <span className="small subtle">{date(v.valid_from)}</span>}
            </button>
          ))}
        </div>
      )}

      {versions.data && versions.data.length === 0 && it && (
        <section className="panel"><div className="panel-head"><div><h2>{t("boms.firstVersion")}</h2><p className="small muted">{t("boms.firstLead")}</p></div></div>
          <div className="panel-body stack">
            {general && <Notice tone="danger">{general}</Notice>}
            {headerForm(!editCompany)}
            {editCompany && <div><Button variant="primary" icon={<LuPlus />} busy={busy === "create"} disabled={!header.batch_size || !header.batch_uom_id} onClick={createVersion}>{t("boms.firstVersion")}</Button></div>}
          </div>
        </section>
      )}

      {b && (
        <div className="stack">
          {!draft && <Notice>{t("boms.frozen", { status: t(`boms.status.${b.status}` as never).toLowerCase() })}</Notice>}
          {general && <Notice tone="danger">{general}</Notice>}
          <section className="panel" aria-labelledby="hdr-h">
            <div className="panel-head"><h2 id="hdr-h">{t("boms.header")}</h2><span className="spacer" />
              {b.valid_from && <span className="small muted">{t("boms.validFrom")}: {date(b.valid_from)}{b.valid_to ? ` · ${t("boms.validTo")}: ${date(b.valid_to)}` : ""}</span>}
            </div>
            <div className="panel-body stack">
              {headerForm(!canEdit)}
              {canEdit && <div><Button variant="primary" size="sm" busy={busy === "header"} onClick={saveHeader}>{t("boms.saveHeader")}</Button></div>}
            </div>
          </section>

          <section className="panel" aria-labelledby="lines-h">
            <div className="panel-head"><div><h2 id="lines-h">{t("boms.lines")}</h2><p className="small muted">{t("boms.linesLead")}</p></div>
              <span className="spacer" />{dirty && canEdit && <Badge tone="warn" dot>{t("common.unsaved")}</Badge>}</div>
            <div className="table-wrap">
              <table className="table bom-lines">
                <thead><tr>
                  <th className="cell-tight">#</th><th>{t("boms.component")}</th><th className="num">{t("boms.qty")}</th><th>{t("boms.unit")}</th>
                  <th className="center">{t("boms.assay")}</th><th className="num">{t("boms.overage")}</th><th className="center">{t("boms.compensating")}</th><th />
                </tr></thead>
                <tbody>
                  {lines.length === 0 && <tr><td colSpan={8} className="subtle small">{t("boms.noLines")}</td></tr>}
                  {lines.map((l, i) => {
                    const err = errs[`lines.${i}`];
                    return (
                      <Fragment key={l.key}>
                        <tr className={err ? "row-error" : ""}>
                          <td className="num subtle">{i + 1}</td>
                          <td style={{ minWidth: 240 }}>
                            {canEdit ? (
                              <select className="select" value={l.component_item_id} aria-label={t("boms.component")} aria-invalid={!!err}
                                onChange={(e) => setLine(l.key, { component_item_id: e.target.value })}>
                                <option value="">{t("boms.chooseComponent")}</option>
                                {(["raw_material", "packaging", "wip", "semi_finished", "finished"] as ItemType[]).map((ty) => {
                                  const opts = compOptions.filter((c) => c.type === ty);
                                  return opts.length ? <optgroup key={ty} label={t(`type.${ty}` as never)}>
                                    {opts.map((c) => <option key={c.id} value={c.id}>{c.code} · {nameOf(c, lang)}</option>)}</optgroup> : null;
                                })}
                              </select>
                            ) : (
                              <div><Link to={["wip", "semi_finished", "finished"].includes(l.component_type ?? "") ? `/master/boms/${l.component_item_id}` : "/master/items"} className="mono-id">{l.component_code}</Link>
                                <div className="cell-sub">{l.component_name_en ? nameOf({ name_en: l.component_name_en, name_ar: l.component_name_ar }, lang) : ""}</div></div>
                            )}
                          </td>
                          <td className="num" style={{ width: 130 }}>{canEdit
                            ? <input className="input num" type="number" min="0" step="any" value={l.quantity} aria-label={t("boms.qty")} onChange={(e) => setLine(l.key, { quantity: e.target.value })} />
                            : qty(l.quantity, 4)}</td>
                          <td style={{ width: 100 }}>{canEdit
                            ? <select className="select" value={l.uom_id} aria-label={t("boms.unit")} onChange={(e) => setLine(l.key, { uom_id: e.target.value })}>
                                {uomList.map((u) => <option key={u.id} value={u.id}>{u.code}</option>)}</select>
                            : <span className="mono-id">{l.uom}</span>}</td>
                          <td className="center"><input type="checkbox" className="cb" checked={l.assay_compensated} disabled={!canEdit || l.is_compensating}
                            aria-label={t("boms.assay")} onChange={(e) => setLine(l.key, { assay_compensated: e.target.checked })} /></td>
                          <td className="num" style={{ width: 96 }}>{canEdit
                            ? <input className="input num" type="number" min="0" max="100" step="any" value={l.overage_pct} aria-label={t("boms.overage")} onChange={(e) => setLine(l.key, { overage_pct: e.target.value })} />
                            : Number(l.overage_pct) > 0 ? `${qty(l.overage_pct, 2)}%` : <span className="subtle">—</span>}</td>
                          <td className="center"><input type="radio" className="cb" name="compensating" checked={l.is_compensating} disabled={!canEdit}
                            aria-label={t("boms.compensating")} onChange={() => setLine(l.key, { is_compensating: true })}
                            onClick={() => { if (l.is_compensating && canEdit) setLine(l.key, { is_compensating: false }); }} /></td>
                          <td className="actions">{canEdit && <Button variant="ghost" size="sm" iconOnly aria-label={t("common.remove")} icon={<LuTrash2 />}
                            onClick={() => { setDirty(true); setLines(lines.filter((x) => x.key !== l.key)); }} />}</td>
                        </tr>
                        {err && <tr className="row-error-msg"><td /><td colSpan={7} className="error small">{err}</td></tr>}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {canEdit && <div className="panel-body row" style={{ borderTop: "1px solid var(--line)" }}>
              <Button size="sm" icon={<LuPlus />} onClick={() => { setDirty(true); setLines([...lines, toEdit({ component_item_id: "", quantity: "", uom_id: uomList[0]?.id ?? "", assay_compensated: false, overage_pct: 0, is_compensating: false })]); }}>{t("boms.addLine")}</Button>
              <Button size="sm" variant="primary" busy={busy === "lines"} onClick={saveLines} disabled={lines.some((l) => !l.component_item_id || !l.quantity)}>{t("boms.saveLines")}</Button>
            </div>}
          </section>

          <div className="bom-bottom">
            <section className="panel" aria-labelledby="tree-h">
              <div className="panel-head"><div><h2 id="tree-h">{t("boms.structure")}</h2>
                {tree.data && <p className="small muted">{t("boms.structureLead", { qty: qty(tree.data.quantity), uom: tree.data.uom })}</p>}</div></div>
              {tree.error ? <div className="panel-body"><Notice tone="warn">{errorText(tree.error, t)}</Notice></div>
                : !tree.data ? <div className="panel-body"><div className="skeleton" style={{ width: "60%" }} /></div>
                  : <div className="tree"><Tree nodes={tree.data.children} /></div>}
            </section>
            <section className="panel" aria-labelledby="lot-h">
              <div className="panel-head"><LuCalculator aria-hidden className="muted" /><div><h2 id="lot-h">{t("boms.lotCheck")}</h2><p className="small muted">{t("boms.lotLead")}</p></div></div>
              <div className="panel-body">{uoms.data && <LotCheck key={b.updated_at} bom={b} uoms={uoms.data.items} />}</div>
            </section>
          </div>
        </div>
      )}

      {activating !== null && b && (
        <Dialog title={t("boms.activateTitle", { v: b.version })} onClose={() => setActivating(null)} footer={<>
          <Button onClick={() => setActivating(null)}>{t("common.cancel")}</Button>
          <Button variant="primary" busy={busy === "activate"} onClick={async () => {
            setBusy("activate");
            try { await post(`/api/boms/${b.id}/activate`, { valid_from: activating }); toast(t("boms.activatedToast")); setActivating(null); refreshAll(); }
            catch (e) { fail(e); setActivating(null); } finally { setBusy(null); }
          }}>{t("boms.activate")}</Button></>}>
          <p>{t("boms.activateBody")}</p>
          <TextField label={t("boms.validFrom")} type="date" value={activating} onChange={setActivating} />
        </Dialog>
      )}
      {discarding && b && <Confirm danger title={t("boms.discardTitle", { v: b.version })} body={t("boms.discardBody")} confirmLabel={t("boms.discard")}
        onClose={() => setDiscarding(false)} onConfirm={async () => { await del(`/api/boms/${b.id}`); toast(t("boms.discardedToast")); setBomId(null); versions.reload(); }} />}
    </>
  );
}
