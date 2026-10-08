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
                 post: Callable[..., Any] = requests.post,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if not app_client_id:
            raise ValueError("The App must expose an OAuth client ID for notebook authentication.")
        self.workspace = workspace
        self.app_client_id = app_client_id
        self.post = post
        self.clock = clock
        self._token: str | None = None
        self._refresh_at = 0.0

    def headers(self) -> dict[str, str]:
        if self._token is None or self.clock() >= self._refresh_at:
            native = self.workspace.config.authenticate().get("Authorization", "")
            if not native.lower().startswith("bearer ") or not native[7:].strip():
                raise RuntimeError("Notebook authentication did not provide a bearer token.")
            response = self.post(
                f"{self.workspace.config.host.rstrip('/')}/oidc/v1/token",
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                    "subject_token": native[7:].strip(),
                    "subject_token_type": "urn:databricks:params:oauth:token-type:personal-access-token",
                    "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
                    "scope": "all-apis",
                    "audience": self.app_client_id,
                }, timeout=30, allow_redirects=False,
            )
            if response.status_code != 200:
                # Never echo response payloads: OAuth errors can contain credentials.
                raise RuntimeError(f"Notebook-to-App token exchange failed: HTTP {response.status_code}.")
            payload = response.json()
            token = payload.get("access_token")
            if not isinstance(token, str) or not token:
                raise RuntimeError("Notebook-to-App token exchange returned no access token.")
            lifetime = max(1, int(payload.get("expires_in", 300)))
            self._token = token
            self._refresh_at = self.clock() + max(1, lifetime - min(60, lifetime / 2))
        return {"Authorization": f"Bearer {self._token}"}
