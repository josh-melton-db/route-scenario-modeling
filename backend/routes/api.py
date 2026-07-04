from __future__ import annotations

from fastapi import APIRouter

from .baseline import router as baseline_router
from .meta import router as meta_router
from .results import router as results_router
from .runs import router as runs_router
from .scenarios import router as scenarios_router

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


router.include_router(meta_router)
router.include_router(baseline_router)
router.include_router(scenarios_router)
router.include_router(results_router)
router.include_router(runs_router)
