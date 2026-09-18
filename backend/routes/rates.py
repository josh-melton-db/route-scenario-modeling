from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query, Response, status

from ..models import (
    RateAuthoringOptions,
    RateContractCreateRequest,
    RateContractDetail,
    RateContractSummary,
    RateDraftUpdateRequest,
    RatePublishRequest,
    RateQuote,
    RateQuoteRequest,
    RateValidationResponse,
    RateVersionCreateRequest,
)
from ..services.rates import (
    create_rate_contract,
    create_rate_version,
    discard_rate_draft,
    get_rate_contract_detail,
    list_rate_authoring_options,
    list_rate_contract_summaries,
    publish_rate_draft,
    preview_rate_quote,
    save_rate_draft,
    validate_rate_draft,
)
from ..services.store_provider import get_store

router = APIRouter(prefix="/rates", tags=["rates"])


@router.get("/authoring-options", response_model=RateAuthoringOptions)
async def rate_authoring_options() -> RateAuthoringOptions:
    return list_rate_authoring_options(get_store())


@router.get("/contracts", response_model=list[RateContractSummary])
async def rate_contracts(
    service_date: str = Query(default_factory=lambda: date.today().isoformat()),
) -> list[RateContractSummary]:
    return list_rate_contract_summaries(get_store(), service_date)


@router.post(
    "/contracts",
    response_model=RateContractDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_contract(payload: RateContractCreateRequest) -> RateContractDetail:
    return create_rate_contract(get_store(), payload)


@router.get(
    "/contracts/{contract_id}/versions/{version_id}",
    response_model=RateContractDetail,
)
async def rate_contract_detail(
    contract_id: str, version_id: str
) -> RateContractDetail:
    return get_rate_contract_detail(get_store(), contract_id, version_id)


@router.post(
    "/contracts/{contract_id}/versions",
    response_model=RateContractDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_contract_version(
    contract_id: str, payload: RateVersionCreateRequest
) -> RateContractDetail:
    return create_rate_version(get_store(), contract_id, payload)


@router.put(
    "/contracts/{contract_id}/versions/{version_id}",
    response_model=RateContractDetail,
)
async def update_contract_draft(
    contract_id: str, version_id: str, payload: RateDraftUpdateRequest
) -> RateContractDetail:
    return save_rate_draft(get_store(), contract_id, version_id, payload)


@router.post(
    "/contracts/{contract_id}/versions/{version_id}/validate",
    response_model=RateValidationResponse,
)
async def validate_contract_draft(
    contract_id: str, version_id: str
) -> RateValidationResponse:
    return validate_rate_draft(get_store(), contract_id, version_id)


@router.post(
    "/contracts/{contract_id}/versions/{version_id}/publish",
    response_model=RateContractDetail,
)
async def publish_contract_draft(
    contract_id: str, version_id: str, payload: RatePublishRequest
) -> RateContractDetail:
    return publish_rate_draft(get_store(), contract_id, version_id, payload)


@router.delete(
    "/contracts/{contract_id}/versions/{version_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_contract_draft(contract_id: str, version_id: str) -> Response:
    discard_rate_draft(get_store(), contract_id, version_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/quote", response_model=RateQuote)
async def quote_rate(payload: RateQuoteRequest) -> RateQuote:
    return preview_rate_quote(get_store(), payload)
