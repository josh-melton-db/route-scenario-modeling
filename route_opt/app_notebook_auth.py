"""Audience-scoped OAuth for notebook calls to a Databricks App API."""
from __future__ import annotations

import time
from typing import Any, Callable

import requests


class NotebookAppAuth:
    """Exchange the job identity's ephemeral notebook token; cache only in memory.

    Native notebook tokens authenticate workspace APIs but not an App ingress.
    Databricks requires the App OAuth client ID as the token audience:
    https://docs.databricks.com/aws/en/dev-tools/databricks-apps/connect-local
    """

    def __init__(self, workspace: Any, app_client_id: str, *,
                 notebook_token: Callable[[], str] | None = None,
                 post: Callable[..., Any] = requests.post,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if not app_client_id:
            raise ValueError("The App must expose an OAuth client ID for notebook authentication.")
        self.workspace = workspace
        self.app_client_id = app_client_id
        self.notebook_token = notebook_token
        self.post = post
        self.clock = clock
        self._token: str | None = None
        self._refresh_at = 0.0

    def headers(self) -> dict[str, str]:
        if self._token is None or self.clock() >= self._refresh_at:
            if self.notebook_token:
                subject_token = self.notebook_token()
            else:
                native = self.workspace.config.authenticate().get("Authorization", "")
                subject_token = native[7:].strip() if native.lower().startswith("bearer ") else ""
            if not subject_token:
                raise RuntimeError("Notebook authentication did not provide a bearer token.")
            response = self.post(
                f"{self.workspace.config.host.rstrip('/')}/oidc/v1/token",
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                    "subject_token": subject_token,
                    "subject_token_type": "urn:databricks:params:oauth:token-type:personal-access-token",
                    "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
                    "scope": "all-apis",
                    "audience": self.app_client_id,
                }, timeout=30, allow_redirects=False,
            )
            if response.status_code != 200:
                # Never echo raw responses: OAuth error descriptions may contain credentials.
                detail = _safe_exchange_error(response)
                raise RuntimeError(f"Notebook-to-App token exchange failed: HTTP {response.status_code}.{detail}")
            payload = response.json()
            token = payload.get("access_token")
            if not isinstance(token, str) or not token:
                raise RuntimeError("Notebook-to-App token exchange returned no access token.")
            lifetime = max(1, int(payload.get("expires_in", 300)))
            self._token = token
            self._refresh_at = self.clock() + max(1, lifetime - min(60, lifetime / 2))
        return {"Authorization": f"Bearer {self._token}"}


def _safe_exchange_error(response: Any) -> str:
    try:
        payload = response.json()
        code = str(payload.get("errorCode", payload.get("error", payload.get("error_code", ""))))
        known_codes = {
            "invalid_request", "invalid_grant", "invalid_scope", "invalid_target", "invalid_client",
            "unauthorized_client", "unsupported_grant_type", "unsupported_token_type", "access_denied",
            "INVALID_PARAMETER_VALUE", "PERMISSION_DENIED", "UNAUTHENTICATED", "BAD_REQUEST",
        }
        safe_code = code if code in known_codes else "unclassified_oauth_error"
        message = str(payload.get("error_description", payload.get("errorSummary", payload.get("message", "")))).lower()
        categories = (
            (("audience", "target"), "app audience rejected"),
            (("subject_token_type", "subject token type", "token-type"), "subject token type rejected"),
            (("scope",), "requested scope rejected"),
            (("expired",), "notebook credential expired"),
            (("token exchange", "exchange"), "token exchange rejected"),
            (("permission", "not authorized", "unauthorized"), "identity not authorized"),
            (("token",), "notebook credential rejected"),
        )
        category = next((label for words, label in categories if any(word in message for word in words)), "no recognized error category")
        return f" OAuth code: {safe_code}; category: {category}."
    except Exception:
        return ""
