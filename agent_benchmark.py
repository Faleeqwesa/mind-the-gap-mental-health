#!/usr/bin/env python3
"""Reproducible 20-case evaluation of the existing Mind the Gap Render agent.

Uses only the existing POST /analyze request and the bundled CDC snapshot.
No new API, judge, credentials, or infrastructure are used.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import re
import statistics
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_API = "https://cdc-mental-health-agent-api.onrender.com"
CASES_FILE = ROOT / "agent_benchmark_cases.json"
DATA_FILE = ROOT / "mental_health_cdi.csv"
RESULT_FILE = ROOT / "agent_benchmark_results.json"
CSV_FILE = ROOT / "agent_benchmark_cases.csv"
SUMMARY_FILE = ROOT / "agent_benchmark_summary.json"
SVG_FILE = ROOT / "agent_benchmark.svg"
REVIEW_FILE = ROOT / "agent_benchmark_review.csv"
TOLERANCE = 0.051
VALID_CASES = 18
CHECKS_PER_CASE = 20
BASELINE_PER_CASE = 9

DIRECTION_TERMS = {
    "up": ("up", "increas", "rose", "higher", "increased"),
    "down": ("down", "decreas", "fell", "lower", "decreased"),
    "unchanged": ("unchanged", "stable", "flat", "steady"),
}


def read_cases(path=CASES_FILE):
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    cases = document["cases"]
    if len(cases) != 20 or len({case["id"] for case in cases}) != 20:
        raise ValueError("The fixed benchmark file must contain 20 unique cases.")
    signatures = {
        json.dumps(case["filters"], sort_keys=True, ensure_ascii=False)
        for case in cases
    }
    if len(signatures) != 20:
        raise ValueError("The 20 cases must use distinct filter combinations.")
    return document, cases


def numeric(value):
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def load_snapshot(path=DATA_FILE):
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    return rows, digest


def matching_rows(rows, filters):
    locations = set(filters["locations"])
    categories = set(filters["demographic_categories"])
    groups = set(filters["demographic_groups"])
    selected = []
    for row in rows:
        year = numeric(row.get("YearStart"))
        if year is None:
            continue
        category = (row.get("StratificationCategory1") or "Not reported").strip()
        group = (row.get("Stratification1") or "Not reported").strip()
        if (
            row.get("Question") == filters["question"]
            and row.get("DataValueUnit") == filters["data_unit"]
            and row.get("DataValueType") == filters["estimate_type"]
            and int(year) in range(filters["start_year"], filters["end_year"] + 1)
            and row.get("LocationDesc") in locations
            and category in categories
            and group in groups
        ):
            selected.append(row)
    return selected


def source_reference(rows, filters):
    selected = matching_rows(rows, filters)
    valid = []
    by_location = {loc: set() for loc in filters["locations"]}
    annual = defaultdict(list)
    for row in selected:
        year_num = numeric(row.get("YearStart"))
        if year_num is not None:
            year = int(year_num)
            by_location.setdefault(row["LocationDesc"], set()).add(year)
            value = numeric(row.get("DataValue"))
            if value is not None:
                valid.append(row)
                key = (
                    row["LocationDesc"],
                    year,
                    (row.get("StratificationCategory1") or "Not reported").strip(),
                    (row.get("Stratification1") or "Not reported").strip(),
                )
                annual[key].append(value)
    years_by_location = {
        loc: sorted(by_location.get(loc, set())) for loc in filters["locations"]
    }
    period = set(range(filters["start_year"], filters["end_year"] + 1))
    missing_by_location = {
        loc: sorted(period - set(years_by_location.get(loc, [])))
        for loc in filters["locations"]
    }
    year_sets = [set(v) for v in years_by_location.values()]
    shared = sorted(set.intersection(*year_sets)) if year_sets else []
    annual_rows = []
    for (location, year, category, group), values in sorted(annual.items()):
        annual_rows.append({
            "LocationDesc": location,
            "YearStart": year,
            "StratificationCategory1": category,
            "Stratification1": group,
            "mean_value": sum(values) / len(values),
            "number_of_records": len(values),
        })
    return {
        "matching_rows": len(selected),
        "rows_with_values": len(valid),
        "rows_missing_values": len(selected) - len(valid),
        "years_by_location": years_by_location,
        "missing_years_by_location": missing_by_location,
        "years_shared_by_all_selected_locations": shared,
        "valid_rows_used": len(valid),
        "summary_by_location_and_year": annual_rows,
        "series_count": len({
            (r["LocationDesc"], r["StratificationCategory1"], r["Stratification1"])
            for r in annual_rows
        }),
    }


def key_for_row(row):
    return (
        str(row.get("LocationDesc", "")),
        int(numeric(row.get("YearStart")) or 0),
        str(row.get("StratificationCategory1") or "Not reported"),
        str(row.get("Stratification1") or "Not reported"),
    )


def compare_structured(answer, expected):
    parts = {}
    retrieval = answer.get("retrieval") or {}
    quality = answer.get("quality") or {}
    analysis = answer.get("analysis") or {}

    parts["record_counts"] = all(
        retrieval.get(key) == expected[key]
        for key in ("matching_rows", "rows_with_values", "rows_missing_values")
    )
    parts["coverage_years"] = (
        {k: sorted(v) for k, v in (quality.get("years_by_location") or {}).items()}
        == expected["years_by_location"]
        and {
            k: sorted(v) for k, v in (quality.get("missing_years_by_location") or {}).items()
        } == expected["missing_years_by_location"]
        and sorted(quality.get("years_shared_by_all_selected_locations") or [])
        == expected["years_shared_by_all_selected_locations"]
    )
    parts["valid_row_count"] = analysis.get("valid_rows_used") == expected["valid_rows_used"]

    expected_rows = {key_for_row(row): row for row in expected["summary_by_location_and_year"]}
    actual_list = analysis.get("summary_by_location_and_year") or []
    actual_rows = {key_for_row(row): row for row in actual_list}
    annual_match = expected_rows.keys() == actual_rows.keys()
    if annual_match:
        for key, row in expected_rows.items():
            actual = actual_rows[key]
            actual_mean = numeric(actual.get("mean_value"))
            actual_n = actual.get("number_of_records")
            if (
                actual_mean is None
                or not math.isclose(actual_mean, row["mean_value"], abs_tol=0.005, rel_tol=0)
                or actual_n != row["number_of_records"]
            ):
                annual_match = False
                break
    parts["annual_values_and_counts"] = annual_match
    return parts


def has_number(text, number, tolerance=0.051):
    target = numeric(number)
    if target is None:
        return False
    tokens = re.findall(r"(?<!\w)-?\d[\d,]*(?:\.\d+)?", text)
    return any(
        (value := numeric(token)) is not None
        and abs(value - target) <= tolerance
        for token in tokens
    )


def series_for_reference(expected):
    grouped = defaultdict(list)
    for row in expected["summary_by_location_and_year"]:
        key = " | ".join(
            (row["LocationDesc"], row["StratificationCategory1"], row["Stratification1"])
        )
        grouped[key].append(row)
    for values in grouped.values():
        values.sort(key=lambda row: int(row["YearStart"]))
    return grouped


def summary_checks(filters, expected, summary):
    """20 deterministic evidence-coverage checks against the independent CSV reference."""
    text = re.sub(r"\s+", " ", str(summary or "")).casefold()
    series = series_for_reference(expected)
    checks = [
        filters["question"].casefold() in text,
        (("percent" in text) or ("%" in text))
        if filters["data_unit"] == "%"
        else "day" in text or "days" in text,
        filters["estimate_type"].casefold() in text,
        str(filters["start_year"]) in text,
        str(filters["end_year"]) in text,
        all(value.casefold() in text for value in filters["locations"]),
        all(value.casefold() in text for value in filters["demographic_categories"]),
        all(value.casefold() in text for value in filters["demographic_groups"]),
        str(filters["start_year"]) in text
        and str(filters["end_year"]) in text
        and "year" in text,
    ]
    row_terms = ("record", "row", "observation", "data point")
    matching_count = expected["matching_rows"]
    checks.append(
        has_number(text, matching_count)
        and any(term in text for term in row_terms)
    )
    numeric_count = expected["rows_with_values"]
    checks.append(
        has_number(text, numeric_count)
        and any(term in text for term in ("valid", "numeric", "record", "row", "data point"))
    )
    missing_count = expected["rows_missing_values"]
    checks.append(
        "missing" in text
        and (
            has_number(text, missing_count)
            or (missing_count == 0 and any(t in text for t in ("none", "no missing", "complete")))
        )
    )

    observed = [
        year for values in expected["years_by_location"].values() for year in values
    ]
    checks.append(
        bool(observed)
        and all(str(year) in text for year in sorted(set(observed)))
        and ("coverage" in text or "year" in text)
    )
    missing_years = [
        year for values in expected["missing_years_by_location"].values() for year in values
    ]
    checks.append(
        (all(str(year) in text for year in missing_years) and "missing" in text)
        if missing_years
        else any(term in text for term in ("no missing", "no gaps", "complete coverage"))
    )
    shared = expected["years_shared_by_all_selected_locations"]
    checks.append(
        (
            all(str(year) in text for year in shared)
            and any(term in text for term in ("shared", "common", "across"))
        )
        if shared
        else any(term in text for term in ("no shared", "no common", "none"))
    )
    checks.append(
        has_number(text, expected["series_count"])
        and any(word in text for word in ("series", "groups", "populations"))
    )
    first_points = [values[0] for values in series.values() if values]
    checks.append(
        bool(first_points)
        and all(
            str(int(row["YearStart"])) in text
            and has_number(text, round(row["mean_value"], 1))
            for row in first_points
        )
    )
    last_points = [values[-1] for values in series.values() if values]
    checks.append(
        bool(last_points)
        and all(
            str(int(row["YearStart"])) in text
            and has_number(text, round(row["mean_value"], 1))
            for row in last_points
        )
    )
    peaks = []
    for values in series.values():
        if values:
            peak_value = max(row["mean_value"] for row in values)
            peak_years = [
                int(row["YearStart"])
                for row in values
                if abs(row["mean_value"] - peak_value) <= 0.0005
            ]
            peaks.append((peak_value, peak_years))
    checks.append(
        bool(peaks)
        and all(
            has_number(text, round(value, 1))
            and all(str(year) in text for year in years)
            for value, years in peaks
        )
    )
    directions = []
    for values in series.values():
        if not values:
            continue
        delta = values[-1]["mean_value"] - values[0]["mean_value"]
        directions.append("up" if delta > 0.0005 else "down" if delta < -0.0005 else "unchanged")
    checks.append(
        bool(directions)
        and all(any(term in text for term in DIRECTION_TERMS[d]) for d in directions)
        and not any(term in text for term in ("caused by", "causes", "because of", "leads to"))
    )
    if len(checks) != CHECKS_PER_CASE:
        raise RuntimeError(f"Expected {CHECKS_PER_CASE} summary checks; got {len(checks)}.")
    return checks


def post_analyze(api_base, filters, timeout):
    url = api_base.rstrip("/") + "/analyze"
    body = json.dumps(filters).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
        raw = error.read().decode("utf-8", errors="replace")
    except Exception as error:
        return None, None, round(time.perf_counter() - started, 3), f"{type(error).__name__}: {error}"
    latency = round(time.perf_counter() - started, 3)
    try:
        return status, json.loads(raw), latency, None
    except json.JSONDecodeError:
        return status, {"raw_body": raw[:2000]}, latency, "Response was not valid JSON."


def edge_behavior_ok(case, status, payload):
    detail = str((payload or {}).get("detail", "")).casefold()
    behavior = case["expected_behavior"]
    if behavior == "empty_data_rejection":
        return status == 400 and "no cdc records match" in detail
    if behavior == "missing_location_rejection":
        return status == 400 and "location" in detail
    return None


def evaluate_case(case, rows, api_base, timeout):
    filters = case["filters"]
    expected = source_reference(rows, filters)
    status, payload, latency, transport_error = post_analyze(api_base, filters, timeout)
    request_ok = status is not None and 200 <= status < 300
    response = payload if isinstance(payload, dict) and request_ok else {}
    explanation = str(response.get("explanation") or "")
    required_sections = ("retrieval", "quality", "analysis")
    schema_ok = all(isinstance(response.get(key), dict) for key in required_sections)
    usable = bool(schema_ok and explanation.strip())
    has_chart_rows = bool(
        ((response.get("analysis") or {}).get("summary_by_location_and_year") or [])
    )
    edge_ok = edge_behavior_ok(case, status, payload)
    is_expected_edge = case["expected_behavior"] in (
        "empty_data_rejection", "missing_location_rejection"
    )
    reference_comparable = bool(request_ok and schema_ok and not is_expected_edge)
    components = compare_structured(response, expected) if reference_comparable else {}
    structured_match = all(components.values()) if components else None
    checks = (
        summary_checks(filters, expected, explanation)
        if usable and not is_expected_edge
        else ([False] * CHECKS_PER_CASE if not is_expected_edge else None)
    )
    failure_notes = []
    if transport_error:
        failure_notes.append(transport_error)
    if is_expected_edge and edge_ok is False:
        failure_notes.append("Expected validation rejection was not returned.")
    elif not is_expected_edge and not request_ok:
        failure_notes.append(f"Expected HTTP success; received {status}.")
    if request_ok and not usable:
        failure_notes.append("Response was missing required structured data or explanation.")
    if structured_match is False:
        failure_notes.extend(
            "Structured snapshot mismatch: " + name
            for name, passed in components.items()
            if not passed
        )
    if checks is not None and not all(checks):
        failure_notes.append(
            "Summary evidence checks missed: "
            + ", ".join(f"B{i+1:02d}" for i, passed in enumerate(checks) if not passed)
        )
    return {
        "id": case["id"],
        "tag": case["tag"],
        "scenario": case["scenario"],
        "expected_behavior": case["expected_behavior"],
        "filters": filters,
        "reference": expected,
        "request_succeeded": request_ok,
        "http_status": status,
        "agent_response_usable": usable,
        "graph_data_available": has_chart_rows,
        "expected_edge_behavior_met": edge_ok,
        "reference_comparable": reference_comparable,
        "structured_match_components": components,
        "structured_snapshot_match": structured_match,
        "summary_check_results": checks,
        "summary_checks_passed": sum(checks) if checks is not None else None,
        "filters_only_baseline_passes": BASELINE_PER_CASE if checks is not None else None,
        "api_latency_seconds": latency,
        "explanation": explanation,
        "error_detail": (payload or {}).get("detail") if isinstance(payload, dict) else None,
        "transport_error": transport_error,
        "failure_notes": failure_notes,
        "human_accuracy_review": "pending",
        "raw_response": payload,
    }


def percentile(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil((pct / 100) * len(ordered)) - 1)
    return round(ordered[index], 3)


def summarize(document, results, snapshot_sha, api_base, started_at, complete):
    scored = [
        row for row in results
        if row["expected_behavior"] not in (
            "empty_data_rejection", "missing_location_rejection"
        )
    ]
    request_ok = sum(bool(row["request_succeeded"]) for row in scored)
    usable = sum(bool(row["agent_response_usable"]) for row in scored)
    comparisons = [row for row in scored if row["reference_comparable"]]
    snapshot_matches = sum(row["structured_snapshot_match"] is True for row in comparisons)
    check_total = sum(
        sum(row["summary_check_results"] or [])
        for row in scored
    )
    check_slots = len(scored) * CHECKS_PER_CASE
    latency = [
        row["api_latency_seconds"] for row in results
        if row.get("api_latency_seconds") is not None
    ]
    edge_cases = [
        row for row in results
        if row["expected_behavior"] in (
            "empty_data_rejection", "missing_location_rejection"
        )
    ]
    expected_edges = sum(row["expected_edge_behavior_met"] is True for row in edge_cases)
    missed = [
        f"{row['id']}:{i+1:02d}"
        for row in scored
        for i, passed in enumerate(row["summary_check_results"] or [])
        if not passed
    ]
    failures = [
        row for row in results
        if row["failure_notes"]
    ]
    first_failure = failures[0] if failures else None
    success = next(
        (row for row in results if row["request_succeeded"] and row["structured_snapshot_match"] is True),
        None,
    )
    next_steps = []
    if any(row["structured_snapshot_match"] is False for row in comparisons):
        next_steps.append(
            "Check whether the live CDC/API extract differs from the pinned September 30, 2026 snapshot before attributing value mismatches to the agent."
        )
    if missed:
        next_steps.append(
            "Review the listed summary-check misses against the raw explanation and expected evidence; decide whether the miss reflects an omission or a wording mismatch."
        )
    if any(row["transport_error"] or (not row["request_succeeded"] and row["expected_behavior"] == "analysis") for row in results):
        next_steps.append(
            "Inspect failed Render responses and improve the user-facing handling for the specific API failure pattern."
        )
    if not next_steps:
        next_steps = [
            "Have a second reviewer audit a sample of passing explanations against the saved source evidence.",
            "Repeat the fixed suite after a CDC snapshot update and compare response latency across runs.",
        ]
    return {
        "benchmark": document["benchmark"],
        "protocol_version": document["protocol_version"],
        "status": "complete" if complete else "in_progress",
        "cases_planned": len(document["cases"]),
        "cases_completed": len(results),
        "run_started_utc": started_at,
        "run_finished_utc": datetime.now(timezone.utc).isoformat() if complete else None,
        "api_base": api_base,
        "endpoint": "/analyze",
        "snapshot_file": DATA_FILE.name,
        "snapshot_sha256": snapshot_sha,
        "valid_scenario_requests_succeeded": request_ok,
        "valid_scenarios": len(scored),
        "usable_agent_responses": usable,
        "structured_snapshot_matches": snapshot_matches,
        "structured_comparison_cases": len(comparisons),
        "expected_edge_rejections_met": expected_edges,
        "expected_edge_cases": len(edge_cases),
        "summary_evidence_checks_passed": check_total,
        "summary_evidence_checks_total": check_slots,
        "filters_only_baseline_passes": len(scored) * BASELINE_PER_CASE,
        "filters_only_baseline_total": check_slots,
        "filters_only_baseline_rate": BASELINE_PER_CASE / CHECKS_PER_CASE,
        "api_latency_seconds_median": round(statistics.median(latency), 3) if latency else None,
        "api_latency_seconds_p95": percentile(latency, 95),
        "human_accuracy_review": "pending; deterministic checks do not establish semantic accuracy",
        "representative_success_case": (
            {"id": success["id"], "structured_match": True, "summary_checks_passed": success["summary_checks_passed"]}
            if success else None
        ),
        "representative_failure_case": (
            {"id": first_failure["id"], "failure_notes": first_failure["failure_notes"]}
            if first_failure else None
        ),
        "summary_check_misses": missed,
        "next_steps": next_steps,
        "interpretation": (
            "The filters-only baseline is comparable only for summary-evidence coverage. "
            "It does not measure API completion, structured-value accuracy, agent usability, or latency. "
            "Structured comparisons use the bundled CDC snapshot; live-source revisions can create differences."
        ),
    }


def write_outputs(document, results, summary, outdir, complete):
    outdir.mkdir(parents=True, exist_ok=True)
    output = {
        "protocol": document,
        "summary": summary,
        "cases": results,
    }
    (outdir / RESULT_FILE.name).write_text(
        json.dumps(output, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    columns = [
        "id", "tag", "scenario", "expected_behavior", "request_succeeded",
        "http_status", "agent_response_usable", "graph_data_available",
        "structured_snapshot_match", "summary_checks_passed",
        "filters_only_baseline_passes", "api_latency_seconds",
        "error_detail", "failure_notes", "explanation",
    ]
    with (outdir / CSV_FILE.name).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in results:
            writer.writerow({
                key: (" | ".join(row["failure_notes"]) if key == "failure_notes" else row.get(key))
                for key in columns
            })
    with (outdir / REVIEW_FILE.name).open("w", newline="", encoding="utf-8") as stream:
        review_columns = [
            "id", "review_status", "reviewer", "summary_accuracy_notes",
            "expected_source_facts", "agent_explanation",
        ]
        writer = csv.DictWriter(stream, fieldnames=review_columns)
        writer.writeheader()
        for row in results:
            writer.writerow({
                "id": row["id"],
                "review_status": "pending",
                "reviewer": "",
                "summary_accuracy_notes": "",
                "expected_source_facts": json.dumps(row["reference"], ensure_ascii=False),
                "agent_explanation": row["explanation"],
            })
    (outdir / SUMMARY_FILE.name).write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if complete:
        write_chart(summary, outdir / SVG_FILE.name)


def write_chart(summary, path):
    metrics = [
        ("Request success", summary["valid_scenario_requests_succeeded"], summary["valid_scenarios"], "#2e6f9f"),
        ("Usable responses", summary["usable_agent_responses"], summary["valid_scenarios"], "#397fab"),
        ("Snapshot match", summary["structured_snapshot_matches"], summary["structured_comparison_cases"], "#568eb3"),
        ("Summary evidence", summary["summary_evidence_checks_passed"], summary["summary_evidence_checks_total"], "#70a6c9"),
        ("Filters-only baseline", summary["filters_only_baseline_passes"], summary["filters_only_baseline_total"], "#9aafc0"),
    ]
    width, height = 760, 360
    left, top, bar_width, gap, max_width = 180, 62, 520, 58, 520
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">AI-agent benchmark results</title>',
        '<desc id="desc">Request, usable response, structured snapshot match, summary coverage, and filters-only baseline metrics.</desc>',
        '<rect width="100%" height="100%" fill="#f2f7fb"/>',
        '<text x="30" y="30" font-family="Arial,sans-serif" font-size="19" font-weight="700" fill="#102b42">20-case AI-agent benchmark</text>',
    ]
    for i, (label, value, total, color) in enumerate(metrics):
        y = top + i * gap
        rate = (value / total) if total else 0
        w = round(max_width * rate)
        parts += [
            f'<text x="22" y="{y+18}" font-family="Arial,sans-serif" font-size="13" fill="#17354e">{label}</text>',
            f'<rect x="{left}" y="{y}" width="{bar_width}" height="22" rx="8" fill="#dce9f1"/>',
            f'<rect x="{left}" y="{y}" width="{w}" height="22" rx="8" fill="{color}"/>',
            f'<text x="{left+bar_width+12}" y="{y+17}" font-family="Arial,sans-serif" font-size="13" fill="#17354e">{value}/{total}</text>',
        ]
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Validate cases and snapshot; send no requests.")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--api-base", default=os.getenv("RENDER_API_BASE", DEFAULT_API))
    parser.add_argument("--outdir", type=Path, default=ROOT)
    parser.add_argument("--resume", action="store_true", help="Continue an interrupted run without repeating completed requests.")
    args = parser.parse_args()

    document, cases = read_cases()
    rows, snapshot_sha = load_snapshot()
    planned = []
    for case in cases:
        expected = source_reference(rows, case["filters"])
        planned.append({
            "id": case["id"],
            "tag": case["tag"],
            "scenario": case["scenario"],
            "expected_behavior": case["expected_behavior"],
            "matching_rows": expected["matching_rows"],
            "numeric_rows": expected["rows_with_values"],
            "observed_years": expected["years_by_location"],
            "missing_years": expected["missing_years_by_location"],
            "series_count": expected["series_count"],
        })
    if args.dry_run:
        print(json.dumps({
            "status": "plan_validated_no_requests_sent",
            "cases": len(cases),
            "unique_filter_combinations": len({
                json.dumps(c["filters"], sort_keys=True) for c in cases
            }),
            "snapshot_sha256": snapshot_sha,
            "baseline_per_case": f"{BASELINE_PER_CASE}/{CHECKS_PER_CASE}",
            "case_expectations": planned,
        }, indent=2))
        return

    prior_path = args.outdir / RESULT_FILE.name
    if args.resume:
        if not prior_path.exists():
            raise SystemExit("No saved benchmark run exists to resume.")
        prior = json.loads(prior_path.read_text(encoding="utf-8"))
        prior_summary = prior.get("summary", {})
        if prior_summary.get("status") != "in_progress":
            raise SystemExit("The saved run is not in progress; start a new output directory for another run.")
        if prior_summary.get("snapshot_sha256") != snapshot_sha or prior_summary.get("api_base") != args.api_base:
            raise SystemExit("The saved run uses a different snapshot or API base; refusing to mix results.")
        started = prior_summary.get("run_started_utc")
        results = prior.get("cases", [])
    else:
        if prior_path.exists():
            raise SystemExit("A saved run already exists. Use --resume to continue it or choose a new --outdir.")
        started = datetime.now(timezone.utc).isoformat()
        results = []
        current = summarize(document, results, snapshot_sha, args.api_base, started, False)
        write_outputs(document, results, current, args.outdir, False)
    completed_ids = {result["id"] for result in results}
    for index, case in enumerate(cases, 1):
        if case["id"] in completed_ids:
            continue
        result = evaluate_case(case, rows, args.api_base, args.timeout)
        results.append(result)
        current = summarize(document, results, snapshot_sha, args.api_base, started, False)
        write_outputs(document, results, current, args.outdir, False)
        print(
            f"{index:02d}/20 {case['id']} HTTP={result['http_status']} "
            f"usable={result['agent_response_usable']} "
            f"snapshot_match={result['structured_snapshot_match']} "
            f"summary={result['summary_checks_passed']} "
            f"latency={result['api_latency_seconds']}s",
            flush=True,
        )
    final = summarize(document, results, snapshot_sha, args.api_base, started, True)
    write_outputs(document, results, final, args.outdir, True)
    print(json.dumps(final, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()


