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
types = o["estimate_types"]
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
                fig = px.bar(d, x=x, y="Value", color=color, barmode="group", text_auto=".1f", hover_data=["Records"], title=f"{q} — compared by {compare}")
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
