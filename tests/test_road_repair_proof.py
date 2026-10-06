import copy

import pytest

from route_opt.road_repair_proof import build_repair_proof, verify_repair_proof


DEPOTS = {"DALLAS"}


def _customer(customer_id="NET-CUST-1", depot_id="DALLAS", lat=32.0):
    return {
        "customer_id": customer_id,
        "depot_id": depot_id,
        "lat": lat,
        "lng": -96.0,
        "active": True,
    }


def _repaired(source):
    row = copy.deepcopy(source)
    row.update({
        "lat": 32.001,
        "lng": -96.001,
        "road_access_lat": 32.001,
        "road_access_lng": -96.001,
        "road_snap_distance_miles": 0.1,
        "road_reachability_status": "validated",
    })
    return row


def _proof(source, repaired):
    return build_repair_proof(
        source_customers=source,
        repaired_customers=repaired,
        depot_ids=DEPOTS,
        coverage_id="texas",
        artifact_version="v1",
    )


def test_proof_hash_is_typed_and_scoped_to_covered_generated_customers():
    covered = _customer()
    source = [covered, _customer("NET-CUST-2", "CHICAGO"), _customer("OTHER", "DALLAS")]
    proof = _proof(source, [_repaired(covered)])

    changed_outside_scope = copy.deepcopy(source)
    changed_outside_scope[1]["lat"] = 99.0
    assert verify_repair_proof(
        proof,
        current_customers=changed_outside_scope,
        coverage_id="texas",
        artifact_version="v1",
        depot_ids=DEPOTS,
    ) == proof["repaired_customers"]

    changed_scope = copy.deepcopy(source)
    changed_scope[0]["active"] = False
    with pytest.raises(ValueError, match="source customer hash"):
        verify_repair_proof(
            proof,
            current_customers=changed_scope,
            coverage_id="texas",
            artifact_version="v1",
            depot_ids=DEPOTS,
        )


def test_proof_rejects_payload_tampering_and_non_access_final_coordinates():
    source = [_customer()]
    repaired = [_repaired(source[0])]
    proof = _proof(source, repaired)
    proof["repaired_customers"][0]["lat"] = 33.0

    with pytest.raises(ValueError, match="unvalidated customers"):
        verify_repair_proof(
            proof,
            current_customers=source,
            coverage_id="texas",
            artifact_version="v1",
            depot_ids=DEPOTS,
        )
