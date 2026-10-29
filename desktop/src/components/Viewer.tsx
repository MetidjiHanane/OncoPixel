import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { SliceResults, api } from "../api";
import { useApp } from "../state";
import { Icon } from "../ui";

export interface LayerState {
  mask: boolean;
  contour: boolean;
  gradcam: boolean;
  uncertainty: "off" | "uncertainty" | "variability";
  opacity: number; // mask fill opacity
  overlayOpacity: number; // heatmaps
  invert: boolean;
  brightness: number;
  contrast: number;
}

export const defaultLayers = (opacity = 0.45, contour = true): LayerState => ({
  mask: true, contour, gradcam: false, uncertainty: "off", opacity, overlayOpacity: 0.6, invert: false, brightness: 1, contrast: 1,
});

type Tool = "pan" | "brush" | "eraser";
interface Props {
  sliceId: number;
  width: number;
  height: number;
  spacing: [number, number] | null;
  results: SliceResults | null;
  layers: LayerState;
  color: string;
  version: string;
  slices?: { count: number; index: number; onChange: (i: number) => void };
  onSaved: (r: SliceResults) => void;
  canEdit: boolean;
}

const img = (id: number, kind: string, extra = "") => `/api/slices/${id}/image/${kind}${extra}`;

export default function Viewer({ sliceId, width, height, spacing, results, layers, color, version, slices, onSaved, canEdit }: Props) {
  const { t, toast, errorText } = useApp();
  const stage = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 800, h: 600 });
  const [view, setView] = useState({ s: 1, x: 0, y: 0 });
  const [tool, setTool] = useState<Tool>("pan");
  const [brush, setBrush] = useState(Math.max(6, Math.round(Math.min(width, height) / 30)));
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const history = useRef<ImageData[]>([]);
  const future = useRef<ImageData[]>([]);
  const [histLen, setHistLen] = useState({ u: 0, r: 0 });
  const drag = useRef<{ mode: "pan" | "paint"; sx: number; sy: number; vx: number; vy: number; last?: [number, number] } | null>(null);
  const editing = tool === "brush" || tool === "eraser";
  const hasMask = !!results?.segmentation;

  // ---- fit and resize -------------------------------------------------------------------------
  useLayoutEffect(() => {
    const el = stage.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);
  const fit = useCallback(() => {
    const s = Math.min(size.w / width, size.h / height) * 0.97;
    setView({ s, x: (size.w - width * s) / 2, y: (size.h - height * s) / 2 });
  }, [size.w, size.h, width, height]);
  useEffect(() => { fit(); }, [fit, sliceId]);

  const zoomAt = useCallback((factor: number, cx: number, cy: number) => {
    setView((v) => {
      const s = Math.min(40, Math.max(0.1, v.s * factor));
      const k = s / v.s;
      return { s, x: cx - (cx - v.x) * k, y: cy - (cy - v.y) * k };
    });
  }, []);

  // ---- editable mask canvas -------------------------------------------------------------------
  const loadCanvas = useCallback(async () => {
    const c = canvas.current;
    if (!c || !hasMask) return;
    const im = new Image();
    im.src = img(sliceId, "mask", `?opacity=1&contour=false&color=%23ff5a5f&v=${encodeURIComponent(version)}`);
    await im.decode().catch(() => undefined);
    c.width = width; c.height = height;
    const ctx = c.getContext("2d", { willReadFrequently: true })!;
    ctx.clearRect(0, 0, width, height);
    ctx.drawImage(im, 0, 0, width, height);
    history.current = []; future.current = []; setHistLen({ u: 0, r: 0 }); setDirty(false);
  }, [sliceId, width, height, version, hasMask]);
  useEffect(() => { if (editing) loadCanvas(); }, [editing, loadCanvas]);

  const maxSnaps = width * height > 4_000_000 ? 4 : 30;
  const snapshot = () => {
    const ctx = canvas.current!.getContext("2d", { willReadFrequently: true })!;
    history.current.push(ctx.getImageData(0, 0, width, height));
    if (history.current.length > maxSnaps) history.current.shift();
    future.current = [];
    setHistLen({ u: history.current.length, r: 0 });
  };
  const undo = () => {
    const ctx = canvas.current!.getContext("2d", { willReadFrequently: true })!;
    const prev = history.current.pop();
    if (!prev) return;
    future.current.push(ctx.getImageData(0, 0, width, height));
    ctx.putImageData(prev, 0, 0);
    setHistLen({ u: history.current.length, r: future.current.length });
    setDirty(history.current.length > 0);
  };
  const redo = () => {
    const ctx = canvas.current!.getContext("2d", { willReadFrequently: true })!;
    const next = future.current.pop();
    if (!next) return;
    history.current.push(ctx.getImageData(0, 0, width, height));
    ctx.putImageData(next, 0, 0);
    setHistLen({ u: history.current.length, r: future.current.length });
    setDirty(true);
  };
  const stamp = (x: number, y: number) => {
    const ctx = canvas.current!.getContext("2d", { willReadFrequently: true })!;
    ctx.globalCompositeOperation = tool === "eraser" ? "destination-out" : "source-over";
    ctx.fillStyle = "#ff5a5f";
    ctx.beginPath(); ctx.arc(x, y, brush / 2, 0, Math.PI * 2); ctx.fill();
  };
  const stroke = (from: [number, number], to: [number, number]) => {
    const dist = Math.hypot(to[0] - from[0], to[1] - from[1]);
    const step = Math.max(1, brush / 4);
    for (let d = 0; d <= dist; d += step) stamp(from[0] + ((to[0] - from[0]) * d) / (dist || 1), from[1] + ((to[1] - from[1]) * d) / (dist || 1));
  };

  const save = async () => {
    const c = canvas.current!;
    const ctx = c.getContext("2d", { willReadFrequently: true })!;
    const data = ctx.getImageData(0, 0, width, height);
    const out = document.createElement("canvas");
    out.width = width; out.height = height;
    const octx = out.getContext("2d")!;
    const od = octx.createImageData(width, height);
    for (let i = 0; i < width * height; i++) { const v = data.data[i * 4 + 3] > 127 ? 255 : 0; od.data[i * 4] = od.data[i * 4 + 1] = od.data[i * 4 + 2] = v; od.data[i * 4 + 3] = 255; }
    octx.putImageData(od, 0, 0);
    const blob: Blob = await new Promise((res) => out.toBlob((b) => res(b!), "image/png"));
    setSaving(true);
    try {
      const r = await api<SliceResults>(`/api/slices/${sliceId}/mask`, { method: "PUT", body: blob, headers: { "Content-Type": "image/png" } });
      toast(t("viewer.mask_saved")); setDirty(false); history.current = []; future.current = []; setHistLen({ u: 0, r: 0 });
      onSaved(r);
    } catch (e) { toast(errorText(e), "error"); } finally { setSaving(false); }
  };

  // ---- pointer handling -----------------------------------------------------------------------
  const toImage = (e: { clientX: number; clientY: number }): [number, number] => {
    const r = stage.current!.getBoundingClientRect();
    return [(e.clientX - r.left - view.x) / view.s, (e.clientY - r.top - view.y) / view.s];
  };
  const onPointerDown = (e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest(".stage-tools,.stage-badge")) return;
    stage.current!.setPointerCapture(e.pointerId);
    const p = toImage(e);
    if (e.button === 1 || e.button === 2 || (tool === "pan" && e.button === 0) || e.shiftKey) {
      drag.current = { mode: "pan", sx: e.clientX, sy: e.clientY, vx: view.x, vy: view.y };
    } else if (editing && e.button === 0) {
      snapshot(); stamp(p[0], p[1]); setDirty(true);
      drag.current = { mode: "paint", sx: 0, sy: 0, vx: 0, vy: 0, last: p };
    }
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const p = toImage(e);
    setCursor({ x: p[0], y: p[1] });
    const d = drag.current;
    if (!d) return;
    if (d.mode === "pan") setView((v) => ({ ...v, x: d.vx + e.clientX - d.sx, y: d.vy + e.clientY - d.sy }));
    else if (d.last) { stroke(d.last, p); d.last = p; }
  };
  const onPointerUp = () => { drag.current = null; };
  const onWheel = (e: React.WheelEvent) => {
    const r = stage.current!.getBoundingClientRect();
    if (slices && slices.count > 1 && !e.ctrlKey && !e.metaKey) {
      const next = Math.min(slices.count - 1, Math.max(0, slices.index + (e.deltaY > 0 ? 1 : -1)));
      if (next !== slices.index) slices.onChange(next);
      return;
    }
    zoomAt(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX - r.left, e.clientY - r.top);
  };

  // keyboard
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tag)) return;
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
      if (mod && e.key.toLowerCase() === "s" && dirty) { e.preventDefault(); save(); return; }
      if (mod) return;
      const cx = size.w / 2, cy = size.h / 2;
      if (e.key === "+" || e.key === "=") zoomAt(1.2, cx, cy);
      else if (e.key === "-") zoomAt(1 / 1.2, cx, cy);
      else if (e.key === "0") fit();
      else if (e.key === "h") setTool("pan");
      else if (e.key === "b" && canEdit && hasMask) setTool("brush");
      else if (e.key === "e" && canEdit && hasMask) setTool("eraser");
      else if (e.key === "[") setBrush((b) => Math.max(1, b - 2));
      else if (e.key === "]") setBrush((b) => b + 2);
      else if (e.key === "Escape") { setTool("pan"); }
      else if (slices && (e.key === "ArrowUp" || e.key === "PageUp") && slices.index > 0) { e.preventDefault(); slices.onChange(slices.index - 1); }
      else if (slices && (e.key === "ArrowDown" || e.key === "PageDown") && slices.index < slices.count - 1) { e.preventDefault(); slices.onChange(slices.index + 1); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });

  // ---- derived values -------------------------------------------------------------------------
  const v = encodeURIComponent(version);
  const maskColor = encodeURIComponent(color);
  const filter = `brightness(${layers.brightness}) contrast(${layers.contrast})${layers.invert ? " invert(1)" : ""}`;
  const world: React.CSSProperties = { width, height, transform: `translate(${view.x}px, ${view.y}px) scale(${view.s})` };
  const pixelated = view.s > 2;

  return (
    <div className="stage" ref={stage} onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerLeave={() => { onPointerUp(); setCursor(null); }}
      onWheel={onWheel} onContextMenu={(e) => e.preventDefault()}
      style={{ cursor: tool === "pan" ? (drag.current ? "grabbing" : "grab") : "crosshair" }} tabIndex={0} aria-label={t("viewer.label")}>
      <div style={{ position: "absolute", left: 0, top: 0, ...world, transformOrigin: "0 0", imageRendering: pixelated ? "pixelated" : "auto" }}>
        <img className="layer" src={img(sliceId, "original")} alt="" width={width} height={height} style={{ filter, imageRendering: "inherit" }} draggable={false} />
        {hasMask && layers.mask && !editing && <img className="layer" src={img(sliceId, "mask", `?opacity=1&contour=false&color=${maskColor}&v=${v}`)} alt="" width={width} height={height} style={{ opacity: layers.opacity }} draggable={false} />}
        {hasMask && layers.contour && !editing && <img className="layer" src={img(sliceId, "contour", `?v=${v}`)} alt="" width={width} height={height} draggable={false} />}
        {layers.gradcam && results?.classification?.has_gradcam && <img className="layer" src={img(sliceId, "gradcam", `?v=${encodeURIComponent(results.classification.created_at)}`)} alt="" width={width} height={height} style={{ opacity: layers.overlayOpacity / 0.85 }} draggable={false} />}
        {layers.uncertainty !== "off" && results?.segmentation?.has_uncertainty && <img className="layer" src={img(sliceId, layers.uncertainty, `?v=${v}`)} alt="" width={width} height={height} style={{ opacity: layers.overlayOpacity / 0.9 }} draggable={false} />}
        <canvas ref={canvas} className="edit" width={width} height={height} style={{ display: editing ? "block" : "none", opacity: Math.max(0.35, layers.opacity), pointerEvents: "none" }} />
        <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0, pointerEvents: "none", overflow: "visible" }}>
          {editing && cursor && <circle cx={cursor.x} cy={cursor.y} r={brush / 2} fill="none" stroke={tool === "eraser" ? "#fff" : "#ff5a5f"} strokeWidth={1.5 / view.s} />}
        </svg>
      </div>

      <div className="stage-tools" role="toolbar" aria-label={t("viewer.tools")}>
        {([["pan", "hand", "viewer.tool_pan", "H"]] as const).map(([k, ic, tip, key]) => (
          <button key={k} className={`btn icon sm ${tool === k ? "on" : ""}`} onClick={() => setTool(k)} data-tip={`${t(tip)} (${key})`} aria-label={t(tip)} aria-pressed={tool === k}><Icon name={ic} size={18} /></button>))}
        <button className="btn icon sm" onClick={() => zoomAt(1.25, size.w / 2, size.h / 2)} data-tip={`${t("viewer.zoom_in")} (+)`} aria-label={t("viewer.zoom_in")}><Icon name="zoomin" size={18} /></button>
        <button className="btn icon sm" onClick={() => zoomAt(0.8, size.w / 2, size.h / 2)} data-tip={`${t("viewer.zoom_out")} (-)`} aria-label={t("viewer.zoom_out")}><Icon name="zoomout" size={18} /></button>
        <button className="btn icon sm" onClick={fit} data-tip={`${t("viewer.fit")} (0)`} aria-label={t("viewer.fit")}><Icon name="fit" size={18} /></button>
        {canEdit && hasMask && <>
          <hr style={{ width: "100%", border: 0, borderTop: "1px solid var(--border2)", margin: "2px 0" }} />
          <button className={`btn icon sm ${tool === "brush" ? "on" : ""}`} onClick={() => setTool("brush")} data-tip={`${t("viewer.tool_brush")} (B)`} aria-label={t("viewer.tool_brush")} aria-pressed={tool === "brush"}><Icon name="brush" size={18} /></button>
          <button className={`btn icon sm ${tool === "eraser" ? "on" : ""}`} onClick={() => setTool("eraser")} data-tip={`${t("viewer.tool_eraser")} (E)`} aria-label={t("viewer.tool_eraser")} aria-pressed={tool === "eraser"}><Icon name="eraser" size={18} /></button>
        </>}
      </div>

      {editing && (
        <div className="stage-badge" style={{ background: "color-mix(in srgb, var(--panel) 90%, transparent)", padding: 8, borderRadius: 10, border: "1px solid var(--border2)", alignItems: "center" }}>
          <label className="row" style={{ gap: 6, fontSize: ".8rem" }}>{t("viewer.brush_size")}<input type="range" min={1} max={Math.max(40, Math.round(Math.min(width, height) / 4))} value={brush} onChange={(e) => setBrush(Number(e.target.value))} style={{ width: 110 }} /><span className="mono">{brush}</span></label>
          <button className="btn icon sm" disabled={!histLen.u} onClick={undo} data-tip={t("viewer.undo")} aria-label={t("viewer.undo")}><Icon name="undo" size={16} /></button>
          <button className="btn icon sm" disabled={!histLen.r} onClick={redo} data-tip={t("viewer.redo")} aria-label={t("viewer.redo")}><Icon name="redo" size={16} /></button>
          <button className="btn primary sm" disabled={!dirty || saving} onClick={save}>{t("viewer.save_mask")}</button>
          <button className="btn sm" onClick={() => { setTool("pan"); }}>{t("viewer.done")}</button>
        </div>
      )}

      <div className="stage-info">
        {cursor && cursor.x >= 0 && cursor.y >= 0 && cursor.x < width && cursor.y < height ? `x ${Math.floor(cursor.x)}  y ${Math.floor(cursor.y)}  ·  ` : ""}
        {Math.round(view.s * 100)}%  ·  {width}×{height}px
        {slices && slices.count > 1 && `  ·  ${t("viewer.slice")} ${slices.index + 1}/${slices.count}`}
      </div>
    </div>
  );
}
