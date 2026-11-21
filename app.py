import os
import json
import requests
import pandas as pd
import plotly.express as px
import streamlit as st
import re
import time
from sklearn.linear_model import LinearRegression

API = os.getenv("RENDER_API_BASE", "https://cdc-mental-health-agent-api.onrender.com").rstrip("/")


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
        "Both selected boundary years must appear.",
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
st.set_page_config(page_title="Mind the Gap", page_icon="🧠", layout="wide")
st.title("Mind the Gap")
st.caption("Explore CDC mental health indicators. Select filters, choose what to compare, then view the graph and agent summary.")

@st.cache_data(ttl=1800)
def options():
    r = requests.get(f"{API}/options", timeout=120); r.raise_for_status(); return r.json()

try:
    o = options()
except Exception as e:
    st.error(f"Could not reach the Render data service ({type(e).__name__}). Please refresh in a moment.")
    st.stop()

st.subheader("1. Choose the question and values")
q = st.selectbox("CDC question", o["questions"])
u = "Number" if "average mentally unhealthy days" in q.lower() else "%"
st.caption(f"Unit is set automatically to {u} for this question.")
@st.cache_data
def estimate_options(question, unit):
    data = pd.read_csv("mental_health_cdi.csv", usecols=["Question", "DataValueUnit", "DataValueType"])
    rows = data[(data["Question"] == question) & (data["DataValueUnit"] == unit)]
    return sorted(rows["DataValueType"].dropna().unique())
st.markdown("""<style>
:root{--primary-color:#4b83af}
.stApp,[data-testid="stAppViewContainer"]{background:radial-gradient(ellipse at 82% 10%,rgba(28,65,96,.22),transparent 34%),#080d13;color:#d9e6f1}
[data-testid="stHeader"]{background:rgba(8,13,19,.94)}
h1,h2,h3{color:#91b9dc}
p,label,[data-testid="stWidgetLabel"] p{color:#d3e1ec}
div[data-baseweb="select"]>div,div[data-baseweb="input"]>div{background:#111d29!important;border-color:#36516a!important;color:#e4eef6!important}
[data-baseweb="tag"],[data-baseweb="tag"]>span{background:#254b6b!important;color:#e5f1fa!important}
[data-baseweb="tag"] svg{fill:#cfe4f5!important}
[data-baseweb="slider"] [role="slider"]{background:#78acd4!important;border:2px solid #c8e1f5!important;box-shadow:none!important}
[data-baseweb="slider"] [data-testid="stTickBar"]{background:#345c7b!important}
button[kind="primary"],button[data-testid="baseButton-primary"]{background:#285f8a!important;border-color:#4c82ad!important;color:#f1f7fb!important;border-radius:9px}
button[kind="primary"]:hover,button[data-testid="baseButton-primary"]:hover{background:#346f9c!important;border-color:#6996ba!important}
[data-testid="stDataFrame"]{border:1px solid #263c50;border-radius:9px}
</style>""",unsafe_allow_html=True)
types = estimate_options(q, u)
if not types:
    st.warning("No estimate types are available for this question and unit.")
    st.stop()
def_type = "Crude Mean" if u == "Number" else "Crude Prevalence"
t = st.selectbox("Estimate type", types, index=types.index(def_type) if def_type in types else 0)
y0, y1 = min(o["years"]), max(o["years"])
years = st.slider("Year range", y0, y1, (y0, y1))

st.subheader("2. Choose what to compare")
cats = [c for c in o["demographic_categories"] if c != "Overall"]
compare_options = ["Location"] + cats
if years[0] == years[1]:
    compare_options.insert(1, "Year")
compare = st.selectbox("Compare by", compare_options, help="Year is available only when the selected year range is a single year.")
allcats = o["demographic_categories"]
defcat = "Overall" if "Overall" in allcats else allcats[0]
locs, dcats, groups = [], [], []
if compare == "Location":
    defaults = [x for x in ["North Carolina", "United States"] if x in o["locations"]]
    locs = st.multiselect("Locations", o["locations"], default=defaults)
    c = st.selectbox("Population filter", allcats, index=allcats.index(defcat))
    dcats = [c]; opts = o["groups_by_category"].get(c, [])
    groups = st.multiselect("Population group", opts, default=["Overall"] if "Overall" in opts else opts[:1])
else:
    defaultloc = "North Carolina" if "North Carolina" in o["locations"] else o["locations"][0]
    locs = [st.selectbox("Location", o["locations"], index=o["locations"].index(defaultloc))]
    c = st.selectbox("Population filter", allcats, index=allcats.index(defcat)) if compare == "Year" else compare
    dcats = [c]; opts = o["groups_by_category"].get(c, [])
    groups = st.multiselect("Groups to compare", opts, default=["Overall"] if compare == "Year" and "Overall" in opts else opts)

st.subheader("Benchmark the AI summary")
run_summary_benchmark = st.checkbox("Score the existing AI summary with 20 filter-based questions", value=True,
                                    help="Scoring reuses the response from the existing Generate button. It makes no extra API call.")
with st.expander("Benchmark cases, scoring, and baseline"):
    st.write("The 20 evaluator questions are generated from the selections above. They score the returned summary; they are not 20 prompts sent to the agent because the existing API accepts filters only. For each check, the table shows the question, the full answer, expected evidence from the selected filters or structured API response, the rule, and why it passed or failed. Exact values and all selected names are required where relevant; keyword matches alone are not the scoring policy. The checks are still a deterministic coverage proxy: they can miss paraphrases and contradictions, and API-provided expected evidence is not an independent validation of the CDC source. No LLM judge is used.")
    st.write("The filters-only baseline knows only the submitted controls: B01–B09 are directly answerable and B10–B20 are scored as not answerable without CDC retrieval (9/20). The benchmark reuses the existing graph-and-summary response and makes no additional API call. It does not establish clinical usefulness, safety, or complete factual accuracy.")
benchmark_filters = dict(data_unit=u, question=q, start_year=years[0], end_year=years[1], locations=locs,
                         demographic_categories=dcats, demographic_groups=groups, estimate_type=t)

if st.button("Generate graph and AI summary", type="primary"):
    if not locs or not groups:
        st.warning("Select at least one location and group.")
    else:
        payload = dict(data_unit=u, question=q, start_year=years[0], end_year=years[1], locations=locs,
                       demographic_categories=dcats, demographic_groups=groups, estimate_type=t)
        try:
            with st.spinner("The smolagents workflow is retrieving and checking CDC values…"):
                benchmark_started = time.perf_counter()
                r = requests.post(f"{API}/analyze", json=payload, timeout=180); r.raise_for_status(); answer = r.json()
                benchmark_latency = round(time.perf_counter() - benchmark_started, 2)
            d = pd.DataFrame(answer["analysis"]["summary_by_location_and_year"])
            if d.empty:
                st.warning("No CDC values match these filters. Try another year, group, or estimate.")
            else:
                d["Compare"] = d["YearStart"].astype(str) if compare == "Year" else d["LocationDesc"] if compare == "Location" else d["Stratification1"]
                if compare in ("Location", "Year") and len(groups) > 1:
                    d["Compare"] = d["Compare"].astype(str) + " · " + d["Stratification1"].astype(str)
                d.rename(columns={"YearStart":"Year", "mean_value":"Value", "number_of_records":"Records"}, inplace=True)
                st.subheader("3. Bar graph")
                x = "Compare" if compare == "Year" else "Year"
                color = None if compare == "Year" else "Compare"
                fig = px.bar(d, x=x, y="Value", color=color, color_discrete_sequence=px.colors.sequential.Blues[2:], barmode="group", text_auto=".1f", hover_data=["Records"], title=f"{q} — compared by {compare}")
                fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#0b121a", font_color="#d9e6f1", xaxis_gridcolor="#24384a", yaxis_gridcolor="#24384a")
                st.plotly_chart(fig, use_container_width=True)
                st.subheader("4. AI agent summary")
                st.write(answer.get("explanation", "The agent returned data without a text explanation."))
                st.caption(answer.get("agent_log", "smolagents workflow completed"))
                quality = answer.get("quality", {})
                if quality.get("missing_years_by_location"): st.info(f"Missing-year coverage: {quality['missing_years_by_location']}")
                slopes = {}
                for name, g in d.groupby("Compare"):
                    if g["Year"].nunique() > 1:
                        slopes[str(name)] = LinearRegression().fit(g[["Year"]], g["Value"]).coef_[0]
                if slopes: st.caption("Descriptive linear change per year (not a forecast): " + "; ".join(f"{k}: {v:+.2f}" for k,v in slopes.items()))
                if run_summary_benchmark:
                    case_rows = score_benchmark_summary(benchmark_filters, answer, answer.get("explanation", ""))
                    agent_passes = sum(row["pass"] for row in case_rows)
                    baseline_passes = sum(row["baseline_pass"] for row in case_rows)
                    st.subheader("20-question benchmark results")
                    metric_a, metric_b, metric_c = st.columns(3)
                    metric_a.metric("Summary checks passed", f"{agent_passes}/20", f"{agent_passes / 20:.0%}")
                    metric_b.metric("Filters-only baseline", f"{baseline_passes}/20", f"{baseline_passes / 20:.0%}")
                    metric_c.metric("Existing API request", f"{benchmark_latency:.2f}s")
                    st.dataframe(pd.DataFrame(case_rows)[["id", "question", "pass", "agent_answer", "expected_answer", "scoring_rule", "why"]], use_container_width=True, hide_index=True)
                    st.download_button("Download benchmark results (CSV)", pd.DataFrame(case_rows).to_csv(index=False),
                                       file_name="mind-the-gap-filter-benchmark.csv", mime="text/csv")
                    st.download_button("Download reproducible benchmark (JSON)", json.dumps({
                        "filters": benchmark_filters, "api_latency_seconds": benchmark_latency,
                        "summary_coverage_passes": agent_passes, "filters_only_baseline_passes": baseline_passes,
                        "scoring_note": "Deterministic text checks against the same API response; not a separate LLM judge.",
                        "cases": case_rows,
                    }, indent=2, default=str), file_name="mind-the-gap-filter-benchmark.json", mime="application/json")
        except Exception as e:
            st.error(f"The Render agent could not complete this comparison ({type(e).__name__}). Try again or adjust the filters.")

with st.expander("Limitations and methods"):
    st.write("Render runs the smolagents workflow with retrieval, coverage, and analysis tools. The summary is based on selected CDC records. Linear regression describes the historical slope; it is not a forecast. Missing values are not zero, and population indicators do not explain causes or provide medical advice.")
