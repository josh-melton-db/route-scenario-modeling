from __future__ import annotations

import json
import threading
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from ..config import get_data_backend
from .lakebase_store import lakebase_store
from .network_overview import NetworkRows


@dataclass(frozen=True)
class BaselineRevision:
    revision_id: str
    source_revision_id: str | None
    run_id: str | None
    accepted_at: str | None
    rows: NetworkRows

    def copy(self) -> "BaselineRevision":
        return BaselineRevision(
            revision_id=self.revision_id,
            source_revision_id=self.source_revision_id,
            run_id=self.run_id,
            accepted_at=self.accepted_at,
            rows=deepcopy(self.rows),
        )


@dataclass(frozen=True)
class BaselineProposalRecord:
    proposal_id: str
    run_id: str
    source_revision_id: str
    proposed_revision: BaselineRevision
    status: str = "proposed"


class BaselineRepository:
    """Immutable revision store with a lazy Lakebase path and local fallback."""

    OPTION_ROW_KEYS = (
        "dim_regions",
        "dim_facilities",
        "demand_plan_versions",
        "capacity_plan_versions",
        "baseline_revision_metadata",
    )

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._revisions: dict[str, BaselineRevision] = {}
        self._proposals: dict[str, BaselineProposalRecord] = {}
        self._original_id: str | None = None
        self._active_id: str | None = None
        self._lakebase_ready = False

    @property
    def uses_lakebase(self) -> bool:
        return get_data_backend() == "lakebase"

    def _table(self, name: str) -> str:
        return lakebase_store.postgres.qualified_table(name)

    def _ensure_lakebase(self) -> None:
        if not self.uses_lakebase or self._lakebase_ready:
            return
        with self._lock:
            if self._lakebase_ready:
                return
            lakebase_store.postgres.execute(
                f"""CREATE TABLE IF NOT EXISTS {self._table('network_baseline_state')} (
                  singleton_key TEXT PRIMARY KEY,
                  original_revision_id TEXT NOT NULL,
                  active_revision_id TEXT NOT NULL
                )"""
            )
            lakebase_store.postgres.execute(
                f"""CREATE TABLE IF NOT EXISTS {self._table('network_baseline_revisions')} (
                  revision_id TEXT PRIMARY KEY,
                  source_revision_id TEXT,
                  run_id TEXT,
                  accepted_at TEXT,
                  rows_payload JSONB NOT NULL
                )"""
            )
            lakebase_store.postgres.execute(
                f"""CREATE TABLE IF NOT EXISTS {self._table('network_baseline_option_revisions')} (
                  revision_id TEXT PRIMARY KEY,
                  option_payload JSONB NOT NULL
                )"""
            )
            lakebase_store.postgres.execute(
                f"""CREATE TABLE IF NOT EXISTS {self._table('network_baseline_proposals')} (
                  proposal_id TEXT PRIMARY KEY,
                  run_id TEXT NOT NULL,
                  source_revision_id TEXT NOT NULL,
                  proposed_revision_id TEXT NOT NULL,
                  status TEXT NOT NULL
                )"""
            )
            self._lakebase_ready = True

    def is_initialized(self) -> bool:
        """Cheap pointer check; never materializes or copies revision payloads."""
        self._ensure_lakebase()
        if not self.uses_lakebase:
            with self._lock:
                return self._original_id is not None and self._active_id is not None
        return lakebase_store.postgres.query_one(
            f"SELECT singleton_key FROM {self._table('network_baseline_state')} WHERE singleton_key = %s",
            ("network",),
        ) is not None

    @staticmethod
    def _revision(row: dict[str, Any]) -> BaselineRevision:
        payload = row["rows_payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return BaselineRevision(
            revision_id=str(row["revision_id"]),
            source_revision_id=row.get("source_revision_id"),
            run_id=row.get("run_id"),
            accepted_at=row.get("accepted_at"),
            rows=payload,
        )

    @classmethod
    def _option_payload(cls, rows: NetworkRows) -> NetworkRows:
        return {key: deepcopy(rows[key]) for key in cls.OPTION_ROW_KEYS if key in rows}

    def seed(self, revision: BaselineRevision) -> None:
        self._ensure_lakebase()
        if not self.uses_lakebase:
            with self._lock:
                if self._original_id is None:
                    self._revisions[revision.revision_id] = revision.copy()
                    self._original_id = self._active_id = revision.revision_id
            return
        with lakebase_store.postgres.transaction() as connection:
            state = lakebase_store.postgres.query_one(
                f"SELECT * FROM {self._table('network_baseline_state')} WHERE singleton_key = %s",
                ("network",), connection=connection,
            )
            if state is not None:
                return
            lakebase_store.postgres.execute(
                f"INSERT INTO {self._table('network_baseline_revisions')} VALUES (%s,%s,%s,%s,%s)",
                (revision.revision_id, None, None, None, lakebase_store.postgres.jsonb(revision.rows)),
                connection=connection,
            )
            lakebase_store.postgres.execute(
                f"INSERT INTO {self._table('network_baseline_option_revisions')} VALUES (%s,%s)",
                (
                    revision.revision_id,
                    lakebase_store.postgres.jsonb(self._option_payload(revision.rows)),
                ),
                connection=connection,
            )
            lakebase_store.postgres.execute(
                f"INSERT INTO {self._table('network_baseline_state')} VALUES (%s,%s,%s)",
                ("network", revision.revision_id, revision.revision_id), connection=connection,
            )

    def replace_original(self, revision: BaselineRevision) -> None:
        """Atomically replace all revision history with a refreshed canonical seed."""
        self._ensure_lakebase()
        if not self.uses_lakebase:
            with self._lock:
                self._revisions = {revision.revision_id: revision.copy()}
                self._proposals.clear()
                self._original_id = self._active_id = revision.revision_id
            return
        with lakebase_store.postgres.transaction() as connection:
            lakebase_store.postgres.execute(
                f"DELETE FROM {self._table('network_baseline_proposals')}", connection=connection
            )
            lakebase_store.postgres.execute(
                f"DELETE FROM {self._table('network_baseline_option_revisions')}", connection=connection
            )
            lakebase_store.postgres.execute(
                f"DELETE FROM {self._table('network_baseline_revisions')}", connection=connection
            )
            lakebase_store.postgres.execute(
                f"INSERT INTO {self._table('network_baseline_revisions')} VALUES (%s,%s,%s,%s,%s)",
                (revision.revision_id, None, None, None, lakebase_store.postgres.jsonb(revision.rows)),
                connection=connection,
            )
            lakebase_store.postgres.execute(
                f"INSERT INTO {self._table('network_baseline_option_revisions')} VALUES (%s,%s)",
                (revision.revision_id, lakebase_store.postgres.jsonb(self._option_payload(revision.rows))),
                connection=connection,
            )
            lakebase_store.postgres.execute(
                f"""INSERT INTO {self._table('network_baseline_state')}
                    (singleton_key, original_revision_id, active_revision_id) VALUES (%s,%s,%s)
                    ON CONFLICT (singleton_key) DO UPDATE SET
                      original_revision_id = EXCLUDED.original_revision_id,
                      active_revision_id = EXCLUDED.active_revision_id""",
                ("network", revision.revision_id, revision.revision_id), connection=connection,
            )

    def ids(self) -> tuple[str, str]:
        self._ensure_lakebase()
        if not self.uses_lakebase:
            assert self._original_id and self._active_id
            return self._original_id, self._active_id
        row = lakebase_store.postgres.query_one(
            f"SELECT * FROM {self._table('network_baseline_state')} WHERE singleton_key = %s",
            ("network",),
        )
        if row is None:
            raise RuntimeError("Baseline state has not been seeded.")
        return str(row["original_revision_id"]), str(row["active_revision_id"])

    def revision(self, revision_id: str) -> BaselineRevision:
        self._ensure_lakebase()
        if not self.uses_lakebase:
            with self._lock:
                return self._revisions[revision_id].copy()
        row = lakebase_store.postgres.query_one(
            f"SELECT * FROM {self._table('network_baseline_revisions')} WHERE revision_id = %s",
            (revision_id,),
        )
        if row is None:
            raise KeyError(revision_id)
        return self._revision(row)

    def revision_header(self, revision_id: str) -> dict[str, Any]:
        """Read revision metadata without materializing the snapshot payload."""

        self._ensure_lakebase()
        if not self.uses_lakebase:
            with self._lock:
                revision = self._revisions[revision_id]
                return {
                    "revision_id": revision.revision_id,
                    "source_revision_id": revision.source_revision_id,
                    "run_id": revision.run_id,
                    "accepted_at": revision.accepted_at,
                }
        row = lakebase_store.postgres.query_one(
            f"SELECT revision_id, source_revision_id, run_id, accepted_at "
            f"FROM {self._table('network_baseline_revisions')} WHERE revision_id = %s",
            (revision_id,),
        )
        if row is None:
            raise KeyError(revision_id)
        return row

    def option_rows(self, revision_id: str) -> NetworkRows:
        """Load the small option summary without touching the full snapshot."""

        self._ensure_lakebase()
        if not self.uses_lakebase:
            with self._lock:
                rows = self._revisions[revision_id].rows
                return self._option_payload(rows)
        row = lakebase_store.postgres.query_one(
            f"SELECT option_payload FROM {self._table('network_baseline_option_revisions')} "
            "WHERE revision_id = %s",
            (revision_id,),
        )
        if row is None:
            raise KeyError(revision_id)
        payload = row["option_payload"]
        return payload if isinstance(payload, dict) else json.loads(payload)

    def save_option_rows(self, revision_id: str, rows: NetworkRows) -> None:
        self._ensure_lakebase()
        if not self.uses_lakebase:
            return
        lakebase_store.postgres.execute(
            f"""INSERT INTO {self._table('network_baseline_option_revisions')}
                (revision_id, option_payload) VALUES (%s, %s)
                ON CONFLICT (revision_id) DO UPDATE SET option_payload = EXCLUDED.option_payload""",
            (revision_id, lakebase_store.postgres.jsonb(self._option_payload(rows))),
        )

    def save_proposal(self, proposal: BaselineProposalRecord) -> None:
        self._ensure_lakebase()
        if not self.uses_lakebase:
            with self._lock:
                self._revisions[proposal.proposed_revision.revision_id] = proposal.proposed_revision.copy()
                self._proposals[proposal.proposal_id] = proposal
            return
        with lakebase_store.postgres.transaction() as connection:
            revision = proposal.proposed_revision
            lakebase_store.postgres.execute(
                f"INSERT INTO {self._table('network_baseline_revisions')} VALUES (%s,%s,%s,%s,%s)",
                (revision.revision_id, revision.source_revision_id, revision.run_id, None,
                 lakebase_store.postgres.jsonb(revision.rows)), connection=connection,
            )
            lakebase_store.postgres.execute(
                f"INSERT INTO {self._table('network_baseline_option_revisions')} VALUES (%s,%s)",
                (
                    revision.revision_id,
                    lakebase_store.postgres.jsonb(self._option_payload(revision.rows)),
                ),
                connection=connection,
            )
            lakebase_store.postgres.execute(
                f"INSERT INTO {self._table('network_baseline_proposals')} VALUES (%s,%s,%s,%s,%s)",
                (proposal.proposal_id, proposal.run_id, proposal.source_revision_id,
                 revision.revision_id, proposal.status), connection=connection,
            )

    def proposal(self, proposal_id: str) -> BaselineProposalRecord:
        self._ensure_lakebase()
        if not self.uses_lakebase:
            with self._lock:
                return self._proposals[proposal_id]
        row = lakebase_store.postgres.query_one(
            f"SELECT * FROM {self._table('network_baseline_proposals')} WHERE proposal_id = %s",
            (proposal_id,),
        )
        if row is None:
            raise KeyError(proposal_id)
        revision = self.revision(str(row["proposed_revision_id"]))
        return BaselineProposalRecord(
            proposal_id=str(row["proposal_id"]), run_id=str(row["run_id"]),
            source_revision_id=str(row["source_revision_id"]),
            proposed_revision=revision, status=str(row["status"]),
        )

    def accept(self, proposal_id: str, accepted_at: str) -> BaselineRevision:
        """Atomically compare-and-swap the active pointer; history remains immutable."""
        self._ensure_lakebase()
        if not self.uses_lakebase:
            with self._lock:
                proposal = self._proposals[proposal_id]
                if proposal.status != "proposed" or self._active_id != proposal.source_revision_id:
                    raise ValueError("stale")
                revision = BaselineRevision(**{**proposal.proposed_revision.__dict__, "accepted_at": accepted_at})
                self._revisions[revision.revision_id] = revision
                self._proposals[proposal_id] = BaselineProposalRecord(**{**proposal.__dict__, "status": "accepted"})
                self._active_id = revision.revision_id
                return revision.copy()
        with lakebase_store.postgres.transaction() as connection:
            proposal = lakebase_store.postgres.query_one(
                f"SELECT * FROM {self._table('network_baseline_proposals')} WHERE proposal_id = %s FOR UPDATE",
                (proposal_id,), connection=connection,
            )
            if proposal is None:
                raise KeyError(proposal_id)
            changed = lakebase_store.postgres.execute(
                f"""UPDATE {self._table('network_baseline_state')} SET active_revision_id = %s
                WHERE singleton_key = %s AND active_revision_id = %s""",
                (proposal["proposed_revision_id"], "network", proposal["source_revision_id"]),
                connection=connection,
            )
            if changed == 0 or proposal["status"] != "proposed":
                raise ValueError("stale")
            lakebase_store.postgres.execute(
                f"UPDATE {self._table('network_baseline_revisions')} SET accepted_at = %s WHERE revision_id = %s",
                (accepted_at, proposal["proposed_revision_id"]), connection=connection,
            )
            lakebase_store.postgres.execute(
                f"UPDATE {self._table('network_baseline_proposals')} SET status = 'accepted' WHERE proposal_id = %s",
                (proposal_id,), connection=connection,
            )
        return self.revision(str(proposal["proposed_revision_id"]))

    def reset(self, *, clear_history: bool = False) -> None:
        self._ensure_lakebase()
        if not self.uses_lakebase:
            with self._lock:
                self._active_id = self._original_id
                if clear_history and self._original_id:
                    original = self._revisions[self._original_id]
                    self._revisions = {self._original_id: original}
                    self._proposals.clear()
            return
        with lakebase_store.postgres.transaction() as connection:
            state = lakebase_store.postgres.query_one(
                f"SELECT original_revision_id FROM {self._table('network_baseline_state')} "
                "WHERE singleton_key = %s FOR UPDATE",
                ("network",), connection=connection,
            )
            if state is None:
                raise RuntimeError("Baseline state has not been seeded.")
            original_id = str(state["original_revision_id"])
            lakebase_store.postgres.execute(
                f"UPDATE {self._table('network_baseline_state')} SET active_revision_id = %s "
                "WHERE singleton_key = %s",
                (original_id, "network"), connection=connection,
            )
            if clear_history:
                lakebase_store.postgres.execute(
                    f"DELETE FROM {self._table('network_baseline_proposals')}",
                    connection=connection,
                )
                lakebase_store.postgres.execute(
                    f"DELETE FROM {self._table('network_baseline_option_revisions')} "
                    "WHERE revision_id <> %s",
                    (original_id,), connection=connection,
                )
                lakebase_store.postgres.execute(
                    f"DELETE FROM {self._table('network_baseline_revisions')} "
                    "WHERE revision_id <> %s",
                    (original_id,), connection=connection,
                )
