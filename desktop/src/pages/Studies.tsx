import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { CLASS_NAMES, StudySummary, get, qs } from "../api";
import { useApp } from "../state";
import { ClassChip, Empty, Icon, StatusChip, fmtDate, pct, useAsync, useDebounced } from "../ui";

export default function Studies() {
  const { t, lang } = useApp();
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [label, setLabel] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const dq = useDebounced(q);
  const { data, loading } = useAsync<{ total: number; items: StudySummary[] }>(
    () => get(`/api/studies${qs({ q: dq, status, label, date_from: from, date_to: to, limit: 200 })}`), [dq, status, label, from, to]);
  return (
    <div className="page">
      <div className="page-head">
        <div className="grow"><h1>{t("studies.title")}</h1><p className="sub">{t("studies.subtitle")}</p></div>
        <a className="btn" href="/api/studies/export.csv" download><Icon name="download" size={18} />{t("studies.export_csv")}</a>
        <Link to="/import" className="btn primary"><Icon name="plus" size={18} />{t("dash.new")}</Link>
      </div>
      <div className="card card-pad">
        <div className="row wrap" style={{ alignItems: "flex-end" }}>
          <label className="field" style={{ flex: "2 1 220px" }}><span>{t("common.search")}</span><input type="search" placeholder={t("studies.search_ph")} value={q} onChange={(e) => setQ(e.target.value)} /></label>
          <label className="field" style={{ flex: "1 1 150px" }}><span>{t("studies.status")}</span>
            <select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">{t("common.all")}</option>{["pending", "analyzed", "reviewed", "flagged"].map((s) => <option key={s} value={s}>{t(`status.${s}`)}</option>)}</select></label>
          <label className="field" style={{ flex: "1 1 170px" }}><span>{t("studies.prediction")}</span>
            <select value={label} onChange={(e) => setLabel(e.target.value)}><option value="">{t("common.all")}</option>{CLASS_NAMES.map((c) => <option key={c} value={c}>{t(`class.${c}`)}</option>)}</select></label>
          <label className="field" style={{ flex: "1 1 150px" }}><span>{t("common.from")}</span><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
          <label className="field" style={{ flex: "1 1 150px" }}><span>{t("common.to")}</span><input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
        </div>
      </div>
      <div className="card">
        {data && data.items.length ? (
          <div className="table-wrap"><table className="tb">
            <thead><tr><th>{t("studies.id")}</th><th>{t("studies.patient")}</th><th>{t("studies.date")}</th><th>{t("studies.prediction")}</th><th>{t("studies.confidence")}</th><th>{t("studies.status")}</th><th>{t("studies.slices")}</th></tr></thead>
            <tbody>{data.items.map((s) => (
              <tr key={s.id} onClick={() => nav(`/studies/${s.id}`)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && nav(`/studies/${s.id}`)}>
                <td className="mono">{s.code}</td>
                <td>{s.patient ? <><b style={{ fontWeight: 500 }}>{s.patient.name}</b> <span className="mono" style={{ color: "var(--dim)" }}>{s.patient.code}</span></> : <span style={{ color: "var(--dim)" }}>{t("studies.unassigned")}</span>}</td>
                <td>{fmtDate(s.study_date, lang)}</td>
                <td>{s.prediction ? <ClassChip label={s.prediction.label} /> : <span style={{ color: "var(--dim)" }}>-</span>}</td>
                <td className="mono">{s.prediction ? pct(s.prediction.confidence) : "-"}</td>
                <td><StatusChip status={s.status} flagged={s.flagged} /></td>
                <td className="mono">{s.slice_count}</td>
              </tr>))}</tbody></table></div>
        ) : loading ? <div className="empty"><span className="spinner" /></div> : <Empty icon="history" title={t("studies.empty")} text={t("studies.empty_text")} action={<Link className="btn primary" to="/import">{t("dash.new")}</Link>} />}
      </div>
      {data && <p className="sub">{t("studies.count", { n: data.total })}</p>}
    </div>
  );
}
