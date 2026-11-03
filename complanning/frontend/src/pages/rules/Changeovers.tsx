import { useEffect, useState, type ReactElement } from "react";
import { LuArrowRight, LuArrowRightLeft, LuLayers, LuPlus, LuRepeat, LuSearchCheck, LuShuffle, LuSparkles } from "react-icons/lu";
import {
  Badge, Button, Confirm, Empty, LoadError, Notice, PageHead, SelectField, errorText, useLoad, useToast,
} from "../../components/ui";
import { ReadOnlyNote } from "../../components/master";
import {
  GroupSheet, RuleSheet, VerIcon, useDuration,
  type Cell, type CleaningGroup, type ItemTimes, type Matrix, type Rule, type RuleDraft, type RuleKind, type Verification,
} from "../../components/rules";
import { get, post, qs } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { usePerms } from "../../lib/session";
import { nameOf, type Resource } from "../../lib/types";

interface Resolved {
  rule: Rule | null; source: RuleKind | "none"; scope?: "site" | "machine"; from_group: string | null; to_group: string | null;
  total_minutes: number; cleaning_minutes: number; format_minutes: number; verification: Verification; verification_wait_minutes: number;
}

type Open = { rule: Rule | null; draft: RuleDraft | null };

function CheckChangeover({ siteId, machines, products, scope, version }: { siteId: string; machines: Resource[]; products: ItemTimes[]; scope: string; version: string }) {
  const { t, lang } = useI18n();
  const dur = useDuration();
  const [f, setF] = useState({ resource_id: scope, from: products[0]?.id ?? "", to: products[1]?.id ?? products[0]?.id ?? "" });
  const [res, setRes] = useState<Resolved | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { setF((s) => ({ ...s, resource_id: scope })); }, [scope]);
  useEffect(() => {
    if (!f.from || !f.to) return;
    let live = true;
    get<Resolved>(`/api/sites/${siteId}/changeovers/resolve` + qs({ resource_id: f.resource_id || undefined, from_item_id: f.from, to_item_id: f.to }))
      .then((r) => { if (live) { setRes(r); setErr(null); } }).catch((e) => live && setErr(errorText(e, t)));
    return () => { live = false; };
  }, [siteId, f.resource_id, f.from, f.to, t, version]);
  const opts = products.map((p) => ({ value: p.id, label: `${p.code} · ${nameOf(p, lang)}` }));
  const ruleLabel = (r: Resolved) => {
    if (!r.rule) return "";
    const k = t(`co.kind.${r.source}` as never);
    const what = r.source === "group_to_group" ? ` (${r.rule.from_group} → ${r.rule.to_group})` : r.source === "same_group" && r.rule.from_group ? ` (${r.rule.from_group})`
      : r.source === "product_pair" ? ` (${r.rule.from_item_code} → ${r.rule.to_item_code})` : "";
    return `${k}${what} · ${r.scope === "machine" ? r.rule.resource_code : t("co.allMachines")}`;
  };
  return (
    <div className="panel">
      <div className="panel-body check-co">
        <div className="check-inputs">
          <SelectField label={t("co.machine")} value={f.resource_id} onChange={(v) => setF({ ...f, resource_id: v })}
            options={[{ value: "", label: t("co.allMachines") }, ...machines.map((m) => ({ value: m.id, label: `${m.code} · ${nameOf(m, lang)}` }))]} />
          <SelectField label={t("co.fromProduct")} value={f.from} onChange={(v) => setF({ ...f, from: v })} options={opts} />
          <SelectField label={t("co.toProduct")} value={f.to} onChange={(v) => setF({ ...f, to: v })} options={opts} />
        </div>
        {err ? <Notice tone="danger">{err}</Notice> : res && (
          <div className={`check-result ${res.rule ? "" : "none"}`} aria-live="polite">
            <div className="big">{res.rule ? dur(res.total_minutes) : t("dur.none")}</div>
            <div className="detail">
              <div className="small muted">{t("co.groups", { from: res.from_group ?? t("co.noGroup"), to: res.to_group ?? t("co.noGroup") })}</div>
              {res.rule ? <>
                <div>{t("co.resultSource", { rule: ruleLabel(res) })}</div>
                <div className="chip-row">
                  {res.cleaning_minutes > 0 && <Badge>{t("co.f.cleaning").replace(/ \(.*\)/, "")}: {dur(res.cleaning_minutes)}</Badge>}
                  {res.format_minutes > 0 && <Badge>{t("co.f.format").replace(/ \(.*\)/, "")}: {dur(res.format_minutes)}</Badge>}
                  {res.verification !== "none" && <Badge tone="warn">{t(`ver.${res.verification}` as never)}{res.verification_wait_minutes > 0 ? ` · ${dur(res.verification_wait_minutes)}` : ""}</Badge>}
                </div>
              </> : <div className="muted">{t("co.resultNone")}</div>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function Changeovers() {
  const { t, lang, number } = useI18n();
  const { editSite, editCompany, site, siteId, admin } = usePerms();
  const toast = useToast();
  const dur = useDuration();
  const [scope, setScope] = useState("");
  useEffect(() => { setScope(""); }, [siteId]);
  const groupsL = useLoad(() => get<{ items: CleaningGroup[] }>("/api/cleaning-groups"));
  const machinesL = useLoad(() => (siteId ? get<{ items: Resource[] }>(`/api/sites/${siteId}/resources`) : Promise.resolve(null)), [siteId]);
  const productsL = useLoad(() => get<{ items: ItemTimes[] }>("/api/item-times"));
  const rulesL = useLoad(() => (siteId ? get<{ items: Rule[] }>(`/api/sites/${siteId}/changeovers`) : Promise.resolve(null)), [siteId]);
  const matrixL = useLoad(() => (siteId ? get<Matrix>(`/api/sites/${siteId}/changeovers/matrix` + qs({ resource_id: scope || undefined })) : Promise.resolve(null)), [siteId, scope]);
  const [groupOpen, setGroupOpen] = useState<CleaningGroup | "new" | null>(null);
  const [open, setOpen] = useState<Open | null>(null);
  const [sampling, setSampling] = useState(false);

  if (!siteId) return <><PageHead title={t("co.title")} /><Notice>{t("common.noSite")}</Notice></>;
  const canEdit = editSite(siteId);
  const groups = groupsL.data?.items ?? [];
  const machines = (machinesL.data?.items ?? []).filter((m) => m.active && m.type === "machine");
  const products = productsL.data?.items ?? [];
  const rules = rulesL.data?.items ?? [];
  const reloadRules = () => { rulesL.reload(); matrixL.reload(); };
  const reloadAll = () => { groupsL.reload(); productsL.reload(); reloadRules(); };
  const scopeId = scope || null;
  const byId = (id: string) => rules.find((r) => r.id === id) ?? null;
  const seedOf = (r: Rule | null) => r ? { cleaning_minutes: r.cleaning_minutes, format_minutes: r.format_minutes, verification: r.verification, verification_wait_minutes: r.verification_wait_minutes } : undefined;
  const loadError = groupsL.error || machinesL.error || rulesL.error || matrixL.error;
  const empty = rulesL.data && rules.length === 0 && groupsL.data && groups.length === 0;

  /** Open the rule written for this exact case and scope, or a new one seeded from the rule in force now. */
  const openCase = (kind: RuleKind, from_group: string | null, to_group: string | null, inForce: Cell | null) => {
    if (!canEdit) return;
    const exact = rules.find((r) => r.kind === kind && r.resource_id === scopeId && (r.from_group ?? null) === from_group && (r.to_group ?? null) === to_group) ?? null;
    if (exact) return setOpen({ rule: exact, draft: null });
    setOpen({ rule: null, draft: { kind, resource_id: scopeId, from_group, to_group, seed: seedOf(inForce ? byId(inForce.rule_id) : null) } });
  };

  const general: { kind: RuleKind; icon: ReactElement; cell: Cell | null }[] = [
    { kind: "same_product", icon: <LuRepeat />, cell: matrixL.data?.same_product ?? null },
    { kind: "same_group", icon: <LuLayers />, cell: (() => {
      const r = rules.find((x) => x.kind === "same_group" && !x.from_group && x.resource_id === scopeId)
        ?? (scopeId ? rules.find((x) => x.kind === "same_group" && !x.from_group && !x.resource_id) : undefined);
      return r ? { rule_id: r.id, kind: r.kind, total_minutes: r.total_minutes, verification: r.verification, specific: true, scope: r.resource_id ? "machine" : "site" } as Cell : null;
    })() },
    { kind: "default", icon: <LuShuffle />, cell: matrixL.data?.default ?? null },
  ];
  const ownScope = (c: Cell | null) => !!c && (c.scope === "machine") === !!scopeId;
  const pairs = rules.filter((r) => r.kind === "product_pair" && (!scopeId || r.resource_id === scopeId || !r.resource_id));

  return (
    <>
      <PageHead title={t("co.title")} lead={t("co.lead", { site: site?.name ?? "" })} actions={<>
        {admin && rulesL.data && rules.length === 0 && <Button icon={<LuSparkles />} onClick={() => setSampling(true)}>{t("co.loadSample")}</Button>}
      </>} />
      <ReadOnlyNote show={!canEdit} />
      {loadError ? <LoadError error={loadError} onRetry={reloadAll} /> : null}

      <div className="section-head" style={{ marginTop: 8 }}>
        <div className="titles"><h2>{t("groups.title")}</h2><p>{t("groups.lead")}</p></div>
        <div className="actions">{editCompany && <Button icon={<LuPlus />} onClick={() => setGroupOpen("new")}>{t("groups.new")}</Button>}</div>
      </div>
      {groupsL.data && groups.length === 0 ? (
        <div className="panel"><Empty icon={<LuLayers />} title={t("groups.title")} body={t("groups.none")} action={<div className="row wrap" style={{ justifyContent: "center" }}>
          {editCompany && <Button variant="primary" icon={<LuPlus />} onClick={() => setGroupOpen("new")}>{t("groups.new")}</Button>}
          {admin && empty && <Button icon={<LuSparkles />} onClick={() => setSampling(true)}>{t("co.loadSample")}</Button>}
        </div>} /></div>
      ) : (
        <div className="group-cards">
          {groups.map((g, i) => (
            <button key={g.id} type="button" className={`group-card tone-${i % 6} ${g.active ? "" : "inactive"}`} disabled={!editCompany} onClick={() => setGroupOpen(g)}>
              <span className="code" dir="ltr">{g.code}</span>
              <span className="name">{nameOf(g, lang)}</span>
              <span className="count">{t("groups.items", { n: number(g.item_count) })}</span>
            </button>
          ))}
        </div>
      )}

      <div className="scope-bar">
        <label htmlFor="co-scope" className="small muted">{t("co.scope")}</label>
        <select id="co-scope" className="select" value={scope} onChange={(e) => setScope(e.target.value)}>
          <option value="">{t("co.allMachines")}</option>
          {machines.map((m) => <option key={m.id} value={m.id}>{m.code} · {nameOf(m, lang)}</option>)}
        </select>
        <span className="small subtle">{t("co.scopeHint")}</span>
      </div>

      <div className="section-head">
        <div className="titles"><h2>{t("co.general")}</h2><p>{t("co.generalLead")}</p></div>
      </div>
      <div className="rule-cards">
        {general.map(({ kind, icon, cell }) => {
          const r = cell ? byId(cell.rule_id) : null;
          const inherited = cell && !ownScope(cell);
          return (
            <button key={kind} type="button" className={`rule-card ${cell ? "" : "unset"} ${inherited ? "inherited" : ""}`} disabled={!canEdit}
              onClick={() => openCase(kind, null, null, cell)}>
              <span className="icon">{icon}</span>
              <span className="title">{t(`co.kind.${kind}` as never)}</span>
              <span className="desc">{t(`co.kind.${kind}.d` as never)}</span>
              <span className="value">{cell ? dur(cell.total_minutes) : t("co.notSet")}{cell && <VerIcon v={cell.verification} />}</span>
              {r && <span className="parts">
                {r.cleaning_minutes > 0 && <span>{t("co.f.cleaning").replace(/ \(.*\)/, "")} {dur(r.cleaning_minutes)}</span>}
                {r.format_minutes > 0 && <span>{t("co.f.format").replace(/ \(.*\)/, "")} {dur(r.format_minutes)}</span>}
                {r.verification_wait_minutes > 0 && <span>{t(`ver.${r.verification}` as never)} {dur(r.verification_wait_minutes)}</span>}
              </span>}
              {inherited && <Badge>{t("co.fromSite")}</Badge>}
              {cell && !inherited && scopeId && <Badge tone="brand">{t("co.machineRule")}</Badge>}
            </button>
          );
        })}
      </div>

      <div className="section-head">
        <div className="titles"><h2>{t("co.matrix")}</h2><p>{t("co.matrixLead")}</p></div>
      </div>
      <div className="panel">
        {matrixL.data && matrixL.data.groups.length > 0 ? (
          <div className="table-wrap">
            <table className="matrix">
              <thead>
                <tr>
                  <th className="corner"><span className="to">{t("co.to")} <LuArrowRight className="flip-rtl" /></span><span className="from">{t("co.from")}</span></th>
                  {matrixL.data.groups.map((g) => <th key={g.code} scope="col" title={nameOf(g, lang)}><span dir="ltr">{g.code}</span></th>)}
                </tr>
              </thead>
              <tbody>
                {matrixL.data.groups.map((fg, i) => (
                  <tr key={fg.code}>
                    <th scope="row" title={nameOf(fg, lang)}><span dir="ltr">{fg.code}</span><span className="sub">{nameOf(fg, lang)}</span></th>
                    {matrixL.data!.matrix[i].map((c, j) => {
                      const tg = matrixL.data!.groups[j];
                      const same = fg.code === tg.code;
                      const mine = c && c.specific && ownScope(c);
                      const heat = c ? Math.min(5, Math.ceil(c.total_minutes / 60)) : 0;
                      return (
                        <td key={tg.code} className={same ? "diag" : ""}>
                          <button type="button" className={`mcell heat-${heat} ${mine ? "own" : "general"} ${c ? "" : "unset"}`} disabled={!canEdit}
                            aria-label={`${fg.code} → ${tg.code}: ${c ? dur(c.total_minutes) : t("co.notSet")}`}
                            onClick={() => openCase(same ? "same_group" : "group_to_group", fg.code, same ? null : tg.code, c)}>
                            <span className="v">{c ? dur(c.total_minutes) : "—"}</span>
                            <span className="meta">{c && <VerIcon v={c.verification} />}{c && !mine && <span className="tag">{c.specific && c.scope === "site" ? t("co.fromSite") : t("co.cellGeneral")}</span>}</span>
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : matrixL.data ? <div className="panel-body small subtle">{t("groups.none")}</div> : <div className="panel-body"><div className="skeleton" style={{ height: 160 }} /></div>}
      </div>

      <div className="section-head">
        <div className="titles"><h2>{t("co.pairs")}</h2><p>{t("co.pairsLead")}</p></div>
        <div className="actions">{canEdit && products.length > 1 && <Button icon={<LuArrowRightLeft />}
          onClick={() => setOpen({ rule: null, draft: { kind: "product_pair", resource_id: scopeId } })}>{t("co.newPair")}</Button>}</div>
      </div>
      <div className="panel">
        {pairs.length === 0 ? <div className="panel-body small subtle">{t("co.noPairs")}</div> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>{t("co.fromProduct")}</th><th>{t("co.toProduct")}</th><th>{t("co.machine")}</th><th className="num">{t("co.total")}</th><th>{t("co.f.notes")}</th></tr></thead>
              <tbody>
                {pairs.map((r) => (
                  <tr key={r.id} className={canEdit ? "clickable" : ""} onClick={() => canEdit && setOpen({ rule: r, draft: null })}>
                    <td className="mono-id cell-main" dir="ltr" style={{ textAlign: "start" }}>{r.from_item_code}</td>
                    <td className="mono-id cell-main" dir="ltr" style={{ textAlign: "start" }}>{r.to_item_code}</td>
                    <td>{r.resource_code ? <span className="mono-id">{r.resource_code}</span> : <span className="muted">{t("co.allMachines")}</span>}</td>
                    <td className="num"><span className="row" style={{ gap: 6, justifyContent: "flex-end" }}><VerIcon v={r.verification} />{dur(r.total_minutes)}</span></td>
                    <td className="small muted">{r.notes}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="section-head">
        <div className="titles"><h2><LuSearchCheck className="inline-icon" /> {t("co.check")}</h2><p>{t("co.checkLead")}</p></div>
      </div>
      {products.length > 0 && <CheckChangeover key={siteId} version={rules.map((r) => r.id + r.total_minutes + r.verification).join(",")} siteId={siteId} machines={machines} products={products} scope={scope} />}

      {groupOpen && <GroupSheet group={groupOpen === "new" ? null : groupOpen} onClose={() => setGroupOpen(null)} onSaved={reloadAll} />}
      {open && <RuleSheet siteId={siteId} rule={open.rule} draft={open.draft} machines={machines} products={products} groups={groups}
        onClose={() => setOpen(null)} onSaved={reloadRules} />}
      {sampling && <Confirm title={t("co.sampleTitle")} body={t("co.sampleBody")} confirmLabel={t("co.loadSample")} onClose={() => setSampling(false)}
        onConfirm={async () => { await post(`/api/sites/${siteId}/sample-rules`); toast(t("co.sampleDone")); reloadAll(); }} />}
    </>
  );
}
