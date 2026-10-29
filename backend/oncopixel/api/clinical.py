"""Patients, studies, import, analysis, mask editing, review, comparison and exports."""
from __future__ import annotations

import io
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..context import AppContext
from ..exports import masks, report
from ..exports.docx import to_docx
from ..exports.pdf import to_pdf
from ..services import analysis, compare, importer, repo
from ..services.media import read_png_gray
from .deps import ApiError, current_user, get_ctx

router = APIRouter(prefix="/api", tags=["clinical"], dependencies=[Depends(current_user)])


# -- patients ------------------------------------------------------------------------------------
class PatientBody(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    age: Optional[int] = None
    sex: Optional[str] = None
    referring_physician: Optional[str] = None
    history: Optional[str] = None


@router.get("/patients")
def patients(q: Optional[str] = None, ctx: AppContext = Depends(get_ctx)):
    return repo.list_patients(ctx, q)


@router.post("/patients", status_code=201)
def create_patient(body: PatientBody, user: str = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    p = repo.create_patient(ctx, body.model_dump(exclude_unset=True))
    ctx.db.log(user, "patient.create", "patient", p["id"])
    return p


@router.get("/patients/{pid}")
def patient(pid: int, ctx: AppContext = Depends(get_ctx)):
    p = repo.get_patient(ctx, pid)
    p["studies"] = repo.list_studies(ctx, patient_id=pid, limit=500)["items"]
    return p


@router.patch("/patients/{pid}")
def patch_patient(pid: int, body: PatientBody, user: str = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    p = repo.update_patient(ctx, pid, body.model_dump(exclude_unset=True))
    ctx.db.log(user, "patient.update", "patient", pid)
    return p


@router.delete("/patients/{pid}", status_code=204)
def delete_patient(pid: int, user: str = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    repo.delete_patient(ctx, pid)
    ctx.db.log(user, "patient.delete", "patient", pid)
    return Response(status_code=204)


# -- studies -------------------------------------------------------------------------------------
@router.get("/studies")
def studies(status: Optional[str] = None, label: Optional[str] = None, q: Optional[str] = None,
            date_from: Optional[str] = None, date_to: Optional[str] = None, patient_id: Optional[int] = None,
            unassigned: bool = False, limit: int = 100, offset: int = 0, ctx: AppContext = Depends(get_ctx)):
    return repo.list_studies(ctx, status, label, q, date_from, date_to, patient_id, unassigned, min(limit, 500), offset)


@router.get("/studies/export.csv")
def studies_csv(ctx: AppContext = Depends(get_ctx)):
    import csv

    items = repo.list_studies(ctx, limit=100000)["items"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["study_id", "patient_id", "study_date", "status", "flagged", "predicted_class", "confidence", "area_px", "area_mm2"])
    for s in items:
        pr = s["prediction"] or {}
        w.writerow([s["code"], (s["patient"] or {}).get("code", ""), s["study_date"], s["status"], int(s["flagged"]),
                    pr.get("label", ""), f"{pr['confidence']:.4f}" if pr else "", s["area_px"] or "", s["area_mm2"] or ""])
    return Response(("﻿" + buf.getvalue()).encode("utf-8"), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="oncopixel-studies.csv"'})


@router.get("/studies/{sid}")
def study(sid: int, ctx: AppContext = Depends(get_ctx)):
    return repo.study_detail(ctx, sid)


class StudyBody(BaseModel):
    patient_id: Optional[int] = None
    study_date: Optional[str] = None
    plane: Optional[str] = None
    sequence: Optional[str] = None
    indication: Optional[str] = None
    primary_slice_id: Optional[int] = None


@router.patch("/studies/{sid}")
def patch_study(sid: int, body: StudyBody, user: str = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    data = body.model_dump(exclude_unset=True)
    prim = data.pop("primary_slice_id", None)
    if prim:
        repo.set_primary_slice(ctx, sid, prim)
    out = repo.update_study(ctx, sid, data) if data else repo.study_detail(ctx, sid)
    ctx.db.log(user, "study.update", "study", sid, {"keys": sorted(body.model_dump(exclude_unset=True))})
    return out


@router.delete("/studies/{sid}", status_code=204)
def delete_study(sid: int, user: str = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    repo.delete_study(ctx, sid)
    ctx.db.log(user, "study.delete", "study", sid)
    return Response(status_code=204)


class SpacingBody(BaseModel):
    row_mm: float = Field(gt=0, le=20)
    col_mm: float = Field(gt=0, le=20)


@router.put("/studies/{sid}/spacing")
def study_spacing(sid: int, body: SpacingBody, user: str = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    importer.set_spacing(ctx, sid, (body.row_mm, body.col_mm), user)
    return repo.study_detail(ctx, sid)


class ReviewBody(BaseModel):
    decision: str  # reviewed | reopen | flag | unflag
    note: str = ""


@router.post("/studies/{sid}/review")
def review(sid: int, body: ReviewBody, user: str = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    out = repo.set_review(ctx, sid, user, body.decision, body.note)
    ctx.db.log(user, f"study.{body.decision}", "study", sid)
    return out


class ClinicianBody(BaseModel):
    decision: Optional[str] = None  # agree | change | reject | null (clear)
    label: Optional[str] = None


@router.post("/studies/{sid}/clinician-decision")
def clinician_decision(sid: int, body: ClinicianBody, user: str = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    out = repo.set_clinician_decision(ctx, sid, body.decision, body.label)
    ctx.db.log(user, "study.clinician_decision", "study", sid, {"decision": body.decision, "label": body.label})
    return out


# -- import --------------------------------------------------------------------------------------
class ImportOptions(BaseModel):
    patient_id: Optional[int] = None
    group_images: str = "separate"
    sequence: str = "T1"
    plane: Optional[str] = None
    study_date: Optional[str] = None
    spacing_row_mm: Optional[float] = None
    spacing_col_mm: Optional[float] = None
    anonymize_dicom: Optional[bool] = None
    indication: str = ""


class ImportPaths(ImportOptions):
    paths: List[str]


def _spacing(o: ImportOptions):
    if o.spacing_row_mm and o.spacing_col_mm:
        return (o.spacing_row_mm, o.spacing_col_mm)
    if o.spacing_row_mm or o.spacing_col_mm:
        raise ApiError(422, "spacing_invalid")
    return None


@router.post("/import/paths")
def import_by_path(body: ImportPaths, user: str = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    """Import files or folders that already exist on this computer (drag and drop in the desktop app)."""
    return importer.import_paths(ctx, body.paths, user, body.patient_id, body.group_images, body.sequence, body.plane,
                                 body.study_date, _spacing(body), body.anonymize_dicom, body.indication)


@router.post("/import/upload")
async def import_upload(files: List[UploadFile] = File(...), options: str = Form("{}"), user: str = Depends(current_user),
                        ctx: AppContext = Depends(get_ctx)):
    """Import uploaded files (used when the path is not available, e.g. a browser file picker)."""
    opts = ImportOptions.model_validate_json(options)
    with tempfile.TemporaryDirectory() as td:
        saved: List[str] = []
        for i, up in enumerate(files):
            name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(up.filename or f"file{i}").name) or f"file{i}"
            dest = Path(td) / f"{i:05d}_{name}"
            with open(dest, "wb") as f:
                shutil.copyfileobj(up.file, f)
            saved.append(str(dest))
        return importer.import_paths(ctx, saved, user, opts.patient_id, opts.group_images, opts.sequence, opts.plane,
                                     opts.study_date, _spacing(opts), opts.anonymize_dicom, opts.indication)


# -- slices: images, analysis, mask --------------------------------------------------------------
def _slice_ok(ctx: AppContext, slice_id: int):
    return repo.get_slice_row(ctx, slice_id)


@router.get("/slices/{slice_id}")
def slice_results(slice_id: int, ctx: AppContext = Depends(get_ctx)):
    _slice_ok(ctx, slice_id)
    return analysis.slice_results(ctx, slice_id)


@router.get("/slices/{slice_id}/image/{kind}")
def slice_image(slice_id: int, kind: str, opacity: Optional[float] = None, color: Optional[str] = None,
                contour: Optional[bool] = None, source: str = "current", ctx: AppContext = Depends(get_ctx)):
    _slice_ok(ctx, slice_id)
    if kind not in analysis.KINDS:
        raise ApiError(404, "unknown_image_kind")
    png = analysis.image_png(ctx, slice_id, kind, opacity, color, contour, "model" if source == "model" else "current")
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, no-cache"})


class AnalyzeBody(BaseModel):
    stages: Optional[List[str]] = None
    gradcam: bool = True


@router.post("/slices/{slice_id}/analyze")
def analyze(slice_id: int, body: AnalyzeBody = AnalyzeBody(), user: str = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    _slice_ok(ctx, slice_id)
    return analysis.analyze(ctx, slice_id, user, body.stages, body.gradcam)


@router.post("/studies/{sid}/analyze")
def analyze_study(sid: int, body: AnalyzeBody = AnalyzeBody(), user: str = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    """Analyse the primary slice of the study (the one shown in lists and reports)."""
    st = repo.study_detail(ctx, sid)
    if not st["primary_slice_id"]:
        raise ApiError(422, "study_has_no_slice")
    return analysis.analyze(ctx, st["primary_slice_id"], user, body.stages, body.gradcam)


@router.post("/slices/{slice_id}/uncertainty")
def uncertainty(slice_id: int, user: str = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    _slice_ok(ctx, slice_id)
    analysis.compute_uncertainty(ctx, slice_id, user)
    return analysis.slice_results(ctx, slice_id)


class ResegmentBody(BaseModel):
    threshold: Optional[float] = None
    postprocess: Optional[Dict[str, Any]] = None
    discard_edits: bool = False


@router.post("/slices/{slice_id}/resegment")
def resegment(slice_id: int, body: ResegmentBody, user: str = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    _slice_ok(ctx, slice_id)
    analysis.resegment(ctx, slice_id, user, body.threshold, body.postprocess, body.discard_edits)
    return analysis.slice_results(ctx, slice_id)


@router.put("/slices/{slice_id}/mask")
async def put_mask(slice_id: int, request: Request, user: str = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    """Save a manually corrected mask: the request body is a PNG with the same size as the image."""
    _slice_ok(ctx, slice_id)
    data = await request.body()
    try:
        mask = read_png_gray(data)
    except ValueError:
        raise ApiError(422, "mask_not_an_image")
    analysis.save_mask(ctx, slice_id, mask, user)
    return analysis.slice_results(ctx, slice_id)


@router.post("/slices/{slice_id}/mask/reset")
def mask_reset(slice_id: int, user: str = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    _slice_ok(ctx, slice_id)
    analysis.reset_mask(ctx, slice_id, user)
    return analysis.slice_results(ctx, slice_id)


# -- comparison ----------------------------------------------------------------------------------
@router.get("/compare")
def compare_studies(a: int, b: int, ctx: AppContext = Depends(get_ctx)):
    return compare.compare_studies(ctx, a, b)


@router.get("/compare/overlay.png")
def compare_overlay(a: int, b: int, ctx: AppContext = Depends(get_ctx)):
    return Response(compare.overlay_png(ctx, a, b), media_type="image/png", headers={"Cache-Control": "private, no-cache"})


# -- exports -------------------------------------------------------------------------------------
EXPORTS = {
    "pdf": ("application/pdf", "pdf"), "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
    "csv": ("text/csv", "csv"), "json": ("application/json", "json"), "mask-png": ("image/png", "mask.png"),
    "mask-nifti": ("application/gzip", "mask.nii.gz"), "dicom-seg": ("application/zip", "dicom-seg.zip"),
    "dicom-sr": ("application/zip", "dicom-sr.zip"),
}


@router.get("/studies/{sid}/export/{fmt}")
def export(sid: int, fmt: str, lang: Optional[str] = None, anonymize: Optional[bool] = None, slice_id: Optional[int] = None,
           save: bool = False, user: str = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    if fmt not in EXPORTS:
        raise ApiError(404, "unknown_export_format")
    st = ctx.settings()
    lang = lang or st["report_language"]
    if lang not in ("en", "fr"):
        raise ApiError(422, "language_invalid")
    anon = st["anonymize_exports"] if anonymize is None else anonymize
    study = repo.study_detail(ctx, sid)
    sl = slice_id or study["primary_slice_id"]
    if not sl:
        raise ApiError(422, "study_has_no_slice")
    try:
        if fmt in ("pdf", "docx", "csv", "json"):
            data = report.build(ctx, sid, lang, anon, sl, with_images=fmt in ("pdf", "docx"))
            blob = {"pdf": to_pdf, "docx": to_docx, "csv": report.to_csv, "json": report.to_json}[fmt](data)
        elif fmt == "mask-png":
            blob = masks.mask_png(ctx, sl)
        elif fmt == "mask-nifti":
            blob = masks.nifti(ctx, sl)
        elif fmt == "dicom-seg":
            blob = masks.dicom_seg_zip(ctx, sid, sl, anon)
        else:
            blob = masks.dicom_sr_zip(ctx, sid, sl, anon, lang)
    except masks.ExportError as exc:
        raise ApiError(422, str(exc))
    media, ext = EXPORTS[fmt]
    stem = study["code"] + ("-anon" if anon else "")
    filename = f"{stem}.{ext}"
    ctx.db.log(user, "export", "study", sid, {"format": fmt, "anonymized": bool(anon), "language": lang})
    if save:
        path = ctx.export_dir() / filename
        path.write_bytes(blob)
        return {"path": str(path), "name": filename, "size_kb": round(len(blob) / 1024, 1)}
    return Response(blob, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
