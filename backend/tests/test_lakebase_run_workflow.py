from __future__ import annotations

from backend.models import ScenarioDefinition, ValidationIssue, ValidationResponse
from backend.services.solve_runs import SolveRunManager


class _InvalidPrecheckStore:
    def __init__(self) -> None:
        self.scenario = ScenarioDefinition(
            scenario_id="scn_invalid",
            scenario_name="Invalid custom scenario",
            scenario_type="custom",
            baseline_scenario_id="baseline",
            depot_id="DPT_NORTH",
            delivery_day="Tuesday",
            parameters={"changes": []},
            status="draft",
        )
        self.events: list[tuple[str, str]] = []

    def claim_solve_run(self, run_id: str, worker_id: str) -> ScenarioDefinition:
        self.events.append(("claim", run_id))
        return self.scenario

    def start_run_stage(self, run_id: str, stage_id: str, message: str, worker_id: str) -> None:
        self.events.append(("start", stage_id))

    def validate_scenario(self, scenario_id: str) -> ValidationResponse:
        self.events.append(("validate", scenario_id))
        return ValidationResponse(
            scenario_id=scenario_id,
            valid=False,
            hard_constraints=[
                ValidationIssue(
                    field="changes",
                    scope="scenario",
                    severity="hard",
                    message="Custom scenarios need at least one change or a cost override.",
                )
            ],
            soft_penalties=[],
            missing_fields=[],
            inferred_fields=[],
            estimated_affected_customers=0,
            estimated_affected_routes=1,
            summary="Scenario is missing required fields or has hard validation errors.",
        )

    def record_run_validation(
        self,
        run_id: str,
        validation: ValidationResponse,
        worker_id: str,
    ) -> None:
        self.events.append(("validation", validation.scenario_id))

    def fail_solve_run(self, run_id: str, stage_id: str, message: str, worker_id: str, **kwargs) -> None:
        self.events.append(("failed", stage_id))

    def set_scenario_status(self, scenario_id: str, status: str) -> None:
        self.events.append(("scenario_status", status))


def test_lakebase_precheck_fails_before_solver(monkeypatch) -> None:
    store = _InvalidPrecheckStore()
    manager = SolveRunManager()

    import backend.services.solve_runs as solve_runs_module

    monkeypatch.setattr(solve_runs_module, "get_store", lambda: store)
    monkeypatch.setattr(
        solve_runs_module.solver_service,
        "prepare_scenario_inputs",
        lambda scenario: (_ for _ in ()).throw(AssertionError("solver preparation must not run")),
    )

    manager._execute_lakebase_run("run_invalid")

    assert store.events == [
        ("claim", "run_invalid"),
        ("start", "precheck"),
        ("validate", "scn_invalid"),
        ("validation", "scn_invalid"),
        ("failed", "precheck"),
        ("scenario_status", "draft"),
    ]
