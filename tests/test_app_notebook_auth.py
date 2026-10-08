from types import SimpleNamespace

import pytest

from route_opt.app_notebook_auth import NotebookAppAuth


def test_notebook_auth_exchanges_audience_scoped_token_and_refreshes():
    calls = []
    now = [0.0]
    workspace = SimpleNamespace(config=SimpleNamespace(host="https://workspace/",
        authenticate=lambda: {"Authorization": "Bearer job-ephemeral-token"}))
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=200, json=lambda: {
            "access_token": f"app-token-{len(calls)}", "expires_in": 120})
    auth = NotebookAppAuth(workspace, "app-client-id", post=post, clock=lambda: now[0])
    assert auth.headers() == {"Authorization": "Bearer app-token-1"}
    assert calls[0][0] == "https://workspace/oidc/v1/token"
    assert calls[0][1]["data"]["audience"] == "app-client-id"
    assert calls[0][1]["data"]["subject_token"] == "job-ephemeral-token"
    assert calls[0][1]["data"]["scope"] == "all-apis"
    assert calls[0][1]["allow_redirects"] is False
    now[0] = 59
    assert auth.headers()["Authorization"] == "Bearer app-token-1"
    now[0] = 61
    assert auth.headers()["Authorization"] == "Bearer app-token-2"


def test_token_exchange_error_exposes_only_status_not_payload():
    workspace = SimpleNamespace(config=SimpleNamespace(host="https://workspace",
        authenticate=lambda: {"Authorization": "Bearer ephemeral"}))
    response = SimpleNamespace(status_code=401, text="sensitive response data")
    auth = NotebookAppAuth(workspace, "app", post=lambda *args, **kwargs: response)
    with pytest.raises(RuntimeError) as exc:
        auth.headers()
    assert str(exc.value) == "Notebook-to-App token exchange failed: HTTP 401."


def test_notebook_auth_requires_app_audience():
    with pytest.raises(ValueError, match="OAuth client ID"):
        NotebookAppAuth(None, "")


def test_exchange_reads_explicit_notebook_context_token():
    calls = []
    workspace = SimpleNamespace(config=SimpleNamespace(host="https://workspace"))
    def post(url, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status_code=200, json=lambda: {"access_token": "app", "expires_in": 300})
    auth = NotebookAppAuth(workspace, "app-id", notebook_token=lambda: "context-ephemeral",
        post=post)
    assert auth.headers() == {"Authorization": "Bearer app"}
    assert calls[0]["data"]["subject_token"] == "context-ephemeral"


def test_exchange_error_diagnostics_classify_without_echoing_tokens():
    workspace = SimpleNamespace(config=SimpleNamespace(host="https://workspace"))
    response = SimpleNamespace(status_code=400, json=lambda: {
        "error": "invalid_request", "error_description": "invalid subject_token_type for secret-example-token"})
    auth = NotebookAppAuth(workspace, "app-id", notebook_token=lambda: "context-ephemeral",
        post=lambda *args, **kwargs: response)
    with pytest.raises(RuntimeError) as exc:
        auth.headers()
    assert 'invalid_request' in str(exc.value)
    assert 'subject token type rejected' in str(exc.value)
    assert 'secret-example-token' not in str(exc.value)
