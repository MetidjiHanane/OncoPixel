"""Mask exports: PNG, NIfTI, DICOM-SEG, and the DICOM SR measurement report."""
from __future__ import annotations

import datetime as dt
import io
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from .. import config
from ..context import AppContext
from ..services import analysis, repo
from ..services.media import png_bytes


class ExportError(ValueError):
    pass


def _mask(ctx: AppContext, slice_id: int) -> np.ndarray:
    m = analysis.load_mask(ctx, slice_id)
    if m is None:
        raise repo.NotFound("segmentation")
    return m


def mask_png(ctx: AppContext, slice_id: int) -> bytes:
    return png_bytes(_mask(ctx, slice_id) * 255)


def nifti(ctx: AppContext, slice_id: int) -> bytes:
    """Gzipped NIfTI-1 of the 2D mask. Voxel i = image column, j = image row (not flipped), k = 1.

    The affine only carries the pixel spacing (1 mm when unknown). There is no orientation
    information for a single exported slice, so the spatial codes are set to "unknown".
    """
    import nibabel as nib

    row = repo.get_slice_row(ctx, slice_id)
    m = _mask(ctx, slice_id)
    sr, sc = (row["spacing_row"], row["spacing_col"]) if row["spacing_row"] else (1.0, 1.0)
    thickness = 1.0
    d = analysis.slice_results(ctx, slice_id)["slice"]["dicom"] or {}
    if d.get("slice_thickness"):
        thickness = float(d["slice_thickness"])
    arr = np.ascontiguousarray(m.T[:, :, None].astype(np.uint8))
    affine = np.diag([sc, sr, thickness, 1.0])
    img = nib.Nifti1Image(arr, affine)
    img.set_sform(affine, code=0)
    img.set_qform(affine, code=0)
    img.header.set_xyzt_units("mm")
    img.header["descrip"] = b"OncoPixel 2D tumor mask; orientation unknown"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "mask.nii.gz"
        nib.save(img, str(p))
        return p.read_bytes()


# -- DICOM ---------------------------------------------------------------------------------------
def _uid() -> str:
    from pydicom.uid import generate_uid

    return generate_uid()  # pydicom's default root; OncoPixel has no registered UID root


def _dicom_name(name: str) -> str:
    parts = name.strip().split()
    if len(parts) >= 2:
        return f"{parts[-1]}^{' '.join(parts[:-1])}"
    return name.strip()


def _source_dataset(ctx: AppContext, study: Dict[str, Any], slice_id: int, anonymize: bool):
    """Secondary Capture rendition of the 8-bit slice, used as the referenced source image."""
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage

    srow = repo.get_slice_row(ctx, slice_id)
    gray = analysis.load_gray(ctx, slice_id)
    now = dt.datetime.now()
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = _uid()
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    p = study.get("patient") or {}
    if anonymize or not p or p.get("anonymized"):
        ds.PatientName, ds.PatientID, ds.PatientBirthDate, ds.PatientSex = "ANONYMOUS^", study["code"], "", ""
    else:
        ds.PatientName, ds.PatientID = _dicom_name(p["name"]), p["code"]
        ds.PatientBirthDate = ""
        ds.PatientSex = p.get("sex") if p.get("sex") in ("M", "F", "O") else ""
        if p.get("age") is not None:
            ds.PatientAge = f"{int(p['age']):03d}Y"
    ds.StudyInstanceUID, ds.SeriesInstanceUID = _uid(), _uid()
    sd = (study.get("study_date") or now.date().isoformat()).replace("-", "")
    ds.StudyDate, ds.StudyTime, ds.StudyID, ds.AccessionNumber = sd, "", study["code"][-16:], ""
    ds.ReferringPhysicianName = "" if anonymize else _dicom_name(p.get("referring_physician", "")) if p else ""
    ds.Modality, ds.ConversionType = "OT", "WSD"
    ds.SeriesNumber, ds.InstanceNumber = 1, srow["idx"] + 1
    ds.Manufacturer, ds.ManufacturerModelName, ds.SoftwareVersions = config.APP_NAME, config.APP_NAME, config.VERSION
    ds.SeriesDescription = "OncoPixel 8-bit rendition of the analysed slice"
    ds.ImageType = ["DERIVED", "SECONDARY"]
    ds.Rows, ds.Columns = int(gray.shape[0]), int(gray.shape[1])
    ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
    ds.BitsAllocated = ds.BitsStored = 8
    ds.HighBit, ds.PixelRepresentation = 7, 0
    if srow["spacing_row"]:
        ds.PixelSpacing = [float(srow["spacing_row"]), float(srow["spacing_col"])]
    ds.PixelData = gray.tobytes()
    ds["PixelData"].VR = "OB"
    ds.is_little_endian, ds.is_implicit_VR = True, False
    return ds


def _dcm_bytes(ds) -> bytes:
    buf = io.BytesIO()
    ds.save_as(buf, enforce_file_format=True)
    return buf.getvalue()


def dicom_seg_zip(ctx: AppContext, study_id: int, slice_id: int, anonymize: bool) -> bytes:
    """Zip with ``source.dcm`` (the referenced image) and ``seg.dcm`` (DICOM-SEG, binary, one segment)."""
    from highdicom import AlgorithmIdentificationSequence
    from highdicom.seg import (Segmentation, SegmentAlgorithmTypeValues, SegmentationTypeValues, SegmentDescription)
    from pydicom.sr.codedict import codes

    m = _mask(ctx, slice_id)
    if not m.any():
        raise ExportError("mask_empty")
    study = repo.study_detail(ctx, study_id)
    src = _source_dataset(ctx, study, slice_id, anonymize)
    seg_info = analysis.segmentation_dict(ctx, slice_id)
    algo = AlgorithmIdentificationSequence(
        name=seg_info["model"]["name"], version=(seg_info["model"].get("sha256") or "")[:12] or config.VERSION,
        family=codes.cid7162.ArtificialIntelligence)
    desc = SegmentDescription(
        segment_number=1, segment_label="Tumor", segmented_property_category=codes.SCT.MorphologicallyAbnormalStructure,
        segmented_property_type=codes.SCT.Neoplasm,
        algorithm_type=(SegmentAlgorithmTypeValues.SEMIAUTOMATIC if seg_info["edited"] else SegmentAlgorithmTypeValues.AUTOMATIC),
        algorithm_identification=algo)
    seg = Segmentation(
        source_images=[src], pixel_array=m.astype(bool)[None], segmentation_type=SegmentationTypeValues.BINARY,
        segment_descriptions=[desc], series_instance_uid=_uid(), series_number=2, sop_instance_uid=_uid(), instance_number=1,
        manufacturer=config.APP_NAME, manufacturer_model_name=config.APP_NAME, software_versions=config.VERSION,
        device_serial_number="0", series_description="OncoPixel tumor mask")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("source.dcm", _dcm_bytes(src))
        z.writestr("seg.dcm", _dcm_bytes(seg))
        z.writestr("README.txt", "source.dcm is an 8-bit Secondary Capture rendition of the analysed slice, not the original DICOM.\n"
                                 "seg.dcm is a binary DICOM-SEG that references it. Research use only.\n")
    return out.getvalue()


def dicom_sr_zip(ctx: AppContext, study_id: int, slice_id: int, anonymize: bool, lang: str = "en") -> bytes:
    """Enhanced SR with the classification result, the measurements and the research disclaimer."""
    from highdicom.sr import CodedConcept, ContainerContentItem, EnhancedSR, NumContentItem, RelationshipTypeValues, TextContentItem
    from highdicom.sr.value_types import ContentSequence

    from .strings import tr

    s = tr(lang)
    study = repo.study_detail(ctx, study_id)
    src = _source_dataset(ctx, study, slice_id, anonymize)
    res = analysis.slice_results(ctx, slice_id)
    cls, meas = res["classification"], res["measurements"]
    C = lambda code, meaning: CodedConcept(code, "99ONCOPIXEL", meaning)  # noqa: E731
    items: List[Any] = [TextContentItem(C("disclaimer", "Disclaimer"), s["disclaimer"], relationship_type=RelationshipTypeValues.CONTAINS)]
    if cls:
        items.append(TextContentItem(C("class", "Predicted class"), s["labels"].get(cls["label"], cls["label"]), relationship_type=RelationshipTypeValues.CONTAINS))
        items.append(NumContentItem(C("conf", "Model confidence estimate (not a calibrated probability)"), round(cls["confidence"] * 100, 2),
                                    CodedConcept("%", "UCUM", "percent"), relationship_type=RelationshipTypeValues.CONTAINS))
    if meas and meas.get("tumor_detected"):
        mm = meas.get("units") == "mm"
        u1 = CodedConcept("mm", "UCUM", "millimeter") if mm else CodedConcept("{px}", "UCUM", "pixels")
        u2 = CodedConcept("mm2", "UCUM", "square millimeter") if mm else CodedConcept("{px}2", "UCUM", "square pixels")
        pick = lambda base: meas.get(f"{base}_mm" if mm else f"{base}_px")  # noqa: E731
        spec = [("area", "Tumor area", meas.get("area_mm2") if mm else meas.get("area_px"), u2),
                ("maxd", "Maximum diameter", pick("max_diameter"), u1), ("mind", "Minimum diameter", pick("min_diameter"), u1),
                ("perim", "Perimeter", pick("perimeter"), u1)]
        for code, meaning, value, unit in spec:
            if value is not None:
                items.append(NumContentItem(C(code, meaning), round(float(value), 3), unit, relationship_type=RelationshipTypeValues.CONTAINS))
        if meas.get("circularity") is not None:
            items.append(NumContentItem(C("circ", "Circularity"), round(float(meas["circularity"]), 4),
                                        CodedConcept("1", "UCUM", "no units"), relationship_type=RelationshipTypeValues.CONTAINS))
    root = ContainerContentItem(name=C("report", "OncoPixel research report"))
    root.ContentSequence = ContentSequence(items)
    sr = EnhancedSR(
        evidence=[src], content=root, series_instance_uid=_uid(), series_number=3, sop_instance_uid=_uid(),
        instance_number=1, manufacturer=config.APP_NAME, is_complete=False, is_final=False, series_description="OncoPixel research report")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("source.dcm", _dcm_bytes(src))
        z.writestr("report_sr.dcm", _dcm_bytes(sr))
    return out.getvalue()
