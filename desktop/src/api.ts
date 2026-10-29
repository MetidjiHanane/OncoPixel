// Typed client for the local OncoPixel API. Every error carries a stable code the UI can translate.

export class ApiError extends Error {
  status: number;
  code: string;
  extra: Record<string, any>;
  constructor(status: number, code: string, message: string, extra: Record<string, any> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.extra = extra;
  }
}

async function parse(res: Response): Promise<any> {
  const type = res.headers.get("content-type") || "";
  if (type.includes("application/json")) return res.json();
  return res;
}

export async function api<T = any>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers = new Headers(init.headers);
  let body = init.body;
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.json);
  }
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers, body, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, "backend_unreachable", "The OncoPixel backend is not reachable");
  }
  if (res.status === 204) return undefined as T;
  const data = await parse(res);
  if (!res.ok) {
    const e = (data && data.error) || {};
    const { code, message, ...extra } = e;
    if (res.status === 401 && code === "not_authenticated") window.dispatchEvent(new Event("oncopixel:signed-out"));
    throw new ApiError(res.status, code || `http_${res.status}`, message || res.statusText, extra);
  }
  return data as T;
}

export const get = <T = any>(p: string) => api<T>(p);
export const post = <T = any>(p: string, json?: unknown) => api<T>(p, { method: "POST", json: json ?? {} });
export const patch = <T = any>(p: string, json: unknown) => api<T>(p, { method: "PATCH", json });
export const put = <T = any>(p: string, json: unknown) => api<T>(p, { method: "PUT", json });
export const del = <T = any>(p: string) => api<T>(p, { method: "DELETE" });

export function qs(params: Record<string, any>): string {
  const u = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") u.set(k, String(v));
  });
  const s = u.toString();
  return s ? `?${s}` : "";
}

// ---- types -------------------------------------------------------------------------------------
export type Lang = "en" | "fr";
export type StudyStatus = "pending" | "analyzed" | "reviewed";
export type ClassName = "glioma" | "meningioma" | "no_tumor" | "pituitary";
export const CLASS_NAMES: ClassName[] = ["glioma", "meningioma", "no_tumor", "pituitary"];

export interface Settings {
  theme: "dark" | "light";
  language: Lang;
  high_contrast: boolean;
  font_size: "small" | "medium" | "large";
  overlay_opacity: number;
  overlay_color: string;
  show_contour: boolean;
  export_dir: string;
  report_language: Lang;
  anonymize_exports: boolean;
  device: "auto" | "mps" | "cpu" | "cuda";
  classifier_tta: boolean;
  segmenter_tta: boolean | null;
  review_threshold: number;
  segmentation_threshold: number | null;
  classification_checkpoint: string;
  segmentation_checkpoint: string;
  watch_enabled: boolean;
  watch_dir: string;
  anonymize_dicom_on_import: boolean;
  welcome_seen: boolean;
  tour_done: boolean;
  [k: string]: any;
}

export interface AuthState {
  setup_required: boolean;
  authenticated: boolean;
  user: { username: string; display_name: string; has_recovery_key?: boolean } | null;
  app: { name: string; version: string; tagline: string };
  disclaimer: { en: string; fr: string };
}

export interface Patient {
  id: number;
  code: string;
  name: string;
  age: number | null;
  sex: "F" | "M" | "O" | null;
  referring_physician: string;
  history: string;
  study_count?: number;
  last_study_date?: string | null;
  studies?: StudySummary[];
}

export interface StudySummary {
  id: number;
  code: string;
  patient: { id: number; code: string; name: string } | null;
  study_date: string | null;
  created_at: string;
  status: StudyStatus;
  flagged: boolean;
  flag_reasons: string[];
  sequence: string;
  plane: string;
  source_type: string;
  slice_count: number;
  primary_slice_id: number | null;
  prediction: { label: ClassName; confidence: number; needs_review: boolean } | null;
  segmented: boolean;
  mask_edited: boolean;
  area_px: number | null;
  area_mm2: number | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
}

export interface Warning {
  code: string;
  severity: "info" | "warning" | "error";
  params: Record<string, any>;
}

export interface SliceInfo {
  id: number;
  study_id: number;
  idx: number;
  width: number;
  height: number;
  pixel_spacing_mm: [number, number] | null;
  spacing_source: string | null;
  warnings: Warning[];
  dicom: Record<string, any>;
  classified?: boolean;
  segmented?: boolean;
}

export interface StudyDetail extends StudySummary {
  indication: string;
  review_note: string;
  clinician_decision?: "agree" | "change" | "reject" | null;
  clinician_class?: string | null;
  patient: Patient | null;
  slices: SliceInfo[];
}

export interface ModelInfo {
  kind: string;
  name: string;
  sha256: string;
  short_id: string;
  input_size: number;
  device: string;
  size_mb: number;
  test_fixture: boolean;
  epoch?: number;
  temperature?: number;
  classes?: string[];
  gradcam_supported?: boolean;
  encoder?: string;
  defaults?: Record<string, any>;
  limitations?: string;
}

export interface ClassificationResult {
  label: ClassName;
  confidence: number;
  probabilities: Record<ClassName, number>;
  needs_review: boolean;
  model: ModelInfo;
  params: { tta: boolean; temperature: number; review_threshold: number };
  gradcam_status: string;
  has_gradcam: boolean;
  inference_ms: number;
  created_at: string;
}

export interface UncertaintyStats {
  n_perturbations: number;
  stability_dice_mean: number;
  stability_dice_min: number;
  boundary_entropy_mean: number | null;
  boundary_variability_mean: number | null;
  uncertain_pixels_px: number;
  uncertain_fraction_of_mask: number | null;
  calibrated: boolean;
}

export interface SegmentationResult {
  threshold: number;
  tta: boolean;
  postprocess: { min_component_area: number; keep_largest: boolean; fill_holes: boolean };
  model: ModelInfo;
  edited: boolean;
  edited_at: string | null;
  has_uncertainty: boolean;
  uncertainty: UncertaintyStats | null;
  inference_ms: number;
  created_at: string;
}

export interface Measurements {
  units: "px" | "mm";
  tumor_detected: boolean;
  image_width_px: number;
  image_height_px: number;
  pixel_spacing_mm: [number, number] | null;
  area_px: number;
  area_mm2?: number;
  area_fraction_of_image: number;
  n_components?: number;
  bbox_xyxy_px?: number[];
  bbox_width_px?: number;
  bbox_height_px?: number;
  bbox_width_mm?: number;
  bbox_height_mm?: number;
  centroid_xy_px?: [number, number];
  centroid_xy_mm?: [number, number];
  perimeter_px?: number;
  perimeter_mm?: number;
  circularity?: number | null;
  equivalent_diameter_px?: number;
  equivalent_diameter_mm?: number;
  max_diameter_px?: number;
  min_diameter_px?: number;
  max_diameter_mm?: number;
  min_diameter_mm?: number;
  max_diameter_angle_deg?: number;
  max_diameter_endpoints_px?: [[number, number], [number, number]];
  aspect_ratio?: number | null;
  midline_distance_px?: number | null;
  midline_distance_mm?: number;
  intensity?: { mean: number; std: number; median: number; min: number; max: number; surrounding_ring_mean?: number; contrast_ratio?: number | null };
  mask_edited: boolean;
  computed_at: string;
}

export interface SliceResults {
  slice: SliceInfo;
  classification: ClassificationResult | null;
  segmentation: SegmentationResult | null;
  measurements: Measurements | null;
  warnings: Warning[];
  skipped?: Record<string, { kind: string; state: string; code: string; detail: string; path: string }>;
}

export interface ModelStatus {
  kind: "classification" | "segmentation";
  path: string;
  path_source: string;
  exists: boolean;
  state: "ready" | "missing" | "invalid";
  code: string | null;
  detail: string | null;
  info: ModelInfo | null;
}

export interface ModelsStatus {
  models: { classification: ModelStatus; segmentation: ModelStatus };
  devices: Record<string, boolean>;
  resolved_device: string;
  any_test_fixture: boolean;
  all_ready: boolean;
}

export interface Dashboard {
  total_studies: number;
  analyses_completed: number;
  pending_reviews: number;
  flagged: number;
  not_analyzed: number;
  patients: number;
  by_class: Record<string, number>;
  studies_per_day: { day: string; count: number }[];
  recent_activity: { ts: string; user: string; action: string; entity: string | null; entity_id: number | null; detail: Record<string, any> }[];
  models: Record<string, string>;
}

export interface ImportResult {
  created: number[];
  rejected: { name: string; warnings: Warning[] }[];
  studies: StudyDetail[];
}

export interface CompareResult {
  a: { study: any; slice_id: number };
  b: { study: any; slice_id: number };
  comparison: { unit_system: "px" | "mm"; rows: { metric: string; unit: string; a: number; b: number; delta: number; percent: number | null }[]; comparable_in_mm: boolean };
  measurements: { a: Measurements; b: Measurements };
  days_between: number | null;
  area_change_per_day?: number;
  mask_overlap: { dice: number | null; iou: number | null; overlap_px: number; only_a_px: number; only_b_px: number } | null;
  notes: string[];
}

export interface SelfTest {
  classification: { state: string; info?: ModelInfo; checks: { name: string; ok: boolean; detail: string }[]; forward_ms?: number; error?: any } | null;
  segmentation: { state: string; info?: ModelInfo; checks: { name: string; ok: boolean; detail: string }[]; forward_ms?: number; error?: any } | null;
  all_ok: boolean;
  test_fixture: boolean;
  device: string;
}
