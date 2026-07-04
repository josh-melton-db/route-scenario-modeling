from backend.services.run_simulator import RunSimulator


def test_run_simulator_terminal_status(monkeypatch) -> None:
    monkeypatch.setenv("RUN_QUEUED_DURATION_SECONDS", "0")
    monkeypatch.setenv("RUN_RUNNING_DURATION_SECONDS", "0")

    simulator = RunSimulator()
    started = simulator.create_run("scn_test", "succeeded")
    status = simulator.get_run_status(started.run_id)

    assert status.status == "succeeded"
    assert status.progress_pct == 100
    assert status.completed_at is not None
    assert all(stage.status == "completed" for stage in status.stages)


def test_run_simulator_infeasible_status(monkeypatch) -> None:
    monkeypatch.setenv("RUN_QUEUED_DURATION_SECONDS", "0")
    monkeypatch.setenv("RUN_RUNNING_DURATION_SECONDS", "0")

    simulator = RunSimulator()
    started = simulator.create_run("scn_test", "infeasible")
    status = simulator.get_run_status(started.run_id)

    assert status.status == "infeasible"
    assert status.message == "Optimization completed with infeasible constraints."
