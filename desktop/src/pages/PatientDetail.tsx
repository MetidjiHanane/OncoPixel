import React, { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Patient, StudySummary, del, get, patch } from "../api";
import { useApp } from "../state";
import { ClassChip, Confirm, Empty, Icon, Modal, StatusChip, fmtDate, pct, useAsync } from "../ui";
import { PatientForm, toForm } from "../components/PatientForm";

export default function PatientDetail() {
  const { id } = useParams();
  const { t, lang, toast, errorText } = useApp();
  const nav = useNavigate();
  const { data: p, error, reload } = useAsync<Patient>(() => get(`/api/patients/${id}`), [id]);
  const [editing, setEditing] = useState<ReturnType<typeof toForm> | null>(null);
  const [confirmDel, setConfirmDel] = useState(false);
  if (error) return <div className="page"><Empty icon="alert" title={t("err.not_found")} action={<Link className="btn" to="/patients">{t("common.back")}</Link>} /></div>;
  if (!p) return <div className="page"><span className="spinner" /></div>;
  const save = async () => {
    try { await patch(`/api/patients/${p.id}`, { ...editing, age: editing!.age === "" ? null : Number(editing!.age) }); setEditing(null); reload(); toast(t("common.saved")); }
    catch (e) { toast(errorText(e), "error"); }
  };
  const studies: StudySummary[] = p.studies ?? [];
  const comparable = studies.filter((s) => s.segmented);
  return (
    <div className="page">
      <div className="page-head">
        <Link to="/patients" className="btn ghost icon" aria-label={t("common.back")}><Icon name="back" /></Link>
        <div className="grow"><h1>{p.name}</h1><p className="sub mono">{p.code}</p></div>
        <button className="btn" onClick={() => setEditing(toForm(p))}><Icon name="edit" size={18} />{t("common.edit")}</button>
        <button className="btn danger" onClick={() => setConfirmDel(true)}><Icon name="trash" size={18} />{t("common.delete")}</button>
      </div>
      <div className="grid c2">
        <div className="card card-pad"><div className="kv">
          <div className="k">{t("patients.age")}</div><div className="v">{p.age ?? "-"}</div>
          <div className="k">{t("patients.sex")}</div><div className="v">{p.sex ? t(`sex.${p.sex}`) : "-"}</div>
          <div className="k">{t("patients.history")}</div><div className="v">{p.history || "-"}</div>
        </div></div>
        <div className="card card-pad col">
          <h3>{t("patients.actions")}</h3>
          <Link className="btn" to={`/import?patient=${p.id}`}><Icon name="upload" size={18} />{t("patients.new_study")}</Link>
          {comparable.length >= 2 ? <Link className="btn" to={`/compare?patient=${p.id}`}><Icon name="compare" size={18} />{t("patients.compare")}</Link> : <p className="sub">{t("patients.compare_hint")}</p>}
        </div>
      </div>
      <div className="card">
        <div className="card-head"><h3>{t("patients.studies")}</h3></div>
        {studies.length ? <div className="table-wrap"><table className="tb"><thead><tr><th>{t("studies.id")}</th><th>{t("studies.date")}</th><th>{t("studies.prediction")}</th><th>{t("studies.status")}</th></tr></thead>
          <tbody>{studies.map((s) => <tr key={s.id} onClick={() => nav(`/studies/${s.id}`)}><td className="mono">{s.code}</td><td>{fmtDate(s.study_date, lang)}</td>
            <td>{s.prediction ? <><ClassChip label={s.prediction.label} /> <span className="mono" style={{ marginLeft: 6, color: "var(--muted)" }}>{pct(s.prediction.confidence, 0)}</span></> : "-"}</td><td><StatusChip status={s.status} flagged={s.flagged} /></td></tr>)}</tbody></table></div>
          : <Empty icon="file" title={t("patients.no_studies")} />}
      </div>
      {editing && <Modal title={t("common.edit")} onClose={() => setEditing(null)} footer={<><button className="btn" onClick={() => setEditing(null)}>{t("common.cancel")}</button><button className="btn primary" onClick={save}>{t("common.save")}</button></>}><PatientForm value={editing} onChange={setEditing} /></Modal>}
      {confirmDel && <Confirm danger title={t("patients.delete_title")} text={t("patients.delete_text")} confirmLabel={t("common.delete")} onClose={() => setConfirmDel(false)} onConfirm={async () => { await del(`/api/patients/${p.id}`); nav("/patients"); }} />}
    </div>
  );
}
