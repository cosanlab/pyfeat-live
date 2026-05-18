"""/api/system/* — runtime introspection (compute, etc.)."""

from __future__ import annotations

import os
from typing import Any

import torch
from fastapi import APIRouter


router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/compute")
def compute() -> dict[str, Any]:
    """Report which compute backends are usable on this machine.

    Frontend uses this to populate the Compute picker and disable
    backends that aren't available.
    """
    cpu = {"available": True, "label": f"{os.cpu_count() or 1} cores"}

    mps_available = (
        torch.backends.mps.is_available() and torch.backends.mps.is_built()
    )
    mps = {"available": mps_available}
    if mps_available:
        # PyTorch doesn't expose a friendly MPS model name; we keep it
        # short and let the frontend brand-detect if it wants more.
        mps["label"] = "Apple MPS"

    cuda_available = torch.cuda.is_available()
    cuda: dict[str, Any] = {"available": cuda_available}
    if cuda_available:
        names = [
            torch.cuda.get_device_name(i)
            for i in range(torch.cuda.device_count())
        ]
        cuda["label"] = names[0] if names else "CUDA"
        cuda["devices"] = names

    return {"cpu": cpu, "mps": mps, "cuda": cuda}
