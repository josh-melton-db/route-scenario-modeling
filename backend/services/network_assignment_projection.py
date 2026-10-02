"""Project run-scoped depot responsibility without rewriting published demand."""
from collections import defaultdict
from typing import Any, Mapping, Sequence


def merge_assignment_overlays(
    existing: Sequence[dict[str, Any]], replacements: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    def key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
        return (str(row['demand_plan_version_id']), str(row['capacity_plan_version_id']),
                str(row['service_date'])[:10], str(row['customer_id']))
    replaced = {key(row) for row in replacements}
    return [row for row in existing if key(row) not in replaced] + list(replacements)


def projected_demand_rows(
    rows: Mapping[str, Sequence[Mapping[str, Any]]],
    demand_plan_version_id: str,
    capacity_plan_version_id: str,
) -> list[dict[str, Any]]:
    selected_demand = [
        row for row in rows.get('demand_plan_daily', [])
        if str(row['demand_plan_version_id']) == demand_plan_version_id
    ]
    selected_overlays = [
        row for row in rows.get('network_customer_assignments_daily', [])
        if (str(row['demand_plan_version_id']) == demand_plan_version_id
            and str(row['capacity_plan_version_id']) == capacity_plan_version_id)
    ]
    # Published legacy snapshots may contain depot/market aggregates. Without
    # reassignment there is nothing to project and their totals remain valid.
    if not selected_overlays:
        return [dict(row) for row in selected_demand]
    if any(not row.get('customer_id') for row in selected_demand):
        raise ValueError('Customer reassignment requires customer-level demand; this legacy baseline contains aggregate demand.')
    canonical: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows.get('demand_plan_daily', []):
        if str(row['demand_plan_version_id']) == demand_plan_version_id:
            canonical[(str(row['service_date'])[:10], str(row['customer_id']))].append(row)
    overlays: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    facilities = {str(row['facility_id']): row for row in rows.get('dim_facilities', [])}
    for row in rows.get('network_customer_assignments_daily', []):
        if (str(row['demand_plan_version_id']) == demand_plan_version_id
                and str(row['capacity_plan_version_id']) == capacity_plan_version_id):
            key = (str(row['service_date'])[:10], str(row['customer_id']))
            if key not in canonical:
                raise ValueError('Assignment overlay references demand that does not exist.')
            depot_id = str(row['depot_id'])
            facility = facilities.get(depot_id)
            if facility is None or facility.get('facility_type', 'depot') != 'depot':
                raise ValueError('Assignment overlay references an unknown depot.')
            required = int(row['required_units'])
            assigned, unmet = int(row['assigned_units']), int(row['unmet_units'])
            if min(required, assigned, unmet) < 0 or required != assigned + unmet:
                raise ValueError('Assignment overlay must conserve assigned and unmet cases.')
            overlays[key].append(row)
    result: list[dict[str, Any]] = []
    for key, demand in canonical.items():
        allocation = overlays.get(key)
        if not allocation:
            result.extend(dict(row) for row in demand)
            continue
        if sum(int(row['required_units']) for row in allocation) != sum(int(row['demand_units']) for row in demand):
            raise ValueError('Assignment overlay changes required customer/date demand.')
        seen: set[str] = set()
        for row in allocation:
            depot_id = str(row['depot_id'])
            if depot_id in seen:
                raise ValueError('Assignment overlay contains duplicate customer/date/depot responsibility.')
            seen.add(depot_id)
            result.append({
                **demand[0],
                'depot_id': depot_id,
                'region_id': facilities[depot_id].get('region_id', demand[0].get('region_id')),
                'demand_units': int(row['required_units']),
            })
    return result
