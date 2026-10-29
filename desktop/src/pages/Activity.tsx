import React, { useState } from "react";
import { Link } from "react-router-dom";
import { get, qs } from "../api";
import { useApp } from "../state";
import { Empty, fmtDateTime, useAsync } from "../ui";

interface Item { id: number; ts: string; user: string; action: string; entity: string | null; entity_id: number | null; detail: Record<string, any> }

export default function Activity() {
  const { t, lang } = useApp();
  const [page, setPage] = useState(0);
  const size = 50;
  const { data } = useAsync<{ total: number; items: Item[] }>(() => get(`/api/activity${qs({ limit: size, offset: page * size })}`), [page]);
  return (
    <div className="page">
      <div className="page-head"><div className="grow"><h1>{t("activity.title")}</h1><p className="sub">{t("activity.subtitle")}</p></div></div>
      <div className="card">
        {data && data.items.length ? (
          <div className="table-wrap"><table className="tb"><thead><tr><th>{t("activity.when")}</th><th>{t("activity.user")}</th><th>{t("activity.what")}</th><th>{t("activity.object")}</th><th>{t("activity.detail")}</th></tr></thead>
            <tbody>{data.items.map((a) => (
              <tr key={a.id} style={{ cursor: "default" }}>
                <td className="mono" style={{ color: "var(--muted)" }}>{fmtDateTime(a.ts, lang)}</td><td>{a.user ?? "-"}</td><td>{t(`activity.${a.action}`)}</td>
                <td>{a.entity === "study" && a.entity_id ? <Link to={`/studies/${a.entity_id}`}>ST-{String(a.entity_id).padStart(5, "0")}</Link> : a.entity ? `${a.entity} #${a.entity_id}` : ""}</td>
                <td className="mono" style={{ color: "var(--dim)", fontSize: ".8rem", maxWidth: 360, overflow: "hidden", textOverflow: "ellipsis" }}>{Object.keys(a.detail).length ? JSON.stringify(a.detail) : ""}</td>
              </tr>))}</tbody></table></div>
        ) : <Empty icon="activity" title={t("dash.no_activity")} />}
      </div>
      {data && data.total > size && <div className="row"><button className="btn sm" disabled={page === 0} onClick={() => setPage(page - 1)}>{t("common.back")}</button><span className="sub">{page + 1} / {Math.ceil(data.total / size)}</span><button className="btn sm" disabled={(page + 1) * size >= data.total} onClick={() => setPage(page + 1)}>{t("common.next")}</button></div>}
    </div>
  );
}
