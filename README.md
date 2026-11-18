# Mind the Gap

Interactive CDC mental health indicator explorer, built for public health and healthcare teams. Choose an indicator, measure, demographic factor/group, locations, and years; inspect the chart and underlying table; review a concise summary and missing-year coverage.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

The included `data/mental_health_cdi.csv` is the mental-health subset of the CDC U.S. Chronic Disease Indicators file supplied for this project. To use a newer source file, run `python data/extract.py "path/to/U.S._Chronic_Disease_Indicators.csv"`.

## Optional LLM agent

Without an API key the app shows a deterministic data summary. For the agent summary, set `OPENAI_API_KEY` (and optionally `MODEL_ID`) in the environment or Streamlit secrets. The fixed smolagents workflow calls a data inspection tool, then drafts a short summary from only the filtered values and coverage. The app catches agent errors and falls back to the data-only summary. Do not enter personal health information.

For Streamlit Community Cloud, deploy this repository with `app.py` as the entry point and add `OPENAI_API_KEY` under app Secrets. The GitHub Pages site is the project story and links to the live Streamlit app; GitHub Pages itself does not run Streamlit.

## Method and limits

The app keeps CDC rows with Topic `Mental Health`, filters all values interactively, and averages duplicate rows within year/location/group for plotting while showing the row count. It does not replace missing values. A scikit-learn linear regression slope summarizes direction across observed years; it is descriptive, not a forecast or causal estimate. CDC estimates may be missing, revised, or not comparable across measures, populations, and years. Check indicator definitions and footnotes before operational use.

## Reproducible evaluation

`benchmark.py` builds 20 fixed query cases from the included CSV and writes case-level results, a summary, and an SVG chart under `benchmark_results/`. It uses only the Python standard library and scores data retrieval and coverage, not LLM prose. Run with `python benchmark.py`. See `benchmark_results/README.md` for case design and interpretation.

## Architecture

Streamlit controls → CDC CSV filter → grouped annual values → Plotly chart/table + scikit-learn trend → smolagents inspection tool → grounded summary. If the LLM is unavailable, the deterministic summary remains usable.
