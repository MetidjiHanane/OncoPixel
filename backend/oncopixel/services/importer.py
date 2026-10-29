"""Turns files and folders into studies and slices stored in the encrypted file store."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..context import AppContext
from ..db import now_iso
from . import repo
from .imaging import ImportRejected, LoadedGroup, discover, load_dicom_groups, load_image_file
from .media import png_bytes


def slice_dir(study_id: int, slice_id: int) -> str:
    return f"studies/{study_id}/slice_{slice_id}"


def _store_group(ctx: AppContext, group: LoadedGroup, patient_id: Optional[int], source_type: str,
                 sequence: str, plane: Optional[str], study_date: Optional[str],
                 spacing_override: Optional[Tuple[float, float]], indication: str = "") -> int:
    ts = now_iso()
    sd = study_date or group.study_date or date.today().isoformat()
    study_id = ctx.db.insert("studies", {
        "code": None, "patient_id": patient_id, "study_date": sd, "created_at": ts, "updated_at": ts,
        "status": "pending", "flagged": 0, "flag_reason": "[]", "modality": "MRI", "sequence": sequence,
        "plane": plane or group.plane or "unknown", "source_type": source_type,
        "indication_enc": ctx.vault.encrypt_text(indication),
    })
    ctx.db.update("studies", "id=?", (study_id,), {"code": f"ST-{study_id:05d}"})
    first_slice = None
    for idx, sl in enumerate(group.slices):
        spacing, source = sl.spacing, sl.spacing_source
        warns = list(sl.warnings)
        if spacing_override:
            spacing, source = spacing_override, "user"
            warns = [w for w in warns if w["code"] != "pixel_spacing_unknown"]
        h, w = sl.gray.shape
        png = png_bytes(sl.gray)
        sid = ctx.db.insert("slices", {
            "study_id": study_id, "idx": idx, "file_rel": None, "width": w, "height": h,
            "orig_name_enc": ctx.vault.encrypt_text(sl.name),
            "spacing_row": spacing[0] if spacing else None, "spacing_col": spacing[1] if spacing else None,
            "spacing_source": source, "dicom_json": json.dumps(sl.dicom) if sl.dicom else None,
            "warnings_json": json.dumps(warns), "sha256": hashlib.sha256(sl.gray.tobytes()).hexdigest(),
        })
        rel = ctx.files.write(f"{slice_dir(study_id, sid)}/original.png", png)
        ctx.db.update("slices", "id=?", (sid,), {"file_rel": rel})
        if first_slice is None:
            first_slice = sid
    # for a series the primary slice is the middle one; the user can change it
    primary = ctx.db.all("SELECT id FROM slices WHERE study_id=? ORDER BY idx", (study_id,))
    ctx.db.update("studies", "id=?", (study_id,), {"primary_slice_id": primary[len(primary) // 2]["id"]})
    repo.recompute_state(ctx, study_id)
    return study_id


def _resolve_patient(ctx: AppContext, patient_id: Optional[int], hint: Dict[str, Any]) -> Optional[int]:
    if patient_id:
        repo.get_patient(ctx, patient_id)
        return patient_id
    code, name = (hint.get("code") or "").strip(), (hint.get("name") or "").strip()
    if code and name:
        row = ctx.db.one("SELECT id FROM patients WHERE code=?", (code,))
        if row:
            return int(row["id"])
        return repo.create_patient(ctx, {"code": code, "name": name, "age": hint.get("age"), "sex": hint.get("sex")})["id"]
    return None


def import_paths(ctx: AppContext, paths: List[str], username: str, patient_id: Optional[int] = None,
                 group_images: str = "separate", sequence: str = "T1", plane: Optional[str] = None,
                 study_date: Optional[str] = None, spacing_mm: Optional[Tuple[float, float]] = None,
                 anonymize_dicom: Optional[bool] = None, indication: str = "") -> Dict[str, Any]:
    """Import files or folders. ``group_images``: ``separate`` (one study per image) or ``series``.

    Returns the created study ids and, for every file that was not imported, the reason.
    """
    if sequence not in repo.SEQUENCES:
        raise repo.Invalid("sequence_invalid")
    if plane is not None and plane not in repo.PLANES:
        raise repo.Invalid("plane_invalid")
    if group_images not in ("separate", "series"):
        raise repo.Invalid("group_invalid")
    if spacing_mm and not (spacing_mm[0] > 0 and spacing_mm[1] > 0):
        raise repo.Invalid("spacing_invalid")
    if study_date:
        date.fromisoformat(study_date)
    st = ctx.settings()
    anonymize = st["anonymize_dicom_on_import"] if anonymize_dicom is None else anonymize_dicom
    images, dicoms = discover(paths)
    created: List[int] = []
    rejected: List[Dict[str, Any]] = []

    loaded_images: List[LoadedGroup] = []
    for p in images:
        try:
            loaded_images.append(load_image_file(p, int(st["max_image_pixels"]), int(st["max_file_mb"])))
        except ImportRejected as exc:
            rejected.append({"name": exc.name, "warnings": exc.warnings})
    if loaded_images:
        if group_images == "series" and len(loaded_images) > 1:
            merged = LoadedGroup(kind="image", slices=[s for g in loaded_images for s in g.slices])
            created.append(_store_group(ctx, merged, patient_id, "image", sequence, plane, study_date, spacing_mm, indication))
        else:
            for g in loaded_images:
                created.append(_store_group(ctx, g, patient_id, "image", sequence, plane, study_date, spacing_mm, indication))

    if not images:
        rejected.append({"name": "(selection)", "warnings": [{"code": "no_supported_files", "severity": "error", "params": {}}]})
    for sid in created:
        ctx.db.log(username, "study.import", "study", sid, {"source": "image"})
    return {"created": created, "rejected": rejected, "studies": [repo.study_detail(ctx, s) for s in created]}


def set_spacing(ctx: AppContext, study_id: int, spacing_mm: Tuple[float, float], username: str) -> None:
    """User-supplied pixel spacing for every slice of a study; measurements are recomputed."""
    if not (spacing_mm[0] > 0 and spacing_mm[1] > 0):
        raise repo.Invalid("spacing_invalid")
    rows = ctx.db.all("SELECT id, warnings_json FROM slices WHERE study_id=?", (study_id,))
    if not rows:
        raise repo.NotFound("study")
    for r in rows:
        warns = [w for w in json.loads(r["warnings_json"]) if w["code"] != "pixel_spacing_unknown"]
        ctx.db.update("slices", "id=?", (r["id"],), {
            "spacing_row": spacing_mm[0], "spacing_col": spacing_mm[1], "spacing_source": "user",
            "warnings_json": json.dumps(warns)})
    from . import analysis  # local import: analysis depends on this module for paths

    for r in rows:
        analysis.recompute_measurements(ctx, r["id"])
    ctx.db.log(username, "study.spacing", "study", study_id, {"row_mm": spacing_mm[0], "col_mm": spacing_mm[1]})
