import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CompareResult, Patient, StudySummary, get, qs } from "../api";
import { useApp } from "../state";
import { Banner, Empty, Field, Spinner, fmtDate, num, pct, useAsync } from "../ui";

export default function Compare() {
  const { t, lang, errorText } = useApp();
  const [params, setParams] = useSearchParams();
  const [patientId, setPatientId] = useState(params.get("patient") ?? "");
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [res, setRes] = useState<CompareResult | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const { data: patients } = useAsync<Patient[]>(() => get("/api/patients"), []);
  const { data: studies } = useAsync<{ items: StudySummary[] }>(() => (patientId ? get(`/api/studies${qs({ patient_id: patientId, limit: 200 })}`) : Promise.resolve({ items: [] })), [patientId]);
  const usable = (studies?.items ?? []).filter((s) => s.segmented).sort((x, y) => (x.study_date ?? "").localeCompare(y.study_date ?? ""));

  useEffect(() => { setA(""); setB(""); setRes(null); if (patientId) setParams({ patient: patientId }, { replace: true }); }, [patientId]); // eslint-disable-line
  useEffect(() => { if (usable.length >= 2 && !a && !b) { setA(String(usable[0].id)); setB(String(usable[usable.length - 1].id)); } }, [usable.length]); // eslint-disable-line
  useEffect(() => {
    if (!a || !b || a === b) { setRes(null); return; }
    setBusy(true); setErr("");
    get<CompareResult>(`/api/compare${qs({ a, b })}`).then(setRes).catch((e) => { setRes(null); setErr(errorText(e)); }).finally(() => setBusy(false));
  }, [a, b]); // eslint-disable-line

  const unit = (m: string, u: string) => (u === "mm2" ? "mm²" : u === "px" && m === "area" ? "px²" : u);
  return (
    <div className="page">
      <div className="page-head"><div className="grow"><h1>{t("cmp.title")}</h1><p className="sub">{t("cmp.subtitle")}</p></div></div>
      <div className="card card-pad" data-tour="compare-pick"><div className="grid c3">
        <Field label={t("import.patient")}><select value={patientId} onChange={(e) => setPatientId(e.target.value)}><option value="">-</option>{patients?.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.code})</option>)}</select></Field>
        <Field label={t("cmp.baseline")}><select value={a} onChange={(e) => setA(e.target.value)} disabled={!usable.length}><option value="">-</option>{usable.map((s) => <option key={s.id} value={s.id}>{s.code} · {fmtDate(s.study_date, lang)}</option>)}</select></Field>
        <Field label={t("cmp.followup")}><select value={b} onChange={(e) => setB(e.target.value)} disabled={!usable.length}><option value="">-</option>{usable.map((s) => <option key={s.id} value={s.id}>{s.code} · {fmtDate(s.study_date, lang)}</option>)}</select></Field>
      </div></div>
      {!patientId && <Empty icon="compare" title={t("cmp.pick")} text={t("cmp.pick_text")} />}
      {patientId && usable.length < 2 && <Banner kind="info">{t("cmp.need_two")}</Banner>}
      {a && b && a === b && <Banner kind="warn">{t("err.same_study")}</Banner>}
      {err && <Banner kind="danger">{err}</Banner>}
      {busy && <Spinner />}
      {res && (
        <>
          <div className="grid c3">
            <div className="card card-pad col"><h3>{t("cmp.baseline")} · {res.a.study.code}</h3><div style={{ background: "#000", borderRadius: 8, overflow: "hidden" }}><img style={{ width: "100%", display: "block" }} src={`/api/slices/${res.a.slice_id}/image/overlay`} alt={t("cmp.baseline")} /></div><span className="sub">{fmtDate(res.a.study.study_date, lang)}</span></div>
            <div className="card card-pad col"><h3>{t("cmp.followup")} · {res.b.study.code}</h3><div style={{ background: "#000", borderRadius: 8, overflow: "hidden" }}><img style={{ width: "100%", display: "block" }} src={`/api/slices/${res.b.slice_id}/image/overlay`} alt={t("cmp.followup")} /></div><span className="sub">{fmtDate(res.b.study.study_date, lang)}{res.days_between != null && ` · ${t("cmp.days", { n: res.days_between })}`}</span></div>
            <div className="card card-pad col"><h3>{t("cmp.overlay")}</h3><div style={{ background: "#000", borderRadius: 8, overflow: "hidden" }}><img style={{ width: "100%", display: "block" }} src={`/api/compare/overlay.png${qs({ a, b })}`} alt={t("cmp.overlay")} /></div>
              <div className="legend"><span><i style={{ background: "#00c8ff" }} />{t("cmp.only_a")}</span><span><i style={{ background: "#ff3cc8" }} />{t("cmp.only_b")}</span><span><i style={{ background: "#ffd60a" }} />{t("cmp.both")}</span></div></div>
          </div>
          <div className="col">
            <div className="card">
              <div className="card-head"><h3>{t("cmp.change")}</h3></div>
              <table className="tb"><thead><tr><th>{t("cmp.metric")}</th><th>{t("cmp.baseline")}</th><th>{t("cmp.followup")}</th><th>{t("cmp.delta")}</th><th>%</th></tr></thead>
                <tbody>{res.comparison.rows.map((r) => {
                  const up = r.delta > 0;
                  return <tr key={r.metric} style={{ cursor: "default" }}><td>{t(`meas.${r.metric === "area" ? "area" : r.metric === "max_diameter" ? "max_d" : r.metric === "min_diameter" ? "min_d" : "perimeter"}`)}</td>
                    <td className="mono">{num(r.a)} {unit(r.metric, r.unit)}</td><td className="mono">{num(r.b)} {unit(r.metric, r.unit)}</td>
                    <td className="mono" style={{ color: up ? "var(--warn)" : "var(--ok)" }}>{up ? "+" : ""}{num(r.delta)}</td><td className="mono" style={{ color: up ? "var(--warn)" : "var(--ok)" }}>{r.percent == null ? "-" : `${up ? "+" : ""}${r.percent.toFixed(1)}`}</td></tr>;
                })}</tbody></table>
              {res.area_change_per_day != null && <p className="sub" style={{ padding: "0 20px 14px" }}>{t("cmp.rate", { v: num(res.area_change_per_day, 2), u: res.comparison.unit_system === "mm" ? "mm²" : "px²" })}</p>}
            </div>
            {res.notes.filter((n) => n !== "images_not_registered").map((n) => <Banner key={n} kind="warn">{t(`cmp.note_${n}`)}</Banner>)}
          </div>
        </>
      )}
    </div>
  );
}
