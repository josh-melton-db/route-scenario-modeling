from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


FacilityType = Literal["distribution_center", "depot"]
EndpointType = Literal["facility", "market", "customer"]
LaneType = Literal["LINEHAUL", "MARKET", "DELIVERY"]
PlanType = Literal["demand", "capacity"]


class NetworkModel(BaseModel):
    """Immutable, strict contract shared by synthetic inputs and network planning."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class NetworkRegion(NetworkModel):
    region_id: str
    region_name: str


class NetworkFacility(NetworkModel):
    facility_id: str
    facility_name: str
    facility_type: FacilityType
    region_id: str
    parent_facility_id: str | None = None
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    timezone: str
    active: bool = True

    @model_validator(mode="after")
    def validate_parent(self) -> "NetworkFacility":
        if self.facility_type == "distribution_center" and self.parent_facility_id is not None:
            raise ValueError("Distribution centers cannot have a parent facility.")
        if self.facility_type == "depot" and not self.parent_facility_id:
            raise ValueError("Depots require a parent distribution center.")
        return self


class FacilityHierarchy(NetworkModel):
    ancestor_id: str
    ancestor_type: Literal["region", "facility"]
    descendant_facility_id: str
    relationship_type: Literal["region_contains", "distribution_center_serves"]
    depth: int = Field(ge=1)


class NetworkMarket(NetworkModel):
    market_id: str
    market_name: str
    region_id: str
    primary_depot_id: str
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class NetworkCustomer(NetworkModel):
    customer_id: str
    customer_name: str
    customer_tier: Literal["strategic", "key", "standard"]
    region_id: str
    distribution_center_id: str
    depot_id: str
    market_id: str
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class NetworkLane(NetworkModel):
    lane_id: str
    lane_name: str
    lane_type: LaneType
    origin_endpoint_id: str
    origin_endpoint_type: EndpointType
    destination_endpoint_id: str
    destination_endpoint_type: EndpointType
    mode: Literal["ground"] = "ground"
    distance_miles: float = Field(ge=0)
    transit_minutes: int = Field(ge=0)
    active: bool = True

    @model_validator(mode="after")
    def validate_lane_endpoints(self) -> "NetworkLane":
        endpoint_types = (
            self.origin_endpoint_type,
            self.destination_endpoint_type,
        )
        expected = {
            "LINEHAUL": ("facility", "facility"),
            "MARKET": ("facility", "market"),
            "DELIVERY": ("facility", "customer"),
        }[self.lane_type]
        if endpoint_types != expected:
            raise ValueError(
                f"{self.lane_type} lanes require {expected[0]} -> {expected[1]} endpoints."
            )
        if self.origin_endpoint_id == self.destination_endpoint_id:
            raise ValueError("Lane origin and destination must differ.")
        return self


class ExternalPlanVersion(NetworkModel):
    plan_version_id: str
    plan_id: str
    revision: int = Field(ge=1)
    plan_type: PlanType
    display_name: str
    source_system: str
    published_at: datetime
    as_of_date: date
    horizon_start: date
    horizon_end: date
    time_grain: Literal["day"] = "day"
    unit: Literal["cases"] = "cases"
    status: Literal["published"] = "published"
    record_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_horizon(self) -> "ExternalPlanVersion":
        if self.horizon_end < self.horizon_start:
            raise ValueError("Plan horizon end must not precede its start.")
        return self


class DemandPlanDaily(NetworkModel):
    demand_plan_version_id: str
    service_date: date
    region_id: str
    distribution_center_id: str
    depot_id: str
    market_id: str
    customer_id: str
    demand_units: int = Field(ge=0)


class FacilityCapacityDaily(NetworkModel):
    capacity_plan_version_id: str
    service_date: date
    facility_id: str
    capacity_units: int = Field(ge=0)


class LaneCapacityDaily(NetworkModel):
    capacity_plan_version_id: str
    service_date: date
    lane_id: str
    capacity_units: int = Field(ge=0)


class BaselineNetworkFlowDaily(NetworkModel):
    demand_plan_version_id: str
    capacity_plan_version_id: str
    service_date: date
    lane_id: str
    lane_type: LaneType
    assigned_units: int = Field(ge=0)


NETWORK_TABLE_MODELS: dict[str, type[NetworkModel]] = {
    "dim_regions": NetworkRegion,
    "dim_facilities": NetworkFacility,
    "facility_hierarchy": FacilityHierarchy,
    "dim_markets": NetworkMarket,
    "dim_network_customers": NetworkCustomer,
    "dim_network_lanes": NetworkLane,
    "demand_plan_versions": ExternalPlanVersion,
    "demand_plan_daily": DemandPlanDaily,
    "capacity_plan_versions": ExternalPlanVersion,
    "facility_capacity_daily": FacilityCapacityDaily,
    "lane_capacity_daily": LaneCapacityDaily,
    "baseline_network_flow_daily": BaselineNetworkFlowDaily,
}
