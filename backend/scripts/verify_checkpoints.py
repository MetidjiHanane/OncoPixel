#!/usr/bin/env python3
"""Verify that your checkpoints match the architectures and run on this machine.

    python scripts/verify_checkpoints.py                       # default folder: <repo>/models
    python scripts/verify_checkpoints.py --classifier PATH --segmenter PATH
    python scripts/verify_checkpoints.py --image slice.png     # also run both models on a real image

What is checked
  classifier  torch.load(weights_only=True) -> keys -> class order -> timm model builds ->
              state dict loads with strict=True -> forward pass (+ flip) -> Grad-CAM
  segmenter   torch.load(weights_only=True) -> config + state_dict -> U-Net builds ->
              state dict loads -> forward pass -> probability map aligned with the input
Exit code 0 only if both models pass. Nothing is uploaded; nothing is written except the report
you ask for with --out.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

GREEN, RED, YELLOW, DIM, END = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def mark(ok: bool) -> str:
    return f"{GREEN}PASS{END}" if ok else f"{RED}FAIL{END}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--classifier", help="path to the classification checkpoint (best.pt)")
    ap.add_argument("--segmenter", help="path to the segmentation checkpoint (tumor_seg_model.pt)")
    ap.add_argument("--device", default="auto", choices=["auto", "mps", "cpu", "cuda"])
    ap.add_argument("--image", help="optional real slice (PNG/JPG) to run both models on")
    ap.add_argument("--out", help="write the full report as JSON to this file")
    args = ap.parse_args()

    from oncopixel import config
    from oncopixel.ml.devices import available_devices
    from oncopixel.ml.registry import ModelRegistry
    from oncopixel.services import selftest

    clf_path = Path(args.classifier).expanduser() if args.classifier else config.default_classifier_path()
    seg_path = Path(args.segmenter).expanduser() if args.segmenter else config.default_segmenter_path()
    settings = {"device": args.device, "classification_checkpoint": str(clf_path), "segmentation_checkpoint": str(seg_path)}
    for var in ("ONCOPIXEL_CLASSIFIER_CKPT", "ONCOPIXEL_SEGMENTER_CKPT"):
        os.environ.pop(var, None)  # the command line wins in this script
    reg = ModelRegistry(lambda: settings)

    print(f"OncoPixel checkpoint verification (application {config.VERSION})")
    print(f"devices: {json.dumps(available_devices())}  ->  using: {reg.device()}")
    print(f"classifier : {clf_path}\nsegmenter  : {seg_path}\n")

    report = selftest.run(reg)
    ok_all = True
    for kind, label in (("classification", "CLASSIFIER"), ("segmentation", "SEGMENTER")):
        r = report[kind]
        print(f"== {label} ==")
        if r["state"] != "ready":
            e = r["error"]
            print(f"  {mark(False)} cannot be used: [{e['code']}] {e['detail']}")
            hint = {
                "file_not_found": "Copy the file to the path above or pass --classifier/--segmenter.",
                "class_order_mismatch": "The classes saved in the checkpoint are not glioma, meningioma, no_tumor, pituitary in that order.",
                "weights_do_not_match_architecture": "The weights belong to a different architecture than the one the notebook builds.",
                "unreadable_checkpoint": "Re-save the checkpoint from the notebook (torch.save of a dict of tensors and plain values).",
            }.get(e["code"])
            if hint:
                print(f"  {DIM}hint: {hint}{END}")
            ok_all = False
            print()
            continue
        info = r["info"]
        print(f"  {mark(True)} loaded: {info['name']}  sha256 {info['sha256'][:16]}...  {info['size_mb']} MB  on {info['device']}")
        if info.get("test_fixture"):
            print(f"  {YELLOW}WARNING: this is an untrained test fixture, not your trained model.{END}")
        for c in r["checks"]:
            print(f"  {mark(c['ok'])} {c['name']}" + (f"  {DIM}({c['detail']}){END}" if c["detail"] else ""))
            ok_all &= c["ok"]
        print(f"  forward pass on a synthetic phantom: {r['forward_ms']} ms\n")

    if args.image and report["classification"]["state"] == "ready" and report["segmentation"]["state"] == "ready":
        from oncopixel.ml import segmenter as S
        from oncopixel.services.measurements import compute_measurements

        gray = S.load_gray_uint8(Path(args.image).expanduser())
        print(f"== REAL IMAGE: {args.image}  ({gray.shape[1]}x{gray.shape[0]}) ==")
        clf, seg = reg.classifier(), reg.segmenter()
        t0 = time.perf_counter()
        out = clf.predict(gray, tta=True)
        print("  classification:", out.label, f"{100 * out.confidence:.1f}%", {k: round(v, 3) for k, v in out.probabilities.items()})
        prob, _ = seg.predict_prob(gray, tta=None)
        res = seg.finalize(prob, gray, None, False)
        m = compute_measurements(gray, res.binary_mask)
        print(f"  segmentation : threshold {res.threshold}, tumor area {m['area_px']} px, components {m.get('n_components', 0)}")
        print(f"  total time (cold, includes first-call overhead): {(time.perf_counter() - t0):.2f} s")
        for _ in range(2):
            t0 = time.perf_counter(); clf.predict(gray); seg.predict_prob(gray, tta=None)
        print(f"  warm run (both models): {(time.perf_counter() - t0):.2f} s  (target: under 10 s)\n")
        report["real_image"] = {"label": out.label, "confidence": out.confidence, "area_px": m["area_px"]}

    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2, default=str))
    ok_all &= report["classification"]["state"] == "ready" and report["segmentation"]["state"] == "ready"
    print(f"{'ALL CHECKS PASSED' if ok_all else 'VERIFICATION FAILED'}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
