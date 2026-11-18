import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from sklearn.linear_model import LinearRegression

st.set_page_config(page_title="Mind the Gap | U.S. mental health", page_icon=":brain:", layout="wide")
st.title("Mind the Gap")
st.caption("Explore CDC mental health indicators across years and populations. This is descriptive surveillance data, not a diagnosis or clinical recommendation.")

@st.cache_data
def load_data():
    path = "mental_health_cdi.csv" if Path("mental_health_cdi.csv").exists() else "data/mental_health_cdi.csv"
    d = pd.read_csv(path)
    d["Year"] = pd.to_numeric(d.YearStart, errors="coerce")
    d["Value"] = pd.to_numeric(d.DataValue, errors="coerce")
    d["Group"] = d.Stratification1.fillna("Overall")
    return d.dropna(subset=["Year"])

d = load_data()
st.subheader("1. Choose your filters")
st.caption("Compare locations, demographic groups such as age or sex, or both. Choose one location to compare groups within it, or select multiple locations and groups.")
questions = sorted(d.Question.dropna().unique())
question = st.selectbox("Indicator / question", questions, index=questions.index("Depression among adults") if "Depression among adults" in questions else 0)
metric_rows = d[d.Question == question]
row1 = st.columns(3)
metric = row1[0].selectbox("Measure", sorted(metric_rows.DataValueType.dropna().unique()))
units = sorted(metric_rows.loc[metric_rows.DataValueType == metric, "DataValueUnit"].dropna().unique())
unit = row1[1].selectbox("Unit", units) if len(units) > 1 else (units[0] if units else "")
categories = sorted(metric_rows.StratificationCategory1.fillna("Overall").unique())
category = row1[2].selectbox("Demographic factor", categories, index=categories.index("Overall") if "Overall" in categories else 0)
group_rows = metric_rows[metric_rows.StratificationCategory1.fillna("Overall") == category]
groups = sorted(group_rows.Stratification1.fillna("Overall").unique())
row2 = st.columns(2)
selected_groups = row2[0].multiselect("Groups to compare", groups, default=["Overall"] if "Overall" in groups else groups[:1])
available_locations = sorted(d.LocationDesc.dropna().unique())
defaults = [x for x in ["North Carolina", "United States"] if x in available_locations]
locations = row2[1].multiselect("Locations to compare", available_locations, default=defaults)
years = st.slider("Year range", int(d.Year.min()), int(d.Year.max()), (int(d.Year.min()), int(d.Year.max())))

f = d[(d.Question == question) & (d.DataValueType == metric) & (d.DataValueUnit == unit) &
      (d.StratificationCategory1.fillna("Overall") == category) &
      d.Stratification1.fillna("Overall").isin(selected_groups) & d.LocationDesc.isin(locations) & d.Year.between(*years)].dropna(subset=["Value"]).copy()

st.subheader("2. Comparison bar graph")
if f.empty:
    st.warning("No values match these filters. Choose at least one group and location, or adjust the indicator or year range.")
else:
    series = f.groupby(["Year", "LocationDesc", "Group"], as_index=False).agg(Value=("Value", "mean"), Records=("Value", "size"))
    chart = px.bar(series, x="Year", y="Value", color="LocationDesc", pattern_shape="Group", barmode="group",
                   text_auto=".1f", labels={"Value": unit, "Year": "Year"}, title=f"{question} - {category}")
    chart.update_layout(legend_title_text="Location / group", hovermode="x unified")
    st.plotly_chart(chart, use_container_width=True)

    st.subheader("3. AI agent summary")
    st.caption("The smolagents workflow checks the filtered data and coverage before writing. Add an OPENAI_API_KEY in Streamlit app Secrets to enable its LLM; otherwise the app shows the same evidence as a data-only summary.")
    missing = {f"{loc} / {grp}": sorted(set(range(years[0], years[1] + 1)) - set(series.loc[(series.LocationDesc == loc) & (series.Group == grp), "Year"].astype(int))) for loc in locations for grp in selected_groups}
    trends = {}
    for (loc, grp), q in series.groupby(["LocationDesc", "Group"]):
        if len(q) >= 2:
            trends[f"{loc} / {grp}"] = float(LinearRegression().fit(q[["Year"]], q.Value).coef_[0])
    evidence = {"question": question, "measure": metric, "unit": unit, "factor": category, "groups": selected_groups,
                "years": years, "locations": locations, "values": series.to_dict("records"),
                "missing_years": missing, "linear_change_per_year": trends}
    summary = None
    if os.getenv("OPENAI_API_KEY"):
        try:
            from smolagents import CodeAgent, OpenAIServerModel, tool

            @tool
            def inspect_filtered_data() -> str:
                """Return the selected CDC values, missing years, and descriptive trend estimates."""
                return str(evidence)

            agent = CodeAgent(tools=[inspect_filtered_data], model=OpenAIServerModel(model_id=os.getenv("MODEL_ID", "gpt-4o-mini")), max_steps=3, verbosity_level=0)
            summary = agent.run("Call inspect_filtered_data. Write one factual sentence comparing the selected locations and groups. Mention observed data coverage and missing years where relevant. Do not infer causes, forecast, or give medical advice.")
        except Exception as err:
            st.info(f"The AI agent could not run ({type(err).__name__}); showing the data-only summary.")
    if summary:
        st.write(summary)
    else:
        sentences = []
        for (loc, grp), q in series.groupby(["LocationDesc", "Group"]):
            q = q.sort_values("Year")
            delta = q.Value.iloc[-1] - q.Value.iloc[0] if len(q) > 1 else 0
            gaps = missing[f"{loc} / {grp}"]
            sentences.append(f"{loc} / {grp}: {len(q)} observed year(s), {q.Value.iloc[0]:.1f} to {q.Value.iloc[-1]:.1f} ({delta:+.1f} from first to last); missing years: {gaps or 'none'}")
        st.write(". ".join(sentences) + ". These reported values do not establish why they changed.")
    st.dataframe(series, hide_index=True, use_container_width=True)

with st.expander("How this works and limitations"):
    st.write("The chart averages duplicate rows within each year, location, and group. The agent uses a data inspection tool and the selected values; a scikit-learn linear regression estimates a descriptive slope, not a forecast. CDC estimates may be missing, revised, or not comparable across years or populations. Missing values are never treated as zero.")
