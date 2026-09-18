from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import HTTPException

from route_opt.rates import (
    contract_detail_from_legacy,
    contract_summary,
    quote_contract,
)

from ..models import (
    RateAccessorialTemplate,
    RateAuthoringOptions,
    RateContractCreateRequest,
    RateContractDetail,
    RateContractSummary,
    RateDraftUpdateRequest,
    RatePublishRequest,
    RateQuote,
    RateQuoteRequest,
    RateValidationIssue,
    RateValidationResponse,
    RateVersionCreateRequest,
)


def _writer(store: Any, method_name: str) -> Any:
    method = getattr(store, method_name, None)
    if not callable(method):
        raise HTTPException(
            status_code=501,
            detail="Rate authoring is unavailable for the selected data backend.",
        )
    return method


def list_rate_contract_details(store: Any) -> list[RateContractDetail]:
    rich_loader = getattr(store, "list_rate_contract_details", None)
    if callable(rich_loader):
        details = rich_loader()
        if details:
            return [RateContractDetail.model_validate(row) for row in details]

    carriers = {row.carrier_id: row.carrier_name for row in store.list_carriers()}
    freshness = datetime.now(timezone.utc).isoformat()
    return [
        RateContractDetail.model_validate(
            contract_detail_from_legacy(
                contract.model_dump(mode="json"),
                carriers.get(contract.carrier_id, contract.carrier_id),
                freshness_at=freshness,
            )
        )
        for contract in store.list_carrier_contracts()
    ]


def list_rate_contract_summaries(
    store: Any, service_date: str
) -> list[RateContractSummary]:
    details_by_contract: dict[str, list[RateContractDetail]] = {}
    for detail in list_rate_contract_details(store):
        details_by_contract.setdefault(detail.contract_id, []).append(detail)

    selected_details: list[RateContractDetail] = []
    for details in details_by_contract.values():
        effective = [
            detail
            for detail in details
            if contract_summary(detail.model_dump(mode="json"), service_date)["status"]
            == "published"
        ]
        selected_details.append(
            max(
                effective or details,
                key=lambda detail: detail.version.version_number,
            )
        )
    summaries = [
        RateContractSummary.model_validate(
            {
                **contract_summary(detail.model_dump(mode="json"), service_date),
                "draft_version": next(
                    (
                        row.version.model_dump(mode="json")
                        for row in details_by_contract[detail.contract_id]
                        if row.version.status == "draft"
                    ),
                    None,
                ),
            }
        )
        for detail in selected_details
    ]
    return sorted(summaries, key=lambda row: (row.carrier_name, row.contract_name))


def list_rate_authoring_options(store: Any) -> RateAuthoringOptions:
    details = list_rate_contract_details(store)
    destinations = sorted(
        {
            rule.destination.strip()
            for detail in details
            for rule in detail.lane_rates
            if rule.destination.strip() and rule.destination.strip() != "*"
        },
        key=str.casefold,
    )
    accessorials_by_code: dict[str, RateAccessorialTemplate] = {}
    for detail in details:
        for rule in detail.accessorials:
            code = rule.code.strip().upper()
            accessorials_by_code.setdefault(
                code,
                RateAccessorialTemplate(
                    code=code,
                    name=rule.name,
                    charge_type=rule.charge_type,
                    rate=rule.rate,
                    description=rule.description,
                ),
            )
    return RateAuthoringOptions(
        destinations=destinations,
        accessorials=sorted(
            accessorials_by_code.values(), key=lambda row: row.name.casefold()
        ),
    )


def get_rate_contract_detail(
    store: Any, contract_id: str, version_id: str | None = None
) -> RateContractDetail:
    all_details = list_rate_contract_details(store)
    detail = next(
        (
            row
            for row in all_details
            if row.contract_id == contract_id
            and (version_id is None or row.version.version_id == version_id)
        ),
        None,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Rate contract version not found.")
    history = sorted(
        (row.version for row in all_details if row.contract_id == contract_id),
        key=lambda version: version.version_number,
        reverse=True,
    )
    return detail.model_copy(update={"version_history": history})


def create_rate_contract(
    store: Any, request: RateContractCreateRequest
) -> RateContractDetail:
    detail = _writer(store, "create_rate_contract")(request)
    return get_rate_contract_detail(
        store, detail.contract_id, detail.version.version_id
    )


def create_rate_version(
    store: Any, contract_id: str, request: RateVersionCreateRequest
) -> RateContractDetail:
    detail = _writer(store, "create_rate_version")(contract_id, request)
    return get_rate_contract_detail(store, contract_id, detail.version.version_id)


def save_rate_draft(
    store: Any,
    contract_id: str,
    version_id: str,
    request: RateDraftUpdateRequest,
) -> RateContractDetail:
    existing = get_rate_contract_detail(store, contract_id, version_id)
    if existing.version.status != "draft":
        raise HTTPException(status_code=409, detail="Published versions are immutable.")
    _writer(store, "replace_rate_draft")(contract_id, version_id, request)
    return get_rate_contract_detail(store, contract_id, version_id)


def _parsed_date(
    value: str | None,
    field: str,
    issues: list[RateValidationIssue],
) -> date | None:
    if not value:
        issues.append(
            RateValidationIssue(
                severity="error",
                code="required_date",
                field=field,
                message="An effective date is required.",
            )
        )
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        issues.append(
            RateValidationIssue(
                severity="error",
                code="invalid_date",
                field=field,
                message="Enter a valid calendar date.",
            )
        )
        return None


def validate_rate_contract_detail(
    detail: RateContractDetail,
    all_details: list[RateContractDetail],
) -> RateValidationResponse:
    issues: list[RateValidationIssue] = []

    def issue(
        code: str,
        field: str,
        message: str,
        severity: Literal["error", "warning"] = "error",
    ) -> None:
        issues.append(
            RateValidationIssue(
                severity=severity,
                code=code,
                field=field,
                message=message,
            )
        )

    if detail.version.status != "draft":
        issue("immutable_version", "version.status", "Only draft versions can be validated for publication.")
    if not detail.contract_name.strip():
        issue("required", "contract_name", "Contract name is required.")
    if len(detail.version.currency.strip()) != 3:
        issue("invalid_currency", "version.currency", "Currency must be a three-letter code.")
    if not (detail.version.change_reason or "").strip():
        issue("required", "version.change_reason", "Describe what changed before publishing.")

    effective_start = _parsed_date(detail.version.effective_start, "version.effective_start", issues)
    effective_end = _parsed_date(detail.version.effective_end, "version.effective_end", issues)
    if effective_start and effective_end and effective_start > effective_end:
        issue("invalid_range", "version.effective_end", "Effective end must be on or after effective start.")

    if not detail.lane_rates:
        issue("required_lane", "lane_rates", "Add at least one lane rate before publishing.")

    seen_rule_ids: set[str] = set()
    for family, rules in (
        ("lane_rates", detail.lane_rates),
        ("fuel_surcharges", detail.fuel_surcharges),
        ("accessorials", detail.accessorials),
        ("volume_tiers", detail.volume_tiers),
        ("capacity_commitments", detail.capacity_commitments),
    ):
        for index, rule in enumerate(rules):
            if not rule.rule_id.strip():
                issue("required", f"{family}.{index}.rule_id", "Rule ID is required.")
            elif rule.rule_id in seen_rule_ids:
                issue("duplicate_rule_id", f"{family}.{index}.rule_id", "Rule IDs must be unique across the version.")
            seen_rule_ids.add(rule.rule_id)

    lane_keys: set[tuple[str, str, int]] = set()
    for index, rule in enumerate(detail.lane_rates):
        prefix = f"lane_rates.{index}"
        if not rule.lane_name.strip() or not rule.origin.strip() or not rule.destination.strip():
            issue("required", prefix, "Lane name, origin, and destination are required.")
        key = (rule.origin.strip().casefold(), rule.destination.strip().casefold(), rule.priority)
        if key in lane_keys:
            issue("duplicate_lane", prefix, "Origin, destination, and priority must be unique.")
        lane_keys.add(key)
        for field_name in ("flat_rate", "rate_per_mile", "rate_per_stop", "included_stops", "minimum_charge"):
            if float(getattr(rule, field_name)) < 0:
                issue("negative_value", f"{prefix}.{field_name}", "Rates and quantities cannot be negative.")

    fuel_windows: list[tuple[int, date, date]] = []
    for index, rule in enumerate(detail.fuel_surcharges):
        prefix = f"fuel_surcharges.{index}"
        if not rule.name.strip():
            issue("required", f"{prefix}.name", "Fuel schedule name is required.")
        if rule.rate_pct < 0:
            issue("negative_value", f"{prefix}.rate_pct", "Fuel surcharge cannot be negative.")
        fuel_start = _parsed_date(rule.effective_start, f"{prefix}.effective_start", issues)
        fuel_end = _parsed_date(rule.effective_end, f"{prefix}.effective_end", issues)
        if fuel_start and fuel_end and fuel_start > fuel_end:
            issue("invalid_range", f"{prefix}.effective_end", "Fuel end must be on or after its start.")
        if effective_start and fuel_start and fuel_start < effective_start:
            issue("outside_version", f"{prefix}.effective_start", "Fuel schedule starts before the contract version.")
        if effective_end and fuel_end and fuel_end > effective_end:
            issue("outside_version", f"{prefix}.effective_end", "Fuel schedule ends after the contract version.")
        if fuel_start and fuel_end:
            fuel_windows.append((index, fuel_start, fuel_end))
    ordered_fuel_windows = sorted(fuel_windows, key=lambda row: row[1])
    for position, (index, fuel_start, _) in enumerate(ordered_fuel_windows):
        if position == 0:
            continue
        previous_index, _, previous_end = ordered_fuel_windows[position - 1]
        if fuel_start <= previous_end:
            issue(
                "fuel_date_overlap",
                f"fuel_surcharges.{index}.effective_start",
                f"This schedule overlaps fuel schedule {previous_index + 1}.",
            )

    accessorial_codes: set[str] = set()
    for index, rule in enumerate(detail.accessorials):
        prefix = f"accessorials.{index}"
        code = rule.code.strip().upper()
        if not code or not rule.name.strip():
            issue("required", prefix, "Accessorial code and name are required.")
        if code in accessorial_codes:
            issue("duplicate_accessorial", f"{prefix}.code", "Accessorial codes must be unique.")
        accessorial_codes.add(code)
        if rule.rate < 0:
            issue("negative_value", f"{prefix}.rate", "Accessorial rate cannot be negative.")

    tier_groups: dict[tuple[str, str], list[tuple[int, Any]]] = {}
    for index, rule in enumerate(detail.volume_tiers):
        prefix = f"volume_tiers.{index}"
        if not rule.name.strip():
            issue("required", f"{prefix}.name", "Tier name is required.")
        if rule.min_volume < 0 or (rule.max_volume is not None and rule.max_volume < 0):
            issue("negative_value", prefix, "Tier bounds cannot be negative.")
        if rule.max_volume is not None and rule.min_volume > rule.max_volume:
            issue("invalid_range", f"{prefix}.max_volume", "Maximum volume must be at least the minimum.")
        if rule.discount_pct < 0 or rule.discount_pct > 100:
            issue("invalid_discount", f"{prefix}.discount_pct", "Discount must be between 0% and 100%.")
        tier_groups.setdefault((rule.period, rule.unit), []).append((index, rule))
    for rows in tier_groups.values():
        ordered = sorted(rows, key=lambda item: item[1].min_volume)
        if ordered and ordered[0][1].min_volume != 0:
            issue("tier_gap", f"volume_tiers.{ordered[0][0]}.min_volume", "The first tier must start at 0.")
        for position, (index, rule) in enumerate(ordered):
            if rule.max_volume is None and position != len(ordered) - 1:
                issue("open_tier_not_last", f"volume_tiers.{index}.max_volume", "Only the final tier can be open-ended.")
            if position == 0:
                continue
            previous_index, previous = ordered[position - 1]
            if previous.max_volume is None:
                issue("tier_overlap", f"volume_tiers.{index}.min_volume", "This tier overlaps an open-ended tier.")
            elif rule.min_volume <= previous.max_volume:
                issue("tier_overlap", f"volume_tiers.{index}.min_volume", f"This tier overlaps tier {previous_index + 1}.")
            elif rule.min_volume > previous.max_volume + 1:
                issue("tier_gap", f"volume_tiers.{index}.min_volume", f"There is a gap after tier {previous_index + 1}.")

    commitment_keys: set[tuple[str, str]] = set()
    for index, rule in enumerate(detail.capacity_commitments):
        prefix = f"capacity_commitments.{index}"
        if not rule.name.strip():
            issue("required", f"{prefix}.name", "Commitment name is required.")
        for field_name in ("committed_quantity", "capacity_quantity", "current_utilization", "shortfall_rate", "overage_rate"):
            if float(getattr(rule, field_name)) < 0:
                issue("negative_value", f"{prefix}.{field_name}", "Commitment quantities and rates cannot be negative.")
        if rule.committed_quantity > rule.capacity_quantity:
            issue("commitment_above_capacity", f"{prefix}.committed_quantity", "Committed quantity cannot exceed maximum capacity.")
        key = (rule.period, rule.unit)
        if key in commitment_keys:
            issue(
                "duplicate_commitment",
                prefix,
                "Only one commitment can use the same period and unit.",
            )
        commitment_keys.add(key)

    if effective_start and effective_end:
        for other in all_details:
            if other.contract_id != detail.contract_id or other.version.version_id == detail.version.version_id or other.version.status != "published":
                continue
            other_start = date.fromisoformat(other.version.effective_start) if other.version.effective_start else date.min
            other_end = date.fromisoformat(other.version.effective_end) if other.version.effective_end else date.max
            if effective_start <= other_end and other_start <= effective_end:
                if other_start < effective_start:
                    issue(
                        "prior_version_will_close",
                        "version.effective_start",
                        f"Version {other.version.version_number} will be end-dated {(effective_start - timedelta(days=1)).isoformat()} when this draft is published.",
                        "warning",
                    )
                else:
                    issue(
                        "published_date_overlap",
                        "version.effective_start",
                        f"Effective dates overlap published version {other.version.version_number}.",
                    )

    errors = [row for row in issues if row.severity == "error"]
    warnings = [row for row in issues if row.severity == "warning"]
    if errors:
        summary = f"Resolve {len(errors)} error{'s' if len(errors) != 1 else ''} before publishing."
    elif warnings:
        summary = f"Ready to publish with {len(warnings)} warning{'s' if len(warnings) != 1 else ''}."
    else:
        summary = "All five rule families and effective dates are ready to publish."
    return RateValidationResponse(
        contract_id=detail.contract_id,
        version_id=detail.version.version_id,
        valid=not errors,
        issues=issues,
        summary=summary,
    )


def validate_rate_draft(
    store: Any, contract_id: str, version_id: str
) -> RateValidationResponse:
    detail = get_rate_contract_detail(store, contract_id, version_id)
    return validate_rate_contract_detail(detail, list_rate_contract_details(store))


def publish_rate_draft(
    store: Any,
    contract_id: str,
    version_id: str,
    request: RatePublishRequest,
) -> RateContractDetail:
    detail = get_rate_contract_detail(store, contract_id, version_id)
    if request.change_reason.strip() and request.change_reason.strip() != (detail.version.change_reason or "").strip():
        update = RateDraftUpdateRequest(
            contract_name=detail.contract_name,
            currency=detail.version.currency,
            effective_start=detail.version.effective_start or "",
            effective_end=detail.version.effective_end or "",
            change_reason=request.change_reason.strip(),
            lane_rates=detail.lane_rates,
            fuel_surcharges=detail.fuel_surcharges,
            accessorials=detail.accessorials,
            volume_tiers=detail.volume_tiers,
            capacity_commitments=detail.capacity_commitments,
        )
        _writer(store, "replace_rate_draft")(contract_id, version_id, update)
    validation = validate_rate_draft(store, contract_id, version_id)
    if not validation.valid:
        raise HTTPException(
            status_code=422,
            detail={"message": validation.summary, "issues": [row.model_dump() for row in validation.issues]},
        )
    _writer(store, "publish_rate_draft")(
        contract_id, version_id, request.published_by.strip() or "Rate manager"
    )
    return get_rate_contract_detail(store, contract_id, version_id)


def discard_rate_draft(store: Any, contract_id: str, version_id: str) -> None:
    existing = get_rate_contract_detail(store, contract_id, version_id)
    if existing.version.status != "draft":
        raise HTTPException(status_code=409, detail="Published versions cannot be discarded.")
    _writer(store, "delete_rate_draft")(contract_id, version_id)


def preview_rate_quote(store: Any, request: RateQuoteRequest) -> RateQuote:
    detail = get_rate_contract_detail(store, request.contract_id, request.version_id)
    try:
        quote = quote_contract(
            detail.model_dump(mode="json"), request.model_dump(mode="json")
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RateQuote.model_validate(quote)
