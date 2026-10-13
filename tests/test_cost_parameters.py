from route_opt.cost import CostParameters


def test_merged_ignores_blank_overrides_and_preserves_field_types() -> None:
    # Spark-written override rows store all-null columns as "".
    params = CostParameters().merged({
        "overtime_threshold_minutes": "",
        "labor_regular_hour": "90",
        "max_route_minutes": 540.0,
        "unknown": 1,
    })
    assert params.overtime_threshold_minutes == 480
    assert params.labor_regular_hour == 90.0
    assert params.max_route_minutes == 540
    assert isinstance(params.max_route_minutes, int)
