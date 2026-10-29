import React, { useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, ImportResult, Patient, api, get, post } from "../api";
import { useApp } from "../state";
import { Banner, Field, Icon, Spinner, shell, useAsync } from "../ui";
import ModelBanner from "../components/ModelBanner";
import Warnings from "../components/Warnings";

export default function ImportPage() {
  const { t, toast, errorText, models } = useApp();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const { data: patients } = useAsync<Patient[]>(() => get("/api/patients"), []);
  const [patientId, setPatientId] = useState<string>(params.get("patient") ?? "");
  const [group, setGroup] = useState<"separate" | "series">("separate");
  const sequence = "T1"; // OncoPixel works on T1-weighted slices only
  const [plane, setPlane] = useState("");
  const [studyDate, setStudyDate] = useState("");
  const [indication, setIndication] = useState("");
  const [spRow, setSpRow] = useState("");
  const [spCol, setSpCol] = useState("");
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [progress, setProgress] = useState<{ done: number; total: number; failed: number } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const dirInput = useRef<HTMLInputElement>(null);

  const options = () => ({
    patient_id: patientId ? Number(patientId) : null, group_images: group, sequence, plane: plane || null,
    study_date: studyDate || null, indication,
    spacing_row_mm: spRow ? Number(spRow) : null, spacing_col_mm: spCol ? Number(spCol) : null,
  });
  const optionsValid = () => (!!spRow === !!spCol);

  const finish = (r: ImportResult) => {
    setResult(r);
    if (r.created.length) toast(t("import.done", { n: r.created.length }));
    if (!r.created.length && r.rejected.length) toast(t("import.none_imported"), "warn");
  };

  const importPaths = async (paths: string[]) => {
    if (!optionsValid()) { toast(t("err.spacing_invalid"), "error"); return; }
    setBusy(true);
    try { finish(await post<ImportResult>("/api/import/paths", { ...options(), paths })); }
    catch (e) { toast(errorText(e), "error"); } finally { setBusy(false); }
  };
  const importFiles = async (all: File[]) => {
    if (!all.length) return;
    const files = all.filter((f) => /\.(png|jpe?g)$/i.test(f.name));
    if (!files.length) { toast(t("import.only_png_jpg"), "warn"); return; }
    if (files.length < all.length) toast(t("import.skipped_other", { n: all.length - files.length }), "warn");
    if (!optionsValid()) { toast(t("err.spacing_invalid"), "error"); return; }
    if (shell.getPathForFile) { // desktop app: use the real paths, no copying
      const paths = files.map((f) => shell.getPathForFile!(f)).filter(Boolean);
      if (paths.length) return importPaths(paths);
    }
    setBusy(true);
    try {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f, f.name));
      fd.append("options", JSON.stringify(options()));
      finish(await api<ImportResult>("/api/import/upload", { method: "POST", body: fd }));
    } catch (e) { toast(errorText(e), "error"); } finally { setBusy(false); }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault(); setOver(false);
    importFiles(Array.from(e.dataTransfer.files));
  };

  const analyzeAll = async (ids: number[]) => {
    setProgress({ done: 0, total: ids.length, failed: 0 });
    let failed = 0;
    for (let i = 0; i < ids.length; i++) {
      try { await post(`/api/studies/${ids[i]}/analyze`); }
      catch (e) {
        failed++;
        if (e instanceof ApiError && e.code === "MODEL_MISSING") { toast(errorText(e), "error"); setProgress(null); return; }
      }
      setProgress({ done: i + 1, total: ids.length, failed });
    }
    toast(t("import.analysis_done", { n: ids.length - failed }));
    if (ids.length === 1 && !failed) nav(`/studies/${ids[0]}`);
  };

  const pickFolder = async () => {
    if (shell.selectFolder) { const p = await shell.selectFolder(); if (p) importPaths([p]); }
    else dirInput.current?.click();
  };
  const modelsReady = models?.all_ready;
  return (
    <div className="page">
      <div className="page-head"><div className="grow"><h1>{t("import.title")}</h1><p className="sub">{t("import.subtitle")}</p></div></div>
      <ModelBanner />
      <div className="grid" style={{ gridTemplateColumns: "minmax(0,3fr) minmax(0,2fr)", alignItems: "start" }}>
        <div className="col">
          <div data-tour="import-drop" className={`dropzone ${over ? "over" : ""}`} onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={onDrop} role="group" aria-label={t("import.drop")}>
            {busy ? <Spinner /> : <Icon name="upload" size={38} />}
            <h3 style={{ color: "var(--text)" }}>{t("import.drop")}</h3>
            <p style={{ maxWidth: 440 }}>{t("import.formats")}</p>
            <div className="row wrap" style={{ justifyContent: "center" }}>
              <button className="btn primary" disabled={busy} onClick={() => fileInput.current?.click()}><Icon name="file" size={18} />{t("import.choose_files")}</button>
              <button className="btn" disabled={busy} onClick={pickFolder}><Icon name="folder" size={18} />{t("import.choose_folder")}</button>
            </div>
            <input ref={fileInput} type="file" multiple hidden accept=".png,.jpg,.jpeg,image/png,image/jpeg" onChange={(e) => { importFiles(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
            <input ref={dirInput} type="file" hidden {...({ webkitdirectory: "", directory: "" } as any)} onChange={(e) => { importFiles(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
          </div>

          {result && (
            <div className="card">
              <div className="card-head">
                <h3>{t("import.result")}</h3>
                {result.created.length > 0 && <button className="btn primary sm" disabled={!!progress && progress.done < progress.total || !modelsReady} onClick={() => analyzeAll(result.created)} data-tip={modelsReady ? undefined : t("import.models_needed")}><Icon name="play" size={16} />{t("import.analyze_all", { n: result.created.length })}</button>}
              </div>
              <div className="card-pad col">
                {progress && <div className="col" style={{ gap: 6 }}><div className="progress"><div style={{ width: `${(100 * progress.done) / progress.total}%` }} /></div><span className="sub">{t("import.progress", { done: progress.done, total: progress.total })}{progress.failed > 0 && ` - ${t("import.failed", { n: progress.failed })}`}</span></div>}
                {result.studies.map((s) => (
                  <div key={s.id} className="card card-pad col" style={{ background: "var(--surface2)", gap: 8 }}>
                    <div className="row"><b className="mono">{s.code}</b><span className="chip">{t("import.slices", { n: s.slice_count })}</span>{s.flagged && <span className="chip warn">{t("status.flagged")}</span>}<span style={{ flex: 1 }} /><Link to={`/studies/${s.id}`} className="btn sm">{t("common.open")}</Link></div>
                    <Warnings items={s.slices[0]?.warnings ?? []} hideInfo />
                  </div>
                ))}
                {result.rejected.map((r, i) => (
                  <Banner key={i} kind="danger" title={t("import.rejected", { name: r.name })}><Warnings items={r.warnings} /></Banner>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="col">
          <div className="card card-pad col" data-tour="import-patient">
            <h3>{t("import.options")}</h3>
            <Field label={t("import.patient")}>
              <select value={patientId} onChange={(e) => setPatientId(e.target.value)}>
                <option value="">{t("import.no_patient")}</option>
                {patients?.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.code})</option>)}
              </select>
            </Field>
            <Field label={t("import.group")} hint={t("import.group_hint")}>
              <div className="seg"><button className={group === "separate" ? "on" : ""} onClick={() => setGroup("separate")}>{t("import.group_separate")}</button><button className={group === "series" ? "on" : ""} onClick={() => setGroup("series")}>{t("import.group_series")}</button></div>
            </Field>
            <div className="grid c2">
              <Field label={t("import.plane")}><select value={plane} onChange={(e) => setPlane(e.target.value)}><option value="">{t("import.plane_auto")}</option>{["axial", "sagittal", "coronal"].map((p) => <option key={p} value={p}>{t(`plane.${p}`)}</option>)}</select></Field>
            </div>
            <Field label={t("import.date")}><input type="date" value={studyDate} onChange={(e) => setStudyDate(e.target.value)} /></Field>
            <Field label={t("import.indication")}><input type="text" value={indication} onChange={(e) => setIndication(e.target.value)} /></Field>
            <div className="grid c2">
              <Field label={t("import.spacing_row")} hint={t("import.spacing_hint")}><input type="number" min="0.01" step="0.01" value={spRow} onChange={(e) => setSpRow(e.target.value)} /></Field>
              <Field label={t("import.spacing_col")}><input type="number" min="0.01" step="0.01" value={spCol} onChange={(e) => setSpCol(e.target.value)} /></Field>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
