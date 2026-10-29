import React, { useEffect, useState } from "react";
import { CLASS_NAMES, Measurements, ModelInfo, Patient, SliceResults, StudyDetail, get, patch, post, put } from "../api";
import { useApp } from "../state";
import { Banner, Confirm, Field, Icon, Spinner, num, pct, shell, useAsync } from "../ui";
import { LayerState } from "./Viewer";
import Warnings from "./Warnings";

type Common = { study: StudyDetail; results: SliceResults | null; reload: () => Promise<void>; setResults: (r: SliceResults) => void; sliceId: number };

export function ModelLine({ info }: { info: ModelInfo }) {
  const { t } = useApp();
  return (
    <div className="sub mono" style={{ fontSize: ".78rem" }}>
      {info.name} · {t("models.checkpoint")} {info.short_id} · {info.device}
      {info.test_fixture && <span className="chip danger" style={{ marginLeft: 8 }}>{t("models.test_fixture")}</span>}
    </div>
  );
}

// ---- classification ------------------------------------------------------------------------------
export function ClassificationPanel({ results, layers, setLayers, study, reload }: { results: SliceResults | null; layers: LayerState; setLayers: (l: LayerState) => void; study?: StudyDetail; reload?: () => Promise<void> }) {
  const { t, settings, toast, errorText } = useApp();
  const decide = async (decision: string, label?: string) => {
    if (!study) return;
    try { await post(`/api/studies/${study.id}/clinician-decision`, { decision, label }); if (reload) await reload(); } catch (e) { toast(errorText(e), "error"); }
  };
  const cd = study?.clinician_decision ?? null;
  const c = results?.classification;
  if (!c) return <div className="card card-pad"><p className="sub">{t("cls.none")}</p></div>;
  const threshold = c.params.review_threshold;
  return (
    <div className="col">
      <div className="card card-pad col" style={{ gap: 6 }}>
        <span className="sub">{t("cls.predicted")}</span>
        <div className="big-result" style={{ color: `var(--class-${c.label})` }}>{t(`class.${c.label}`)}</div>
        <div className="row"><span className="mono" style={{ fontSize: "1.4rem", fontWeight: 600 }}>{pct(c.confidence)}</span><span className="sub">{t("cls.confidence")}</span></div>
        <p className="sub" style={{ fontSize: ".8rem" }}>{t("cls.confidence_note")}</p>
        {c.needs_review && <Banner kind="warn" title={t("cls.review_title")}>{t("cls.review_text", { thr: pct(threshold, 0) })}</Banner>}
        {c.model.test_fixture && <Banner kind="danger">{t("banner.fixture.text")}</Banner>}
      </div>
      {study && (
        <div className="card card-pad col" style={{ gap: 10 }}>
          <h3>{t("cr.title")}</h3>
          <div className="row wrap" style={{ gap: 18 }}>
            {(["agree", "change", "reject"] as const).map((k) => (
              <label key={k} className="check"><input type="radio" name="clinician-decision" checked={cd === k} disabled={study.status === "reviewed"}
                onChange={() => decide(k, k === "change" ? (study.clinician_class ?? c.label) : undefined)} /><span>{t(`cr.${k}`)}</span></label>))}
          </div>
          {cd === "change" && (
            <Field label={t("cr.class")}><select value={study.clinician_class ?? c.label} disabled={study.status === "reviewed"} onChange={(e) => decide("change", e.target.value)}>
              {CLASS_NAMES.map((k) => <option key={k} value={k}>{t(`class.${k}`)}</option>)}</select></Field>
          )}
        </div>
      )}
      <div className="card card-pad col">
        <h3>{t("cls.scores")}</h3>
        {CLASS_NAMES.map((k) => (
          <div key={k} className="prob-row"><span style={{ fontWeight: k === c.label ? 600 : 400 }}>{t(`class.${k}`)}</span>
            <div className="bar"><div style={{ width: `${100 * c.probabilities[k]}%`, background: `var(--class-${k})` }} /></div><span className="mono">{pct(c.probabilities[k])}</span></div>))}
      </div>
    </div>
  );
}

// ---- segmentation --------------------------------------------------------------------------------
export function SegmentationPanel({ results, layers, setLayers, setResults, sliceId, reload }: Common & { layers: LayerState; setLayers: (l: LayerState) => void }) {
  const { t, toast, errorText, settings, updateSettings } = useApp();
  const s = results?.segmentation;
  const [busy, setBusy] = useState<string>("");
  if (!s) return <div className="card card-pad"><p className="sub">{t("seg.none")}</p></div>;

  const run = async (name: string, fn: () => Promise<SliceResults>) => {
    setBusy(name);
    try { setResults(await fn()); await reload(); } catch (e) { toast(errorText(e), "error"); } finally { setBusy(""); }
  };

  return (
    <div className="col">
      <div className="card card-pad col">
        <h3>{t("seg.layers")}</h3>
        <label className="check"><input type="checkbox" checked={layers.mask} onChange={(e) => setLayers({ ...layers, mask: e.target.checked })} /><span>{t("seg.show_mask")}</span></label>
        <label className="check"><input type="checkbox" checked={layers.contour} onChange={(e) => setLayers({ ...layers, contour: e.target.checked })} /><span>{t("seg.show_contour")}</span></label>
        <label className="field"><span>{t("seg.opacity")}: {Math.round(layers.opacity * 100)}%</span>
          <input type="range" min={0} max={1} step={0.05} value={layers.opacity} onChange={(e) => setLayers({ ...layers, opacity: Number(e.target.value) })} onPointerUp={() => updateSettings({ overlay_opacity: layers.opacity })} /></label>
        <div className="row"><span className="sub" style={{ flex: 1 }}>{t("seg.color")}</span><input type="color" value={settings?.overlay_color ?? "#ff5a5f"} onChange={(e) => updateSettings({ overlay_color: e.target.value })} aria-label={t("seg.color")} style={{ width: 40, height: 28, border: 0, background: "none" }} /></div>
        {s.edited && <Banner kind="info">{t("seg.edited")}</Banner>}
        <p className="sub" style={{ fontSize: ".82rem" }}><Icon name="brush" size={14} /> {t("seg.edit_hint")}</p>
        {s.edited && <button className="btn sm" disabled={!!busy} onClick={() => run("reset", () => post(`/api/slices/${sliceId}/mask/reset`))}>{t("seg.reset_mask")}</button>}
      </div>
    </div>
  );
}

// ---- measurements --------------------------------------------------------------------------------
export function measurementRows(m: Measurements, t: (k: string, p?: any) => string): [string, string][] {
  const mm = m.units === "mm";
  const u = mm ? "mm" : "px", u2 = mm ? "mm²" : "px²";
  const g = (px?: number, mmv?: number) => (mm ? mmv : px);
  const rows: [string, string][] = [[t("meas.detected"), m.tumor_detected ? t("common.yes") : t("common.no")]];
  if (!m.tumor_detected) return rows;
  const f = (v: number | undefined | null, d = 1) => (v == null ? "-" : num(v, d));
  rows.push(
    [t("meas.area"), `${f(mm ? m.area_mm2 : m.area_px, mm ? 1 : 0)} ${u2}`],
    [t("meas.area_fraction"), pct(m.area_fraction_of_image, 2)],
    [t("meas.bbox"), `${f(g(m.bbox_width_px, m.bbox_width_mm))} × ${f(g(m.bbox_height_px, m.bbox_height_mm))} ${u}`],
    [t("meas.max_d"), `${f(g(m.max_diameter_px, m.max_diameter_mm))} ${u}`],
    [t("meas.min_d"), `${f(g(m.min_diameter_px, m.min_diameter_mm))} ${u}`],
    [t("meas.equiv_d"), `${f(g(m.equivalent_diameter_px, m.equivalent_diameter_mm))} ${u}`],
    [t("meas.perimeter"), `${f(g(m.perimeter_px, m.perimeter_mm))} ${u}`],
    [t("meas.circularity"), f(m.circularity, 3)],
    [t("meas.aspect"), f(m.aspect_ratio, 2)],
    [t("meas.centroid"), `(${(mm ? m.centroid_xy_mm : m.centroid_xy_px)?.map((v) => num(v, 1)).join(", ")}) ${u}`],
    [t("meas.midline"), m.midline_distance_px == null ? t("meas.midline_na") : `${f(g(m.midline_distance_px, m.midline_distance_mm))} ${u}`],
    [t("meas.components"), String(m.n_components ?? "-")],
  );
  if (m.intensity) rows.push([t("meas.intensity"), `${f(m.intensity.mean)} ± ${f(m.intensity.std)}`], [t("meas.contrast"), f(m.intensity.contrast_ratio, 2)]);
  return rows;
}

export function MeasurementsPanel({ results, study, reload }: Common) {
  const { t, toast, errorText } = useApp();
  const m = results?.measurements;
  const [row, setRow] = useState("");
  const [col, setCol] = useState("");
  if (!m) return <div className="card card-pad"><p className="sub">{t("meas.none")}</p></div>;
  const rows = measurementRows(m, t);
  const setSpacing = async () => {
    try { await put(`/api/studies/${study.id}/spacing`, { row_mm: Number(row), col_mm: Number(col || row) }); await reload(); toast(t("common.saved")); }
    catch (e) { toast(errorText(e), "error"); }
  };
  return (
    <div className="col">
      <div className="card card-pad">
        <div className="kv">{rows.map(([k, v]) => <React.Fragment key={k}><div className="k">{k}</div><div className="v mono">{v}</div></React.Fragment>)}</div>
        {m.mask_edited && <p className="sub" style={{ marginTop: 8 }}>{t("meas.edited_note")}</p>}
      </div>
      <div className="card card-pad col">
        <h3>{t("meas.spacing")}</h3>
        <p className="sub">{m.pixel_spacing_mm ? t("meas.spacing_known", { r: m.pixel_spacing_mm[0].toFixed(3), c: m.pixel_spacing_mm[1].toFixed(3) }) : t("meas.spacing_unknown")}</p>
        <div className="grid c2">
          <Field label={t("import.spacing_row")}><input type="number" min="0.01" step="0.01" value={row} onChange={(e) => setRow(e.target.value)} /></Field>
          <Field label={t("import.spacing_col")}><input type="number" min="0.01" step="0.01" value={col} placeholder={row} onChange={(e) => setCol(e.target.value)} /></Field>
        </div>
        <button className="btn sm" disabled={!row} onClick={setSpacing}>{t("meas.set_spacing")}</button>
      </div>
      <p className="sub" style={{ fontSize: ".8rem" }}>{t("meas.limits")}</p>
    </div>
  );
}

// ---- report / review -----------------------------------------------------------------------------
export const FORMATS: [string, string, string][] = [
  ["pdf", "file", "export.pdf"], ["docx", "file", "export.docx"], ["csv", "file", "export.csv"], ["json", "file", "export.json"],
  ["mask-png", "layers", "export.mask_png"], ["mask-nifti", "layers", "export.mask_nifti"], ["dicom-seg", "layers", "export.dicom_seg"], ["dicom-sr", "file", "export.dicom_sr"],
];

export function ReportPanel({ study, results, reload }: Common) {
  const { t, settings, updateSettings, toast, errorText } = useApp();
  const [lang, setLang] = useState<"en" | "fr">(settings?.report_language ?? "en");
  const [anon, setAnon] = useState<boolean>(settings?.anonymize_exports ?? false);
  const [note, setNote] = useState(study.review_note ?? "");
  const { data: patients } = useAsync<Patient[]>(() => (study.patient ? Promise.resolve([]) : get("/api/patients")), [study.id, study.patient?.id]);
  const hasSeg = !!results?.segmentation;
  const need: Record<string, boolean> = { "mask-png": hasSeg, "mask-nifti": hasSeg, "dicom-seg": hasSeg, "dicom-sr": !!results?.classification || hasSeg, pdf: true, docx: true, csv: true, json: true };
  const q = `?lang=${lang}&anonymize=${anon}`;
  const saveCopy = async (fmt: string) => {
    try { const r = await get<{ path: string; name: string }>(`/api/studies/${study.id}/export/${fmt}${q}&save=true`); toast(t("export.saved", { path: r.path })); shell.showItemInFolder?.(r.path); }
    catch (e) { toast(errorText(e), "error"); }
  };
  const decide = async (decision: string) => {
    try { await post(`/api/studies/${study.id}/review`, { decision, note }); await reload(); toast(t("common.saved")); } catch (e) { toast(errorText(e), "error"); }
  };
  const assign = async (id: string) => { try { await patch(`/api/studies/${study.id}`, { patient_id: id ? Number(id) : null }); await reload(); } catch (e) { toast(errorText(e), "error"); } };
  return (
    <div className="col">
      <div className="card card-pad col">
        <h3>{t("review.title")}</h3>
        {study.status === "reviewed"
          ? <Banner kind="info" title={t("review.done", { user: study.reviewed_by ?? "" })}>{study.review_note}</Banner>
          : <p className="sub">{study.status === "pending" ? t("review.need_analysis") : t("review.text")}</p>}
        <Field label={t("review.note")}><textarea value={note} onChange={(e) => setNote(e.target.value)} disabled={study.status === "reviewed"} /></Field>
        <div className="row wrap">
          {study.status !== "reviewed"
            ? <button className="btn primary" disabled={study.status === "pending"} onClick={() => decide("reviewed")}><Icon name="check" size={18} />{t("review.mark")}</button>
            : <button className="btn" onClick={() => decide("reopen")}>{t("review.reopen")}</button>}
          {study.flag_reasons.includes("manual")
            ? <button className="btn" onClick={() => decide("unflag")}><Icon name="flag" size={18} />{t("review.unflag")}</button>
            : <button className="btn" onClick={() => decide("flag")}><Icon name="flag" size={18} />{t("review.flag")}</button>}
        </div>
        {!study.patient && <Field label={t("review.assign")}><select value="" onChange={(e) => assign(e.target.value)}><option value="">{t("studies.unassigned")}</option>{patients?.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.code})</option>)}</select></Field>}
      </div>
      <div className="card card-pad col">
        <h3>{t("export.title")}</h3>
        <div className="row wrap">
          <div className="seg" role="group" aria-label={t("export.language")}>{(["en", "fr"] as const).map((l) => <button key={l} className={lang === l ? "on" : ""} onClick={() => { setLang(l); updateSettings({ report_language: l }); }}>{l === "en" ? "English" : "Français"}</button>)}</div>
        </div>
        <label className="check"><input type="checkbox" checked={anon} onChange={(e) => { setAnon(e.target.checked); updateSettings({ anonymize_exports: e.target.checked }); }} /><span>{t("export.anonymize")}<small>{t("export.anonymize_hint")}</small></span></label>
        <div className="grid c2" style={{ gap: 8 }}>
          {FORMATS.map(([fmt, ic, key]) => (
            <div key={fmt} className="row" style={{ gap: 4 }}>
              <a className={`btn sm ${need[fmt] ? "" : "ghost"}`} style={{ flex: 1, pointerEvents: need[fmt] ? "auto" : "none", opacity: need[fmt] ? 1 : 0.45 }} href={`/api/studies/${study.id}/export/${fmt}${q}`} download aria-disabled={!need[fmt]}><Icon name="download" size={15} />{t(key)}</a>
              <button className="btn sm ghost icon" disabled={!need[fmt]} onClick={() => saveCopy(fmt)} data-tip={t("export.save_to_folder")} aria-label={t("export.save_to_folder")}><Icon name="folder" size={15} /></button>
            </div>))}
        </div>
        <p className="sub" style={{ fontSize: ".8rem" }}>{t("export.dicom_note")}</p>
        <p className="sub" style={{ fontSize: ".8rem" }}>{t("export.folder", { dir: settings?.export_dir ?? "" })}</p>
      </div>
    </div>
  );
}
