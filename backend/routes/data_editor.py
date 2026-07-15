"""Authenticated API surface for the session-isolated planning-data editor."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Query, Request

from ..config import get_data_backend
from ..models import (
    EditorCommitResponse,
    EditorDeleteRequest,
    EditorEntityType,
    EditorInsertRequest,
    EditorPage,
    EditorPatchRequest,
    EditorPreviewRequest,
    EditorPreviewResponse,
    EditorRow,
    EditorSession,
    EditorValidationResponse,
)
from ..services.ground_truth_store import ground_truth_store

router = APIRouter(prefix="/data-editor", tags=["data-editor"])


def _principal(request: Request) -> str:
    """Use a reverse-proxy identity, never a browser-supplied session owner."""
    for header in ("x-forwarded-email", "x-forwarded-user", "x-databricks-user"):
        value = request.headers.get(header, "").strip()
        if value:
            return value

    # Local direct development does not traverse the Databricks Apps proxy.
    # Production always has DATABRICKS_APP_PORT and must provide a proxy identity.
    if not os.getenv("DATABRICKS_APP_PORT", "").strip():
        return os.getenv("DATA_EDITOR_LOCAL_PRINCIPAL", "local-dev").strip() or "local-dev"
    raise HTTPException(status_code=401, detail="Authenticated Databricks user identity is required.")


def _require_lakebase() -> None:
    if get_data_backend() != "lakebase":
        raise HTTPException(
            status_code=503,
            detail="The Data editor is available only when DATA_BACKEND=lakebase.",
        )


@router.post("/sessions", response_model=EditorSession)
async def open_editor_session(request: Request) -> EditorSession:
    _require_lakebase()
    return ground_truth_store.open_session(_principal(request))


@router.get("/sessions/{session_id}", response_model=EditorSession)
async def editor_session(session_id: str, request: Request) -> EditorSession:
    _require_lakebase()
    return ground_truth_store.get_session(session_id, _principal(request))


@router.get("/sessions/{session_id}/rows/{entity_type}", response_model=EditorPage)
async def editor_rows(
    session_id: str,
    entity_type: EditorEntityType,
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> EditorPage:
    _require_lakebase()
    return ground_truth_store.list_rows(
        session_id,
        _principal(request),
        entity_type,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/sessions/{session_id}/rows/{entity_type}",
    response_model=EditorRow,
)
async def insert_editor_row(
    session_id: str,
    entity_type: EditorEntityType,
    payload: EditorInsertRequest,
    request: Request,
) -> EditorRow:
    _require_lakebase()
    return ground_truth_store.insert_row(
        session_id,
        _principal(request),
        entity_type,
        payload,
    )


@router.patch(
    "/sessions/{session_id}/rows/{entity_type}/{row_id}",
    response_model=EditorRow,
)
async def patch_editor_row(
    session_id: str,
    entity_type: EditorEntityType,
    row_id: str,
    payload: EditorPatchRequest,
    request: Request,
) -> EditorRow:
    _require_lakebase()
    return ground_truth_store.patch_row(
        session_id,
        _principal(request),
        entity_type,
        row_id,
        payload,
    )


@router.delete(
    "/sessions/{session_id}/rows/{entity_type}/{row_id}",
    response_model=EditorSession,
)
async def delete_editor_row(
    session_id: str,
    entity_type: EditorEntityType,
    row_id: str,
    payload: EditorDeleteRequest,
    request: Request,
) -> EditorSession:
    _require_lakebase()
    return ground_truth_store.delete_row(
        session_id,
        _principal(request),
        entity_type,
        row_id,
        payload,
    )


@router.post(
    "/sessions/{session_id}/validate",
    response_model=EditorValidationResponse,
)
async def validate_editor_session(
    session_id: str,
    request: Request,
) -> EditorValidationResponse:
    _require_lakebase()
    return ground_truth_store.validate_session(session_id, _principal(request))


@router.post(
    "/sessions/{session_id}/preview",
    response_model=EditorPreviewResponse,
)
async def preview_editor_baseline(
    session_id: str,
    payload: EditorPreviewRequest,
    request: Request,
) -> EditorPreviewResponse:
    _require_lakebase()
    return ground_truth_store.preview_baseline(session_id, _principal(request), payload)


@router.post(
    "/sessions/{session_id}/commit",
    response_model=EditorCommitResponse,
)
async def commit_editor_session(
    session_id: str,
    request: Request,
) -> EditorCommitResponse:
    _require_lakebase()
    return ground_truth_store.commit_session(session_id, _principal(request))


@router.post(
    "/sessions/{session_id}/discard",
    response_model=EditorSession,
)
async def discard_editor_session(
    session_id: str,
    request: Request,
) -> EditorSession:
    _require_lakebase()
    return ground_truth_store.discard_session(session_id, _principal(request))
