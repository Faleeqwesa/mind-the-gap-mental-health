import os
import pandas as pd
import plotly.express as px
import streamlit as st
from sklearn.linear_model import LinearRegression

st.set_page_config(page_title="Mind the Gap | U.S. mental health", page_icon=":brain:", layout="wide")
st.title("Mind the Gap")
st.caption("Explore CDC mental health indicators across years and populations. This is descriptive surveillance data, not a diagnosis or clinical recommendation.")

@st.cache_data
def load_data():
    d = pd.read_csv("mental_health_cdi.csv")
    d["Year"] = pd.to_numeric(d.YearStart, errors="coerce")
    d["Value"] = pd.to_numeric(d.DataValue, errors="coerce")
    d["Group"] = d.Stratification1.fillna("Overall")
    return d.dropna(subset=["Year"])

d = load_data()
with st.sidebar:
    st.header("Choose a comparison")
    questions = sorted(d.Question.dropna().unique())
    question = st.selectbox("Indicator", questions, index=questions.index("Depression among adults") if "Depression among adults" in questions else 0)
    metric_rows = d[d.Question == question]
    metric = st.selectbox("Measure", sorted(metric_rows.DataValueType.dropna().unique()))
    units = sorted(metric_rows.loc[metric_rows.DataValueType == metric, "DataValueUnit"].dropna().unique())
    unit = st.selectbox("Unit", units) if len(units) > 1 else (units[0] if units else "")
    categories = sorted(metric_rows.StratificationCategory1.fillna("Overall").unique())
    category = st.selectbox("Demographic factor", categories, index=categories.index("Overall") if "Overall" in categories else 0)
    group_rows = metric_rows[metric_rows.StratificationCategory1.fillna("Overall") == category]
    groups = sorted(group_rows.Stratification1.fillna("Overall").unique())
    selected_groups = st.multiselect("Groups to compare", groups, default=["Overall"] if "Overall" in groups else groups[:1])
    available_locations = sorted(d.LocationDesc.dropna().unique())
    defaults = [x for x in ["North Carolina", "United States"] if x in available_locations]
    locations = st.multiselect("Locations", available_locations, default=defaults)
    years = st.slider("Years", int(d.Year.min()), int(d.Year.max()), (int(d.Year.min()), int(d.Year.max())))

f = d[(d.Question == question) & (d.DataValueType == metric) & (d.DataValueUnit == unit) & (d.StratificationCategory1.fillna("Overall") == category) & (d.Stratification1.fillna("Overall").isin(selected_groups)) & d.LocationDesc.isin(locations) & d.Year.between(*years)].copy()
f = f.dropna(subset=["Value"])
if f.empty:
    st.warning("No values match these filters. Try another indicator, measure, or population.")
else:
    # Average duplicate source rows within each location-year; preserve sample count for transparency.
    series = f.groupby(["Year", "LocationDesc", "Group"], as_index=False).agg(Value=("Value", "mean"), Records=("Value", "size"))
    chart = px.line(series, x="Year", y="Value", color="LocationDesc", line_dash="Group", markers=True, labels={"Value": unit, "Year": "Year"}, title=f"{question} - {category}")
    chart.update_layout(legend_title_text="Location", hovermode="x unified")
    st.plotly_chart(chart, use_container_width=True)
    cols = st.columns(3)
    for i, loc in enumerate(locations):
        q = series[series.LocationDesc == loc]
        cols[i % 3].metric(f"{loc} - observed years", f"{q.Year.nunique()} / {years[1]-years[0]+1}")
    missing = {f"{loc} / {g}": sorted(set(range(years[0], years[1]+1)) - set(series.loc[(series.LocationDesc == loc) & (series.Group == g), "Year"].astype(int))) for loc in locations for g in selected_groups}
    # Traditional ML: fit a simple linear trend to each available location series.
    trends = {}
    for (loc, grp), q in series.groupby(["LocationDesc", "Group"]):
        if len(q) >= 2:
            model = LinearRegression().fit(q[["Year"]], q.Value)
            trends[f"{loc} / {grp}"] = float(model.coef_[0])
    evidence = {"indicator": question, "measure": metric, "population_factor": category, "groups": selected_groups, "range": years, "points": int(len(f)), "annual_rows": series.to_dict("records"), "missing_years": missing, "linear_change_per_year": trends}
    st.subheader("Data summary")
    st.caption("The summary uses the visible data only. The optional agent checks coverage, calculates trends, and grounds its wording in the values shown.")
    # Fixed agent workflow: retrieve filtered evidence, check coverage/trends, draft grounded summary.
    summary = None
    if os.getenv("OPENAI_API_KEY"):
        try:
            from smolagents import CodeAgent, OpenAIServerModel, tool
            @tool
            def inspect_evidence() -> str:
                """Return the filtered CDC values, missing years, and fitted annual trends."""
                return str(evidence)
            agent = CodeAgent(tools=[inspect_evidence], model=OpenAIServerModel(model_id=os.getenv("MODEL_ID", "gpt-4o-mini")), max_steps=3, verbosity_level=0)
            summary = agent.run("Call inspect_evidence. Write one concise, factual sentence comparing the selected groups and locations. Mention observed coverage and missing years when present. Treat trends as descriptive and do not infer causality or make health recommendations.")
        except Exception as e:
            st.info(f"AI agent unavailable; showing a data-only summary ({type(e).__name__}).")
    if summary:
        st.write(summary)
    else:
        bits = []
        for (loc, grp), q in series.groupby(["LocationDesc", "Group"]):
            delta = q.sort_values("Year").Value.iloc[-1] - q.sort_values("Year").Value.iloc[0] if len(q) > 1 else 0
            bits.append(f"{loc} / {grp}: {len(q)} observed year(s), {q.Value.iloc[0]:.1f} to {q.Value.iloc[-1]:.1f} ({delta:+.1f} across observed endpoints)")
        st.write(". ".join(bits) + ". This describes reported values and does not establish why they changed.")
    with st.expander("How this works and limitations"):
        st.write("A linear regression line slope is fitted to the displayed annual values; it is a simple descriptive ML baseline, not a forecast. CDC estimates can be missing, revised, or not directly comparable across years or populations. Hover over points for values. The app reports observed rows and missing years rather than treating gaps as zero.")
    st.dataframe(series, hide_index=True, use_container_width=True)

