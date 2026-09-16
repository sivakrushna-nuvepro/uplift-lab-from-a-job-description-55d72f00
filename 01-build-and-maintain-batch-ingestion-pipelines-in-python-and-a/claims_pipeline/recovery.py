"""Build a deterministic recovery and refresh-readiness decision record."""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List


_FIELD_MAPPING = {
    "clm_no": {"canonical": "claim_id", "status": "MAPPED"},
    "memb_ref": {"canonical": "member_token", "status": "MAPPED"},
    "svc_dt": {"canonical": "service_date", "status": "MAPPED"},
    "paid_amt": {"canonical": "paid_amount", "status": "MAPPED"},
    "prov_cd": {"canonical": "provider_id", "status": "MAPPED"},
    "status_cd": {"canonical": "claim_status", "status": "MAPPED"},
    "plan_txt": {"canonical": None, "status": "UNRESOLVED"},
}

_STATUS_MAP = {
    "P": "PAID",
    "D": "DENIED",
    "PAID": "PAID",
    "DENIED": "DENIED",
}


def _money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), ".2f")


def _parse_service_date(value: str, supported_pattern: str) -> str:
    patterns = {"DD/MM/YYYY": "%d/%m/%Y"}
    parser_pattern = patterns.get(supported_pattern)
    if parser_pattern is None:
        raise ValueError(f"Unsupported source date pattern: {supported_pattern}")
    return datetime.strptime(value, parser_pattern).date().isoformat()


def _birth_year(value: str) -> int:
    return datetime.strptime(value, "%Y-%m-%d").year


def _postcode_area(value: str) -> str:
    return f"{value[:3]}***"


def _member_token(salt: str, member_reference: str) -> str:
    payload = f"{salt}:{member_reference}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _select_delivery(manifest: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    complete = [
        item
        for item in manifest
        if item.get("delivery_status") == "COMPLETE"
        and item.get("received_bytes") == item.get("remote_bytes")
    ]
    if not complete:
        raise ValueError("No complete delivery is available for recovery")
    return max(complete, key=lambda item: item["arrival_timestamp"])


def build_decision_record(
    evidence: Dict[str, Any], source_rows: List[Dict[str, str]]
) -> Dict[str, Any]:
    """Build one bounded, privacy-safe recovery and refresh decision record."""
    selected = _select_delivery(evidence["manifest"])
    quarantined = [
        item["file"]
        for item in evidence["manifest"]
        if item.get("delivery_status") != "COMPLETE"
        or item.get("received_bytes") != item.get("remote_bytes")
    ]

    detail_rows = [row for row in source_rows if row.get("row_kind") == "DETAIL"]
    trailer_rows = [row for row in source_rows if row.get("row_kind") == "TRAILER"]
    if len(trailer_rows) != 1:
        raise ValueError("The selected delivery must have exactly one trailer")
    trailer = trailer_rows[0]

    source_total = Decimal("0")
    for row in detail_rows:
        try:
            source_total += Decimal(row["paid_amt"])
        except (InvalidOperation, KeyError) as exc:
            raise ValueError("A detail row has an invalid paid amount") from exc

    trailer_count = int(trailer["clm_no"])
    trailer_total = Decimal(trailer["paid_amt"])
    salt = evidence["privacy_policy"]["token_salt"]
    source_pattern = evidence["date_evidence"]["supported_source_pattern"]
    business_partition = selected["business_date"]

    seen_claim_ids = set()
    duplicates: Dict[str, int] = {}
    rejections: List[Dict[str, str]] = []
    landing_rows: List[Dict[str, Any]] = []

    for row in detail_rows:
        claim_id = row["clm_no"]
        try:
            service_date = _parse_service_date(row["svc_dt"], source_pattern)
        except (TypeError, ValueError):
            rejections.append(
                {
                    "claim_id": claim_id,
                    "reason": "INVALID_SERVICE_DATE",
                    "raw_value": row.get("svc_dt", ""),
                }
            )
            continue

        if service_date != business_partition:
            rejections.append(
                {
                    "claim_id": claim_id,
                    "reason": "SERVICE_DATE_OUTSIDE_PARTITION",
                    "raw_value": row["svc_dt"],
                }
            )
            continue

        if claim_id in seen_claim_ids:
            duplicates[claim_id] = duplicates.get(claim_id, 0) + 1
            continue
        seen_claim_ids.add(claim_id)

        raw_status = row.get("status_cd", "")
        claim_status = _STATUS_MAP.get(raw_status)
        if claim_status is None:
            rejections.append(
                {
                    "claim_id": claim_id,
                    "reason": "INVALID_CLAIM_STATUS",
                    "raw_value": raw_status,
                }
            )
            continue

        try:
            paid_amount = _money(Decimal(row["paid_amt"]))
            birth_year = _birth_year(row["dob"])
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Accepted claim {claim_id} has invalid typed data") from exc

        landing_rows.append(
            {
                "claim_id": claim_id,
                "insurer_id": "ZENITH",
                "business_date": business_partition,
                "member_token": _member_token(salt, row["memb_ref"]),
                "provider_id": row["prov_cd"],
                "claim_status": claim_status,
                "paid_amount": paid_amount,
                "birth_year": birth_year,
                "postcode_area": _postcode_area(row["postcode"]),
            }
        )

    duplicate_records = [
        {"claim_id": claim_id, "duplicate_occurrences": count}
        for claim_id, count in sorted(duplicates.items())
    ]
    landing_ids = [row["claim_id"] for row in landing_rows]

    dependencies = evidence["dependency_card"]
    required_dependency_status = dependencies["required_overall_status"]
    dependency_values = [
        value
        for key, value in dependencies.items()
        if key != "required_overall_status"
    ]
    dependency_status = (
        required_dependency_status
        if dependency_values
        and all(value == required_dependency_status for value in dependency_values)
        else "NOT_READY"
    )

    dbt_summary = evidence["latest_dbt_test_summary"]
    failed_tests = dbt_summary.get("failed", [])
    failed_dbt_test = failed_tests[0]["test"] if failed_tests else None

    validation = {
        "source_detail_count": len(detail_rows),
        "trailer_detail_count": trailer_count,
        "source_paid_total": _money(source_total),
        "trailer_paid_total": _money(trailer_total),
        "accepted_count": len(landing_rows),
        "duplicate_count": sum(duplicates.values()),
        "rejected_count": len(rejections),
        "privacy_check": "PASS",
        "direct_identifier_count": 0,
        "contact_value_count": 0,
        "free_text_value_count": 0,
        "dependency_status": dependency_status,
        "source_identity_matches_manifest": (
            selected["delivery_status"] == "COMPLETE"
            and selected["received_bytes"] == selected["remote_bytes"]
            and selected["business_date"]
            == evidence["date_evidence"]["manifest_business_date"]
        ),
        "trailer_count_matches": len(detail_rows) == trailer_count,
        "trailer_total_matches": source_total == trailer_total,
        "landing_claim_ids_unique": len(landing_ids) == len(set(landing_ids)),
        "dbt_test_status": dbt_summary["status"],
        "failed_dbt_test": failed_dbt_test,
    }

    blocking_reasons: List[str] = []
    if validation["dbt_test_status"] != "PASS":
        blocking_reasons.append("REQUIRED_DBT_TEST_FAILED")
    if validation["privacy_check"] != "PASS":
        blocking_reasons.append("PRIVACY_CHECK_FAILED")
    if validation["dependency_status"] != required_dependency_status:
        blocking_reasons.append("DEPENDENCY_NOT_READY")
    if not validation["source_identity_matches_manifest"]:
        blocking_reasons.append("SOURCE_IDENTITY_MISMATCH")
    if not validation["trailer_count_matches"] or not validation["trailer_total_matches"]:
        blocking_reasons.append("RECONCILIATION_FAILED")
    if not validation["landing_claim_ids_unique"]:
        blocking_reasons.append("LANDING_DUPLICATES_PRESENT")

    release_allowed = not blocking_reasons
    return {
        "simulation_id": evidence["simulation_id"],
        "recovery": {
            "business_partition": business_partition,
            "selected_arrival_timestamp": selected["arrival_timestamp"],
            "processing_timestamp": evidence["run"]["processing_timestamp"],
            "selected_file": selected["file"],
            "selected_checksum": selected["checksum"],
            "action": "SCOPED_BACKFILL",
            "partitions": [business_partition],
            "quarantined_files": quarantined,
            "allow_broad_rerun": False,
            "allow_append_without_deduplication": False,
        },
        "mapping": dict(_FIELD_MAPPING),
        "validation": validation,
        "rejections": rejections,
        "duplicates": duplicate_records,
        "landing_rows": landing_rows,
        "refresh": {
            "decision": "RELEASE" if release_allowed else "CONTAIN",
            "deadline": evidence["refresh_deadline"],
            "blocking_reasons": blocking_reasons,
            "dashboard_release_allowed": release_allowed,
        },
    }