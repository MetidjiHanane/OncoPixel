import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Patient, get, post, qs } from "../api";
import { useApp } from "../state";
import { Empty, Icon, Modal, fmtDate, useAsync, useDebounced } from "../ui";
import { PatientForm, blankPatient } from "../components/PatientForm";

export default function Patients() {
  const { t, lang, toast, errorText } = useApp();
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState(blankPatient());
  const { data, reload } = useAsync<Patient[]>(() => get(`/api/patients${qs({ q: dq })}`), [dq]);
  const save = async () => {
    const missing = (["name", "code", "age", "sex", "history"] as const).some((k) => String(form[k]).trim() === "");
    if (missing) { toast(t("err.patient_fields_required"), "error"); return; }
    try {
      const p = await post<Patient>("/api/patients", { ...form, age: Number(form.age) });
      toast(t("patients.created")); setAdding(false); setForm(blankPatient()); reload(); nav(`/patients/${p.id}`);
    } catch (e) { toast(errorText(e), "error"); }
  };
  return (
    <div className="page">
      <div className="page-head">
        <div className="grow"><h1>{t("patients.title")}</h1><p className="sub">{t("patients.subtitle")}</p></div>
        <button className="btn primary" onClick={() => setAdding(true)}><Icon name="plus" size={18} />{t("patients.add")}</button>
      </div>
      <div className="card card-pad"><label className="field"><span>{t("common.search")}</span><input type="search" placeholder={t("patients.search_ph")} value={q} onChange={(e) => setQ(e.target.value)} /></label></div>
      <div className="card">
        {data && data.length ? (
          <div className="table-wrap"><table className="tb"><thead><tr><th>{t("patients.name")}</th><th>{t("patients.code")}</th><th>{t("patients.age")}</th><th>{t("patients.sex")}</th><th>{t("patients.studies")}</th><th>{t("patients.last")}</th></tr></thead>
            <tbody>{data.map((p) => (
              <tr key={p.id} onClick={() => nav(`/patients/${p.id}`)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && nav(`/patients/${p.id}`)}>
                <td style={{ fontWeight: 500 }}>{p.name}</td><td className="mono">{p.code}</td><td>{p.age ?? "-"}</td><td>{p.sex ? t(`sex.${p.sex}`) : "-"}</td><td className="mono">{p.study_count}</td><td>{fmtDate(p.last_study_date, lang)}</td>
              </tr>))}</tbody></table></div>
        ) : <Empty icon="patients" title={t("patients.empty")} text={t("patients.empty_text")} action={<button className="btn primary" onClick={() => setAdding(true)}>{t("patients.add")}</button>} />}
      </div>
      {adding && <Modal title={t("patients.add")} onClose={() => setAdding(false)} footer={<><button className="btn" onClick={() => setAdding(false)}>{t("common.cancel")}</button><button className="btn primary" onClick={save}>{t("common.save")}</button></>}>
        <PatientForm value={form} onChange={setForm} /></Modal>}
    </div>
  );
}
