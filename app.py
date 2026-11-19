import os
import requests
import pandas as pd
import plotly.express as px
import streamlit as st
from sklearn.linear_model import LinearRegression

API = os.getenv("RENDER_API_BASE", "https://cdc-mental-health-agent-api.onrender.com").rstrip("/")
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
compare = st.selectbox("Compare by", ["Location", "Year"] + cats)
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

if st.button("Generate graph and AI summary", type="primary"):
    if not locs or not groups:
        st.warning("Select at least one location and group.")
    else:
        payload = dict(data_unit=u, question=q, start_year=years[0], end_year=years[1], locations=locs,
                       demographic_categories=dcats, demographic_groups=groups, estimate_type=t)
        try:
            with st.spinner("The smolagents workflow is retrieving and checking CDC values…"):
                r = requests.post(f"{API}/analyze", json=payload, timeout=180); r.raise_for_status(); answer = r.json()
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
                st.dataframe(d, hide_index=True, use_container_width=True)
        except Exception as e:
            st.error(f"The Render agent could not complete this comparison ({type(e).__name__}). Try again or adjust the filters.")

with st.expander("How it works and limitations"):
    st.write("Render runs the smolagents workflow with retrieval, coverage, and analysis tools. The summary is based on selected CDC records. Linear regression describes the historical slope; it is not a forecast. Missing values are not zero, and population indicators do not explain causes or provide medical advice.")
