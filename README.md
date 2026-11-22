# Mind the Gap

Live app: https://mind-the-gap-mental-health.streamlit.app/  
Project site: https://faleeqwesa.github.io/mind-the-gap-mental-health/  
Source: https://github.com/Faleeqwesa/mind-the-gap-mental-health

Mind the Gap helps public-health and healthcare audiences compare CDC mental-health indicators by question, year, location, and demographic group. Choose filters, compare the bar graph and AI explanation, then review year coverage and historical trends. The portfolio embeds the app on the same page.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

The included `mental_health_cdi.csv` is the Mental Health topic subset from the U.S. Chronic Disease Indicators snapshot dated 2026-09-30.

## AI agent

The app calls the existing Render API at `https://cdc-mental-health-agent-api.onrender.com/analyze`. Its smolagents workflow retrieves CDC records, checks coverage, and analyzes the selected data. The key remains in Render; the Streamlit app does not require it.

## Methods and evaluation

The app groups duplicate records by year, location, and comparison group, reports missing years without treating them as zero, and fits a separate scikit-learn linear regression for each group. Year is the input and annual mean value is the outcome; the slope describes historical change, not a forecast.

The official Part 5 evaluation is a reproducible 20-scenario test of the existing agent. Run `python agent_benchmark.py --dry-run`, then `python agent_benchmark.py` to collect results. See [BENCHMARK.md](BENCHMARK.md) for scoring and limitations. The optional Streamlit checkbox checks one generated summary against 20 criteria; it is not the official benchmark.

Human semantic review of benchmark summaries remains pending. The project walkthrough video still needs to be recorded and added to the portfolio.
