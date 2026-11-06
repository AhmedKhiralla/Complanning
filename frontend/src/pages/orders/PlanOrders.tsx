/* Plan › Orders: batch numbers, and manufacturing / packaging orders per batch, made for one batch, a product or all. */
import { useEffect, useMemo, useState } from "react";
import { LuFileText, LuFileType, LuHash, LuPenLine, LuPlus, LuRefreshCw, LuSend, LuTrash2, LuX } from "react-icons/lu";
import { TypeBadge } from "../../components/master";
import { Badge, Button, Dialog, Field, LoadError, Notice, SelectField, TextField, errorText, useLoad, useToast } from "../../components/ui";
import { get, post, put } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import type { StringKey } from "../../lib/strings";
import { nameOf, type ItemType } from "../../lib/types";

type Kind = "manufacturing" | "packaging";
const KINDS: Kind[] = ["manufacturing", "packaging"];
interface Order {
  id: string; kind: Kind; number: string; batch_number: string; status: "draft" | "approved" | "issued" | "cancelled"; revision: number;
  item_id: string; ordinal: number; batch_id: string | null; levels: string[]; esign: boolean; outdated: boolean; cancel_reason: string | null;
  signatures: { level: number; title: string; user_id: string; user_name: string; signed_at: string }[];
}
interface Batch {
  id: string; batch_no: string; item_id: string; code: string; name_en: string; name_ar: string | null; type: ItemType; uom: string;
  quantity: number; status: string; start_at: string | null; ordinal: number; lot_no?: string | null;
}
interface OrdersData {
  orders: Order[]; templates: { id: string; kind: Kind; name: string; is_default: boolean; active: boolean }[];
  batch_numbers: Record<string, string>; numbering: { pattern: string | null; next: number; example: string | null };
}

const tone = (s: Order["status"]) => (s === "issued" ? "ok" : s === "approved" ? "brand" : s === "cancelled" ? "danger" : "warn");

export function PlanOrders({ plan, tz, canPlan, onChanged }: {
  plan: { id: string; site_id: string; status: string; batches: Batch[] }; tz: string; canPlan: boolean; onChanged: () => void;
}) {
  const { t, lang, qty, dateTime } = useI18n();
  const toast = useToast();
  const data = useLoad(() => get<OrdersData>(`/api/plans/${plan.id}/orders`), [plan.id]);
  const [product, setProduct] = useState("");
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [kindFilter, setKindFilter] = useState<"" | Kind>("");
  const [dialog, setDialog] = useState<null | "create" | "sign" | "cancel" | "reissue">(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const batches = useMemo(() => plan.batches.filter((b) => b.status === "scheduled"), [plan.batches]);
  const products = useMemo(() => Array.from(new Map(batches.map((b) => [b.item_id, b])).values()), [batches]);
  const shown = batches.filter((b) => !product || b.item_id === product);
  const key = (b: Batch) => `${b.item_id}:${b.ordinal}`;
  const nums = data.data?.batch_numbers ?? {};
  const live = (data.data?.orders ?? []).filter((o) => o.status !== "cancelled");
  const ordersOf = (b: Batch) => live.filter((o) => o.item_id === b.item_id && o.ordinal === b.ordinal);
  const selectedOrders = live.filter((o) => o.batch_id && sel.has(o.batch_id) && (!kindFilter || o.kind === kindFilter));
  const released = plan.status === "released";

  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setErr(null);
    try { await fn(); data.reload(); onChanged(); } catch (e) { setErr(errorText(e, t)); } finally { setBusy(false); }
  };
  const fileUrl = (fmt: "pdf" | "docx") => `/api/orders/file?format=${fmt}&ids=${selectedOrders.map((o) => o.id).join(",")}`;

  if (data.error) return <LoadError error={data.error} onRetry={data.reload} />;
  if (!data.data) return <div className="skeleton" style={{ width: "40%" }} />;

  return (
    <div className="stack">
      {!released && <Notice>{t("po.notReleased")}</Notice>}
      {err && <Notice tone="danger">{err}</Notice>}
      <Numbering siteId={plan.site_id} planId={plan.id} numbering={data.data.numbering} canPlan={canPlan}
        onDone={() => { data.reload(); onChanged(); }} />

      <div className="panel">
        <div className="panel-body po-toolbar">
          <div style={{ minWidth: 200 }}>
            <SelectField label={t("po.product")} value={product} onChange={setProduct}
              options={[{ value: "", label: t("po.allProducts") }, ...products.map((b) => ({ value: b.item_id, label: `${b.code} · ${nameOf(b, lang)}` }))]} />
          </div>
          <div style={{ minWidth: 160 }}>
            <SelectField label={t("po.kindFilter")} value={kindFilter} onChange={(v) => setKindFilter(v as "" | Kind)}
              options={[{ value: "", label: t("po.both") }, ...KINDS.map((k) => ({ value: k, label: t(`ot.kind.${k}` as StringKey) }))]} />
          </div>
          <Button onClick={() => setSel(new Set([...sel, ...shown.map((b) => b.id)]))}>{t("po.selectShown")}</Button>
          {sel.size > 0 && <Button variant="ghost" icon={<LuX />} onClick={() => setSel(new Set())}>{t("po.clear")}</Button>}
          <span className="small muted grow">{sel.size > 0 ? t("po.selected", { n: sel.size }) : ""}</span>
        </div>
        {sel.size > 0 && (
          <div className="panel-body po-actions">
            {canPlan && released && <Button variant="primary" icon={<LuPlus />} onClick={() => setDialog("create")}>{t("po.create")}</Button>}
            <a className={`btn ${selectedOrders.length ? "" : "disabled"}`} aria-disabled={!selectedOrders.length}
              href={selectedOrders.length ? fileUrl("pdf") : undefined}><LuFileText aria-hidden />{t("po.pdf")}</a>
            <a className={`btn ${selectedOrders.length ? "" : "disabled"}`} aria-disabled={!selectedOrders.length}
              href={selectedOrders.length ? fileUrl("docx") : undefined}><LuFileType aria-hidden />{t("po.word")}</a>
            {selectedOrders.some((o) => o.status === "draft" && o.esign) && <Button icon={<LuPenLine />} onClick={() => setDialog("sign")}>{t("po.sign")}</Button>}
            {canPlan && selectedOrders.some((o) => (o.status === "draft" && !o.esign) || o.status === "approved") &&
              <Button icon={<LuSend />} busy={busy} onClick={() => run(async () => {
                const ids = selectedOrders.filter((o) => (o.status === "draft" && !o.esign) || o.status === "approved").map((o) => o.id);
                await post("/api/orders/issue", { order_ids: ids }); toast(t("po.issued", { n: ids.length }));
              })}>{t("po.issue")}</Button>}
            {canPlan && selectedOrders.some((o) => o.status === "approved" || o.status === "issued") &&
              <Button icon={<LuRefreshCw />} onClick={() => setDialog("reissue")}>{t("po.reissue")}</Button>}
            {canPlan && selectedOrders.length > 0 && <Button icon={<LuX />} onClick={() => setDialog("cancel")}>{t("po.cancel")}</Button>}
            {canPlan && selectedOrders.some((o) => o.status === "draft" && !o.signatures.length) &&
              <Button variant="ghost" icon={<LuTrash2 />} busy={busy} onClick={() => run(async () => {
                await post("/api/orders/delete", { order_ids: selectedOrders.filter((o) => o.status === "draft" && !o.signatures.length).map((o) => o.id) });
                toast(t("po.deleted"));
              })}>{t("po.deleteDrafts")}</Button>}
          </div>
        )}
        <div className="table-wrap"><table className="table po-table">
          <thead><tr>
            <th className="center" style={{ width: 36 }}>
              <input type="checkbox" className="cb" aria-label={t("po.selectShown")} checked={shown.length > 0 && shown.every((b) => sel.has(b.id))}
                onChange={(e) => { const n = new Set(sel); shown.forEach((b) => (e.target.checked ? n.add(b.id) : n.delete(b.id))); setSel(n); }} /></th>
            <th>{t("pv.batch")}</th><th>{t("pv.item")}</th><th className="num">{t("pv.qty")}</th><th>{t("pv.start")}</th>
            <th>{t("po.batchNo")}</th>{KINDS.map((k) => <th key={k}>{t(`ot.kind.${k}` as StringKey)}</th>)}
          </tr></thead>
          <tbody>{shown.map((b) => {
            const os = ordersOf(b);
            return (
              <tr key={b.id} className={sel.has(b.id) ? "selected" : ""}>
                <td className="center"><input type="checkbox" className="cb" aria-label={b.batch_no} checked={sel.has(b.id)}
                  onChange={(e) => { const n = new Set(sel); if (e.target.checked) n.add(b.id); else n.delete(b.id); setSel(n); }} /></td>
                <td className="mono-id cell-main">{b.batch_no}</td>
                <td><span className="mono-id">{b.code}</span> <TypeBadge type={b.type} /><div className="small muted">{nameOf(b, lang)}</div></td>
                <td className="num">{qty(b.quantity, 1)} <span className="small subtle">{b.uom}</span></td>
                <td className="small num">{b.start_at ? dateTime(b.start_at, tz) : "—"}</td>
                <td><BatchNumber planId={plan.id} batchId={b.id} value={nums[key(b)] ?? ""} disabled={!canPlan}
                  onSaved={() => { data.reload(); onChanged(); toast(t("po.numberSaved")); }} onError={setErr} /></td>
                {KINDS.map((k) => {
                  const o = os.find((x) => x.kind === k);
                  return <td key={k}>{o ? <OrderCell o={o} /> : <span className="subtle">{t("po.none")}</span>}</td>;
                })}
              </tr>
            );
          })}</tbody>
        </table></div>
      </div>

      {dialog === "create" && <CreateDialog planId={plan.id} batchIds={[...sel]} templates={data.data.templates}
        onClose={() => setDialog(null)} onDone={() => { setDialog(null); data.reload(); onChanged(); }} />}
      {dialog === "sign" && <SignDialog orders={selectedOrders.filter((o) => o.status === "draft" && o.esign)}
        onClose={() => setDialog(null)} onDone={() => { setDialog(null); data.reload(); }} />}
      {(dialog === "cancel" || dialog === "reissue") && <ReasonDialog kind={dialog}
        orders={dialog === "cancel" ? selectedOrders : selectedOrders.filter((o) => o.status === "approved" || o.status === "issued")}
        onClose={() => setDialog(null)} onDone={() => { setDialog(null); data.reload(); }} />}
    </div>
  );
}

function OrderCell({ o }: { o: Order }) {
  const { t } = useI18n();
  return (
    <div className="po-cell">
      <span className="mono-id">{o.number}</span>
      <span className="row" style={{ gap: 6, flexWrap: "wrap" }}>
        <Badge tone={tone(o.status)}>{t(`po.st.${o.status}` as StringKey)}</Badge>
        {o.esign && o.status === "draft" && o.levels.length > 0 &&
          <span className="small subtle" title={o.signatures.map((s) => `${s.title}: ${s.user_name}`).join("\n")}>{t("po.signedOf", { n: o.signatures.length, of: o.levels.length })}</span>}
        {o.revision > 0 && <span className="small subtle">{t("po.rev", { n: o.revision })}</span>}
      </span>
      {o.outdated && <span className="small text-warn">{t("po.outdated")}</span>}
    </div>
  );
}

function BatchNumber({ planId, batchId, value, disabled, onSaved, onError }: {
  planId: string; batchId: string; value: string; disabled: boolean; onSaved: () => void; onError: (m: string | null) => void;
}) {
  const { t } = useI18n();
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  const save = async () => {
    if (v.trim() === value) return;
    try { onError(null); await put(`/api/plans/${planId}/batch-numbers`, { numbers: { [batchId]: v.trim() || null } }); onSaved(); }
    catch (e) { onError(errorText(e, t)); setV(value); }
  };
  return <input className="input po-num" value={v} disabled={disabled} maxLength={40} dir="ltr" placeholder={t("po.batchNoPh")}
    aria-label={t("po.batchNo")} onChange={(e) => setV(e.target.value)} onBlur={save}
    onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") setV(value); }} />;
}

function Numbering({ siteId, planId, numbering, canPlan, onDone }: {
  siteId: string; planId: string; numbering: OrdersData["numbering"]; canPlan: boolean; onDone: () => void;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [pattern, setPattern] = useState(numbering.pattern ?? "");
  const [next, setNext] = useState(String(numbering.next));
  const [err, setErr] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [open, setOpen] = useState(!numbering.pattern);
  useEffect(() => { setNext(String(numbering.next)); setPattern(numbering.pattern ?? ""); }, [numbering.next, numbering.pattern]);
  return (
    <details className="panel po-numbering" open={open} onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary className="panel-head"><h3><LuHash aria-hidden /> {t("po.numbering")}</h3>
        <span className="small muted">{numbering.pattern ? `${numbering.pattern} · ${numbering.example ?? ""}` : ""}</span></summary>
      <div className="panel-body stack">
        <p className="small muted" style={{ margin: 0 }}>{t("po.numberingLead")}</p>
        {msg && <Notice tone="danger">{msg}</Notice>}
        <div className="po-num-form">
          <TextField label={t("po.pattern")} hint={t("po.patternHint")} value={pattern} dir="ltr" maxLength={60} disabled={!canPlan}
            error={err.pattern} onChange={setPattern} />
          <TextField label={t("po.next")} value={next} dir="ltr" inputMode="numeric" disabled={!canPlan} onChange={(v) => setNext(v.replace(/\D/g, ""))} />
          {canPlan && <div className="row" style={{ gap: 8, alignSelf: "flex-end", paddingBottom: 22 }}>
            <Button busy={busy === "save"} onClick={async () => {
              setBusy("save"); setErr({}); setMsg(null);
              try { await put(`/api/sites/${siteId}/batch-numbering`, { pattern: pattern || null, next: Number(next) || 1 }); toast(t("po.patternSaved")); onDone(); }
              catch (e) { setMsg(errorText(e, t)); setErr((e as { fields?: Record<string, string> }).fields ?? {}); } finally { setBusy(null); }
            }}>{t("po.savePattern")}</Button>
            <Button variant="primary" busy={busy === "fill"} disabled={!numbering.pattern} onClick={async () => {
              setBusy("fill"); setMsg(null);
              try { const r = await post<{ filled: number }>(`/api/plans/${planId}/batch-numbers/fill`, {}); toast(t("po.filled", { n: r.filled })); onDone(); }
              catch (e) { setMsg(errorText(e, t)); } finally { setBusy(null); }
            }}>{t("po.fill")}</Button>
          </div>}
        </div>
      </div>
    </details>
  );
}

function CreateDialog({ planId, batchIds, templates, onClose, onDone }: {
  planId: string; batchIds: string[]; templates: OrdersData["templates"]; onClose: () => void; onDone: () => void;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [kinds, setKinds] = useState<Kind[]>(KINDS);
  const [tpl, setTpl] = useState<Record<string, string>>(() => Object.fromEntries(KINDS.map((k) => [k, templates.find((x) => x.kind === k && x.is_default)?.id ?? ""])));
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ created: string[]; skipped: { batch: string; kind: string | null; reason: string }[] } | null>(null);
  return (
    <Dialog title={t("po.createTitle")} onClose={result ? onDone : onClose} footer={result
      ? <Button variant="primary" onClick={onDone}>{t("po.done")}</Button>
      : <><Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" busy={busy} disabled={!kinds.length} onClick={async () => {
          setBusy(true); setErr(null);
          try {
            const r = await post<typeof result & object>(`/api/plans/${planId}/orders`, { batch_ids: batchIds, kinds, template_ids: tpl });
            // A batch without materials of a kind simply has no order of that kind; only list real skips.
            setResult({ ...r, skipped: r.skipped.filter((x) => x.reason !== "no_components") }); toast(t("po.created", { n: r.created.length }));
          } catch (e) { setErr(errorText(e, t)); } finally { setBusy(false); }
        }}>{t("po.create")}</Button></>}>
      {result ? (
        <div className="stack">
          <p><strong>{t("po.created", { n: result.created.length })}</strong>{result.skipped.length ? ` · ${t("po.skipped", { n: result.skipped.length })}` : ""}</p>
          {result.skipped.length > 0 && <ul className="small muted" style={{ margin: 0, maxHeight: 220, overflow: "auto" }}>
            {result.skipped.map((s, i) => <li key={i}>{s.batch}{s.kind ? ` · ${t(`ot.kind.${s.kind}` as StringKey)}` : ""}: {t(`po.reasons.${s.reason}` as StringKey)}</li>)}
          </ul>}
        </div>
      ) : (
        <div className="stack">
          <p className="small muted" style={{ margin: 0 }}>{t("po.createLead")}</p>
          {err && <Notice tone="danger">{err}</Notice>}
          <Field label={t("po.kinds")}>{() => (
            <div className="stack" style={{ gap: 10 }}>
              {KINDS.map((k) => (
                <div key={k} className="row" style={{ gap: 10, flexWrap: "wrap" }}>
                  <label className="row" style={{ gap: 6, minWidth: 190 }}>
                    <input type="checkbox" className="cb" checked={kinds.includes(k)} onChange={(e) => setKinds(e.target.checked ? [...kinds, k] : kinds.filter((x) => x !== k))} />
                    {t(`ot.kind.${k}` as StringKey)}</label>
                  <select className="select" style={{ maxWidth: 260 }} aria-label={t("po.template")} value={tpl[k]} disabled={!kinds.includes(k)}
                    onChange={(e) => setTpl({ ...tpl, [k]: e.target.value })}>
                    {templates.filter((x) => x.kind === k && x.active).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
                  </select>
                </div>
              ))}
            </div>
          )}</Field>
          <p className="small subtle" style={{ margin: 0 }}>{t("po.selected", { n: batchIds.length })}</p>
        </div>
      )}
    </Dialog>
  );
}

function SignDialog({ orders, onClose, onDone }: { orders: Order[]; onClose: () => void; onDone: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const [password, setPassword] = useState("");
  const [meaning, setMeaning] = useState("approved");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <Dialog title={t("po.signTitle", { n: orders.length })} onClose={onClose} footer={<>
      <Button onClick={onClose}>{t("common.cancel")}</Button>
      <Button variant="primary" busy={busy} disabled={!password} onClick={async () => {
        setBusy(true); setErr(null);
        try { await post("/api/orders/sign", { order_ids: orders.map((o) => o.id), password, meaning }); toast(t("po.signed")); onDone(); }
        catch (e) { setErr(errorText(e, t)); setPassword(""); } finally { setBusy(false); }
      }}>{t("po.sign")}</Button></>}>
      <div className="stack">
        <p className="small muted" style={{ margin: 0 }}>{t("po.signLead")}</p>
        {err && <Notice tone="danger">{err}</Notice>}
        <ul className="small" style={{ margin: 0, maxHeight: 160, overflow: "auto" }}>
          {orders.map((o) => <li key={o.id}><span className="mono-id">{o.number}</span> · {o.levels[o.signatures.length] ?? ""}</li>)}
        </ul>
        <SelectField label={t("po.meaning")} value={meaning} onChange={setMeaning}
          options={(["approved", "reviewed", "issued", "received"] as const).map((m) => ({ value: m, label: t(`po.meaning.${m}` as StringKey) }))} />
        <TextField label={t("po.password")} type="password" autoComplete="current-password" value={password} onChange={setPassword} />
      </div>
    </Dialog>
  );
}

function ReasonDialog({ kind, orders, onClose, onDone }: { kind: "cancel" | "reissue"; orders: Order[]; onClose: () => void; onDone: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <Dialog title={t(kind === "cancel" ? "po.cancelTitle" : "po.reissueTitle", { n: orders.length })} onClose={onClose} footer={<>
      <Button onClick={onClose}>{t("common.cancel")}</Button>
      <Button variant={kind === "cancel" ? "danger" : "primary"} busy={busy} disabled={reason.trim().length < 3} onClick={async () => {
        setBusy(true); setErr(null);
        try { await post(`/api/orders/${kind}`, { order_ids: orders.map((o) => o.id), reason }); toast(t("po.done")); onDone(); }
        catch (e) { setErr(errorText(e, t)); } finally { setBusy(false); }
      }}>{t(kind === "cancel" ? "po.cancel" : "po.reissue")}</Button></>}>
      <div className="stack">
        {kind === "reissue" && <p className="small muted" style={{ margin: 0 }}>{t("po.reissueLead")}</p>}
        {err && <Notice tone="danger">{err}</Notice>}
        <ul className="small" style={{ margin: 0, maxHeight: 160, overflow: "auto" }}>
          {orders.map((o) => <li key={o.id}><span className="mono-id">{o.number}</span> · {t(`po.st.${o.status}` as StringKey)}</li>)}
        </ul>
        <TextField label={t("po.reason")} hint={t("po.reasonHint")} value={reason} maxLength={300} onChange={setReason} />
      </div>
    </Dialog>
  );
}

