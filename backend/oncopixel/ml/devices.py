"""Device selection for Apple Silicon (MPS), CUDA and CPU."""
from __future__ import annotations

import os
from typing import Dict

# Allow unsupported MPS operators to fall back to the CPU instead of raising.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")


def available_devices() -> Dict[str, bool]:
    import torch

    mps = bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
    return {"cpu": True, "mps": mps, "cuda": bool(torch.cuda.is_available())}


def resolve_device(preference: str = "auto") -> str:
    avail = available_devices()
    if preference in ("mps", "cuda", "cpu"):
        return preference if avail.get(preference) else "cpu"
    if avail["mps"]:
        return "mps"
    if avail["cuda"]:
        return "cuda"
    return "cpu"
