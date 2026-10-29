import React from "react";
import { Link, useNavigate } from "react-router-dom";
import { CLASS_NAMES, Dashboard as Dash, StudySummary, get } from "../api";
import { useApp } from "../state";
import { ClassChip, Empty, Icon, StatusChip, fmtDateTime, pct, useAsync } from "../ui";
import ModelBanner from "../components/ModelBanner";

export default function Dashboard() {
  const { t, lang } = useApp();
  const nav = useNavigate();
  const { data: d } = useAsync<Dash>(() => get("/api/dashboard"), []);
  const { data: pending } = useAsync<{ items: StudySummary[] }>(() => get("/api/studies?status=analyzed&limit=6"), []);
  const maxDay = Math.max(1, ...(d?.studies_per_day.map((x) => x.count) ?? [1]));
  const totalCls = Math.max(1, Object.values(d?.by_class ?? {}).reduce((a, b) => a + b, 0));
  const stats: [string, number | undefined, string][] = [
    ["dash.total", d?.total_studies, ""], ["dash.analyses", d?.analyses_completed, ""],
    ["dash.pending_reviews", d?.pending_reviews, "info"], ["dash.flagged", d?.flagged, "warn"],
  ];
  return (
    <div className="page">
      <div className="page-head">
        <div className="grow"><h1>{t("dash.title")}</h1><p className="sub">{t("dash.subtitle")}</p></div>
        <Link to="/import" className="btn primary"><Icon name="plus" size={18} />{t("dash.new")}</Link>
      </div>
      <ModelBanner />
      <div className="grid c4" data-tour="dash-stats">
        {stats.map(([k, v, tone]) => (
          <div key={k} className="card stat"><span className="v" style={tone ? { color: `var(--${tone})` } : undefined}>{v ?? "-"}</span><span className="l">{t(k)}</span></div>
        ))}
      </div>
      <div className="grid" style={{ gridTemplateColumns: "minmax(0,3fr) minmax(0,2fr)" }}>
        <div className="card">
          <div className="card-head"><h3>{t("dash.pending_title")}</h3><Link to="/studies">{t("dash.see_all")}</Link></div>
          {pending && pending.items.length > 0 ? (
            <div className="table-wrap"><table className="tb"><thead><tr><th>{t("studies.id")}</th><th>{t("studies.patient")}</th><th>{t("studies.prediction")}</th><th>{t("studies.status")}</th></tr></thead>
              <tbody>{pending.items.map((s) => (
                <tr key={s.id} onClick={() => nav(`/studies/${s.id}`)}>
                  <td className="mono">{s.code}</td><td>{s.patient?.name ?? <span style={{ color: "var(--dim)" }}>{t("studies.unassigned")}</span>}</td>
                  <td>{s.prediction && <><ClassChip label={s.prediction.label} /> <span className="mono" style={{ color: "var(--muted)", marginLeft: 6 }}>{pct(s.prediction.confidence, 0)}</span></>}</td>
                  <td><StatusChip status={s.status} flagged={s.flagged} /></td>
                </tr>))}</tbody></table></div>
          ) : <Empty icon="check" title={t("dash.no_pending")} text={t("dash.no_pending_text")} />}
        </div>
        <div className="card card-pad col">
          <h3>{t("dash.by_class")}</h3>
          {Object.keys(d?.by_class ?? {}).length === 0 ? <p className="sub">{t("dash.no_results")}</p> :
            CLASS_NAMES.map((c) => { const n = d?.by_class[c] ?? 0; return (
              <div key={c} className="prob-row" style={{ gridTemplateColumns: "120px 1fr 32px" }}><span>{t(`class.${c}`)}</span><div className="bar"><div style={{ width: `${(100 * n) / totalCls}%`, background: `var(--class-${c})` }} /></div><span className="mono">{n}</span></div>); })}
          <h3 style={{ marginTop: 10 }}>{t("dash.per_day")}</h3>
          <svg viewBox="0 0 280 70" width="100%" role="img" aria-label={t("dash.per_day")}>
            {(d?.studies_per_day ?? []).map((x, i, a) => { const w = 280 / Math.max(a.length, 14); return <rect key={x.day} x={i * w + 2} y={66 - (60 * x.count) / maxDay} width={w - 4} height={(60 * x.count) / maxDay} rx={2} fill="var(--accent)"><title>{x.day}: {x.count}</title></rect>; })}
            <line x1="0" y1="66" x2="280" y2="66" stroke="var(--border2)" />
          </svg>
        </div>
      </div>
      <div className="card">
        <div className="card-head"><h3>{t("dash.recent")}</h3><Link to="/activity">{t("dash.see_all")}</Link></div>
        {d && d.recent_activity.length ? (
          <div className="table-wrap"><table className="tb"><tbody>
            {d.recent_activity.slice(0, 8).map((a, i) => (
              <tr key={i} style={{ cursor: "default" }}><td className="mono" style={{ color: "var(--muted)", width: 190 }}>{fmtDateTime(a.ts, lang)}</td><td>{a.user}</td><td>{t(`activity.${a.action}`)}</td>
                <td>{a.entity === "study" && a.entity_id ? <Link to={`/studies/${a.entity_id}`}>ST-{String(a.entity_id).padStart(5, "0")}</Link> : null}</td></tr>))}
          </tbody></table></div>
        ) : <Empty icon="activity" title={t("dash.no_activity")} />}
      </div>
    </div>
  );
}
