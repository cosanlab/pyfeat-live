"""/api/live/* — Live page detection + recording."""

from __future__ import annotations

from fastapi import APIRouter


router = APIRouter(prefix="/api/live", tags=["live"])
