import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, SliceResults, StudyDetail, del, get, patch, post } from "../api";
import { useApp } from "../state";
import { Banner, ClassChip, Confirm, Empty, Icon, Spinner, StatusChip, fmtDate, pct } from "../ui";
import ModelBanner from "../components/ModelBanner";
import Viewer, { LayerState, defaultLayers } from "../components/Viewer";
import { ClassificationPanel, MeasurementsPanel, ReportPanel, SegmentationPanel } from "../components/Panels";
import Warnings from "../components/Warnings";

type Tab = "classification" | "segmentation" | "measurements" | "report";

export default function StudyPage() {
  const { id } = useParams();
  const { t, lang, settings, toast, errorText, models, refreshModels } = useApp();
  const nav = useNavigate();
  const [study, setStudy] = useState<StudyDetail | null>(null);
  const [missing, setMissing] = useState(false);
  const [sliceId, setSliceId] = useState<number | null>(null);
  const [results, setResults] = useState<SliceResults | null>(null);
  const [tab, setTab] = useState<Tab>("classification");
  useEffect(() => { const h = (e: Event) => setTab((e as CustomEvent).detail as Tab); window.addEventListener("op-tour-tab", h); return () => window.removeEventListener("op-tour-tab", h); }, []);
  const [layers, setLayers] = useState<LayerState>(defaultLayers(settings?.overlay_opacity, settings?.show_contour));
  const [busy, setBusy] = useState(false);
  const [modelError, setModelError] = useState<string>("");
  const [confirmDel, setConfirmDel] = useState(false);

  const loadStudy = useCallback(async (keepSlice = true) => {
    try {
      const s = await get<StudyDetail>(`/api/studies/${id}`);
      setStudy(s);
      setSliceId((cur) => (keepSlice && cur && s.slices.some((x) => x.id === cur) ? cur : s.primary_slice_id ?? s.slices[0]?.id ?? null));
    } catch (e) { if (e instanceof ApiError && e.status === 404) setMissing(true); else toast(errorText(e), "error"); }
  }, [id, toast, errorText]);
  const loadResults = useCallback(async (sid: number | null) => {
    if (!sid) return;
    try { setResults(await get<SliceResults>(`/api/slices/${sid}`)); } catch (e) { toast(errorText(e), "error"); }
  }, [toast, errorText]);

  useEffect(() => { setStudy(null); setResults(null); setMissing(false); loadStudy(false); }, [id]); // eslint-disable-line
  useEffect(() => { setResults(null); loadResults(sliceId); }, [sliceId]); // eslint-disable-line
  useEffect(() => { setLayers((l) => ({ ...l, opacity: settings?.overlay_opacity ?? l.opacity, contour: settings?.show_contour ?? l.contour })); }, [settings?.show_contour]); // eslint-disable-line

  const reload = useCallback(async () => { await loadStudy(true); await loadResults(sliceId); }, [loadStudy, loadResults, sliceId]);

  const analyze = async (stages?: string[]) => {
    if (!sliceId) return;
    setBusy(true); setModelError("");
    try {
      const r = await post<SliceResults>(`/api/slices/${sliceId}/analyze`, stages ? { stages } : {});
      setResults(r);
      Object.values(r.skipped ?? {}).forEach((s) => toast(`${t(`models.${s.kind}`)}: ${s.detail}`, "warn"));
      await loadStudy(true);
      if (r.segmentation && !r.classification) setTab("segmentation");
    } catch (e) {
      if (e instanceof ApiError && e.code === "MODEL_MISSING") { setModelError(errorText(e)); refreshModels(); }
      else toast(errorText(e), "error");
    } finally { setBusy(false); }
  };

  const version = useMemo(() => {
    const s = results?.segmentation;
    return s ? `${s.created_at}|${s.edited_at}|${s.threshold}|${JSON.stringify(s.postprocess)}|${s.has_uncertainty}` : "0";
  }, [results?.segmentation]);

  if (missing) return <div className="page"><Empty icon="alert" title={t("err.not_found")} action={<Link className="btn" to="/studies">{t("common.back")}</Link>} /></div>;
  if (!study) return <div className="page"><span className="spinner" /></div>;
  const slice = study.slices.find((s) => s.id === sliceId) ?? study.slices[0];
  const idx = study.slices.findIndex((s) => s.id === slice?.id);
  const analysed = !!results?.classification || !!results?.segmentation;
  const flagTexts = study.flag_reasons.map((r) => t(`flag.${r.replace("input:", "")}`));
  const tabs: [Tab, string][] = [["classification", "study.tab_cls"], ["segmentation", "study.tab_seg"], ["measurements", "study.tab_meas"], ["report", "study.tab_report"]];

  return (
    <div className="page">
      <div className="page-head">
        <Link to="/studies" className="btn ghost icon" aria-label={t("common.back")}><Icon name="back" /></Link>
        <div className="grow">
          <div className="row wrap"><h1 className="mono" style={{ fontSize: "1.35rem" }}>{study.code}</h1><StatusChip status={study.status} flagged={study.flagged} />
            {study.prediction && <ClassChip label={study.prediction.label} />}</div>
          <p className="sub">
            {study.patient ? <Link to={`/patients/${study.patient.id}`}>{study.patient.name}</Link> : t("studies.unassigned")} · {fmtDate(study.study_date, lang)} · {study.sequence} · {t(`plane.${study.plane}`)} · {study.source_type === "dicom" ? "DICOM" : "PNG/JPG"}
          </p>
        </div>
        <button className="btn primary" onClick={() => analyze()} disabled={busy || !slice} style={{ height: 42 }} data-tour="analyze">
          {busy ? <Spinner /> : <Icon name="play" size={18} />}{busy ? t("study.analyzing") : analysed ? t("study.reanalyze") : t("study.analyze")}
        </button>
        <button className="btn danger icon" onClick={() => setConfirmDel(true)} aria-label={t("common.delete")} data-tip={t("common.delete")}><Icon name="trash" size={18} /></button>
      </div>

      <ModelBanner />
      {modelError && <Banner kind="danger" title={t("study.no_result_title")} action={<Link className="btn sm" to="/models">{t("banner.missing.action")}</Link>}>{modelError}<div style={{ marginTop: 4 }}>{t("study.no_result_text")}</div></Banner>}
      {flagTexts.length > 0 && <Banner kind="warn" title={t("study.flag_title")}><ul style={{ margin: 0, paddingLeft: 18 }}>{flagTexts.map((f, i) => <li key={i}>{f}</li>)}</ul></Banner>}

      {study.slices.length > 1 && (
        <div className="card card-pad col" style={{ gap: 8 }}>
          <div className="row"><b>{t("study.slices")}</b><span className="sub">{t("study.slice_hint")}</span><span style={{ flex: 1 }} />
            {slice && slice.id !== study.primary_slice_id && <button className="btn sm" onClick={async () => { await patch(`/api/studies/${study.id}`, { primary_slice_id: slice.id }); await loadStudy(true); toast(t("study.primary_set")); }}>{t("study.set_primary")}</button>}
            {slice && slice.id === study.primary_slice_id && <span className="chip accent">{t("study.primary")}</span>}</div>
          <div className="thumbs">{study.slices.map((s, i) => (
            <button key={s.id} className={s.id === slice?.id ? "on" : ""} onClick={() => setSliceId(s.id)} aria-label={`${t("viewer.slice")} ${i + 1}`}><img src={`/api/slices/${s.id}/image/original`} alt="" loading="lazy" />
              <span className="chip" style={{ position: "absolute", right: 2, bottom: 2, padding: "0 5px", fontSize: ".68rem" }}>{i + 1}{s.segmented ? " ●" : ""}</span></button>))}</div>
        </div>
      )}

      {slice && (
        <div className="viewer-grid">
          <div className="col">
            <Viewer sliceId={slice.id} width={slice.width} height={slice.height} spacing={slice.pixel_spacing_mm} results={results} layers={layers}
              color={settings?.overlay_color ?? "#ff5a5f"} version={version} canEdit={!!results?.segmentation && study.status !== "reviewed"}
              slices={{ count: study.slices.length, index: idx, onChange: (i) => setSliceId(study.slices[i].id) }}
              onSaved={(r) => { setResults(r); loadStudy(true); }} />
            <div className="card card-pad">
              <div className="row wrap" style={{ gap: 18 }}>
                <label className="row" style={{ gap: 8, flex: "1 1 180px" }}><Icon name="contrast" size={16} /><span className="sub">{t("viewer.brightness")}</span><input type="range" min={0.4} max={2} step={0.05} value={layers.brightness} onChange={(e) => setLayers({ ...layers, brightness: Number(e.target.value) })} /></label>
                <label className="row" style={{ gap: 8, flex: "1 1 180px" }}><span className="sub">{t("viewer.contrast")}</span><input type="range" min={0.4} max={3} step={0.05} value={layers.contrast} onChange={(e) => setLayers({ ...layers, contrast: Number(e.target.value) })} /></label>
                <label className="check"><input type="checkbox" checked={layers.invert} onChange={(e) => setLayers({ ...layers, invert: e.target.checked })} />{t("viewer.invert")}</label>
                <button className="btn sm ghost" onClick={() => setLayers({ ...layers, brightness: 1, contrast: 1, invert: false })}>{t("viewer.reset")}</button>
              </div>
              <div className="legend" style={{ marginTop: 10 }}>
                <span><i style={{ background: settings?.overlay_color }} />{t("viewer.legend_mask")}</span>
                <span><i style={{ background: "#ffe066" }} />{t("viewer.legend_contour")}</span>
                <span className="sub">{t("viewer.help")}</span>
              </div>
            </div>
            <Warnings items={results?.warnings ?? slice.warnings} hideInfo />
          </div>
          <div className="side" data-tour="v-panel">
            <div className="tabs" role="tablist">{tabs.map(([k, label]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{t(label)}</button>)}</div>
            {!analysed && tab !== "report" && (
              <div className="card card-pad col">
                <h3>{t("study.not_analyzed")}</h3><p className="sub">{models?.all_ready ? t("study.not_analyzed_text") : t("study.models_first")}</p>
                <button className="btn primary" disabled={busy || !models?.all_ready} onClick={() => analyze()}>{busy ? <Spinner /> : <Icon name="play" size={18} />}{t("study.analyze")}</button>
                {models && !models.all_ready && <div className="row wrap">{(["classification", "segmentation"] as const).map((k) => models.models[k].state === "ready" && <button key={k} className="btn sm" disabled={busy} onClick={() => analyze([k])}>{t(`study.only_${k}`)}</button>)}</div>}
              </div>
            )}
            {tab === "classification" && analysed && <ClassificationPanel results={results} layers={layers} setLayers={setLayers} study={study} reload={reload} />}
            {tab === "segmentation" && analysed && <SegmentationPanel study={study} results={results} reload={reload} setResults={setResults} sliceId={slice.id} layers={layers} setLayers={setLayers} />}
            {tab === "measurements" && analysed && <MeasurementsPanel study={study} results={results} reload={reload} setResults={setResults} sliceId={slice.id} />}
            {tab === "report" && <ReportPanel study={study} results={results} reload={reload} setResults={setResults} sliceId={slice.id} />}
          </div>
        </div>
      )}
      {confirmDel && <Confirm danger title={t("study.delete_title")} text={t("study.delete_text")} confirmLabel={t("common.delete")} onClose={() => setConfirmDel(false)} onConfirm={async () => { await del(`/api/studies/${study.id}`); nav("/studies"); }} />}
    </div>
  );
}
