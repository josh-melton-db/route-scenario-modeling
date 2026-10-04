from fastapi.testclient import TestClient

from backend.main import app
from backend.services.baseline_service import baseline_service
from backend.tests.network_run_helpers import run_network_scenario


def test_scenario_create_uses_pointer_and_option_summary(monkeypatch) -> None:
    client = TestClient(app)
    options = client.get('/api/network/options').json()

    def fail_if_full_state_is_loaded():
        raise AssertionError('scenario create must not load the full baseline snapshot')

    monkeypatch.setattr(baseline_service, 'get_state', fail_if_full_state_is_loaded)
    created = client.post('/api/network/scenarios', json={
        'scenario_name': 'Fast create regression',
        'demand_plan_version_id': options['default_demand_plan_version_id'],
        'capacity_plan_version_id': options['default_capacity_plan_version_id'],
        'horizon_start': options['default_horizon_start'],
        'horizon_end': options['default_horizon_end'],
        'region_id': options['default_region_id'],
    })
    assert created.status_code == 201, created.text
    scenario_id = created.json()['scenario_id']
    assert scenario_id
    assert client.delete(f'/api/network/scenarios/{scenario_id}').status_code == 204


def test_real_regional_run_promotes_inherits_and_resets_without_rewriting_history() -> None:
    """Exercise real API/services/solver on the national fixture, not response mocks."""
    client = TestClient(app)
    state = client.get('/api/network/baseline')
    assert state.status_code == 200
    original = client.post('/api/network/baseline/reset').json()
    options = client.get('/api/network/options').json()
    params = {
        'demand_plan_version_id': options['default_demand_plan_version_id'],
        'capacity_plan_version_id': options['default_capacity_plan_version_id'],
        'horizon_start': options['default_horizon_start'],
        'horizon_end': options['default_horizon_start'],
        'region_id': 'REGION_TOLA',
    }
    initial_global = client.get('/api/network/overview', params={**params, 'region_id': 'ALL'}).json()
    created = client.post('/api/network/scenarios', json={
        **params,
        'scenario_name': 'Baseline API integration',
        'assumptions': {'tariffs': [{
            'rule_id': 'api-lifecycle-tariff', 'origin_country': 'MX',
            'destination_country': 'US', 'effective_start': params['horizon_start'],
            'effective_end': params['horizon_end'], 'amount_per_case': 5,
        }]},
    })
    assert created.status_code == 201, created.text
    scenario_id = created.json()['scenario_id']
    solved = run_network_scenario(client, scenario_id)
    result = solved.json()['result']
    run_id = result['run_id']
    historical = client.get(f'/api/network/runs/{run_id}').json()
    proposed = client.post('/api/network/baseline/proposals', json={'run_id': run_id})
    assert proposed.status_code == 200, proposed.text
    try:
        accepted = client.post(f"/api/network/baseline/proposals/{proposed.json()['proposal_id']}/accept")
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()['active_run_id'] == run_id
        assert accepted.json()['active_revision_id'] != original['original_revision_id']
        assert accepted.json()['route_coverage']['ready'] is False
        accepted_options = client.get('/api/network/options').json()
        assert accepted_options['default_capacity_plan_version_id'] == params['capacity_plan_version_id']
        overview = client.get('/api/network/overview', params=params)
        assert overview.status_code == 200, overview.text
        assert overview.json()['kpis'] == result['overview']['kpis']
        full = client.get('/api/network/overview', params={**params, 'region_id': 'ALL'}).json()
        assert full['kpis']['demand_units'] == initial_global['kpis']['demand_units']
        assert len(full['facilities']) == len(initial_global['facilities'])
        # A new scenario takes the accepted immutable source, not the old story.
        child = client.post('/api/network/scenarios', json={**params, 'scenario_name': 'Inherited accepted plan'})
        assert child.status_code == 201, child.text
        assert child.json()['source_baseline_revision_id'] == accepted.json()['active_revision_id']
        assert child.json()['assumptions']['tariffs'] == created.json()['assumptions']['tariffs']
        child_run = run_network_scenario(client, child.json()['scenario_id'])
        assert child_run.json()['result']['baseline_overview']['kpis'] == result['overview']['kpis']
        assert client.post('/api/network/baseline/proposals', json={'run_id': run_id}).status_code == 409
        assert client.get(f'/api/network/runs/{run_id}').json() == historical
        baseline_plan = client.get('/api/network/baseline/plan-run', params=params)
        assert baseline_plan.status_code == 200, baseline_plan.text
        baseline_run_id = baseline_plan.json()['run_id']
        assert baseline_run_id.startswith('baseline-plan-run.')
        compact_baseline = baseline_plan.json()
        compact_baseline.pop('charge_details', None)
        compact_baseline.pop('baseline_charge_details', None)
        assert client.get(f'/api/network/runs/{baseline_run_id}').json() == compact_baseline
        assert client.get('/api/network/baseline/plan-run', params={**params, 'horizon_start': 'bad-date'}).status_code == 422
    finally:
        restored = client.post('/api/network/baseline/reset')
        assert restored.status_code == 200, restored.text
    assert restored.json()['active_revision_id'] == original['original_revision_id']
    assert client.get('/api/network/overview', params={**params, 'region_id': 'ALL'}).json()['kpis'] == initial_global['kpis']
    assert client.get(f'/api/network/runs/{run_id}').json() == historical
