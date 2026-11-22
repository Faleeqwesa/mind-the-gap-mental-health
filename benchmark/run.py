#!/usr/bin/env python3
"""Run the 20-scenario AI-summary evaluation against the existing Render API."""
import argparse
import csv
import hashlib
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASE_FILE = Path(__file__).with_name("cases.json")
RESULT_FILE = Path(__file__).with_name("results.json")
SVG_FILE = Path(__file__).with_name("summary.svg")
DATA_FILE = ROOT / "data" / "mental_health_cdi.csv"
BASELINE = 9

sys.path.insert(0, str(ROOT))
from evaluation import score_benchmark_summary


def read_cases():
    document = json.loads(CASE_FILE.read_text(encoding="utf-8"))
    cases = document["cases"]
    signatures = {json.dumps(c["filters"], sort_keys=True) for c in cases}
    if len(cases) != 20 or len(signatures) != 20:
        raise ValueError("Expected 20 different benchmark filter scenarios.")
    return cases


def filter_exists(case):
    f = case["filters"]
    with DATA_FILE.open(encoding="utf-8-sig", newline="") as source:
        rows = csv.DictReader(source)
        return any(
            row.get("Question") == f["question"]
            and row.get("DataValueUnit") == f["data_unit"]
            and row.get("DataValueType") == f["estimate_type"]
            and row.get("LocationDesc") in f["locations"]
            and (row.get("StratificationCategory1") or "Overall") in f["demographic_categories"]
            and (row.get("Stratification1") or "Overall") in f["demographic_groups"]
            and f["start_year"] <= int(row["YearStart"]) <= f["end_year"]
            for row in rows
        )


def save(document):
    RESULT_FILE.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_chart(results):
    scores = [item["summary_evaluation"]["passed"] for item in results]
    width, left, top, row_h, chart_w = 780, 110, 55, 29, 560
    height = top + len(scores) * row_h + 46
    bits = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
            '<title id="title">AI-summary evaluation by scenario</title><desc id="desc">Twenty summary scores out of twenty. The filters-only baseline is nine.</desc>',
            '<style>text{font:14px system-ui, sans-serif;fill:#17354e}.title{font-size:20px;font-weight:700}.bar{fill:#3679a8}.base{stroke:#8b9eac;stroke-dasharray:6 5;stroke-width:2}.score{font-weight:700}</style>',
            '<rect width="100%" height="100%" fill="#fff" rx="12"/>',
            '<text x="24" y="30" class="title">20 AI-generated summaries · 20 checks each</text>']
    base_x = left + chart_w * BASELINE / 20
    for i, score in enumerate(scores):
        y = top + i * row_h
        bits.append(f'<text x="28" y="{y+17}">{results[i]["id"]}</text>')
        bits.append(f'<rect x="{left}" y="{y}" width="{chart_w}" height="18" rx="5" fill="#e5edf3"/>')
        bits.append(f'<rect x="{left}" y="{y}" width="{chart_w*score/20:.1f}" height="18" rx="5" class="bar"/>')
        bits.append(f'<text x="{left+chart_w+12}" y="{y+15}" class="score">{score}/20</text>')
    bits.append(f'<line x1="{base_x:.1f}" y1="{top-7}" x2="{base_x:.1f}" y2="{top+len(scores)*row_h-5}" class="base"/>')
    bits.append(f'<text x="{left}" y="{height-14}">0</text><text x="{left+chart_w-12}" y="{height-14}">20</text>')
    bits.append(f'<text x="{base_x+6:.1f}" y="{height-14}">Baseline 9/20</text></svg>')
    SVG_FILE.write_text("\n".join(bits), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="check cases and data without API requests")
    parser.add_argument("--api-base", default=os.getenv("RENDER_API_BASE", "https://cdc-mental-health-agent-api.onrender.com"))
    args = parser.parse_args()
    cases = read_cases()
    digest = hashlib.sha256(DATA_FILE.read_bytes()).hexdigest()
    missing = [case["id"] for case in cases if not filter_exists(case)]
    if missing:
        raise ValueError("Filter scenarios missing from snapshot: " + ", ".join(missing))
    if args.dry_run:
        print(json.dumps({"status": "validated_no_requests_sent", "scenarios": len(cases),
                          "unique_filter_sets": len({json.dumps(c['filters'], sort_keys=True) for c in cases}),
                          "snapshot_sha256": digest, "summary_checks_per_scenario": 20,
                          "filters_only_baseline": "9/20"}, indent=2))
        return

    started = datetime.now(timezone.utc).isoformat()
    document = {"benchmark": "20-scenario AI-agent summary evaluation", "started_utc": started,
                "api_endpoint": args.api_base.rstrip("/") + "/analyze", "snapshot_file": "data/mental_health_cdi.csv",
                "snapshot_sha256": digest, "scenarios": [], "summary": {}}
    save(document)
    for case in cases:
        t0 = time.perf_counter()
        record = {"id": case["id"], "scenario": case["scenario"], "filters": case["filters"]}
        try:
            request = urllib.request.Request(document["api_endpoint"], data=json.dumps(case["filters"]).encode(),
                                             headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(request, timeout=180) as response:
                answer = json.loads(response.read().decode("utf-8"))
                record["http_status"] = response.status
            record["response_seconds"] = round(time.perf_counter() - t0, 3)
            record["summary"] = answer.get("explanation", "")
            evidence = {key: answer.get(key, {}) for key in ("retrieval", "quality", "analysis")}
            record["agent_evidence"] = evidence
            rows = score_benchmark_summary(case["filters"], evidence, record["summary"])
            record["summary_evaluation"] = {"passed": sum(bool(row["pass"]) for row in rows), "total": 20,
                                             "filters_only_baseline": BASELINE,
                                             "checks": [{"id": row["id"], "pass": bool(row["pass"])} for row in rows]}
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as exc:
            record["http_status"] = getattr(exc, "code", None)
            record["response_seconds"] = round(time.perf_counter() - t0, 3)
            record["summary"] = ""
            record["error"] = str(exc)
            record["agent_evidence"] = {}
            record["summary_evaluation"] = {"passed": 0, "total": 20, "filters_only_baseline": BASELINE, "checks": []}
        document["scenarios"].append(record)
        scores = [x["summary_evaluation"]["passed"] for x in document["scenarios"]]
        times = [x["response_seconds"] for x in document["scenarios"]]
        ordered_times = sorted(times)
        document["summary"] = {"scenarios_completed": len(scores), "summary_checks_passed": sum(scores),
                               "summary_checks_total": 20 * len(scores), "filters_only_baseline_passed": BASELINE * len(scores),
                               "filters_only_baseline_total": 20 * len(scores), "mean_checks_per_summary": round(statistics.mean(scores), 2),
                               "summary_rate_percent": round(sum(scores) / (20 * len(scores)) * 100, 2),
                               "filters_only_baseline_rate_percent": round(BASELINE / 20 * 100, 2),
                               "response_median_seconds": round(statistics.median(times), 3),
                               "response_p95_seconds": ordered_times[math.ceil(.95 * len(ordered_times)) - 1],
                               "response_maximum_seconds": max(times),
                               "response_time_seconds": {"median": statistics.median(times),
                                                          "p95": ordered_times[math.ceil(.95 * len(ordered_times)) - 1],
                                                          "maximum": max(times), "samples": len(times)}}
        save(document)
        write_chart(document["scenarios"])
        print(f"{case['id']}: {record['summary_evaluation']['passed']}/20 in {record['response_seconds']}s", flush=True)
    document["completed_utc"] = datetime.now(timezone.utc).isoformat()
    save(document)
    print(json.dumps(document["summary"], indent=2))


if __name__ == "__main__":
    main()
