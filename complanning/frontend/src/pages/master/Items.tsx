import { useMemo, useState } from "react";
import { LuBoxes, LuPlus, LuSearch, LuTrash2 } from "react-icons/lu";
import {
  Badge, Button, Dialog, Empty, Field, LoadError, LoadingRows, Notice, PageHead, SelectField, Sheet, Switch, TextField,
  errorText, fieldErrors, useLoad, useToast,
} from "../../components/ui";
import { ExcelMenu, NumberField, ReadOnlyNote, SampleDataButton, TypeBadge, numOrNull, str, useMarkets, useUoms } from "../../components/master";
import { get, patch, post, put } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { navigate } from "../../lib/router";
import { usePerms, useSession } from "../../lib/session";
import { ITEM_TYPES, PRODUCIBLE, nameOf, type ItemDetail, type ItemRow, type ItemType, type Uom } from "../../lib/types";

type Tab = "general" | "planning" | "units" | "markets" | "usage";

const FIELDS = ["name_en", "name_ar", "stock_uom_id", "dispensing_uom_id", "density_kg_per_l", "description", "grade",
  "dosage_form", "cleaning_group", "lead_time_days", "moq", "safety_stock", "qc_release_days", "shelf_life_months",
  "pack_size", "units_per_shipper", "standard_cost", "release_lead_days"] as const;
const NUMERIC = new Set(["density_kg_per_l", "lead_time_days", "moq", "safety_stock", "qc_release_days", "shelf_life_months",
  "pack_size", "units_per_shipper", "standard_cost", "release_lead_days"]);

function UnitsTab({ item, uoms, canEdit, onSaved }: { item: ItemDetail; uoms: Uom[]; canEdit: boolean; onSaved: (d: ItemDetail) => void }) {
  const { t, lang } = useI18n();
  const toast = useToast();
  const [rows, setRows] = useState(item.conversions.map((c) => ({ uom_id: c.uom_id, factor: str(c.factor) })));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const options = uoms.filter((u) => u.active && u.id !== item.stock_uom_id);
  const save = async () => {
    setBusy(true); setErr(null);
    try {
      const d = await put<ItemDetail>(`/api/items/${item.id}/conversions`, {
        conversions: rows.filter((r) => r.uom_id && r.factor).map((r) => ({ uom_id: r.uom_id, factor: Number(r.factor) })) });
      onSaved(d); toast(t("items.savedToast"));
    } catch (e) { setErr(errorText(e, t)); } finally { setBusy(false); }
  };
  return (
    <div className="stack">
      <div><h3>{t("items.conv.title")}</h3><p className="small muted">{t("items.conv.lead", { stock: item.stock_uom })}</p></div>
      {err && <Notice tone="danger">{err}</Notice>}
      {rows.length === 0 && <p className="small subtle">{t("items.conv.none")}</p>}
      {rows.map((r, i) => (
        <div className="conv-row" key={i}>
          <span className="num">1</span>
          <select className="select" value={r.uom_id} disabled={!canEdit} aria-label={t("boms.unit")}
            onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, uom_id: e.target.value } : x)))}>
            <option value="">—</option>
            {options.map((u) => <option key={u.id} value={u.id}>{u.code} · {nameOf(u, lang)}</option>)}
          </select>
          <span className="muted small">{t("items.conv.equals")}</span>
          <input className="input num" type="number" step="any" min="0" value={r.factor} disabled={!canEdit} aria-label={item.stock_uom}
            onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, factor: e.target.value } : x)))} />
          <span className="mono-id">{item.stock_uom}</span>
          {canEdit && <Button variant="ghost" iconOnly size="sm" aria-label={t("common.remove")} icon={<LuTrash2 />}
            onClick={() => setRows(rows.filter((_, j) => j !== i))} />}
        </div>
      ))}
      {canEdit && <div className="row">
        <Button size="sm" icon={<LuPlus />} onClick={() => setRows([...rows, { uom_id: "", factor: "" }])}>{t("items.conv.add")}</Button>
        <Button size="sm" variant="primary" busy={busy} onClick={save}>{t("items.conv.save")}</Button>
      </div>}
    </div>
  );
}

function MarketsTab({ item, canEdit, onSaved }: { item: ItemDetail; canEdit: boolean; onSaved: (d: ItemDetail) => void }) {
  const { t, date, qty, lang } = useI18n();
  const toast = useToast();
  const markets = useMarkets();
  const [rows, setRows] = useState(item.markets.map((m) => ({ market_id: m.market_id, max: str(m.max_sellable_per_month), shelf: str(m.min_remaining_shelf_pct) })));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [newPrice, setNewPrice] = useState<{ market_id: string; price: string; valid_from: string } | null>(null);
  const [priceErr, setPriceErr] = useState<Record<string, string>>({});
  const [ending, setEnding] = useState<{ id: string; valid_to: string } | null>(null);
  const mk = markets.data?.items ?? [];
  const sold = new Set(item.markets.map((m) => m.market_id));

  const saveMarkets = async () => {
    setBusy(true); setErr(null);
    try {
      const d = await put<ItemDetail>(`/api/items/${item.id}/markets`, {
        markets: rows.filter((r) => r.market_id).map((r) => ({ market_id: r.market_id, max_sellable_per_month: numOrNull(r.max), min_remaining_shelf_pct: numOrNull(r.shelf) })) });
      onSaved(d); toast(t("items.savedToast"));
    } catch (e) { setErr(errorText(e, t)); } finally { setBusy(false); }
  };
  const addPrice = async () => {
    if (!newPrice) return;
    setPriceErr({});
    try {
      const d = await post<ItemDetail>(`/api/items/${item.id}/prices`, { market_id: newPrice.market_id, price: Number(newPrice.price), valid_from: newPrice.valid_from });
      onSaved(d); setNewPrice(null); toast(t("items.savedToast"));
    } catch (e) { setPriceErr({ ...fieldErrors(e), _: errorText(e, t) }); }
  };
  const status = (p: ItemDetail["prices"][number]) => {
    const today = new Date().toISOString().slice(0, 10);
    if (p.current) return <Badge tone="ok" dot>{t("items.pr.current")}</Badge>;
    if (p.valid_from > today) return <Badge tone="brand">{t("items.pr.upcoming")}</Badge>;
    return <Badge>{t("items.pr.ended")}</Badge>;
  };

  return (
    <div className="stack">
      <div><h3>{t("items.mk.title")}</h3><p className="small muted">{t("items.mk.lead")}</p></div>
      {err && <Notice tone="danger">{err}</Notice>}
      {rows.length === 0 ? <p className="small subtle">{t("items.mk.none")}</p> : (
        <div className="panel table-wrap">
          <table className="table">
            <thead><tr><th>{t("items.mk.market")}</th><th>{t("items.mk.maxPerMonth")}</th><th>{t("items.mk.minShelf")}</th><th /></tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td><select className="select" value={r.market_id} disabled={!canEdit} aria-label={t("items.mk.market")}
                    onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, market_id: e.target.value } : x)))}>
                    <option value="">—</option>
                    {mk.map((m) => <option key={m.id} value={m.id}>{m.code} · {nameOf(m, lang)}</option>)}
                  </select></td>
                  <td><input className="input num" type="number" min="0" step="any" value={r.max} disabled={!canEdit} aria-label={t("items.mk.maxPerMonth")}
                    onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, max: e.target.value } : x)))} /></td>
                  <td><input className="input num" type="number" min="0" max="100" step="any" value={r.shelf} disabled={!canEdit} aria-label={t("items.mk.minShelf")}
                    onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, shelf: e.target.value } : x)))} /></td>
                  <td className="actions">{canEdit && <Button variant="ghost" iconOnly size="sm" aria-label={t("common.remove")} icon={<LuTrash2 />} onClick={() => setRows(rows.filter((_, j) => j !== i))} />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {canEdit && <div className="row">
        <Button size="sm" icon={<LuPlus />} onClick={() => setRows([...rows, { market_id: "", max: "", shelf: "" }])}>{t("items.mk.add")}</Button>
        <Button size="sm" variant="primary" busy={busy} onClick={saveMarkets}>{t("items.mk.save")}</Button>
      </div>}

      <div className="row" style={{ marginTop: 8 }}><div><h3>{t("items.pr.title")}</h3><p className="small muted">{t("items.pr.lead")}</p></div></div>
      {item.prices.length === 0 ? <p className="small subtle">{t("items.pr.none")}</p> : (
        <div className="panel table-wrap">
          <table className="table">
            <thead><tr><th>{t("items.mk.market")}</th><th className="num">{t("items.pr.price")}</th><th>{t("items.pr.from")}</th><th>{t("items.pr.to")}</th><th>{t("common.status")}</th><th /></tr></thead>
            <tbody>
              {item.prices.map((p) => (
                <tr key={p.id} className={!p.current && p.valid_to ? "inactive" : ""}>
                  <td className="mono-id">{p.market}</td>
                  <td className="num">{qty(p.price, 2)} <span className="subtle small">{p.currency}</span></td>
                  <td className="small">{date(p.valid_from)}</td>
                  <td className="small">{p.valid_to ? date(p.valid_to) : <span className="subtle">{t("items.pr.openEnded")}</span>}</td>
                  <td>{status(p)}</td>
                  <td className="actions">{canEdit && !p.valid_to && <Button size="sm" variant="ghost" onClick={() => setEnding({ id: p.id, valid_to: "" })}>{t("items.pr.end")}</Button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {canEdit && !newPrice && (sold.size === 0
        ? <p className="small subtle">{t("items.pr.noMarkets")}</p>
        : <div><Button size="sm" icon={<LuPlus />} onClick={() => setNewPrice({ market_id: item.markets[0].market_id, price: "", valid_from: new Date().toISOString().slice(0, 10) })}>{t("items.pr.new")}</Button></div>)}
      {newPrice && (
        <div className="panel"><div className="panel-body stack">
          {priceErr._ && <Notice tone="danger">{priceErr._}</Notice>}
          <div className="grid-3">
            <SelectField label={t("items.mk.market")} value={newPrice.market_id} onChange={(v) => setNewPrice({ ...newPrice, market_id: v })}
              options={item.markets.map((m) => ({ value: m.market_id, label: `${m.market} (${m.currency})` }))} />
            <NumberField label={t("items.pr.price")} value={newPrice.price} min={0} error={priceErr.price}
              suffix={item.markets.find((m) => m.market_id === newPrice.market_id)?.currency} onChange={(v) => setNewPrice({ ...newPrice, price: v })} />
            <TextField label={t("items.pr.from")} type="date" value={newPrice.valid_from} error={priceErr.valid_from}
              onChange={(v) => setNewPrice({ ...newPrice, valid_from: v })} />
          </div>
          <div className="row"><Button size="sm" variant="primary" disabled={!newPrice.price || !newPrice.valid_from} onClick={addPrice}>{t("items.pr.add")}</Button>
            <Button size="sm" onClick={() => setNewPrice(null)}>{t("common.cancel")}</Button></div>
        </div></div>
      )}
      {ending && (
        <Dialog title={t("items.pr.endTitle")} onClose={() => setEnding(null)} footer={<>
          <Button onClick={() => setEnding(null)}>{t("common.cancel")}</Button>
          <Button variant="primary" disabled={!ending.valid_to} onClick={async () => {
            try { const d = await post<ItemDetail>(`/api/prices/${ending.id}/end`, { valid_to: ending.valid_to }); onSaved(d); setEnding(null); }
            catch (e) { setPriceErr({ _: errorText(e, t) }); setEnding(null); }
          }}>{t("items.pr.end")}</Button></>}>
          <p>{t("items.pr.endBody")}</p>
          <TextField label={t("items.pr.to")} type="date" value={ending.valid_to} onChange={(v) => setEnding({ ...ending, valid_to: v })} />
        </Dialog>
      )}
    </div>
  );
}

function ItemSheet({ itemId, uoms, onClose, onSaved, defaultType }: { itemId: string | null; uoms: Uom[]; onClose: () => void; onSaved: () => void; defaultType?: ItemType }) {
  const { t, lang } = useI18n();
  const toast = useToast();
  const { editCompany } = usePerms();
  const detail = useLoad(() => (itemId ? get<ItemDetail>(`/api/items/${itemId}`) : Promise.resolve(null)), [itemId]);
  const item = detail.data;
  const [tab, setTab] = useState<Tab>("general");
  const [f, setF] = useState<Record<string, string>>({});
  const [flags, setFlags] = useState({ test_before_sale: false, active: true });
  const [code, setCode] = useState("");
  const [type, setType] = useState<ItemType>(defaultType ?? "raw_material");
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const isNew = !itemId;

  if (item && loadedFor !== item.id + item.updated_at) {
    const next: Record<string, string> = {};
    FIELDS.forEach((k) => { next[k] = str((item as unknown as Record<string, unknown>)[k] as string | number | null); });
    setF(next); setFlags({ test_before_sale: item.test_before_sale, active: item.active });
    setCode(item.code); setType(item.type); setLoadedFor(item.id + item.updated_at);
  }
  if (isNew && loadedFor !== "new") {
    setF({ stock_uom_id: uoms.find((u) => u.code === "KG")?.id ?? "" }); setLoadedFor("new");
  }
  const set = (k: string) => (v: string) => setF((s) => ({ ...s, [k]: v }));
  const ro = !editCompany;
  const uomOptions = [{ value: "", label: "—" }, ...uoms.filter((u) => u.active).map((u) => ({ value: u.id, label: `${u.code} · ${nameOf(u, lang)}` }))];
  const stockCode = uoms.find((u) => u.id === f.stock_uom_id)?.code ?? "";
  const producible = PRODUCIBLE.includes(type);

  const save = async () => {
    setBusy(true); setErrs({}); setGeneral(null);
    const body: Record<string, unknown> = { ...flags };
    FIELDS.forEach((k) => { const v = f[k] ?? ""; body[k] = NUMERIC.has(k) ? numOrNull(v) : v.trim() === "" ? null : v.trim(); });
    try {
      if (isNew) {
        const d = await post<ItemDetail>("/api/items", { ...body, code, type });
        toast(t("items.savedToast")); onSaved(); onClose();
        if (PRODUCIBLE.includes(d.type)) navigate(`/master/boms/${d.id}`);
      } else {
        const d = await patch<ItemDetail>(`/api/items/${itemId}`, body);
        detail.setData(d); toast(t("items.savedToast")); onSaved();
      }
    } catch (e) { setErrs(fieldErrors(e)); setGeneral(errorText(e, t)); }
    finally { setBusy(false); }
  };

  const tabs: Tab[] = isNew ? ["general", "planning"] : ["general", "planning", "units", ...(type === "finished" ? ["markets" as Tab] : []), "usage"];
  const formTab = tab === "general" || tab === "planning";

  return (
    <Sheet title={isNew ? t("items.form.new") : t("items.form.edit")} lead={item ? `${item.code} · ${nameOf(item, lang)}` : undefined}
      onClose={onClose} onSubmit={save} wide
      footer={formTab && !ro ? <><Button onClick={onClose}>{t("common.cancel")}</Button><Button type="submit" variant="primary" busy={busy}>{isNew ? t("common.create") : t("common.save")}</Button></>
        : <Button onClick={onClose}>{t("common.close")}</Button>}
      toolbar={<div className="tabs" role="tablist" style={{ marginBottom: 0, borderBottom: 0 }}>
        {tabs.map((x) => <button key={x} type="button" role="tab" className="tab" aria-selected={tab === x} onClick={() => setTab(x)}>{t(`items.tab.${x}` as never)}</button>)}
      </div>}>
      {detail.error ? <LoadError error={detail.error} onRetry={detail.reload} /> : !isNew && !item ? <div className="skeleton" style={{ width: "50%" }} /> : (
        <>
          <ReadOnlyNote show={ro} />
          {general && formTab && <Notice tone="danger">{general}</Notice>}
          {tab === "general" && <>
            <div className="grid-2">
              <TextField label={t("items.f.code")} hint={isNew ? t("items.f.codeHint") : undefined} value={code} dir="ltr" maxLength={40}
                disabled={!isNew || ro} onChange={(v) => setCode(v.toUpperCase())} error={errs.code} required />
              <SelectField label={t("items.f.type")} value={type} disabled={!isNew || ro} onChange={(v) => setType(v as ItemType)}
                hint={!isNew ? t("items.f.typeLocked") : undefined} options={ITEM_TYPES.map((x) => ({ value: x, label: t(`type.${x}` as never) }))} />
            </div>
            <TextField label={t("items.f.nameEn")} value={f.name_en ?? ""} onChange={set("name_en")} error={errs.name_en} disabled={ro} dir="ltr" required />
            <TextField label={t("items.f.nameAr")} value={f.name_ar ?? ""} onChange={set("name_ar")} disabled={ro} dir="rtl" lang="ar" />
            <div className="grid-2">
              <SelectField label={t("items.f.stockUom")} hint={t("items.f.stockUomHint")} value={f.stock_uom_id ?? ""} onChange={set("stock_uom_id")}
                options={uomOptions} error={errs.stock_uom_id} disabled={ro} />
              <SelectField label={t("items.f.dispUom")} hint={t("items.f.dispUomHint")} value={f.dispensing_uom_id ?? ""} onChange={set("dispensing_uom_id")}
                options={uomOptions} disabled={ro} />
            </div>
            <div className="grid-2">
              <NumberField label={t("items.f.density")} hint={t("items.f.densityHint")} value={f.density_kg_per_l ?? ""} onChange={set("density_kg_per_l")} disabled={ro} min={0} error={errs.density_kg_per_l} />
              <TextField label={t("items.f.grade")} value={f.grade ?? ""} onChange={set("grade")} disabled={ro} />
            </div>
            {producible && <div className="grid-2">
              <TextField label={t("items.f.dosageForm")} value={f.dosage_form ?? ""} onChange={set("dosage_form")} disabled={ro} />
              <TextField label={t("items.f.cleaningGroup")} hint={t("items.f.cleaningGroupHint")} value={f.cleaning_group ?? ""} onChange={set("cleaning_group")} disabled={ro} />
            </div>}
            <Field label={t("items.f.description")}>{(id) => <textarea id={id} className="textarea" value={f.description ?? ""} disabled={ro} maxLength={500} onChange={(e) => set("description")(e.target.value)} />}</Field>
            {!isNew && <div className="feature" style={{ padding: "4px 0", border: 0 }}>
              <div className="text"><strong>{t("items.f.active")}</strong><span>{t("items.f.activeHint")}</span></div>
              <Switch label={t("items.f.active")} checked={flags.active} disabled={ro} onChange={(v) => setFlags({ ...flags, active: v })} />
            </div>}
          </>}
          {tab === "planning" && <>
            {!producible && <div className="grid-2">
              <NumberField label={t("items.f.leadTime")} value={f.lead_time_days ?? ""} onChange={set("lead_time_days")} disabled={ro} min={0} step="1" error={errs.lead_time_days} />
              <NumberField label={t("items.f.qcRelease")} value={f.qc_release_days ?? ""} onChange={set("qc_release_days")} disabled={ro} min={0} />
            </div>}
            <div className="grid-2">
              {!producible && <NumberField label={t("items.f.moq")} value={f.moq ?? ""} onChange={set("moq")} disabled={ro} min={0} suffix={stockCode} />}
              <NumberField label={t("items.f.safety")} value={f.safety_stock ?? ""} onChange={set("safety_stock")} disabled={ro} min={0} suffix={stockCode} />
              {producible && <NumberField label={t("items.f.releaseLead")} value={f.release_lead_days ?? ""} onChange={set("release_lead_days")} disabled={ro} min={0} />}
            </div>
            {(type === "finished" || type === "semi_finished") && <div className="grid-2">
              <NumberField label={t("items.f.shelfLife")} value={f.shelf_life_months ?? ""} onChange={set("shelf_life_months")} disabled={ro} min={1} step="1" />
              {type === "finished" && <NumberField label={t("items.f.stdCost")} value={f.standard_cost ?? ""} onChange={set("standard_cost")} disabled={ro} min={0} />}
            </div>}
            {type === "finished" && <>
              <div className="grid-2">
                <NumberField label={t("items.f.packSize")} value={f.pack_size ?? ""} onChange={set("pack_size")} disabled={ro} min={0} />
                <NumberField label={t("items.f.perShipper")} value={f.units_per_shipper ?? ""} onChange={set("units_per_shipper")} disabled={ro} min={1} step="1" />
              </div>
              <div className="feature" style={{ padding: "4px 0", border: 0 }}>
                <div className="text"><strong>{t("items.f.testBeforeSale")}</strong><span>{t("items.f.testBeforeSaleHint")}</span></div>
                <Switch label={t("items.f.testBeforeSale")} checked={flags.test_before_sale} disabled={ro} onChange={(v) => setFlags({ ...flags, test_before_sale: v })} />
              </div>
            </>}
          </>}
          {tab === "units" && item && <UnitsTab key={item.updated_at} item={item} uoms={uoms} canEdit={!ro} onSaved={(d) => { detail.setData(d); onSaved(); }} />}
          {tab === "markets" && item && <MarketsTab key={item.prices.length + item.markets.length} item={item} canEdit={!ro} onSaved={(d) => { detail.setData(d); onSaved(); }} />}
          {tab === "usage" && item && <>
            <p className="small muted">{t("items.used.lead")}</p>
            {item.used_in.length === 0 ? <p className="small subtle">{t("items.used.none")}</p> : (
              <ul className="link-list">{item.used_in.map((u) => (
                <li key={u.id + u.version}><a href={`/master/boms/${u.id}`} onClick={(e) => { e.preventDefault(); onClose(); navigate(`/master/boms/${u.id}`); }}>
                  <span className="mono-id">{u.code}</span> {nameOf(u, lang)}</a>
                  <Badge tone={u.status === "active" ? "ok" : "warn"}>{t("boms.version", { v: u.version })} · {t(`boms.status.${u.status}` as never)}</Badge></li>
              ))}</ul>
            )}
          </>}
        </>
      )}
    </Sheet>
  );
}

export function Items() {
  const { t, lang, number } = useI18n();
  const { editCompany, admin } = usePerms();
  const { siteId } = useSession();
  const [q, setQ] = useState("");
  const [type, setType] = useState<ItemType | "">("");
  const [newType] = useState<ItemType | undefined>(() => (new URLSearchParams(window.location.search).get("new") === "produced" ? "finished" : undefined));
  const items = useLoad(() => get<{ items: ItemRow[] }>("/api/items"));
  const uoms = useUoms();
  const [open, setOpen] = useState<string | "new" | null>(() => {
    const p = new URLSearchParams(window.location.search).get("new");
    if (p) window.history.replaceState(null, "", "/master/items");
    return p ? "new" : null;
  });
  const all = items.data?.items ?? [];
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    all.forEach((i) => { c[i.type] = (c[i.type] ?? 0) + 1; });
    return c;
  }, [all]);
  const rows = all.filter((i) => (!type || i.type === type) && (!q.trim() ||
    [i.code, i.name_en, i.name_ar ?? ""].some((s) => s.toLowerCase().includes(q.trim().toLowerCase()))));

  return (
    <>
      <PageHead title={t("items.title")} lead={t("items.lead")} actions={<>
        <ExcelMenu entity="items" siteId={siteId ?? undefined} canEdit={editCompany} onImported={items.reload} />
        {editCompany && <Button variant="primary" icon={<LuPlus />} onClick={() => setOpen("new")}>{t("items.new")}</Button>}
      </>} />
      <div className="panel">
        <div className="toolbar">
          <div className="search"><LuSearch aria-hidden />
            <input className="input" type="search" placeholder={t("common.search")} aria-label={t("common.search")} value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <div className="seg" role="group" aria-label={t("items.f.type")}>
            <button type="button" aria-pressed={type === ""} onClick={() => setType("")}>{t("items.allTypes")} <span className="subtle">{number(all.length)}</span></button>
            {ITEM_TYPES.map((x) => (
              <button key={x} type="button" aria-pressed={type === x} onClick={() => setType(x)}>{t(`type.${x}` as never)} <span className="subtle">{number(counts[x] ?? 0)}</span></button>
            ))}
          </div>
        </div>
        {items.error ? <LoadError error={items.error} onRetry={items.reload} /> : !items.loading && all.length === 0 ? (
          <Empty icon={<LuBoxes />} title={t("items.empty")} body={t("items.emptyBody")} action={<div className="row wrap" style={{ justifyContent: "center" }}>
            {editCompany && <Button variant="primary" icon={<LuPlus />} onClick={() => setOpen("new")}>{t("items.new")}</Button>}
            {admin && <SampleDataButton onLoaded={items.reload} />}
          </div>} />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>{t("common.code")}</th><th>{t("common.name")}</th><th>{t("items.f.type")}</th><th>{t("items.stockUnit")}</th><th>{t("items.bom")}</th></tr></thead>
              {items.loading && !items.data ? <LoadingRows cols={5} rows={8} /> : (
                <tbody>
                  {rows.map((i) => (
                    <tr key={i.id} className={`clickable ${i.active ? "" : "inactive"}`} tabIndex={0} onClick={() => setOpen(i.id)}
                      onKeyDown={(e) => { if (e.key === "Enter") setOpen(i.id); }}>
                      <td className="mono-id cell-main" dir="ltr" style={{ textAlign: "start" }}>{i.code}</td>
                      <td>{nameOf(i, lang)}{!i.active && <span className="subtle small"> · {t("items.inactive")}</span>}</td>
                      <td><TypeBadge type={i.type} /></td>
                      <td className="mono-id">{i.stock_uom}</td>
                      <td className="small">{PRODUCIBLE.includes(i.type) ? (
                        i.active_bom_version ? <span>{t("items.bomActive", { v: i.active_bom_version })}</span>
                          : i.bom_versions > 0 ? <span className="warn-text">{t("items.bomDraftOnly")}</span>
                            : <span className="subtle">{t("items.bomNone")}</span>
                      ) : <span className="subtle">—</span>}</td>
                    </tr>
                  ))}
                </tbody>
              )}
            </table>
          </div>
        )}
        {items.data && all.length > 0 && <div className="pager"><span>{t("items.count", { n: number(rows.length) })}</span></div>}
      </div>
      {open && uoms.data && <ItemSheet itemId={open === "new" ? null : open} defaultType={open === "new" ? newType : undefined} uoms={uoms.data.items} onClose={() => setOpen(null)} onSaved={items.reload} />}
    </>
  );
}
