import { useState } from "react";
import { LuPlus } from "react-icons/lu";
import { Badge, Button, LoadError, LoadingRows, Notice, PageHead, SelectField, Sheet, Switch, TextField, errorText, fieldErrors, useToast } from "../../components/ui";
import { NumberField, ReadOnlyNote, str, useMarkets, useUoms } from "../../components/master";
import { patch, post } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { usePerms } from "../../lib/session";
import { nameOf, type Market, type Uom } from "../../lib/types";

const BASE: Record<string, string> = { mass: "KG", volume: "L", time: "H", energy: "KWH", gas: "NM3", other: "1" };
const DIMS = ["mass", "volume", "count", "time", "energy", "gas", "other"] as const;

function UomSheet({ uom, onClose, onSaved }: { uom: Uom | null; onClose: () => void; onSaved: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const [f, setF] = useState({ code: uom?.code ?? "", name_en: uom?.name_en ?? "", name_ar: uom?.name_ar ?? "",
    dimension: uom?.dimension ?? "count", factor: str(uom?.factor_to_base ?? 1), active: uom?.active ?? true });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const count = f.dimension === "count";
  const submit = async () => {
    setBusy(true); setErrs({}); setGeneral(null);
    try {
      if (uom) await patch(`/api/uoms/${uom.id}`, { name_en: f.name_en, name_ar: f.name_ar || null, active: f.active,
        ...(uom.is_system ? {} : { factor_to_base: Number(f.factor) }) });
      else await post("/api/uoms", { code: f.code, name_en: f.name_en, name_ar: f.name_ar || null, dimension: f.dimension, factor_to_base: count ? 1 : Number(f.factor) });
      toast(t("units.savedToast")); onSaved(); onClose();
    } catch (e) { setErrs(fieldErrors(e)); setGeneral(errorText(e, t)); setBusy(false); }
  };
  return (
    <Sheet title={uom ? t("units.form.edit") : t("units.form.new")} lead={uom?.code} onClose={onClose} onSubmit={submit}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button type="submit" variant="primary" busy={busy}>{uom ? t("common.save") : t("common.create")}</Button></>}>
      {general && <Notice tone="danger">{general}</Notice>}
      {!uom && <TextField label={t("units.f.code")} value={f.code} dir="ltr" maxLength={12} onChange={(v) => setF({ ...f, code: v.toUpperCase() })} error={errs.code} required />}
      <TextField label={t("items.f.nameEn")} value={f.name_en} dir="ltr" onChange={(v) => setF({ ...f, name_en: v })} error={errs.name_en} required />
      <TextField label={t("items.f.nameAr")} value={f.name_ar} dir="rtl" lang="ar" onChange={(v) => setF({ ...f, name_ar: v })} />
      <SelectField label={t("units.dimension")} value={f.dimension} disabled={!!uom} onChange={(v) => setF({ ...f, dimension: v as Uom["dimension"] })}
        options={DIMS.map((d) => ({ value: d, label: t(`dim.${d}` as never) }))} />
      {count ? <Notice>{t("units.f.countHint")}</Notice> : (
        <NumberField label={t("units.f.factor", { base: BASE[f.dimension] })} hint={t("units.f.factorHint")} value={f.factor} min={0}
          disabled={!!uom?.is_system} onChange={(v) => setF({ ...f, factor: v })} error={errs.factor_to_base} />
      )}
      {uom && <div className="feature" style={{ padding: "4px 0", border: 0 }}>
        <div className="text"><strong>{t("common.active")}</strong></div>
        <Switch label={t("common.active")} checked={f.active} onChange={(v) => setF({ ...f, active: v })} />
      </div>}
    </Sheet>
  );
}

function MarketSheet({ market, onClose, onSaved }: { market: Market | null; onClose: () => void; onSaved: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const [f, setF] = useState({ code: market?.code ?? "", name_en: market?.name_en ?? "", name_ar: market?.name_ar ?? "",
    currency: market?.currency ?? "EGP", active: market?.active ?? true });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true); setErrs({}); setGeneral(null);
    try {
      if (market) await patch(`/api/markets/${market.id}`, { name_en: f.name_en, name_ar: f.name_ar || null, active: f.active });
      else await post("/api/markets", { code: f.code, name_en: f.name_en, name_ar: f.name_ar || null, currency: f.currency });
      toast(t("markets.savedToast")); onSaved(); onClose();
    } catch (e) { setErrs(fieldErrors(e)); setGeneral(errorText(e, t)); setBusy(false); }
  };
  return (
    <Sheet title={market ? t("markets.form.edit") : t("markets.form.new")} lead={market?.code} onClose={onClose} onSubmit={submit}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button type="submit" variant="primary" busy={busy}>{market ? t("common.save") : t("common.create")}</Button></>}>
      {general && <Notice tone="danger">{general}</Notice>}
      {!market && <TextField label={t("markets.f.code")} value={f.code} dir="ltr" maxLength={20} onChange={(v) => setF({ ...f, code: v.toUpperCase() })} error={errs.code} required />}
      <TextField label={t("items.f.nameEn")} value={f.name_en} dir="ltr" onChange={(v) => setF({ ...f, name_en: v })} error={errs.name_en} required />
      <TextField label={t("items.f.nameAr")} value={f.name_ar} dir="rtl" lang="ar" onChange={(v) => setF({ ...f, name_ar: v })} />
      <TextField label={t("markets.currency")} hint={t("markets.f.currencyHint")} value={f.currency} dir="ltr" maxLength={3} disabled={!!market}
        onChange={(v) => setF({ ...f, currency: v.toUpperCase() })} error={errs.currency} />
      {market && <div className="feature" style={{ padding: "4px 0", border: 0 }}>
        <div className="text"><strong>{t("common.active")}</strong></div>
        <Switch label={t("common.active")} checked={f.active} onChange={(v) => setF({ ...f, active: v })} />
      </div>}
    </Sheet>
  );
}

export function Units() {
  const { t, lang, qty } = useI18n();
  const { editCompany } = usePerms();
  const uoms = useUoms();
  const markets = useMarkets();
  const [uomOpen, setUomOpen] = useState<Uom | "new" | null>(null);
  const [mkOpen, setMkOpen] = useState<Market | "new" | null>(null);
  return (
    <>
      <PageHead title={t("units.title")} lead={t("units.lead")} />
      <ReadOnlyNote show={!editCompany} />
      <div className="units-grid">
        <section className="panel" aria-labelledby="u-h">
          <div className="panel-head">
            <div><h2 id="u-h">{t("units.units")}</h2><p className="small muted">{t("units.unitsLead")}</p></div>
            <span className="spacer" />
            {editCompany && <Button size="sm" icon={<LuPlus />} onClick={() => setUomOpen("new")}>{t("units.new")}</Button>}
          </div>
          {uoms.error ? <LoadError error={uoms.error} onRetry={uoms.reload} /> : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>{t("common.code")}</th><th>{t("common.name")}</th><th>{t("units.dimension")}</th><th>{t("units.size")}</th><th /></tr></thead>
                {!uoms.data ? <LoadingRows cols={5} /> : (
                  <tbody>
                    {uoms.data.items.map((u) => (
                      <tr key={u.id} className={`${editCompany ? "clickable" : ""} ${u.active ? "" : "inactive"}`} onClick={() => editCompany && setUomOpen(u)}>
                        <td className="mono-id cell-main">{u.code}</td>
                        <td>{nameOf(u, lang)}</td>
                        <td className="muted">{t(`dim.${u.dimension}` as never)}</td>
                        <td className="num small">{u.dimension === "count" ? <span className="subtle">{t("units.perItem")}</span> : `${qty(u.factor_to_base, 6)} ${BASE[u.dimension]}`}</td>
                        <td className="actions">{u.is_system ? <Badge>{t("units.standard")}</Badge> : <Badge tone="brand">{t("units.custom")}</Badge>}</td>
                      </tr>
                    ))}
                  </tbody>
                )}
              </table>
            </div>
          )}
        </section>
        <section className="panel" aria-labelledby="m-h">
          <div className="panel-head">
            <div><h2 id="m-h">{t("markets.title")}</h2><p className="small muted">{t("markets.lead")}</p></div>
            <span className="spacer" />
            {editCompany && <Button size="sm" icon={<LuPlus />} onClick={() => setMkOpen("new")}>{t("markets.new")}</Button>}
          </div>
          {markets.error ? <LoadError error={markets.error} onRetry={markets.reload} /> : markets.data && markets.data.items.length === 0 ? (
            <div className="panel-body small subtle">{t("markets.none")}</div>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>{t("common.code")}</th><th>{t("common.name")}</th><th>{t("markets.currency")}</th><th>{t("common.status")}</th></tr></thead>
                {!markets.data ? <LoadingRows cols={4} rows={3} /> : (
                  <tbody>
                    {markets.data.items.map((m) => (
                      <tr key={m.id} className={`${editCompany ? "clickable" : ""} ${m.active ? "" : "inactive"}`} onClick={() => editCompany && setMkOpen(m)}>
                        <td className="mono-id cell-main">{m.code}</td>
                        <td>{nameOf(m, lang)}</td>
                        <td className="mono-id">{m.currency}</td>
                        <td>{m.active ? <Badge tone="ok" dot>{t("common.active")}</Badge> : <Badge>{t("common.inactive")}</Badge>}</td>
                      </tr>
                    ))}
                  </tbody>
                )}
              </table>
            </div>
          )}
        </section>
      </div>
      {uomOpen && <UomSheet uom={uomOpen === "new" ? null : uomOpen} onClose={() => setUomOpen(null)} onSaved={uoms.reload} />}
      {mkOpen && <MarketSheet market={mkOpen === "new" ? null : mkOpen} onClose={() => setMkOpen(null)} onSaved={markets.reload} />}
    </>
  );
}
