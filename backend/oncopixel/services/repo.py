"""Patients, studies and slices: persistence, decryption and serialisation."""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from typing import Any, Dict, List, Optional

from ..context import AppContext
from ..db import now_iso

STATUSES = ("pending", "analyzed", "reviewed")
SEXES = ("F", "M", "O")
PLANES = ("axial", "sagittal", "coronal", "unknown")
SEQUENCES = ("T1", "T1c", "other")


class NotFound(Exception):
    pass


class Invalid(ValueError):
    pass


# -- patients -----------------------------------------------------------------------------------
def patient_dict(ctx: AppContext, row: sqlite3.Row, with_counts: bool = True) -> Dict[str, Any]:
    v = ctx.vault
    out = {
        "id": row["id"], "code": row["code"], "name": v.decrypt_text(row["name_enc"]) or "",
        "age": row["age"], "sex": row["sex"], "referring_physician": v.decrypt_text(row["referring_enc"]) or "",
        "history": v.decrypt_text(row["history_enc"]) or "",
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }
    if with_counts:
        c = ctx.db.one("SELECT COUNT(*) n, MAX(study_date) last FROM studies WHERE patient_id=?", (row["id"],))
        out["study_count"], out["last_study_date"] = c["n"], c["last"]
    return out


def _clean_patient(data: Dict[str, Any], partial: bool = False) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if "code" in data or not partial:
        code = str(data.get("code", "")).strip()
        if not code:
            raise Invalid("patient_code_required")
        out["code"] = code
    if "name" in data or not partial:
        name = str(data.get("name", "")).strip()
        if not name:
            raise Invalid("patient_name_required")
        out["name"] = name
    if "age" in data:
        age = data["age"]
        if age in (None, ""):
            out["age"] = None
        else:
            age = int(age)
            if not 0 <= age <= 130:
                raise Invalid("age_out_of_range")
            out["age"] = age
    if "sex" in data:
        sex = data["sex"] or None
        if sex is not None and sex not in SEXES:
            raise Invalid("sex_invalid")
        out["sex"] = sex
    for k in ("referring_physician", "history"):
        if k in data:
            out[k] = str(data[k] or "").strip()
    return out


def create_patient(ctx: AppContext, data: Dict[str, Any]) -> Dict[str, Any]:
    d = _clean_patient(data)
    if ctx.db.one("SELECT 1 FROM patients WHERE code=?", (d["code"],)):
        raise Invalid("patient_code_exists")
    ts = now_iso()
    pid = ctx.db.insert("patients", {
        "code": d["code"], "name_enc": ctx.vault.encrypt_text(d["name"]), "age": d.get("age"), "sex": d.get("sex"),
        "referring_enc": ctx.vault.encrypt_text(d.get("referring_physician", "")),
        "history_enc": ctx.vault.encrypt_text(d.get("history", "")), "created_at": ts, "updated_at": ts,
    })
    return get_patient(ctx, pid)


def update_patient(ctx: AppContext, pid: int, data: Dict[str, Any]) -> Dict[str, Any]:
    get_patient(ctx, pid)
    d = _clean_patient(data, partial=True)
    vals: Dict[str, Any] = {"updated_at": now_iso()}
    if "code" in d:
        clash = ctx.db.one("SELECT id FROM patients WHERE code=? AND id<>?", (d["code"], pid))
        if clash:
            raise Invalid("patient_code_exists")
        vals["code"] = d["code"]
    if "name" in d:
        vals["name_enc"] = ctx.vault.encrypt_text(d["name"])
    for k, col in (("age", "age"), ("sex", "sex")):
        if k in d:
            vals[col] = d[k]
    if "referring_physician" in d:
        vals["referring_enc"] = ctx.vault.encrypt_text(d["referring_physician"])
    if "history" in d:
        vals["history_enc"] = ctx.vault.encrypt_text(d["history"])
    ctx.db.update("patients", "id=?", (pid,), vals)
    return get_patient(ctx, pid)


def get_patient(ctx: AppContext, pid: int) -> Dict[str, Any]:
    row = ctx.db.one("SELECT * FROM patients WHERE id=?", (pid,))
    if not row:
        raise NotFound("patient")
    return patient_dict(ctx, row)


def list_patients(ctx: AppContext, q: Optional[str] = None) -> List[Dict[str, Any]]:
    rows = ctx.db.all("SELECT * FROM patients ORDER BY updated_at DESC")
    out = [patient_dict(ctx, r) for r in rows]
    if q:
        needle = q.strip().lower()
        out = [p for p in out if needle in p["name"].lower() or needle in p["code"].lower()]
    return out


def delete_patient(ctx: AppContext, pid: int) -> None:
    get_patient(ctx, pid)
    ctx.db.execute("DELETE FROM patients WHERE id=?", (pid,))  # studies keep existing, unassigned


# -- studies ------------------------------------------------------------------------------------
def _loads(text: Optional[str], default: Any = None) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except ValueError:
        return default


def slice_dict(row: sqlite3.Row, with_flags: bool = True, ctx: Optional[AppContext] = None) -> Dict[str, Any]:
    out = {
        "id": row["id"], "study_id": row["study_id"], "idx": row["idx"], "width": row["width"], "height": row["height"],
        "pixel_spacing_mm": [row["spacing_row"], row["spacing_col"]] if row["spacing_row"] else None,
        "spacing_source": row["spacing_source"], "warnings": _loads(row["warnings_json"], []),
        "dicom": _loads(row["dicom_json"], {}),
    }
    if with_flags and ctx is not None:
        sid = row["id"]
        out["classified"] = bool(ctx.db.one("SELECT 1 FROM classifications WHERE slice_id=?", (sid,)))
        out["segmented"] = bool(ctx.db.one("SELECT 1 FROM segmentations WHERE slice_id=?", (sid,)))
    return out


def study_summary(ctx: AppContext, row: sqlite3.Row) -> Dict[str, Any]:
    patient = None
    if row["patient_id"]:
        pr = ctx.db.one("SELECT * FROM patients WHERE id=?", (row["patient_id"],))
        if pr:
            patient = {"id": pr["id"], "code": pr["code"], "name": ctx.vault.decrypt_text(pr["name_enc"]) or ""}
    n_slices = ctx.db.one("SELECT COUNT(*) n FROM slices WHERE study_id=?", (row["id"],))["n"]
    prim = row["primary_slice_id"]
    cls = ctx.db.one("SELECT label, confidence, needs_review, model_json FROM classifications WHERE slice_id=?", (prim,)) if prim else None
    seg = ctx.db.one("SELECT edited FROM segmentations WHERE slice_id=?", (prim,)) if prim else None
    meas = ctx.db.one("SELECT json FROM measurements WHERE slice_id=?", (prim,)) if prim else None
    mj = _loads(meas["json"], {}) if meas else {}
    return {
        "id": row["id"], "code": row["code"], "patient": patient, "study_date": row["study_date"],
        "created_at": row["created_at"], "updated_at": row["updated_at"], "status": row["status"],
        "flagged": bool(row["flagged"]), "flag_reasons": _loads(row["flag_reason"], []),
        "modality": row["modality"], "sequence": row["sequence"], "plane": row["plane"],
        "source_type": row["source_type"], "slice_count": n_slices, "primary_slice_id": prim,
        "prediction": ({"label": cls["label"], "confidence": cls["confidence"], "needs_review": bool(cls["needs_review"])}
                       if cls else None),
        "segmented": bool(seg), "mask_edited": bool(seg and seg["edited"]),
        "area_px": mj.get("area_px"), "area_mm2": mj.get("area_mm2"),
        "reviewed_by": row["reviewed_by"], "reviewed_at": row["reviewed_at"],
    }


def study_detail(ctx: AppContext, study_id: int) -> Dict[str, Any]:
    row = ctx.db.one("SELECT * FROM studies WHERE id=?", (study_id,))
    if not row:
        raise NotFound("study")
    out = study_summary(ctx, row)
    out["indication"] = ctx.vault.decrypt_text(row["indication_enc"]) or ""
    out["review_note"] = ctx.vault.decrypt_text(row["review_note_enc"]) or ""
    out["clinician_decision"] = row["clinician_decision"]
    out["clinician_class"] = row["clinician_class"]
    if row["patient_id"]:
        out["patient"] = patient_dict(ctx, ctx.db.one("SELECT * FROM patients WHERE id=?", (row["patient_id"],)), with_counts=False)
    out["slices"] = [slice_dict(r, ctx=ctx) for r in ctx.db.all("SELECT * FROM slices WHERE study_id=? ORDER BY idx", (study_id,))]
    return out


def list_studies(ctx: AppContext, status: Optional[str] = None, label: Optional[str] = None,
                 q: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
                 patient_id: Optional[int] = None, unassigned: bool = False,
                 limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    where, params = [], []
    if status == "flagged":
        where.append("s.flagged=1")
    elif status in STATUSES:
        where.append("s.status=?")
        params.append(status)
    if label:
        where.append("c.label=?")
        params.append(label)
    if date_from:
        where.append("COALESCE(s.study_date, substr(s.created_at,1,10)) >= ?")
        params.append(date_from)
    if date_to:
        where.append("COALESCE(s.study_date, substr(s.created_at,1,10)) <= ?")
        params.append(date_to)
    if patient_id:
        where.append("s.patient_id=?")
        params.append(patient_id)
    if unassigned:
        where.append("s.patient_id IS NULL")
    sql = ("SELECT s.* FROM studies s LEFT JOIN classifications c ON c.slice_id=s.primary_slice_id"
           + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY s.created_at DESC, s.id DESC")
    rows = ctx.db.all(sql, params)
    items = [study_summary(ctx, r) for r in rows]
    if q:
        needle = q.strip().lower()
        items = [i for i in items if needle in (i["code"] or "").lower()
                 or (i["patient"] and (needle in i["patient"]["code"].lower() or needle in i["patient"]["name"].lower()))]
    total = len(items)
    return {"total": total, "items": items[offset: offset + limit]}


def update_study(ctx: AppContext, study_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    row = ctx.db.one("SELECT * FROM studies WHERE id=?", (study_id,))
    if not row:
        raise NotFound("study")
    vals: Dict[str, Any] = {"updated_at": now_iso()}
    if "patient_id" in data:
        pid = data["patient_id"]
        if pid is not None:
            get_patient(ctx, int(pid))
        vals["patient_id"] = pid
    if "study_date" in data:
        sd = data["study_date"] or None
        if sd:
            date.fromisoformat(sd)  # raises ValueError for bad input
        vals["study_date"] = sd
    if "plane" in data:
        if data["plane"] not in PLANES:
            raise Invalid("plane_invalid")
        vals["plane"] = data["plane"]
    if "sequence" in data:
        if data["sequence"] not in SEQUENCES:
            raise Invalid("sequence_invalid")
        vals["sequence"] = data["sequence"]
    if "indication" in data:
        vals["indication_enc"] = ctx.vault.encrypt_text(str(data["indication"] or "").strip())
    ctx.db.update("studies", "id=?", (study_id,), vals)
    if "sequence" in data or "plane" in data:
        recompute_state(ctx, study_id)
    return study_detail(ctx, study_id)


def delete_study(ctx: AppContext, study_id: int) -> None:
    if not ctx.db.one("SELECT 1 FROM studies WHERE id=?", (study_id,)):
        raise NotFound("study")
    ctx.db.execute("DELETE FROM studies WHERE id=?", (study_id,))
    ctx.files.delete_tree(f"studies/{study_id}")


def get_slice_row(ctx: AppContext, slice_id: int) -> sqlite3.Row:
    row = ctx.db.one("SELECT * FROM slices WHERE id=?", (slice_id,))
    if not row:
        raise NotFound("slice")
    return row


# -- state ---------------------------------------------------------------------------------------
def recompute_state(ctx: AppContext, study_id: int, results_changed: bool = False) -> None:
    """Derive status and automatic flags from stored results; keep a manual flag if set."""
    row = ctx.db.one("SELECT * FROM studies WHERE id=?", (study_id,))
    if not row:
        return
    reasons = [r for r in _loads(row["flag_reason"], []) if r == "manual"]
    cls_rows = ctx.db.all(
        "SELECT c.needs_review FROM classifications c JOIN slices s ON s.id=c.slice_id WHERE s.study_id=?", (study_id,))
    if any(r["needs_review"] for r in cls_rows):
        reasons.append("low_confidence")
    if row["sequence"] == "other":
        reasons.append("sequence_not_t1")
    for s in ctx.db.all("SELECT warnings_json FROM slices WHERE study_id=?", (study_id,)):
        for w in _loads(s["warnings_json"], []):
            if w["code"] in ("image_is_colour", "sequence_not_t1") and f"input:{w['code']}" not in reasons:
                reasons.append(f"input:{w['code']}")
    prim = row["primary_slice_id"]
    if prim:
        c = ctx.db.one("SELECT label FROM classifications WHERE slice_id=?", (prim,))
        m = ctx.db.one("SELECT json FROM measurements WHERE slice_id=?", (prim,))
        if c and m:
            detected = bool(_loads(m["json"], {}).get("tumor_detected"))
            if (c["label"] == "no_tumor") == detected:
                reasons.append("model_disagreement")
    reasons = list(dict.fromkeys(reasons))
    analysed = bool(cls_rows) or bool(ctx.db.one(
        "SELECT 1 FROM segmentations g JOIN slices s ON s.id=g.slice_id WHERE s.study_id=?", (study_id,)))
    status = row["status"]
    if not analysed:
        status = "pending"
    elif status == "pending" or results_changed:
        status = "analyzed"
    ctx.db.update("studies", "id=?", (study_id,), {
        "status": status, "flagged": 1 if reasons else 0, "flag_reason": json.dumps(reasons), "updated_at": now_iso(),
        **({"reviewed_by": None, "reviewed_at": None} if status != "reviewed" else {}),
    })


def set_review(ctx: AppContext, study_id: int, username: str, decision: str, note: str = "") -> Dict[str, Any]:
    row = ctx.db.one("SELECT * FROM studies WHERE id=?", (study_id,))
    if not row:
        raise NotFound("study")
    ts = now_iso()
    if decision == "reviewed":
        if row["status"] == "pending":
            raise Invalid("cannot_review_before_analysis")
        ctx.db.update("studies", "id=?", (study_id,), {
            "status": "reviewed", "reviewed_by": username, "reviewed_at": ts, "updated_at": ts,
            "review_note_enc": ctx.vault.encrypt_text(note.strip()),
        })
    elif decision == "reopen":
        ctx.db.update("studies", "id=?", (study_id,), {"status": "analyzed", "reviewed_by": None, "reviewed_at": None, "updated_at": ts})
    elif decision in ("flag", "unflag"):
        reasons = [r for r in _loads(row["flag_reason"], []) if r != "manual"]
        if decision == "flag":
            reasons.append("manual")
        ctx.db.update("studies", "id=?", (study_id,), {"flagged": 1 if reasons else 0, "flag_reason": json.dumps(reasons), "updated_at": ts})
        if decision == "unflag":
            recompute_state(ctx, study_id)
    else:
        raise Invalid("decision_invalid")
    return study_detail(ctx, study_id)


def set_clinician_decision(ctx: AppContext, study_id: int, decision: Optional[str], label: Optional[str] = None) -> Dict[str, Any]:
    """Record the clinician's verdict on the model's class: agree, change (with the class) or reject."""
    from ..config import EXPECTED_CLASSES
    if not ctx.db.one("SELECT 1 FROM studies WHERE id=?", (study_id,)):
        raise NotFound("study")
    if decision not in (None, "agree", "change", "reject"):
        raise Invalid("decision_invalid")
    if decision == "change" and label not in EXPECTED_CLASSES:
        raise Invalid("decision_invalid")
    ctx.db.update("studies", "id=?", (study_id,), {
        "clinician_decision": decision, "clinician_class": label if decision == "change" else None, "updated_at": now_iso()})
    return study_detail(ctx, study_id)


def set_primary_slice(ctx: AppContext, study_id: int, slice_id: int) -> None:
    row = ctx.db.one("SELECT 1 FROM slices WHERE id=? AND study_id=?", (slice_id, study_id))
    if not row:
        raise NotFound("slice")
    ctx.db.update("studies", "id=?", (study_id,), {"primary_slice_id": slice_id, "updated_at": now_iso()})


# -- dashboard -----------------------------------------------------------------------------------
def dashboard(ctx: AppContext) -> Dict[str, Any]:
    db = ctx.db
    total = db.one("SELECT COUNT(*) n FROM studies")["n"]
    analysed = db.one("SELECT COUNT(*) n FROM studies WHERE status IN ('analyzed','reviewed')")["n"]
    pending_review = db.one("SELECT COUNT(*) n FROM studies WHERE status='analyzed'")["n"]
    flagged = db.one("SELECT COUNT(*) n FROM studies WHERE flagged=1")["n"]
    not_analysed = db.one("SELECT COUNT(*) n FROM studies WHERE status='pending'")["n"]
    by_class = {r["label"]: r["n"] for r in db.all(
        "SELECT c.label, COUNT(*) n FROM studies s JOIN classifications c ON c.slice_id=s.primary_slice_id GROUP BY c.label")}
    recent = []
    for r in db.all("SELECT * FROM activity ORDER BY id DESC LIMIT 12"):
        recent.append({"ts": r["ts"], "user": r["username"], "action": r["action"], "entity": r["entity"],
                       "entity_id": r["entity_id"], "detail": _loads(r["detail_json"], {})})
    per_day = [{"day": r["d"], "count": r["n"]} for r in db.all(
        "SELECT substr(created_at,1,10) d, COUNT(*) n FROM studies WHERE created_at >= date('now','-13 day') GROUP BY d ORDER BY d")]
    return {"total_studies": total, "analyses_completed": analysed, "pending_reviews": pending_review,
            "flagged": flagged, "not_analyzed": not_analysed, "by_class": by_class, "recent_activity": recent,
            "studies_per_day": per_day, "patients": db.one("SELECT COUNT(*) n FROM patients")["n"]}
