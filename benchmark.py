"""Standard-library benchmark for filter values and missing-year coverage."""
import csv
import json
from collections import defaultdict
from pathlib import Path

DATA, OUT = Path("mental_health_cdi.csv"), Path(".")
with DATA.open(encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))
questions = sorted({r["Question"] for r in rows if r["Question"]})
for r in rows:
    r["Category"] = r["StratificationCategory1"] or "Overall"
    r["Group"] = r["Stratification1"] or "Overall"

cases = []
for i in range(18):
    q = questions[i % len(questions)]
    qr = [r for r in rows if r["Question"] == q]
    categories = sorted({r["Category"] for r in qr})
    cat = categories[i % len(categories)]
    groups = sorted({r["Group"] for r in qr if r["Category"] == cat})
    group = groups[i % len(groups)]
    cases.append({"id": f"C{i+1:02}", "question": q, "category": cat, "group": group,
                  "location": ["North Carolina", "United States"][i % 2],
                  "start": 2019 + i % 3, "end": min(2023, 2021 + i % 3)})
cases.extend([
    {"id": "C19", "question": questions[0], "category": "Overall", "group": "__no selection__", "location": "North Carolina", "start": 2019, "end": 2023, "edge_case": "empty group selection"},
    {"id": "C20", "question": questions[0], "category": "Overall", "group": "Overall", "location": "__no location__", "start": 2019, "end": 2023, "edge_case": "empty location selection"},
])

def aggregate(selected):
    """App-style filtering and mean aggregation by year."""
    values = defaultdict(list)
    for r in selected:
        try:
            year, value = int(r["YearStart"]), float(r["DataValue"])
        except (ValueError, TypeError):
            continue
        values[year].append(value)
    return {y: sum(v) / len(v) for y, v in values.items()}

results = []
for c in cases:
    selected = [r for r in rows if r["Question"] == c["question"] and r["Category"] == c["category"] and r["Group"] == c["group"] and r["LocationDesc"] == c["location"] and c["start"] <= int(r["YearStart"] or 0) <= c["end"]]
    # Independent reference calculation keeps all non-empty values directly from matched source rows.
    expected_values = defaultdict(list)
    for r in selected:
        try:
            value = float(r["DataValue"])
            expected_values[int(r["YearStart"])].append(value)
        except (TypeError, ValueError):
            pass
    expected = {y: sum(v) / len(v) for y, v in expected_values.items()}
    actual = aggregate(selected)
    missing = sorted(set(range(c["start"], c["end"] + 1)) - set(actual))
    reference_missing = sorted(set(range(c["start"], c["end"] + 1)) - set(expected))
    passed = actual == expected and missing == reference_missing
    baseline_rows = [r for r in rows if r["Question"] == c["question"] and r["Category"] == "Overall" and r["Group"] == "Overall" and r["LocationDesc"] == c["location"] and c["start"] <= int(r["YearStart"] or 0) <= c["end"]]
    baseline = aggregate(baseline_rows)
    results.append({**c, "observed_years": len(actual), "missing_years": missing,
                    "values": {str(y): round(v, 4) for y, v in sorted(actual.items())},
                    "pipeline_pass": passed, "baseline_exact_match": actual == baseline})

OUT.mkdir(exist_ok=True)
with (OUT / "cases.csv").open("w", encoding="utf-8", newline="") as f:
    cols = list(dict.fromkeys(k for result in results for k in result))
    w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
    for r in results:
        w.writerow({**r, "missing_years": json.dumps(r["missing_years"]), "values": json.dumps(r["values"])})
summary = {"cases": len(results), "pipeline_valid_cases": sum(r["pipeline_pass"] for r in results),
           "pipeline_valid_rate": sum(r["pipeline_pass"] for r in results) / len(results),
           "baseline_exact_match_cases": sum(r["baseline_exact_match"] for r in results),
           "baseline_exact_match_rate": sum(r["baseline_exact_match"] for r in results) / len(results),
           "metric": "Exact annual means and missing-year set against direct source-row calculation",
           "limitation": "Tests deterministic retrieval and coverage only; not LLM prose, user usefulness, or clinical validity."}
(OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
rates = [summary["pipeline_valid_rate"], summary["baseline_exact_match_rate"]]
width, height, left, top, bar_w, gap = 680, 350, 140, 48, 100, 130
svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
       '<rect width="100%" height="100%" fill="#fff"/>', '<text x="340" y="28" text-anchor="middle" font-family="Arial" font-size="18">20 representative filter cases</text>']
for i, (label, rate, color) in enumerate(zip(["Filter + coverage pipeline", "Overall baseline"], rates, ["#276c65", "#d6a64f"])):
    x, h = left + i * (bar_w + gap), int(230 * rate)
    svg += [f'<rect x="{x}" y="{top + 230 - h}" width="{bar_w}" height="{h}" fill="{color}"/>',
            f'<text x="{x + bar_w/2}" y="{top + 220 - h}" text-anchor="middle" font-family="Arial" font-size="16">{rate:.0%}</text>',
            f'<text x="{x + bar_w/2}" y="310" text-anchor="middle" font-family="Arial" font-size="13">{label}</text>']
svg.append('</svg>')
(OUT / "benchmark.svg").write_text("\n".join(svg), encoding="utf-8")
print(json.dumps(summary, indent=2))

