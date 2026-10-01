from __future__ import annotations

import hashlib
import json
import uuid
import threading
from collections import OrderedDict, defaultdict
from copy import deepcopy
from datetime import date, datetime, timezone
from typing import Any

from fastapi import HTTPException

from ..baseline_models import (
    BaselineProposalResponse,
    BaselineRouteCoverage,
    BaselineState,
)
from .baseline_repository import (
    BaselineProposalRecord,
    BaselineRepository,
    BaselineRevision,
)
from .network_overview import NetworkRows, network_overview_service
from .network_assignment_projection import projected_demand_rows


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BaselineService:
    def __init__(self, repository: BaselineRepository | None = None) -> None:
        self.repository = repository or BaselineRepository()
        self._seed_lock = threading.Lock()
        self._seeded = False
        self._plan_run_cache: OrderedDict[str, Any] = OrderedDict()
        self._plan_cache_lock = threading.RLock()

    def _ensure_seeded(self) -> None:
        if self._seeded:
            return
        with self._seed_lock:
            if self._seeded:
                return
            if self.repository.is_initialized():
                self._seeded = True
                return
            rows = deepcopy(network_overview_service._load_rows())  # canonical, unfiltered snapshot
            # New original revisions freeze rates once, just like accepted
            # revisions. Reconstructing a baseline planning run after eviction
            # must not consult a subsequently edited rate book.
            from ..models import NetworkPricingContext
            from .rates import list_rate_contract_details
            from .store_provider import get_store

            contracts = list_rate_contract_details(get_store())
            existing_metadata = rows.get("baseline_revision_metadata", [])
            metadata = deepcopy(existing_metadata[0]) if existing_metadata else {}
            metadata.setdefault("route_coverage", self._coverage(rows).model_dump(mode="json"))
            metadata.setdefault("tariffs", [])
            metadata["network_pricing_context"] = NetworkPricingContext(
                pricing_basis="comparable_pinned_dated_contracts_v1",
                contract_snapshots=[row.model_dump(mode="json") for row in contracts],
                contract_version_ids=sorted({row.version.version_id for row in contracts}),
                objective_cost_basis="baseline_snapshot_no_reoptimization",
            ).model_dump(mode="json")
            rows["baseline_revision_metadata"] = [metadata]
            identity = {
                "demand": rows.get("demand_plan_versions", []),
                "capacity": rows.get("capacity_plan_versions", []),
            }
            digest = hashlib.sha256(
                json.dumps(identity, sort_keys=True, default=str).encode()
            ).hexdigest()[:16]
            self.repository.seed(
                BaselineRevision(
                    revision_id=f"baseline-original-{digest}",
                    source_revision_id=None,
                    run_id=None,
                    accepted_at=None,
                    rows=rows,
                )
            )
            self._seeded = True

    def get_revision(self, revision_id: str | None = None) -> BaselineRevision:
        """Read-only revision snapshot for Stream B scenario provenance/comparison."""
        self._ensure_seeded()
        _, active_id = self.repository.ids()
        try:
            return self.repository.revision(revision_id or active_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Baseline revision not found.") from exc

    def active_rows(self) -> NetworkRows:
        return self.get_revision().rows

    @staticmethod
    def _plan_ids(rows: NetworkRows) -> tuple[str | None, str | None]:
        metadata = rows.get("baseline_revision_metadata", [])
        if metadata and metadata[0].get("demand_plan_version_id"):
            return (
                str(metadata[0]["demand_plan_version_id"]),
                str(metadata[0]["capacity_plan_version_id"]),
            )
        demand = rows.get("demand_plan_versions", [])
        capacity = rows.get("capacity_plan_versions", [])
        demand_default = max(demand, key=lambda row: str(row.get("published_at", "")), default=None)
        capacity_default = max(capacity, key=lambda row: str(row.get("published_at", "")), default=None)
        return (
            str(demand_default["plan_version_id"]) if demand_default else None,
            str(capacity_default["plan_version_id"]) if capacity_default else None,
        )

    @classmethod
    def _coverage(cls, rows: NetworkRows) -> BaselineRouteCoverage:
        metadata = rows.get("baseline_revision_metadata", [])
        if metadata:
            return BaselineRouteCoverage.model_validate(metadata[0]["route_coverage"])
        expected, _ = cls._flow_coverage(rows)
        return BaselineRouteCoverage(
            ready=False, covered_dates=0,
            expected_dates=len({day for day, _ in expected}),
            covered_depots=0,
            expected_depots=len({depot for _, depot in expected}),
            message="No frozen depot route-plan results are attached to this baseline revision.",
        )

    @classmethod
    def _flow_coverage(cls, rows: NetworkRows) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
        demand_id, capacity_id = cls._plan_ids(rows)
        expected = {
            (str(row["service_date"])[:10], str(row["depot_id"]))
            for row in rows.get("demand_plan_daily", [])
            if (demand_id is None or str(row.get("demand_plan_version_id")) == demand_id)
            and int(row.get("demand_units", 0)) > 0
        }
        lane_dest = {
            str(row["lane_id"]): str(row["destination_endpoint_id"])
            for row in rows.get("dim_network_lanes", [])
            if str(row.get("lane_type")) == "LINEHAUL"
        }
        covered = {
            (str(row["service_date"])[:10], lane_dest[str(row["lane_id"])])
            for row in rows.get("baseline_network_flow_daily", [])
            if str(row.get("lane_id")) in lane_dest
            and (capacity_id is None or str(row.get("capacity_plan_version_id")) == capacity_id)
            and int(row.get("assigned_units", 0)) > 0
        }
        return expected, covered

    @staticmethod
    def _freeze_route_coverage(run_id: str, snapshot: Any) -> dict[str, Any]:
        from .depot_plan_repository import depot_plan_repository

        start, end = snapshot.scenario.horizon_start, snapshot.scenario.horizon_end
        expected_depots = {
            str(row["destination_endpoint_id"])
            for row in snapshot.network_rows.get("dim_network_lanes", [])
            if str(row.get("lane_type")) == "LINEHAUL"
            and any(str(flow.get("lane_id")) == str(row["lane_id"]) for flow in snapshot.flow_rows)
        }
        expected_dates = {
            str(row["service_date"])[:10] for row in snapshot.flow_rows
            if start <= str(row["service_date"])[:10] <= end
        }
        if depot_plan_repository._uses_lakebase:
            from .lakebase_store import lakebase_store

            records = [
                json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
                for row in lakebase_store.postgres.query(
                    f"SELECT payload FROM {depot_plan_repository._table()} WHERE parent_run_id = %s",
                    (run_id,),
                )
            ]
        else:
            with depot_plan_repository._lock:
                records = [deepcopy(row) for row in depot_plan_repository._records.values()
                           if str(row.get("parent_run_id")) == run_id]
        covered: set[tuple[str, str]] = set()
        selected_ids: list[str] = []
        has_unserved = False
        for record in records:
            depot = record.get("depot", {})
            depot_id = str(record.get("depot_id") or depot.get("depot_id") or "")
            for day_text, day in record.get("days", {}).items():
                result_ids = [day.get("default_result_id"), *day.get("selected_result_ids", {}).values()]
                frozen_ids = [str(result_id) for result_id in result_ids if result_id]
                if frozen_ids:
                    covered.add((str(day_text), depot_id))
                    selected_ids.extend(frozen_ids)
                    has_unserved = has_unserved or any(
                        int(day.get("results", {}).get(result_id, {}).get("unserved_cases", 0)) > 0
                        for result_id in frozen_ids
                    )
        expected = {(day, depot) for day in expected_dates for depot in expected_depots}
        actual = covered & expected
        ready = bool(expected) and actual == expected and not has_unserved
        return {
            "route_coverage": BaselineRouteCoverage(
                ready=ready,
                covered_dates=len({day for day, _ in actual}),
                expected_dates=len(expected_dates),
                covered_depots=len({depot for _, depot in actual}),
                expected_depots=len(expected_depots),
                message=("All selected depot-plan daily results are frozen with no unserved cases."
                         if ready else (
                             "Frozen depot route-plan results contain unserved cases."
                             if has_unserved else
                             f"{len(actual)} of {len(expected)} depot-day route results are frozen."
                         )),
            ).model_dump(),
            "selected_child_result_ids": sorted(set(selected_ids)),
        }

    def get_state(self) -> BaselineState:
        self._ensure_seeded()
        original_id, active_id = self.repository.ids()
        active = self.repository.revision(active_id)
        demand_id, capacity_id = self._plan_ids(active.rows)
        demand_version = next(
            (row for row in active.rows.get("demand_plan_versions", [])
             if str(row["plan_version_id"]) == demand_id), None,
        )
        active_dates = sorted({
            str(row["service_date"])[:10]
            for row in active.rows.get("demand_plan_daily", [])
            if str(row.get("demand_plan_version_id")) == demand_id
        })
        plan_start = (
            str(demand_version.get("horizon_start"))[:10]
            if demand_version and demand_version.get("horizon_start")
            else active_dates[0] if active_dates else "unknown"
        )
        plan_end = (
            str(demand_version.get("horizon_end"))[:10]
            if demand_version and demand_version.get("horizon_end")
            else active_dates[-1] if active_dates else "unknown"
        )
        plan_suffix = f"{active_id}.{demand_id}.{capacity_id}.{plan_start}.{plan_end}"
        return BaselineState(
            original_revision_id=original_id,
            active_revision_id=active_id,
            active_run_id=active.run_id,
            active_plan_run_id=f"baseline-plan-run.{plan_suffix}",
            active_plan_scenario_id=f"baseline-plan-scenario.{plan_suffix}",
            default_demand_plan_version_id=demand_id,
            default_capacity_plan_version_id=capacity_id,
            accepted_at=active.accepted_at,
            route_coverage=self._coverage(active.rows),
        )

    @staticmethod
    def _has_pending_demand(run_id: str) -> bool:
        try:
            from .demand_changes import demand_change_service
        except ImportError:
            return False
        return bool(demand_change_service.has_pending(run_id))

    @staticmethod
    def _merge_rows(source: NetworkRows, snapshot: Any) -> NetworkRows:
        merged = deepcopy(source)
        run_rows: NetworkRows = snapshot.network_rows
        scenario = snapshot.scenario
        start, end = scenario.horizon_start, scenario.horizon_end
        region = scenario.region_id

        # Responsibility is capacity-context-specific; the upstream demand rows
        # remain immutable and other capacity variants keep their allocations.
        assignment_keys = {
            (str(row['demand_plan_version_id']), str(row['capacity_plan_version_id']),
             str(row['service_date'])[:10], str(row['customer_id']))
            for row in run_rows.get('network_customer_assignments_daily', [])
            if str(row['demand_plan_version_id']) == scenario.demand_plan_version_id
            and str(row['capacity_plan_version_id']) == scenario.capacity_plan_version_id
            and start <= str(row['service_date'])[:10] <= end
        }
        merged['network_customer_assignments_daily'] = [
            deepcopy(row) for row in source.get('network_customer_assignments_daily', [])
            if (str(row['demand_plan_version_id']), str(row['capacity_plan_version_id']),
                str(row['service_date'])[:10], str(row['customer_id'])) not in assignment_keys
        ] + [
            deepcopy(row) for row in run_rows.get('network_customer_assignments_daily', [])
            if (str(row['demand_plan_version_id']), str(row['capacity_plan_version_id']),
                str(row['service_date'])[:10], str(row['customer_id'])) in assignment_keys
        ]

        # Dimensions may gain eligible lanes/customers in a reassignment child.
        for table, key in (
            ("dim_regions", "region_id"), ("dim_facilities", "facility_id"),
            ("dim_markets", "market_id"), ("dim_network_customers", "customer_id"),
            ("dim_network_lanes", "lane_id"),
        ):
            by_key = {str(row[key]): deepcopy(row) for row in merged.get(table, [])}
            by_key.update({str(row[key]): deepcopy(row) for row in run_rows.get(table, [])})
            merged[table] = list(by_key.values())
        for table in ("demand_plan_versions", "capacity_plan_versions"):
            by_key = {
                str(row["plan_version_id"]): deepcopy(row)
                for row in merged.get(table, [])
            }
            by_key.update({
                str(row["plan_version_id"]): deepcopy(row)
                for row in run_rows.get(table, [])
            })
            merged[table] = list(by_key.values())

        source_demand_ids = {
            str(row.get("demand_plan_version_id"))
            for row in source.get("demand_plan_daily", [])
        }
        is_derived_demand = scenario.demand_plan_version_id not in source_demand_ids
        source_demand_id, _ = BaselineService._plan_ids(source)

        facilities = {str(row["facility_id"]): row for row in merged.get("dim_facilities", [])}
        lanes = {str(row["lane_id"]): row for row in merged.get("dim_network_lanes", [])}

        def in_scope(row: dict[str, Any]) -> bool:
            day = str(row.get("service_date", ""))[:10]
            if not (start <= day <= end):
                return False
            if region == "ALL":
                return True
            row_region = row.get("region_id")
            if row_region is not None:
                return str(row_region) == region
            facility = facilities.get(str(row.get("facility_id", "")))
            if facility:
                return str(facility.get("region_id")) == region
            lane = lanes.get(str(row.get("lane_id", "")))
            if lane:
                endpoint = facilities.get(str(lane.get("destination_endpoint_id", ""))) or facilities.get(
                    str(lane.get("origin_endpoint_id", ""))
                )
                return bool(endpoint and str(endpoint.get("region_id")) == region)
            return False

        def matching_version(table: str, row: dict[str, Any]) -> bool:
            if table == "demand_plan_daily":
                return str(row.get("demand_plan_version_id")) == scenario.demand_plan_version_id
            if table in {"facility_capacity_daily", "lane_capacity_daily"}:
                return str(row.get("capacity_plan_version_id")) == scenario.capacity_plan_version_id
            return True

        key_fields = {
            "demand_plan_daily": ("demand_plan_version_id", "service_date", "region_id",
                                  "distribution_center_id", "depot_id", "market_id", "customer_id"),
            "facility_capacity_daily": ("capacity_plan_version_id", "service_date", "facility_id"),
            "lane_capacity_daily": ("capacity_plan_version_id", "service_date", "lane_id"),
        }
        for table, keys in key_fields.items():
            # Replace, rather than upsert, the full solved slice. This preserves
            # explicit deletions/moves in customer demand rows.
            retained = [deepcopy(row) for row in merged.get(table, [])
                        if not (matching_version(table, row) and
                                (in_scope(row) or (table == "demand_plan_daily" and is_derived_demand)))]
            current = {tuple(str(row.get(k, "")) for k in keys): row for row in retained}
            for row in run_rows.get(table, []):
                if matching_version(table, row) and (
                    in_scope(row) or (table == "demand_plan_daily" and is_derived_demand)
                ):
                    current[tuple(str(row.get(k, "")) for k in keys)] = deepcopy(row)
            merged[table] = list(current.values())

        solved_lane_types = {
            str(row.get("lane_type") or lanes.get(str(row.get("lane_id")), {}).get("lane_type"))
            for row in snapshot.flow_rows
        }
        if is_derived_demand and source_demand_id:
            merged["baseline_network_flow_daily"] = [
                *merged.get("baseline_network_flow_daily", []),
                *[
                    {**deepcopy(row), "demand_plan_version_id": scenario.demand_plan_version_id}
                    for row in source.get("baseline_network_flow_daily", [])
                    if str(row.get("demand_plan_version_id")) == source_demand_id
                    and str(row.get("capacity_plan_version_id")) == scenario.capacity_plan_version_id
                ],
            ]
        retained_flows = [row for row in merged.get("baseline_network_flow_daily", [])
                          if not (str(row.get("demand_plan_version_id")) == scenario.demand_plan_version_id
                                  and str(row.get("capacity_plan_version_id")) == scenario.capacity_plan_version_id
                                  and str(row.get("lane_type") or lanes.get(str(row.get("lane_id")), {}).get("lane_type")) in solved_lane_types
                                  and in_scope(row))]
        flow_by_key = {
            (str(row.get("demand_plan_version_id", "")), str(row.get("capacity_plan_version_id", "")),
             str(row["service_date"])[:10], str(row["lane_id"])): deepcopy(row)
            for row in retained_flows
        }
        for row in snapshot.flow_rows:
            flow_by_key[(str(row.get("demand_plan_version_id", scenario.demand_plan_version_id)),
                         str(row.get("capacity_plan_version_id", scenario.capacity_plan_version_id)),
                         str(row["service_date"])[:10], str(row["lane_id"]))] = deepcopy(row)
        merged["baseline_network_flow_daily"] = list(flow_by_key.values())
        retained_costs = [row for row in merged.get("network_flow_cost_daily", [])
                          if not (str(row.get("demand_plan_version_id", scenario.demand_plan_version_id)) == scenario.demand_plan_version_id
                                  and str(row.get("capacity_plan_version_id", scenario.capacity_plan_version_id)) == scenario.capacity_plan_version_id
                                  and in_scope(row))]
        cost_by_key = {
            (str(row.get("demand_plan_version_id", "")), str(row.get("capacity_plan_version_id", "")),
             str(row["service_date"])[:10], str(row["lane_id"])): deepcopy(row)
            for row in retained_costs
        }
        for row in snapshot.cost_rows:
            enriched = {"demand_plan_version_id": scenario.demand_plan_version_id,
                        "capacity_plan_version_id": scenario.capacity_plan_version_id, **row}
            cost_by_key[(scenario.demand_plan_version_id, scenario.capacity_plan_version_id,
                         str(row["service_date"])[:10], str(row["lane_id"]))] = enriched
        merged["network_flow_cost_daily"] = list(cost_by_key.values())
        return merged

    @classmethod
    def _validate(cls, rows: NetworkRows) -> BaselineRouteCoverage:
        coverage = cls._coverage(rows)
        _, covered_flow = cls._flow_coverage(rows)
        lanes = {str(row["lane_id"]): row for row in rows.get("dim_network_lanes", [])}
        customers = {str(row["customer_id"]) for row in rows.get("dim_network_customers", [])}
        facilities_by_id = {str(row['facility_id']): row for row in rows.get('dim_facilities', [])}
        flow_rows = rows.get("baseline_network_flow_daily", [])
        if any(int(row.get("assigned_units", 0)) < 0 for row in flow_rows):
            raise HTTPException(status_code=409, detail="Proposed baseline contains negative assigned flow.")
        if any(str(row.get("lane_id")) not in lanes for row in flow_rows):
            raise HTTPException(status_code=409, detail="Proposed baseline references an unknown lane.")
        if any(
            str(lanes[str(row["lane_id"])].get("lane_type")) == "DELIVERY"
            and str(lanes[str(row["lane_id"])].get("destination_endpoint_id")) not in customers
            for row in flow_rows
        ):
            raise HTTPException(status_code=409, detail="Proposed baseline references an unknown delivery customer.")
        capacity = {
            (str(row.get("capacity_plan_version_id", "")), str(row["service_date"])[:10],
             str(row["lane_id"])): int(row["capacity_units"])
            for row in rows.get("lane_capacity_daily", [])
        }
        lane_flow: defaultdict[tuple[str, str, str, str], int] = defaultdict(int)
        for row in rows.get("baseline_network_flow_daily", []):
            lane_flow[(str(row.get("demand_plan_version_id", "")),
                       str(row.get("capacity_plan_version_id", "")),
                       str(row["service_date"])[:10], str(row["lane_id"]))] += int(row.get("assigned_units", 0))
        if any(
            units > capacity.get((capacity_id, day, lane_id), -1)
            for (_, capacity_id, day, lane_id), units in lane_flow.items()
            if units > 0
        ):
            raise HTTPException(status_code=409, detail="Proposed baseline exceeds lane capacity.")

        facility_capacity = {
            (str(row.get("capacity_plan_version_id", "")), str(row["service_date"])[:10],
             str(row["facility_id"])): int(row["capacity_units"])
            for row in rows.get("facility_capacity_daily", [])
        }
        facility_flow: defaultdict[tuple[str, str, str, str], int] = defaultdict(int)
        for row in rows.get("baseline_network_flow_daily", []):
            lane = lanes.get(str(row["lane_id"]))
            if not lane or str(lane.get("lane_type")) != "LINEHAUL":
                continue
            demand_version = str(row.get("demand_plan_version_id", ""))
            capacity_version = str(row.get("capacity_plan_version_id", ""))
            day = str(row["service_date"])[:10]
            units = int(row.get("assigned_units", 0))
            facility_flow[(demand_version, capacity_version, day, str(lane["origin_endpoint_id"]))] += units
            facility_flow[(demand_version, capacity_version, day, str(lane["destination_endpoint_id"]))] += units
        if any(
            units > facility_capacity.get((capacity_id, day, facility_id), -1)
            for (_, capacity_id, day, facility_id), units in facility_flow.items()
            if units > 0
        ):
            raise HTTPException(status_code=409, detail="Proposed baseline exceeds facility capacity.")

        demand: defaultdict[tuple[str, str, str], int] = defaultdict(int)
        for row in rows.get("demand_plan_daily", []):
            demand[(str(row.get("demand_plan_version_id", "")),
                    str(row["service_date"])[:10], str(row["depot_id"]))] += int(row["demand_units"])
        lane_dest = {
            str(row["lane_id"]): str(row["destination_endpoint_id"])
            for row in rows.get("dim_network_lanes", []) if str(row.get("lane_type")) == "LINEHAUL"
        }
        assigned: defaultdict[tuple[str, str, str, str], int] = defaultdict(int)
        represented: set[tuple[str, str, str, str]] = set()
        for row in rows.get("baseline_network_flow_daily", []):
            lane_id = str(row["lane_id"])
            if lane_id in lane_dest:
                key = (str(row.get("demand_plan_version_id", "")),
                       str(row.get("capacity_plan_version_id", "")),
                       str(row["service_date"])[:10], lane_dest[lane_id])
                represented.add(key)
                assigned[key] += int(row["assigned_units"])
        contexts = {(demand_id, capacity_id) for demand_id, capacity_id, _, _ in represented}
        responsible_demand: defaultdict[tuple[str, str, str, str], int] = defaultdict(int)
        for demand_id, capacity_id in contexts:
            try:
                projected = projected_demand_rows(rows, demand_id, capacity_id)
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            for row in projected:
                responsible_demand[(demand_id, capacity_id, str(row['service_date'])[:10],
                                    str(row['depot_id']))] += int(row['demand_units'])
        expected = set(responsible_demand)
        if not expected.issubset(represented):
            raise HTTPException(status_code=409, detail="Proposed baseline lacks full network depot-date coverage.")
        if any(assigned[key] > responsible_demand[key] for key in represented):
            raise HTTPException(status_code=409, detail="Proposed baseline assigns more cases than required demand.")
        if any(key not in expected for key, units in assigned.items() if units):
            raise HTTPException(status_code=409, detail="Proposed baseline assigns cases without matching demand.")

        layer_totals: defaultdict[tuple[str, str, str, str, str], int] = defaultdict(int)
        delivery_customer: defaultdict[tuple[str, str, str, str], int] = defaultdict(int)
        demand_customer: defaultdict[tuple[str, str, str], int] = defaultdict(int)
        for row in rows.get("demand_plan_daily", []):
            demand_customer[(str(row.get("demand_plan_version_id", "")),
                             str(row["service_date"])[:10], str(row.get("customer_id", "")))] += int(row["demand_units"])
        present_layers: set[str] = set()
        for row in flow_rows:
            lane = lanes[str(row["lane_id"])]
            layer = str(lane.get("lane_type"))
            present_layers.add(layer)
            destination = str(lane.get('destination_endpoint_id', ''))
            facility = facilities_by_id.get(destination, {})
            if layer == "LINEHAUL" and facility.get('facility_type', 'depot') == 'depot':
                depot = str(lane["destination_endpoint_id"])
            elif layer in {"MARKET", "DELIVERY"}:
                depot = str(lane["origin_endpoint_id"])
            else:
                continue
            context = (str(row.get("demand_plan_version_id", "")),
                       str(row.get("capacity_plan_version_id", "")),
                       str(row["service_date"])[:10], depot)
            units = int(row.get("assigned_units", 0))
            layer_totals[(*context, layer)] += units
            if layer == "DELIVERY":
                customer = str(lane["destination_endpoint_id"])
                delivery_customer[(context[0], context[1], context[2], customer)] += units
        if {"LINEHAUL", "MARKET", "DELIVERY"}.issubset(present_layers):
            layer_contexts = {key[:4] for key in layer_totals}
            if any(
                len({layer_totals[(*context, layer)] for layer in ("LINEHAUL", "MARKET", "DELIVERY")}) != 1
                for context in layer_contexts
            ):
                raise HTTPException(status_code=409, detail="Proposed baseline does not conserve flow across network layers.")
        if any(
            units > demand_customer.get((demand_id, day, customer), -1)
            for (demand_id, _capacity_id, day, customer), units in delivery_customer.items()
        ):
            raise HTTPException(status_code=409, detail="Proposed delivery flow exceeds customer demand.")
        return coverage

    def propose(self, run_id: str) -> BaselineProposalResponse:
        self._ensure_seeded()
        if self._has_pending_demand(run_id):
            raise HTTPException(status_code=409, detail="Resolve pending demand changes before proposing this run.")
        from .network_scenarios import network_scenario_service
        snapshot = network_scenario_service.get_run_snapshot(run_id)
        original_id, active_id = self.repository.ids()
        # New scenarios freeze this field at creation. Legacy snapshots predate
        # active-baseline inheritance and therefore belong to the original.
        source_id = (
            getattr(snapshot.scenario, "source_baseline_revision_id", None)
            or original_id
        )
        try:
            self.repository.revision(source_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=409,
                detail="Run source baseline revision is no longer available.",
            ) from exc
        if source_id != active_id:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Run was solved from a historical baseline revision; rerun it "
                    "from the active baseline before proposing promotion."
                ),
            )
        rows = self._merge_rows(self.repository.revision(source_id).rows, snapshot)
        metadata = self._freeze_route_coverage(run_id, snapshot)
        metadata["demand_plan_version_id"] = snapshot.scenario.demand_plan_version_id
        metadata["capacity_plan_version_id"] = snapshot.scenario.capacity_plan_version_id
        metadata['tariffs'] = [rule.model_dump(mode='json') for rule in snapshot.scenario.assumptions.tariffs]
        metadata["network_pricing_context"] = snapshot.result.pricing_context.model_dump(mode="json")
        rows["baseline_revision_metadata"] = [metadata]
        self._validate(rows)
        coverage = self._coverage(rows)
        proposal_id = f"baseline-proposal-{uuid.uuid4()}"
        revision = BaselineRevision(
            revision_id=f"baseline-revision-{uuid.uuid4()}", source_revision_id=source_id,
            run_id=run_id, accepted_at=None, rows=rows,
        )
        self.repository.save_proposal(BaselineProposalRecord(
            proposal_id=proposal_id, run_id=run_id, source_revision_id=source_id,
            proposed_revision=revision,
        ))
        return BaselineProposalResponse(
            proposal_id=proposal_id, status="proposed", run_id=run_id,
            source_revision_id=source_id, route_coverage=coverage,
        )

    def accept(self, proposal_id: str) -> BaselineState:
        try:
            proposal = self.repository.proposal(proposal_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Baseline proposal not found.") from exc
        if self._has_pending_demand(proposal.run_id):
            raise HTTPException(status_code=409, detail="Resolve pending demand changes before accepting this proposal.")
        self._validate(proposal.proposed_revision.rows)
        try:
            self.repository.accept(proposal_id, _now())
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="Proposal source revision is stale.") from exc
        network_overview_service._options_cache = None
        return self.get_state()

    def reset(self) -> BaselineState:
        self._ensure_seeded()
        self.repository.reset()
        network_overview_service._options_cache = None
        return self.get_state()

    def get_plan_run(
        self,
        revision_id: str | None = None,
        *,
        demand_plan_version_id: str | None = None,
        capacity_plan_version_id: str | None = None,
        horizon_start: str | None = None,
        horizon_end: str | None = None,
    ) -> Any:
        """Return a full-network immutable snapshot for depot child planning.

        This run is distinct from proposal provenance and is intentionally
        deterministic per baseline revision.
        """
        revision = self.get_revision(revision_id)
        from ..models import (
            NetworkOverviewContext,
            NetworkPricingContext,
            NetworkRateCoverage,
            RateContractDetail,
            NetworkScenario,
            NetworkScenarioAssumptions,
            NetworkScenarioKpiDeltas,
            NetworkScenarioResult,
        )
        from .network_run_snapshots import NetworkRunSnapshot
        from .network_rating import rate_network_flows, resolve_network_tariffs
        from .rates import list_rate_contract_details
        from .store_provider import get_store

        default_demand_id, default_capacity_id = self._plan_ids(revision.rows)
        demand_id = demand_plan_version_id or default_demand_id
        capacity_id = capacity_plan_version_id or default_capacity_id
        if not demand_id or not capacity_id:
            raise HTTPException(status_code=409, detail="Baseline planning inputs are incomplete.")
        demand_version = next(
            (row for row in revision.rows.get("demand_plan_versions", [])
             if str(row["plan_version_id"]) == demand_id), None,
        )
        capacity_version = next(
            (row for row in revision.rows.get("capacity_plan_versions", [])
             if str(row["plan_version_id"]) == capacity_id), None,
        )
        if demand_version is None:
            raise HTTPException(status_code=404, detail="Demand plan version not found in baseline revision.")
        if capacity_version is None:
            raise HTTPException(status_code=404, detail="Capacity plan version not found in baseline revision.")
        demand_rows = [
            row for row in revision.rows.get("demand_plan_daily", [])
            if str(row.get("demand_plan_version_id")) == demand_id
        ]
        dates = sorted({str(row["service_date"])[:10] for row in demand_rows})
        if not dates:
            raise HTTPException(status_code=409, detail="Baseline planning horizon is empty.")
        start = horizon_start or dates[0]
        end = horizon_end or dates[-1]
        try:
            start, end = date.fromisoformat(start).isoformat(), date.fromisoformat(end).isoformat()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail='Plan-run dates must use YYYY-MM-DD.') from exc
        if end < start or start < dates[0] or end > dates[-1]:
            raise HTTPException(status_code=422, detail="Plan-run horizon must be ordered and covered by the demand plan.")
        capacity_start = str(capacity_version["horizon_start"])[:10]
        capacity_end = str(capacity_version["horizon_end"])[:10]
        if start < capacity_start or end > capacity_end:
            raise HTTPException(status_code=422, detail="Plan-run horizon must be covered by the capacity plan.")
        suffix = f"{revision.revision_id}.{demand_id}.{capacity_id}.{start}.{end}"
        scenario_id = f"baseline-plan-scenario.{suffix}"
        plan_run_id = f"baseline-plan-run.{suffix}"
        with self._plan_cache_lock:
            cached = self._plan_run_cache.get(plan_run_id)
            if cached is not None:
                self._plan_run_cache.move_to_end(plan_run_id)
        if cached is not None:
            return cached.copy()
        generated_at = str(demand_version.get("published_at") or demand_version.get("as_of_date"))
        metadata = revision.rows.get('baseline_revision_metadata', [])
        baseline_tariffs = metadata[0].get('tariffs', []) if metadata else []
        scenario = NetworkScenario(
            scenario_id=scenario_id, scenario_name="Active baseline child-planning snapshot",
            source_baseline_revision_id=revision.revision_id,
            demand_plan_version_id=demand_id, capacity_plan_version_id=capacity_id,
            horizon_start=start, horizon_end=end, region_id="ALL",
            status="solved", created_at=generated_at, updated_at=generated_at,
            solved_at=generated_at,
            assumptions=NetworkScenarioAssumptions.model_validate({
                'source_baseline_revision_id': revision.revision_id,
                'tariffs': baseline_tariffs,
            }),
        )
        context = NetworkOverviewContext(
            scenario_id=scenario_id, demand_plan_version_id=demand_id,
            capacity_plan_version_id=capacity_id, horizon_start=start,
            horizon_end=end, region_id="ALL", lane_type="LINEHAUL",
            metric="assigned_flow",
        )
        flow_rows = [
            deepcopy(row) for row in revision.rows.get("baseline_network_flow_daily", [])
            if str(row.get("demand_plan_version_id")) == demand_id
            and str(row.get("capacity_plan_version_id")) == capacity_id
            and start <= str(row["service_date"])[:10] <= end
        ]
        cost_rows = [
            deepcopy(row) for row in revision.rows.get("network_flow_cost_daily", [])
            if str(row.get("demand_plan_version_id", demand_id)) == demand_id
            and str(row.get("capacity_plan_version_id", capacity_id)) == capacity_id
            and start <= str(row["service_date"])[:10] <= end
        ]
        original_published_cost = (
            round(sum(float(row.get("total_cost", 0)) for row in cost_rows), 2)
            if cost_rows else None
        )
        pinned_context = metadata[0].get("network_pricing_context", {}) if metadata else {}
        contracts = (
            [RateContractDetail.model_validate(row) for row in pinned_context.get("contract_snapshots", [])]
            if "contract_snapshots" in pinned_context
            else list_rate_contract_details(get_store())
        )
        tariff_map = resolve_network_tariffs(
            revision.rows, scenario.assumptions.tariffs, start, end
        )
        rated = rate_network_flows(
            revision.rows, flow_rows, tariff_map, contracts=contracts
        )
        cost_rows = rated.cost_rows
        comparable_rows = deepcopy(revision.rows)
        comparable_rows["baseline_network_flow_daily"] = flow_rows
        comparable_rows["network_flow_cost_daily"] = cost_rows
        overview = network_overview_service.build_overview(
            comparable_rows, context=context, scenario_id=scenario_id
        )
        governed = [r for r in rated.charge_details if r.rate_source == "governed_contract"]
        fallback = [r for r in rated.charge_details if r.rate_source == "planning_fallback"]
        coverage = NetworkRateCoverage(
            governed_charge_count=len(governed), fallback_charge_count=len(fallback),
            governed_assigned_units=sum(r.assigned_units for r in governed),
            fallback_assigned_units=sum(r.assigned_units for r in fallback),
        )
        freight_total = round(sum(r.freight_total for r in rated.charge_details), 2)
        tariff_total = round(sum(r.tariff_total for r in rated.charge_details), 2)
        result = NetworkScenarioResult(
            run_id=plan_run_id, scenario_id=scenario_id, revision=1,
            generated_at=generated_at, overview=overview,
            baseline_overview=overview.model_copy(deep=True),
            kpi_deltas=NetworkScenarioKpiDeltas(
                demand_units=0, assigned_units=0, unmet_units=0, total_cost=0,
                cost_per_unit=0, on_time_pct=0, utilization_pct=0,
            ),
            freight_total_cost=freight_total, tariff_total_cost=tariff_total,
            baseline_freight_total_cost=freight_total,
            baseline_tariff_total_cost=tariff_total,
            baseline_total_modeled_cost=round(freight_total + tariff_total, 2),
            scenario_total_modeled_cost=round(freight_total + tariff_total, 2),
            original_published_baseline_cost=original_published_cost,
            charge_details=rated.charge_details,
            baseline_charge_details=[r.model_copy(deep=True) for r in rated.charge_details],
            baseline_rate_coverage=coverage, scenario_rate_coverage=coverage,
            pricing_context=NetworkPricingContext(
                pricing_basis="comparable_pinned_dated_contracts_v1",
                contract_snapshots=[r.model_dump(mode="json") for r in contracts],
                contract_version_ids=sorted({r.version.version_id for r in contracts}),
                rate_book_snapshot_ids=sorted({
                    r.rate_book_snapshot_id for r in rated.charge_details
                    if r.rate_book_snapshot_id
                }),
                baseline_tariffs=scenario.assumptions.tariffs,
                scenario_tariffs=scenario.assumptions.tariffs,
                objective_cost_basis="baseline_snapshot_no_reoptimization",
            ),
        )
        snapshot = NetworkRunSnapshot(
            scenario=scenario, result=result, network_rows=revision.rows,
            flow_rows=flow_rows, cost_rows=cost_rows,
        )
        with self._plan_cache_lock:
            self._plan_run_cache[plan_run_id] = snapshot
            # IDs are reconstructible; don't retain every filtered full network.
            while len(self._plan_run_cache) > 4:
                self._plan_run_cache.popitem(last=False)
        return snapshot.copy()

    def resolve_plan_run(self, run_id: str) -> Any:
        prefix = "baseline-plan-run."
        if not run_id.startswith(prefix):
            raise HTTPException(status_code=404, detail="Baseline plan run not found.")
        parts = run_id[len(prefix):].split(".")
        if len(parts) != 5:
            raise HTTPException(status_code=404, detail="Baseline plan run ID is invalid.")
        revision_id, demand_id, capacity_id, start, end = parts
        return self.get_plan_run(
            revision_id,
            demand_plan_version_id=demand_id,
            capacity_plan_version_id=capacity_id,
            horizon_start=start,
            horizon_end=end,
        )


baseline_service = BaselineService()
