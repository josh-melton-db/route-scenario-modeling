from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from ..models import NetworkScenario, NetworkScenarioResult
from .network_overview import NetworkRows


@dataclass(frozen=True)
class NetworkRunSnapshot:
    scenario: NetworkScenario
    result: NetworkScenarioResult
    network_rows: NetworkRows
    flow_rows: list[dict[str, Any]]
    cost_rows: list[dict[str, Any]]

    def copy(self) -> "NetworkRunSnapshot":
        return NetworkRunSnapshot(
            scenario=self.scenario.model_copy(deep=True),
            result=self.result.model_copy(deep=True),
            network_rows=deepcopy(self.network_rows),
            flow_rows=deepcopy(self.flow_rows),
            cost_rows=deepcopy(self.cost_rows),
        )
