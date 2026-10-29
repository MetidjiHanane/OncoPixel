"""Research report (PDF, Word), CSV and JSON for one study (its primary slice by default)."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .. import config
from ..context import AppContext
from ..services import analysis, repo
from .strings import tr

SCHEMA_VERSION = "oncopixel-report/1"


# -- data assembly -------------------------------------------------------------------------------
def build(ctx: AppContext, study_id: int, lang: str = "en", anonymize: bool = False,
          slice_id: Optional[int] = None, with_images: bool = True) -> Dict[str, Any]:
    study = repo.study_detail(ctx, study_id)
    sid = slice_id or study["primary_slice_id"]
    if not sid or not any(s["id"] == sid for s in study["slices"]):
        raise repo.NotFound("slice")
    res = analysis.slice_results(ctx, sid)
    srow = repo.get_slice_row(ctx, sid)
    patient = study.get("patient")
    if anonymize:
        patient = {"code": study["code"], "anonymized": True}
    models = {}
    if res["classification"]:
        models["classification"] = res["classification"]["model"]
    if res["segmentation"]:
        models["segmentation"] = res["segmentation"]["model"]
    data: Dict[str, Any] = {
        "schema": SCHEMA_VERSION, "app": {"name": config.APP_NAME, "version": config.VERSION},
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "language": lang,
        "anonymized": bool(anonymize), "disclaimer": tr(lang)["disclaimer"],
        "patient": patient,
        "study": {k: study[k] for k in ("id", "code", "study_date", "sequence", "plane", "source_type", "status", "flagged", "flag_reasons",
                                       "reviewed_by", "reviewed_at", "review_note", "clinician_decision", "clinician_class")}
        | {"indication": None if anonymize else study["indication"], "slice_id": sid, "slice_index": srow["idx"],
           "slice_count": len(study["slices"]), "image_size_px": [srow["width"], srow["height"]],
           "pixel_spacing_mm": res["slice"]["pixel_spacing_mm"], "spacing_source": res["slice"]["spacing_source"]},
        "classification": res["classification"], "segmentation": res["segmentation"], "measurements": res["measurements"],
        "warnings": res["warnings"], "models": models,
        "test_fixture": any(bool(m.get("test_fixture")) for m in models.values()),
    }
    if anonymize:
        data["study"]["review_note"] = ""
    if with_images:
        data["images"] = _images(ctx, sid, res)
    return data


def _images(ctx: AppContext, sid: int, res: Dict[str, Any]) -> Dict[str, bytes]:
    out: Dict[str, bytes] = {"original": analysis.image_png(ctx, sid, "original")}
    wanted = []
    if res["segmentation"]:
        wanted.append(("overlay", "overlay"))
        if res["segmentation"]["has_uncertainty"]:
            wanted.append(("uncertainty", "uncertainty_overlay"))
    if res["classification"] and res["classification"]["has_gradcam"]:
        wanted.append(("gradcam", "gradcam_overlay"))
    for key, kind in wanted:
        try:
            out[key] = analysis.image_png(ctx, sid, kind, opacity=0.45, contour=True)
        except repo.NotFound:
            pass
    return out


def _fmt(v: Any, nd: int = 2) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def measurement_rows(m: Optional[Dict[str, Any]], lang: str) -> List[Tuple[str, str]]:
    """(label, value-with-unit) pairs, in millimetres when the spacing is known, else pixels."""
    s = tr(lang)
    if not m:
        return []
    mm = m.get("units") == "mm"
    u, u2 = (s["mm"], s["mm2"]) if mm else (s["px"], s["px"] + "²")
    rows: List[Tuple[str, str]] = [(s["tumor_detected"], s["yes"] if m.get("tumor_detected") else s["no"])]
    if not m.get("tumor_detected"):
        return rows
    g = lambda base: m.get(f"{base}_mm" if mm else f"{base}_px")  # noqa: E731
    rows += [
        (s["area"], f"{_fmt(m.get('area_mm2') if mm else m.get('area_px'), 1)} {u2}"),
        (s["area_fraction"], f"{_fmt(100 * m['area_fraction_of_image'], 2)} %"),
        (s["bbox"], f"{_fmt(g('bbox_width'), 1)} × {_fmt(g('bbox_height'), 1)} {u}"),
        (s["max_d"], f"{_fmt(g('max_diameter'), 1)} {u}"),
        (s["min_d"], f"{_fmt(g('min_diameter'), 1)} {u}"),
        (s["equiv_d"], f"{_fmt(g('equivalent_diameter'), 1)} {u}"),
        (s["perimeter"], f"{_fmt(g('perimeter'), 1)} {u}"),
        (s["circularity"], _fmt(m.get("circularity"), 3)),
        (s["centroid"], "(" + ", ".join(_fmt(v, 1) for v in (m.get("centroid_xy_mm") if mm else m.get("centroid_xy_px")) or []) + f") {u}"),
        (s["midline"], f"{_fmt(g('midline_distance'), 1)} {u}" if m.get("midline_distance_px") is not None else "-"),
        (s["components"], str(m.get("n_components", "-"))),
    ]
    inten = m.get("intensity") or {}
    rows += [(s["intensity_mean"], _fmt(inten.get("mean"), 1)), (s["intensity_std"], _fmt(inten.get("std"), 1)),
             (s["contrast"], _fmt(inten.get("contrast_ratio"), 2))]
    return rows


def warning_texts(data: Dict[str, Any], lang: str) -> List[str]:
    s = tr(lang)
    out = []
    for w in data["warnings"]:
        if w["severity"] == "info" and w["code"] in ("spacing_from_dicom",):
            continue
        txt = s["warnings"].get(w["code"])
        if txt:
            out.append(txt)
    return out


# -- JSON / CSV ----------------------------------------------------------------------------------
def to_json(data: Dict[str, Any]) -> bytes:
    d = {k: v for k, v in data.items() if k != "images"}
    return json.dumps(d, indent=2, ensure_ascii=False, default=str).encode("utf-8")


def to_csv(data: Dict[str, Any]) -> bytes:
    s = tr(data["language"])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([s["csv_note"]])
    w.writerow(["study_id", "slice_index", "section", "key", "value", "unit"])
    st = data["study"]
    base = [st["code"], st["slice_index"]]

    def row(section: str, key: str, value: Any, unit: str = "") -> None:
        w.writerow(base + [section, key, "" if value is None else value, unit])

    if data["patient"] and not data["anonymized"]:
        p = data["patient"]
        for k in ("code", "name", "age", "sex", "referring_physician"):
            row("patient", k, p.get(k))
    for k in ("study_date", "sequence", "plane", "source_type", "status", "flagged", "reviewed_by", "reviewed_at"):
        row("study", k, st.get(k))
    c = data["classification"]
    if c:
        row("classification", "label", c["label"])
        row("classification", "model_confidence_estimate", round(c["confidence"], 6))
        row("classification", "needs_review", c["needs_review"])
        for k, v in c["probabilities"].items():
            row("classification", f"score_{k}", round(v, 6))
        row("classification", "model", c["model"]["name"])
        row("classification", "checkpoint_sha256", c["model"]["sha256"])
    sg = data["segmentation"]
    if sg:
        row("segmentation", "threshold", sg["threshold"])
        row("segmentation", "mask_manually_edited", sg["edited"])
        row("segmentation", "model", sg["model"]["name"])
        row("segmentation", "checkpoint_sha256", sg["model"]["sha256"])
        if sg["uncertainty"]:
            row("segmentation", "stability_dice_mean", round(sg["uncertainty"]["stability_dice_mean"], 4))
    m = data["measurements"]
    if m:
        skip = {"intensity", "bbox_xyxy_px", "centroid_xy_px", "centroid_xy_mm", "max_diameter_endpoints_px", "pixel_spacing_mm",
                "midline_note", "spacing_note", "units", "computed_at", "spacing_source"}
        for k, v in m.items():
            if k in skip or isinstance(v, (list, dict)):
                continue
            unit = "mm2" if k.endswith("_mm2") else "mm" if k.endswith("_mm") else "px" if k.endswith("_px") else ""
            row("measurements", k, round(v, 6) if isinstance(v, float) else v, unit)
        if m.get("centroid_xy_px"):
            row("measurements", "centroid_x_px", round(m["centroid_xy_px"][0], 3), "px")
            row("measurements", "centroid_y_px", round(m["centroid_xy_px"][1], 3), "px")
        for k, v in (m.get("intensity") or {}).items():
            row("measurements", f"intensity_{k}", round(v, 4) if isinstance(v, float) else v)
    row("clinician_review", "decision", st.get("clinician_decision"))
    row("clinician_review", "class", st.get("clinician_class"))
    row("meta", "disclaimer", data["disclaimer"])
    row("meta", "test_fixture", data["test_fixture"])
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM so Excel reads accents correctly


# -- common layout helpers -----------------------------------------------------------------------
def patient_rows(data: Dict[str, Any], lang: str) -> List[Tuple[str, str]]:
    s = tr(lang)
    p = data["patient"]
    if data["anonymized"] or not p:
        return [(s["patient_id"], (p or {}).get("code", "-")), ("", s["anonymized"])] if data["anonymized"] else [("", s["unavailable"])]
    return [(s["name"], p["name"]), (s["patient_id"], p["code"]), (s["age"], _fmt(p.get("age"))),
            (s["sex"], s["sexes"].get(p.get("sex"), "-")),
            (s["indication"], data["study"].get("indication") or "-"), (s["history"], p.get("history") or "-")]


def study_rows(data: Dict[str, Any], lang: str) -> List[Tuple[str, str]]:
    s, st = tr(lang), data["study"]
    sp = st["pixel_spacing_mm"]
    return [(s["study_id"], st["code"]), (s["study_date"], st["study_date"] or "-"), (s["sequence"], st["sequence"]),
            (s["plane"], s["planes"].get(st["plane"], st["plane"])), (s["source"], s["sources"].get(st["source_type"], st["source_type"])),
            (s["slice"], f"{st['slice_index'] + 1} / {st['slice_count']}"),
            (s["spacing"], f"{sp[0]:.3f} × {sp[1]:.3f} mm ({st['spacing_source']})" if sp else s["spacing_unknown"]),
            (s["status"], s["statuses"].get(st["status"], st["status"])), (s["flagged"], s["yes"] if st["flagged"] else s["no"])]


def clinician_rows(data: Dict[str, Any], lang: str) -> List[Tuple[str, str]]:
    """The clinician's verdict on the model class (agree / change / reject), or a note that none was recorded."""
    s, st = tr(lang), data["study"]
    d = st.get("clinician_decision")
    if not d:
        return [(s["clinician_review"], s["cr_none"])]
    txt = s[f"cr_{d}"]
    if d == "change" and st.get("clinician_class"):
        txt += f" {s['labels'].get(st['clinician_class'], st['clinician_class'])}"
    return [(s["clinician_review"], txt)]


def model_rows(data: Dict[str, Any], lang: str) -> List[Tuple[str, str]]:
    s = tr(lang)
    rows: List[Tuple[str, str]] = []
    c, g = data["classification"], data["segmentation"]
    if c:
        mi = c["model"]
        rows += [(f"{s['model']} (cls)", mi["name"]), (f"{s['checkpoint']} (cls)", mi["short_id"]),
                 (s["temperature"], _fmt(c["params"]["temperature"], 3)), (f"{s['tta']} (cls)", s["yes"] if c["params"]["tta"] else s["no"]),
                 (s["device"] + " (cls)", mi["device"])]
    if g:
        mi = g["model"]
        pp = g["postprocess"]
        pps = ", ".join(k for k, v in pp.items() if v) or s["none"]
        rows += [(f"{s['model']} (seg)", f"{mi['name']} / {mi.get('encoder')}"), (f"{s['checkpoint']} (seg)", mi["short_id"]),
                 (s["threshold"], _fmt(g["threshold"], 3)), (f"{s['tta']} (seg)", s["yes"] if g["tta"] else s["no"]),
                 (s["postprocess"], pps), (s["device"] + " (seg)", mi["device"])]
    return rows


def result_lines(data: Dict[str, Any], lang: str) -> List[Tuple[str, str]]:
    s = tr(lang)
    c = data["classification"]
    if not c:
        return [(s["prediction"], s["unavailable"])]
    rows = [(s["prediction"], s["labels"].get(c["label"], c["label"])),
            (s["confidence"], f"{100 * c['confidence']:.1f} %")]
    if c["needs_review"]:
        rows.append(("", s["needs_review"]))
    rows.append((s["probabilities"], "; ".join(f"{s['labels'].get(k, k)} {100 * v:.1f} %" for k, v in c["probabilities"].items())))
    return rows
