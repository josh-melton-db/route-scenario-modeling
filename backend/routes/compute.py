from typing import Literal

from fastapi import APIRouter

from ..services.solver_warmup import solver_warmup_service
from ..services.warehouse_warmup import warehouse_warmup_service

router = APIRouter(prefix="/compute", tags=["compute"])


@router.post("/{resource}/ping", status_code=202)
def ping_compute(resource: Literal["sql-warehouse", "route-solver"]) -> dict:
    if resource == "sql-warehouse":
        return warehouse_warmup_service.start()
    return solver_warmup_service.start()
