"""Pure validation shared by durable prechecks and the legacy validation route."""

from __future__ import annotations

from ..models import (
    ScenarioDefinition,
    ScenarioTypeSpec,
    ValidationIssue,
    ValidationResponse,
)


def validate_scenario_definition(
    scenario: ScenarioDefinition,
    scenario_types: list[ScenarioTypeSpec],
) -> ValidationResponse:
    spec = next(
        (item for item in scenario_types if item.scenario_type == scenario.scenario_type),
        None,
    )
    missing = [
        field.name
        for field in (spec.fields if spec is not None else [])
        if field.required and scenario.parameters.get(field.name) in (None, "")
    ]
    hard_constraints: list[ValidationIssue] = []
    soft_penalties: list[ValidationIssue] = []
    estimated_customers = 0
    estimated_routes = 1

    if scenario.scenario_type == "custom":
        changes = scenario.parameters.get("changes") or []
        if not isinstance(changes, list) or not changes:
            cost = scenario.parameters.get("cost")
            if not isinstance(cost, dict) or not any(value is not None for value in cost.values()):
                hard_constraints.append(
                    ValidationIssue(
                        field="changes",
                        scope="scenario",
                        severity="hard",
                        message="Custom scenarios need at least one change or a cost override.",
                    )
                )
        else:
            for index, change in enumerate(changes):
                if not isinstance(change, dict):
                    hard_constraints.append(
                        ValidationIssue(
                            field=f"changes[{index}]",
                            scope="scenario",
                            severity="hard",
                            message="Each change must be an object with a kind.",
                        )
                    )
                    continue
                kind = change.get("kind")
                if kind == "add_deliveries":
                    deliveries = change.get("deliveries") or []
                    if not deliveries:
                        hard_constraints.append(
                            ValidationIssue(
                                field=f"changes[{index}].deliveries",
                                scope="customer",
                                severity="hard",
                                message="Add-deliveries changes require at least one delivery pin.",
                            )
                        )
                    else:
                        estimated_customers += len(deliveries)
                        for delivery_index, delivery in enumerate(deliveries):
                            if not isinstance(delivery, dict):
                                continue
                            for coord in ("lat", "lng"):
                                if delivery.get(coord) is None:
                                    hard_constraints.append(
                                        ValidationIssue(
                                            field=f"changes[{index}].deliveries[{delivery_index}].{coord}",
                                            scope="customer",
                                            severity="hard",
                                            message=f"Delivery is missing {coord}.",
                                        )
                                    )
                elif kind == "driver_count_change":
                    delta = int(change.get("driver_delta") or 0)
                    if delta == 0:
                        soft_penalties.append(
                            ValidationIssue(
                                field=f"changes[{index}].driver_delta",
                                scope="scenario",
                                severity="soft",
                                message="Driver delta is zero and will not change fleet size.",
                            )
                        )
                    if delta < -3:
                        soft_penalties.append(
                            ValidationIssue(
                                field=f"changes[{index}].driver_delta",
                                scope="scenario",
                                severity="soft",
                                message="Removing more than 3 drivers may make the network infeasible.",
                            )
                        )
                    estimated_routes = max(estimated_routes, abs(delta) + 1)
                elif kind == "delivery_frequency_day_change":
                    if not change.get("target_day"):
                        hard_constraints.append(
                            ValidationIssue(
                                field=f"changes[{index}].target_day",
                                scope="customer",
                                severity="hard",
                                message="Day-change requires a target_day.",
                            )
                        )
                    estimated_customers += 6
                elif kind == "facility_move":
                    location = change.get("new_depot_location")
                    if (
                        not isinstance(location, dict)
                        or location.get("lat") is None
                        or location.get("lng") is None
                    ):
                        hard_constraints.append(
                            ValidationIssue(
                                field=f"changes[{index}].new_depot_location",
                                scope="depot",
                                severity="hard",
                                message="Facility move requires a new depot lat/lng.",
                            )
                        )
                    estimated_routes = max(estimated_routes, 3)
                else:
                    hard_constraints.append(
                        ValidationIssue(
                            field=f"changes[{index}].kind",
                            scope="scenario",
                            severity="hard",
                            message=f"Unsupported change kind: {kind}",
                        )
                    )
        if isinstance(scenario.parameters.get("cost"), dict):
            soft_penalties.append(
                ValidationIssue(
                    field="cost",
                    scope="scenario",
                    severity="soft",
                    message="Cost overrides apply to both baseline and scenario costing for a fair comparison.",
                )
            )

    valid = not missing and not hard_constraints
    return ValidationResponse(
        scenario_id=scenario.scenario_id,
        valid=valid,
        hard_constraints=hard_constraints,
        soft_penalties=soft_penalties,
        missing_fields=missing,
        inferred_fields=[],
        estimated_affected_customers=estimated_customers,
        estimated_affected_routes=estimated_routes,
        summary=(
            "Scenario parameters are complete and ready to run."
            if valid
            else "Scenario is missing required fields or has hard validation errors."
        ),
    )
