# Mind the Gap

Mind the Gap is a Streamlit explorer for CDC population-level mental-health indicators. Users filter by question, year, location, and population group, then review a graph, data-coverage notes, and an AI-generated summary. The existing Render API uses smolagents tools to retrieve, check, and analyze CDC records. Scikit-learn adds a descriptive linear trend for each graph series.

## Run the app

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

The app calls the [existing Render API](https://github.com/Faleeqwesa/530_Midtermproject_FatimaAleem/tree/main/backend) configured in `app.py`; API credentials stay in Render. The interactive app is also hosted at [mind-the-gap-mental-health.streamlit.app](https://mind-the-gap-mental-health.streamlit.app/).

## Data

`data/mental_health_cdi.csv` is the 21,883-row Mental Health subset used for local filter options and reproducibility. To rebuild it from the full CDC CSV, run:

```bash
python data/prepare_dataset.py path/to/U.S._Chronic_Disease_Indicators.csv
```

## AI-agent evaluation

The one official benchmark applies the existing 20-question AI-summary checker to 20 filter scenarios and compares the results with the 9/20 filters-only baseline. The Streamlit app also offers the same optional checker for one generated summary. There is no LLM judge. See [BENCHMARK.md](BENCHMARK.md), [case definitions](benchmark/cases.json), [recorded results](benchmark/results.json), and the [summary chart](benchmark/summary.svg).

```bash
python benchmark/run.py --dry-run
python benchmark/run.py
```

The live run calls the existing Render `/analyze` endpoint and writes actual results and question-level checks to `benchmark/results.json`. Review `BENCHMARK.md` for scoring details and limitations.

## Portfolio

`index.html` is the GitHub Pages portfolio. It embeds the hosted Streamlit app and presents the project, data, system workflow, benchmark, and limitations.
