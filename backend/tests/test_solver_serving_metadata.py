from __future__ import annotations

from backend.services import solver as solver_module


class Value:
    def __init__(self, payload):
        self.payload = payload

    def as_dict(self):
        return self.payload


def test_serving_metadata_resolves_entity_and_model_version(monkeypatch) -> None:
    solver_module._serving_metadata_cache.clear()

    class Endpoints:
        def get(self, *, name):
            assert name == "route-solver"
            return Value({
                "config": {
                    "served_entities": [{
                        "name": "route-solver-entity",
                        "entity_name": "catalog.schema.route_solver",
                        "entity_version": "7",
                    }]
                }
            })

    workspace = type("Workspace", (), {"serving_endpoints": Endpoints()})()
    metadata = solver_module._serving_endpoint_metadata(
        workspace,
        "route-solver",
        Value({"request_id": "request-1", "served_model_name": "route-solver-entity"}),
    )

    assert metadata["request_id"] == "request-1"
    assert metadata["served_entity_name"] == "route-solver-entity"
    assert metadata["model_entity_name"] == "catalog.schema.route_solver"
    assert metadata["model_entity_version"] == "7"
