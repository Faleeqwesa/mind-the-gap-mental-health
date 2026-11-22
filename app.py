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
st.set_page_config(page_title="Mind the Gap", page_icon="🧠", layout="wide")
st.title("Mind the Gap")
st.caption("Explore CDC mental health indicators. Select filters, choose what to compare, then view the graph and agent summary.")

@st.cache_data(ttl=1800)
def options():
    r = requests.get(f"{API}/options", timeout=120); r.raise_for_status(); return r.json()

try:
    o = options()
except Exception as e:
    st.error("The data service is unavailable. Refresh in a moment and try again.")
    with st.expander("Technical details"):
        st.caption(type(e).__name__)
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
.stApp,[data-testid="stAppViewContainer"]{background:radial-gradient(ellipse at 78% 0%,rgba(45,99,141,.20),transparent 38%),#0a1119;color:#e1ebf3}
[data-testid="stHeader"]{background:rgba(10,17,25,.96)}
.block-container{max-width:1200px;padding-top:2.1rem;padding-bottom:3rem}
h1,h2,h3{color:#a9cbea;letter-spacing:-.02em}
h1{font-size:2.7rem!important}h2{font-size:1.7rem!important}
p,label,[data-testid="stWidgetLabel"] p{color:#d6e3ee;line-height:1.55}
[data-testid="stCaptionContainer"] p{color:#9eb4c6}
div[data-baseweb="select"]>div,div[data-baseweb="input"]>div{background:#111e2b!important;border-color:#35536c!important;color:#e4eef6!important;border-radius:9px}
[data-baseweb="tag"],[data-baseweb="tag"]>span{background:#254b6b!important;color:#e5f1fa!important;border-radius:7px}
[data-baseweb="tag"] svg{fill:#cfe4f5!important}
[data-baseweb="slider"] [role="slider"]{background:#78acd4!important;border:2px solid #d2e6f4!important;box-shadow:0 0 0 3px #254b6b!important}
[data-baseweb="slider"] [data-testid="stTickBar"]{background:#345c7b!important}
button[kind="primary"],button[data-testid="baseButton-primary"]{background:linear-gradient(120deg,#285f8a,#377ca9)!important;border:1px solid #6091b6!important;color:#f1f7fb!important;border-radius:10px;padding:.55rem 1rem;transition:background .15s ease}
button[kind="primary"]:hover,button[data-testid="baseButton-primary"]:hover{background:#4287b4!important;border-color:#8ab5d5!important}
div[data-testid="stVerticalBlockBorderWrapper"]{border-color:#29465d!important;border-radius:14px!important;background:linear-gradient(135deg,rgba(30,58,79,.72),rgba(15,27,39,.86))}
[data-testid="stMetric"]{background:#112131;border:1px solid #29465d;border-radius:12px;padding:14px}
[data-testid="stMetricLabel"] p{color:#b8cde0!important}[data-testid="stMetricValue"]{color:#d8ebfa!important}
[data-testid="stDataFrame"]{border:1px solid #29465d;border-radius:10px}
[data-testid="stExpander"]{border:1px solid #29465d!important;border-radius:10px!important;background:#101b27}
div[data-testid="stAlert"]{background:#132a3d!important;border:1px solid #355a77!important;color:#e2eef6!important;border-radius:10px}
div[data-testid="stAlert"] p{color:#e2eef6!important}
:focus-visible{outline:3px solid #8ac2e8!important;outline-offset:2px}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;transition:none!important}}
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

st.subheader("Optional AI-summary evaluation")
run_summary_benchmark = st.checkbox("Score the existing AI summary with 20 filter-based questions", value=False,
                                    help="Select this before generating results to show the evaluation.")
with st.expander("What the evaluation checks"):
    st.write("The 20 checks are built from your selected filters and assess the returned summary: question, unit, population, years, record counts, missing data, annual values, and trends. They are checks on one answer—not 20 prompts sent to the agent.")
    st.write("The filters-only baseline is 9/20 because it knows your selections but has no retrieved CDC data. Scoring reuses the graph-and-summary API response, with no extra API call. It is a deterministic coverage check, not an independent CDC data verification; no LLM judge is used.")
with st.expander("Evaluation details"):
    st.caption("Each check compares the summary with selected filters or evidence in the same API response. Exact names, values, and context are required where specified. Text matching can miss paraphrases or contradictions and does not establish usefulness or clinical safety.")
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
                st.markdown("### 1. Results graph")
                x = "Compare" if compare == "Year" else "Year"
                color = None if compare == "Year" else "Compare"
                fig = px.bar(
                    d, x=x, y="Value", color=color,
                    color_discrete_sequence=px.colors.sequential.Blues[2:],
                    barmode="group", text_auto=".1f", hover_data=["Records"],
                    title=f"{q} — compared by {compare}"
                )
                fig.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#0b121a",
                    font_color="#d9e6f1", xaxis_gridcolor="#24384a",
                    yaxis_gridcolor="#24384a", title_font_size=18,
                    legend_title_text="Comparison group", margin=dict(l=16,r=16,t=58,b=20)
                )
                fig.update_yaxes(title_text="Days" if u == "Number" else "Percent (%)", rangemode="tozero")
                fig.update_xaxes(title_text="Year" if compare != "Year" else "Selected year")
                st.plotly_chart(fig, use_container_width=True)
                with st.container(border=True):
                    st.markdown("### 2. AI-generated summary")
                    st.markdown(answer.get("explanation", "The agent returned data without a text explanation."))

                st.markdown("### 3. Data coverage")
                quality = answer.get("quality", {})
                missing_by_location = quality.get("missing_years_by_location", {})
                observed_by_location = quality.get("years_by_location", {})
                if missing_by_location:
                    coverage_columns = st.columns(min(3, len(missing_by_location)))
                    for i, location in enumerate(missing_by_location):
                        with coverage_columns[i % len(coverage_columns)]:
                            with st.container(border=True):
                                st.markdown(f"**{location}**")
                                missing_years = sorted(missing_by_location.get(location) or [])
                                if missing_years:
                                    st.warning("Missing years: " + ", ".join(map(str, missing_years)))
                                else:
                                    st.success("No missing years in the selected period.")
                                observed_years = sorted(observed_by_location.get(location) or [])
                                if observed_years:
                                    st.caption("Years with records: " + ", ".join(map(str, observed_years)))
                else:
                    st.info("The service did not return year-coverage details for this selection.")

                st.markdown("### 4. Linear trend analysis")
                st.caption("Linear regression describes the fitted change across observed years. A positive slope points upward; a negative slope points downward. This is a descriptive trend, not a prediction.")
                slopes = {}
                for name, group in d.groupby("Compare"):
                    if group["Year"].nunique() > 1:
                        slopes[str(name)] = LinearRegression().fit(group[["Year"]], group["Value"]).coef_[0]
                if slopes:
                    slope_columns = st.columns(min(3, len(slopes)))
                    slope_unit = "days per year" if u == "Number" else "percentage points per year"
                    for i, (name, slope) in enumerate(slopes.items()):
                        with slope_columns[i % len(slope_columns)]:
                            with st.container(border=True):
                                st.markdown(f"**{name}**")
                                st.metric("Fitted slope", f"{slope:+.2f} {slope_unit}",
                                          "Upward" if slope > 0.005 else "Downward" if slope < -0.005 else "Nearly flat")
                else:
                    st.info("A linear trend needs observed values from more than one year.")

                if run_summary_benchmark:
                    case_rows = score_benchmark_summary(benchmark_filters, answer, answer.get("explanation", ""))
                    agent_passes = sum(row["pass"] for row in case_rows)
                    baseline_passes = sum(row["baseline_pass"] for row in case_rows)
                    st.markdown("### 5. AI-summary benchmark")
                    st.caption("These checks evaluate the summary shown above and reuse this request.")
                    metric_a, metric_b, metric_c = st.columns(3)
                    metric_a.metric("Summary checks passed", f"{agent_passes}/20", f"{agent_passes / 20:.0%}")
                    metric_b.metric("Filters-only baseline", f"{baseline_passes}/20", f"{baseline_passes / 20:.0%}")
                    metric_c.metric("API response time", f"{benchmark_latency:.2f}s")
                    with st.expander("Review all 20 evaluation checks"):
                        st.dataframe(
                            pd.DataFrame(case_rows)[["id", "question", "pass", "agent_answer", "expected_answer", "scoring_rule", "why"]],
                            use_container_width=True, hide_index=True
                        )
        except Exception as e:
            st.error("This comparison could not be completed. Try again or adjust the selected filters.")
            with st.expander("Technical details"):
                st.caption(type(e).__name__)

with st.expander("Limitations and methods"):
    st.write("Render runs the smolagents workflow with retrieval, coverage, and analysis tools. The summary is based on selected CDC records. Linear regression describes the historical slope; it is not a forecast. Missing values are not zero, and population indicators do not explain causes or provide medical advice.")
