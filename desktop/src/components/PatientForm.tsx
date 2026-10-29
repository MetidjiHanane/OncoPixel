import React from "react";
import { Patient } from "../api";
import { useApp } from "../state";
import { Field } from "../ui";

export interface PatientFormValue { code: string; name: string; age: string | number; sex: string; referring_physician: string; history: string }
export const blankPatient = (): PatientFormValue => ({ code: "", name: "", age: "", sex: "", referring_physician: "", history: "" });
export const toForm = (p: Patient): PatientFormValue => ({ code: p.code, name: p.name, age: p.age ?? "", sex: p.sex ?? "", referring_physician: p.referring_physician, history: p.history });

export function PatientForm({ value, onChange }: { value: PatientFormValue; onChange: (v: PatientFormValue) => void }) {
  const { t } = useApp();
  const set = (k: keyof PatientFormValue) => (e: React.ChangeEvent<any>) => onChange({ ...value, [k]: e.target.value });
  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="grid c2">
        <Field label={t("patients.name")} required><input type="text" value={value.name} onChange={set("name")} autoFocus /></Field>
        <Field label={t("patients.code")} required><input type="text" value={value.code} onChange={set("code")} /></Field>
        <Field label={t("patients.age")} required><input type="number" min={0} max={130} value={value.age} onChange={set("age")} /></Field>
        <Field label={t("patients.sex")} required><select value={value.sex} onChange={set("sex")}><option value="">-</option>{["F", "M"].map((s) => <option key={s} value={s}>{t(`sex.${s}`)}</option>)}</select></Field>
      </div>
      <Field label={t("patients.history")} required><textarea value={value.history} onChange={set("history")} /></Field>
    </div>
  );
}
