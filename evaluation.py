import json
import re

def benchmark_questions(filters):
    """Build 20 evaluator questions with the current website filter values."""
    selected = (
        f"{filters['question']} | {filters['data_unit']} | {filters['estimate_type']} | "
        f"{filters['start_year']}-{filters['end_year']} | "
        f"{', '.join(filters['locations'])} | {', '.join(filters['demographic_categories'])} | "
        f"{', '.join(filters['demographic_groups'])}"
    )
    prompts = [
        f"Does the summary name the selected CDC question ({filters['question']})?",
        f"Does the summary identify the selected unit ({filters['data_unit']})?",
        f"Does the summary identify the selected estimate ({filters['estimate_type']})?",
        f"Does the summary include the start year {filters['start_year']}?",
        f"Does the summary include the end year {filters['end_year']}?",
        f"Does the summary name every selected location ({', '.join(filters['locations'])})?",
        f"Does the summary name the selected population category ({', '.join(filters['demographic_categories'])})?",
        f"Does the summary name the selected population group ({', '.join(filters['demographic_groups'])})?",
        f"Does the summary clearly describe the selected {filters['start_year']}-{filters['end_year']} time window?",
        "Does the summary report the number of matching CDC records?",
        "Does the summary report how many matching records contain numeric values?",
        "Does the summary report whether values are missing?",
        "Does the summary accurately describe observed-year coverage by location?",
        "Does the summary identify missing years without treating them as zero?",
        "Does the summary state which years are shared across the selected locations?",
        "Does the summary describe the number of returned location/population series?",
        "Does the summary report each series' first year and mean?",
        "Does the summary report each series' latest year and mean?",
        "Does the summary report each series' highest annual mean and year?",
        "Does the summary characterize each series' first-to-last direction without causal claims?",
    ]
    return [{"id": f"B{i:02d}", "question": question, "selection": selected} for i, question in enumerate(prompts, 1)]


def _series_key(row):
    return " | ".join(str(row.get(k) or "Overall") for k in ("LocationDesc", "StratificationCategory1", "Stratification1"))


def benchmark_expected(filters, result):
    """Reference facts from the existing API response; this does not call the API."""
    retrieval, quality = result.get("retrieval", {}), result.get("quality", {})
    analysis = result.get("analysis", {})
    rows = analysis.get("summary_by_location_and_year", [])
    series = {}
    for row in rows:
        series.setdefault(_series_key(row), []).append(row)
    for values in series.values():
        values.sort(key=lambda r: int(r["YearStart"]))
    first = {k: {"year": int(v[0]["YearStart"]), "mean": round(float(v[0]["mean_value"]), 3)} for k, v in series.items() if v}
    last = {k: {"year": int(v[-1]["YearStart"]), "mean": round(float(v[-1]["mean_value"]), 3)} for k, v in series.items() if v}
    highest = {}
    for k, values in series.items():
        if values:
            peak = max(float(r["mean_value"]) for r in values)
            highest[k] = {"years": sorted(int(r["YearStart"]) for r in values if abs(float(r["mean_value"]) - peak) <= 0.0005), "mean": round(peak, 3)}
    direction = {}
    for k, v in series.items():
        if not v:
            continue
        delta = float(v[-1]["mean_value"]) - float(v[0]["mean_value"])
        direction[k] = "up" if delta > 0.0005 else "down" if delta < -0.0005 else "unchanged"
    return [
        filters["question"], filters["data_unit"], filters["estimate_type"], filters["start_year"], filters["end_year"],
        sorted(filters["locations"]), sorted(filters["demographic_categories"]), sorted(filters["demographic_groups"]),
        filters["end_year"] - filters["start_year"] + 1, retrieval.get("matching_rows"),
        retrieval.get("rows_with_values", analysis.get("valid_rows_used")), retrieval.get("rows_missing_values"),
        {k: sorted(v) for k, v in quality.get("years_by_location", {}).items()},
        {k: sorted(v) for k, v in quality.get("missing_years_by_location", {}).items()},
        sorted(quality.get("years_shared_by_all_selected_locations", [])), len(series), first, last, highest, direction,
    ]


def _text_has_number(text, number, tolerance=0.05):
    try:
        target = float(number)
    except (TypeError, ValueError):
        return False
    return any(abs(float(token.replace(",", "")) - target) <= tolerance for token in re.findall(r"(?<!\w)-?\d[\d,]*(?:\.\d+)?", text))


def score_benchmark_summary(filters, result, summary):
    """Score summary coverage with transparent deterministic text checks."""
    text = re.sub(r"\s+", " ", str(summary or "")).casefold()
    questions = benchmark_questions(filters)
    expected = benchmark_expected(filters, result)
    retrieval = result.get("retrieval", {})
    quality = result.get("quality", {})
    analysis = result.get("analysis", {})
    rows = analysis.get("summary_by_location_and_year", [])
    series = {}
    for row in rows:
        series.setdefault(_series_key(row), []).append(row)
    for values in series.values():
        values.sort(key=lambda r: int(r["YearStart"]))

    checks = []
    checks.append(filters["question"].casefold() in text)
    checks.append(("percent" in text or "%" in text) if filters["data_unit"] == "%" else "day" in text or _text_has_number(text, 1))
    checks.append(filters["estimate_type"].casefold() in text)
    checks.append(str(filters["start_year"]) in text)
    checks.append(str(filters["end_year"]) in text)
    checks.append(all(location.casefold() in text for location in filters["locations"]))
    checks.append(all(value.casefold() in text for value in filters["demographic_categories"]))
    checks.append(all(value.casefold() in text for value in filters["demographic_groups"]))
    checks.append(str(filters["start_year"]) in text and str(filters["end_year"]) in text and "year" in text)
    matching_rows = retrieval.get("matching_rows")
    checks.append(matching_rows is not None and _text_has_number(text, matching_rows) and any(word in text for word in ("record", "row", "observation", "data point")))
    rows_with_values = retrieval.get("rows_with_values", analysis.get("valid_rows_used"))
    checks.append(rows_with_values is not None and _text_has_number(text, rows_with_values) and any(word in text for word in ("valid", "numeric", "record", "row", "data point")))
    rows_missing_values = retrieval.get("rows_missing_values")
    checks.append(rows_missing_values is not None and "missing" in text and (_text_has_number(text, rows_missing_values) or (rows_missing_values == 0 and any(word in text for word in ("none", "no missing", "complete")))))
    years_by_location = quality.get("years_by_location", {})
    observed = [year for years_for_location in years_by_location.values() for year in years_for_location]
    checks.append(bool(observed) and all(str(year) in text for year in sorted(set(observed))) and ("coverage" in text or "year" in text))
    missing_years_by_location = quality.get("missing_years_by_location", {})
    missing_years = [year for years_for_location in missing_years_by_location.values() for year in years_for_location]
    checks.append((all(str(year) in text for year in missing_years) and "missing" in text) if missing_years else any(term in text for term in ("no missing", "no gaps", "complete coverage")))
    shared = quality.get("years_shared_by_all_selected_locations", [])
    checks.append((all(str(year) in text for year in shared) and any(term in text for term in ("shared", "common", "across"))) if shared else any(term in text for term in ("no shared", "no common", "none")))
    checks.append(_text_has_number(text, len(series)) and any(word in text for word in ("series", "groups", "populations")))
    first_points = [v[0] for v in series.values() if v]
    checks.append(bool(first_points) and all(str(int(row["YearStart"])) in text and _text_has_number(text, round(float(row["mean_value"]), 1), 0.051) for row in first_points))
    last_points = [v[-1] for v in series.values() if v]
    checks.append(bool(last_points) and all(str(int(row["YearStart"])) in text and _text_has_number(text, round(float(row["mean_value"]), 1), 0.051) for row in last_points))
    peak_points = []
    for values in series.values():
        if values:
            peak = max(float(row["mean_value"]) for row in values)
            peak_points.append((peak, [int(row["YearStart"]) for row in values if abs(float(row["mean_value"]) - peak) <= 0.0005]))
    checks.append(bool(peak_points) and all(_text_has_number(text, round(value, 1), 0.051) and all(str(year) in text for year in years_for_peak) for value, years_for_peak in peak_points))
    direction_terms = {"up": ("up", "increas", "rose", "higher"), "down": ("down", "decreas", "fell", "lower"), "unchanged": ("unchanged", "stable", "flat")}
    checks.append(bool(series) and all(any(term in text for term in direction_terms[direction]) for direction in expected[-1].values()) and not any(term in text for term in ("caused by", "causes", "because of", "leads to")))

    scoring_rules = [
        "The exact selected CDC question must appear in the summary.",
        "The selected unit must be explicit: percent (%) for percentage measures, or days for the days measure.",
        "The exact selected estimate type must appear.",
        "The selected start year must appear.",
        "The selected end year must appear.",
        "Every selected location name must appear.",
        "Every selected demographic category must appear.",
        "Every selected demographic group must appear.",
        "The summary must identify the selected year range as a time period.",
        "The exact matching-record count and a record/row/observation label must appear.",
        "The exact numeric-record count and a numeric/valid-record label must appear.",
        "The missing-record count must be reported; when zero, an explicit no-missing statement is required.",
        "Observed coverage years from the structured API evidence must be reported with coverage context.",
        "Every expected missing year must be identified; if none are expected, the summary must explicitly report no gaps.",
        "Shared years must be named with shared/common/across context; if none, that absence must be explicit.",
        "The exact number of returned series must appear with a series/group/population label.",
        "For every series, its first observed year and corresponding mean must appear.",
        "For every series, its latest observed year and corresponding mean must appear.",
        "For every series, its peak mean and peak year(s) must appear.",
        "Every series' first-to-last direction must be represented, and causal wording must be absent.",
    ]
    answer = str(summary or "")
    rows_out = []
    for i, case in enumerate(questions):
        passed = bool(checks[i])
        expected_text = json.dumps(expected[i], ensure_ascii=False, sort_keys=True, default=str)
        reason = (
            f"Pass: the deterministic check found the required evidence. Rule: {scoring_rules[i]} "
            f"Expected: {expected_text}"
            if passed else
            f"Fail: the required evidence was not detected. Rule: {scoring_rules[i]} "
            f"Expected: {expected_text}"
        )
        rows_out.append({
            **case,
            "expected_answer": expected[i],
            "agent_answer": answer,
            "scoring_rule": scoring_rules[i],
            "why": reason,
            "pass": passed,
            "baseline_pass": i < 9,
        })
    return rows_out

