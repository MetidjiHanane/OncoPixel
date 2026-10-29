"""Reading PNG/JPG and DICOM into 8-bit grayscale slices.

DICOM data is converted to 8 bits with the window stored in the file (or the 0.5 to 99.5
percentile range when none is present) because the models were trained on 8-bit images. The
conversion is recorded as a warning so the user knows it happened. Only technical tags are
kept; patient identifiers are returned separately and used only when anonymisation is off.
"""
from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np

from ..ml import segmenter as S
from .validation import sequence_warning, validate_pixels, warn, INFO, WARNING

IMAGE_EXT = {".png", ".jpg", ".jpeg"}
DICOM_EXT = {".dcm", ".dicom", ".ima"}


@dataclass
class LoadedSlice:
    gray: np.ndarray
    name: str
    spacing: Optional[Tuple[float, float]] = None
    spacing_source: Optional[str] = None
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    dicom: Dict[str, Any] = field(default_factory=dict)
    sort_key: Tuple = (0,)


@dataclass
class LoadedGroup:
    kind: str  # image | dicom
    slices: List[LoadedSlice]
    patient_hint: Dict[str, Any] = field(default_factory=dict)
    study_date: Optional[str] = None
    plane: str = "unknown"
    description: Optional[str] = None


class ImportRejected(Exception):
    def __init__(self, name: str, warnings: List[Dict[str, Any]]):
        super().__init__(name)
        self.name = name
        self.warnings = warnings


def is_hidden(p: Path) -> bool:
    return p.name.startswith(".") or p.name.startswith("._")


def is_dicom_file(path: Path) -> bool:
    if path.suffix.lower() in DICOM_EXT:
        return True
    if path.suffix.lower() in IMAGE_EXT:
        return False
    try:
        with open(path, "rb") as f:
            f.seek(128)
            return f.read(4) == b"DICM"
    except OSError:
        return False


def discover(paths: Iterable[str]) -> Tuple[List[Path], List[Path]]:
    """Expand files and folders into (image files, dicom files)."""
    images: List[Path] = []
    dicoms: List[Path] = []
    seen = set()

    def add(p: Path) -> None:
        rp = p.resolve()
        if rp in seen or is_hidden(p) or not p.is_file():
            return
        seen.add(rp)
        if p.suffix.lower() in IMAGE_EXT:
            images.append(p)
        # Only PNG and JPG are imported. Other files (including DICOM) are ignored.

    for raw in paths:
        p = Path(raw).expanduser()
        if p.is_dir():
            for root, _dirs, files in os.walk(p):
                for name in sorted(files):
                    add(Path(root) / name)
        else:
            add(p)
    return sorted(images), sorted(dicoms)


# -- PNG / JPG ----------------------------------------------------------------------------------
def _chroma(path: Path) -> Optional[float]:
    from PIL import Image

    try:
        with Image.open(path) as im:
            if im.mode in ("L", "1", "I", "I;16", "F", "LA"):
                return 0.0
            rgb = np.asarray(im.convert("RGB"), dtype=np.int16)
            return float((rgb.max(2) - rgb.min(2)).mean())
    except Exception:
        return None


def load_image_file(path: Path, max_pixels: int, max_file_mb: int) -> LoadedGroup:
    if path.stat().st_size > max_file_mb * 1024 * 1024:
        raise ImportRejected(path.name, [warn("file_too_large", "error", limit_mb=max_file_mb)])
    try:
        gray = S.load_gray_uint8(path)
    except Exception as exc:
        raise ImportRejected(path.name, [warn("cannot_decode", "error", reason=str(exc)[:200])]) from exc
    warns = validate_pixels(gray, _chroma(path), max_pixels)
    if any(w["severity"] == "error" for w in warns):
        raise ImportRejected(path.name, warns)
    sl = LoadedSlice(gray=gray, name=path.name, warnings=warns)
    sl.warnings.append(warn("pixel_spacing_unknown", INFO))
    return LoadedGroup(kind="image", slices=[sl])


# -- DICOM --------------------------------------------------------------------------------------
def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first(value: Any) -> Any:
    try:
        if hasattr(value, "__len__") and not isinstance(value, (str, bytes)):
            return value[0]
    except (IndexError, TypeError):
        return None
    return value


def _to_uint8_windowed(arr: np.ndarray, ds: Any) -> Tuple[np.ndarray, Dict[str, Any]]:
    a = arr.astype(np.float64)
    slope, inter = _num(getattr(ds, "RescaleSlope", 1)) or 1.0, _num(getattr(ds, "RescaleIntercept", 0)) or 0.0
    a = a * slope + inter
    center, width = _num(_first(getattr(ds, "WindowCenter", None))), _num(_first(getattr(ds, "WindowWidth", None)))
    if center is not None and width and width > 1:
        lo, hi, source = center - width / 2.0, center + width / 2.0, "dicom_window"
    else:
        lo, hi = np.percentile(a, [0.5, 99.5])
        source = "percentile_0.5_99.5"
        if hi <= lo:
            lo, hi = float(a.min()), float(a.max()) if a.max() > a.min() else float(a.min()) + 1.0
    out = np.clip((a - lo) / (hi - lo), 0.0, 1.0) * 255.0
    if str(getattr(ds, "PhotometricInterpretation", "")).upper() == "MONOCHROME1":
        out = 255.0 - out
    return np.rint(out).astype(np.uint8), {"window_low": float(lo), "window_high": float(hi), "window_source": source}


def _plane_from_orientation(iop: Any) -> str:
    try:
        v = [float(x) for x in iop]
        row, col = np.array(v[:3]), np.array(v[3:6])
        n = np.abs(np.cross(row, col))
        return ("sagittal", "coronal", "axial")[int(np.argmax(n))]
    except Exception:
        return "unknown"


def _age_years(value: Any) -> Optional[int]:
    if not value:
        return None
    s = str(value)
    try:
        n = int(s[:-1])
    except ValueError:
        return None
    unit = s[-1].upper()
    return n if unit == "Y" else (0 if unit in "MWD" else None)


def _format_dicom_name(value: Any) -> str:
    return str(value or "").replace("^", " ").strip()


def load_dicom_groups(paths: List[Path], anonymize: bool, max_pixels: int, max_file_mb: int
                      ) -> Tuple[List[LoadedGroup], List[Tuple[str, List[Dict[str, Any]]]]]:
    """Group DICOM files by series. Returns (groups, rejected[(name, warnings)])."""
    import pydicom

    by_series: Dict[str, List[Tuple[Path, Any]]] = defaultdict(list)
    rejected: List[Tuple[str, List[Dict[str, Any]]]] = []
    for p in paths:
        try:
            if p.stat().st_size > max_file_mb * 1024 * 1024:
                rejected.append((p.name, [warn("file_too_large", "error", limit_mb=max_file_mb)]))
                continue
            ds = pydicom.dcmread(str(p), force=False)
            if "PixelData" not in ds:
                rejected.append((p.name, [warn("dicom_without_pixel_data", "error")]))
                continue
            by_series[str(getattr(ds, "SeriesInstanceUID", p.parent))].append((p, ds))
        except Exception as exc:
            rejected.append((p.name, [warn("cannot_decode", "error", reason=str(exc)[:200])]))

    groups: List[LoadedGroup] = []
    for _uid, items in by_series.items():
        slices: List[LoadedSlice] = []
        first_ds = items[0][1]
        modality = str(getattr(first_ds, "Modality", "") or "")
        description = str(getattr(first_ds, "SeriesDescription", "") or "") or None
        series_warns: List[Dict[str, Any]] = []
        if modality and modality != "MR":
            for p, _ in items:
                rejected.append((p.name, [warn("dicom_not_mr", "error", modality=modality)]))
            continue
        seq_warn = sequence_warning(description)
        if seq_warn:
            series_warns.append(seq_warn)
        for p, ds in items:
            try:
                arr = ds.pixel_array
            except Exception as exc:
                rejected.append((p.name, [warn("cannot_decode", "error", reason=str(exc)[:200])]))
                continue
            frames: List[np.ndarray]
            if arr.ndim == 2:
                frames = [arr]
            elif arr.ndim == 3 and getattr(ds, "SamplesPerPixel", 1) == 1:
                frames = [arr[i] for i in range(arr.shape[0])]
            elif arr.ndim == 3 and arr.shape[-1] in (3, 4):
                frames = [np.asarray(arr[..., :3]).mean(axis=2)]
            else:
                rejected.append((p.name, [warn("unsupported_dicom_layout", "error", shape=list(arr.shape))]))
                continue
            ps = getattr(ds, "PixelSpacing", None) or getattr(ds, "ImagerPixelSpacing", None)
            spacing = None
            if ps is not None and len(ps) == 2 and _num(ps[0]) and _num(ps[1]):
                spacing = (float(ps[0]), float(ps[1]))
            position = getattr(ds, "ImagePositionPatient", None)
            inst = int(getattr(ds, "InstanceNumber", 0) or 0)
            iop = getattr(ds, "ImageOrientationPatient", None)
            for fi, frame in enumerate(frames):
                gray, win = _to_uint8_windowed(frame, ds)
                warns = validate_pixels(gray, None, max_pixels)
                if any(w["severity"] == "error" for w in warns):
                    rejected.append((p.name, warns))
                    continue
                warns += series_warns
                warns.append(warn("dicom_converted_to_8bit", INFO, **win))
                if spacing is None:
                    warns.append(warn("pixel_spacing_unknown", WARNING))
                else:
                    warns.append(warn("spacing_from_dicom", INFO))
                tech = {
                    "modality": modality, "series_description": description, "instance_number": inst,
                    "slice_thickness": _num(getattr(ds, "SliceThickness", None)),
                    "spacing_between_slices": _num(getattr(ds, "SpacingBetweenSlices", None)),
                    "image_position_patient": [float(x) for x in position] if position is not None else None,
                    "image_orientation_patient": [float(x) for x in iop] if iop is not None else None,
                    "rows": int(gray.shape[0]), "columns": int(gray.shape[1]), **win,
                }
                pos_key = float(position[2]) if position is not None and len(position) == 3 else 0.0
                slices.append(LoadedSlice(
                    gray=gray, name=p.name if len(frames) == 1 else f"{p.name}#{fi + 1}", spacing=spacing,
                    spacing_source="dicom" if spacing else None, warnings=warns, dicom=tech,
                    sort_key=(inst, pos_key, fi),
                ))
        if not slices:
            continue
        slices.sort(key=lambda s: s.sort_key)
        hint: Dict[str, Any] = {}
        if not anonymize:
            hint = {
                "name": _format_dicom_name(getattr(first_ds, "PatientName", "")),
                "code": str(getattr(first_ds, "PatientID", "") or ""),
                "age": _age_years(getattr(first_ds, "PatientAge", None)),
                "sex": {"M": "M", "F": "F", "O": "O"}.get(str(getattr(first_ds, "PatientSex", "")).upper()),
            }
        raw_date = str(getattr(first_ds, "StudyDate", "") or "")
        study_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}" if len(raw_date) == 8 else None
        groups.append(LoadedGroup(
            kind="dicom", slices=slices, patient_hint=hint, study_date=study_date,
            plane=_plane_from_orientation(getattr(first_ds, "ImageOrientationPatient", None)),
            description=description,
        ))
    return groups, rejected
