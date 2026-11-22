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


from evaluation import score_benchmark_summary

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
    data = pd.read_csv("data/mental_health_cdi.csv", usecols=["Question", "DataValueUnit", "DataValueType"])
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
st.caption("Optional: check whether this one AI summary communicates the selected question, unit, population, years, record counts, missing data, annual values, and trends.")
with st.expander("Evaluation details"):
    st.caption("The 20 deterministic checks reuse the graph-and-summary response. The filters-only baseline is 9/20. Checks compare selected filters and evidence in that response; text matching can miss paraphrases or contradictions and does not establish factual or clinical accuracy. This is an optional one-summary quality check, not the official 20-scenario agent benchmark.")
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

                if run_summary_benchmark:
                    case_rows = score_benchmark_summary(benchmark_filters, answer, answer.get("explanation", ""))
                    agent_passes = sum(row["pass"] for row in case_rows)
                    baseline_passes = sum(row["baseline_pass"] for row in case_rows)
                    st.markdown("### Optional AI-summary quality check")
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

                st.markdown("### 5. Linear trend analysis")
                st.caption("A scikit-learn linear regression is fitted separately for each comparison group: year is the input and annual mean value is the outcome. Positive and negative slopes describe upward and downward historical change; this is not a future prediction.")
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

        except Exception as e:
            st.error("This comparison could not be completed. Try again or adjust the selected filters.")
            with st.expander("Technical details"):
                st.caption(type(e).__name__)

with st.expander("Limitations and methods"):
    st.write("Render runs the smolagents workflow with retrieval, coverage, and analysis tools. The summary is based on selected CDC records. Linear regression describes the historical slope; it is not a forecast. Missing values are not zero, and population indicators do not explain causes or provide medical advice.")

