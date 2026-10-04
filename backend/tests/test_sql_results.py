from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from backend.services import sql


def execution(result, *, count=2, chunks=2, error=None):
    from databricks.sdk.service.sql import StatementState
    return NS(
        statement_id="S", result=result,
        manifest=NS(schema=NS(columns=[NS(name="units", type_name="BIGINT")]),
                    total_row_count=count, total_chunk_count=chunks, truncated=False),
        status=NS(state=StatementState.FAILED if error else StatementState.SUCCEEDED, error=error),
    )


def test_inline_reader_fetches_every_chunk():
    first = execution(NS(data_array=[["1"]], external_links=[]))
    client = NS(statement_execution=NS(get_statement_result_chunk_n=Mock(
        return_value=NS(data_array=[["2"]], external_links=[])
    )))
    assert sql._read_results(client, first) == [{"units": 1}, {"units": 2}]


def test_large_select_retries_with_signed_chunks_without_credentials(monkeypatch):
    from databricks.sdk.service.sql import Disposition, Format
    link = NS(chunk_index=0, external_link="https://storage.example/result", row_count=2)
    service = NS(execute_statement=Mock(side_effect=[
        execution(None, error="Inline byte limit exceeded"),
        execution(NS(external_links=[link]), chunks=1),
    ]))
    monkeypatch.setattr(sql, "get_workspace_client", lambda: NS(statement_execution=service))
    monkeypatch.setattr(sql, "resolve_sql_warehouse_id", lambda: "W")
    download = Mock(return_value=NS(raise_for_status=lambda: None, json=lambda: [["1"], ["2"]]))
    monkeypatch.setattr(sql.httpx, "get", download)
    assert sql.execute_sql("SELECT * FROM network") == [{"units": 1}, {"units": 2}]
    assert service.execute_statement.call_args.kwargs["format"] == Format.JSON_ARRAY
    assert service.execute_statement.call_args.kwargs["disposition"] == Disposition.EXTERNAL_LINKS
    download.assert_called_once_with(link.external_link, timeout=60)


def test_reader_rejects_incomplete_results():
    first = execution(NS(data_array=[["1"]]), chunks=1)
    with pytest.raises(HTTPException, match="row count mismatch"):
        sql._read_results(NS(), first)


def test_mutation_is_never_reexecuted(monkeypatch):
    service = NS(execute_statement=Mock(return_value=execution(None, error="secret_catalog.private_table failed")))
    monkeypatch.setattr(sql, "get_workspace_client", lambda: NS(statement_execution=service))
    monkeypatch.setattr(sql, "resolve_sql_warehouse_id", lambda: "W")
    with pytest.raises(HTTPException) as raised:
        sql.execute_sql("INSERT INTO network SELECT * FROM other")
    assert raised.value.detail == "The analytics query could not be completed."
    assert "secret_catalog" not in raised.value.detail
    assert service.execute_statement.call_count == 1


@pytest.mark.parametrize(
    "url,in_app,allowed",
    [
        ("http://storage-proxy.databricks.com/result", True, True),
        ("http://storage-proxy.databricks.com/result", False, False),
        ("http://other.example/result", True, False),
        ("http://storage-proxy.databricks.com:8080/result", True, False),
    ],
)
def test_http_links_are_limited_to_the_app_storage_proxy(monkeypatch, url, in_app, allowed):
    if in_app:
        monkeypatch.setenv("DATABRICKS_APP_NAME", "demo")
    else:
        monkeypatch.delenv("DATABRICKS_APP_NAME", raising=False)
    download = Mock(return_value=NS(raise_for_status=lambda: None, json=lambda: [["1"], ["2"]]))
    monkeypatch.setattr(sql.httpx, "get", download)
    result = execution(NS(external_links=[NS(chunk_index=0, external_link=url, row_count=2)]), chunks=1)
    if allowed:
        assert sql._read_results(NS(), result) == [{"units": 1}, {"units": 2}]
        download.assert_called_once_with(url, timeout=60)
    else:
        with pytest.raises(HTTPException, match="requires HTTPS"):
            sql._read_results(NS(), result)
        download.assert_not_called()
