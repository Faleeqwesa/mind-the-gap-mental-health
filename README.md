# Mind the Gap

A Streamlit explorer for comparing CDC population-level mental-health indicators by question, year, location, age, sex, and race/ethnicity.

- [Live application](https://mind-the-gap-mental-health.streamlit.app/)
- [Project portfolio](https://faleeqwesa.github.io/mind-the-gap-mental-health/)
- [GitHub repository](https://github.com/Faleeqwesa/mind-the-gap-mental-health)

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

The application uses the existing Render `/analyze` API; API credentials stay in Render. Its bundled data is the Mental Health subset of the CDC Chronic Disease Indicators snapshot dated 2026-09-30.

## Official benchmark

The only official evaluation applies the existing Streamlit 20-question summary checker to 20 distinct filter scenarios. The app and reproducible runner use the same scorer and 9/20 filters-only baseline.

```bash
python benchmark/run.py --dry-run
python benchmark/run.py
```

See [BENCHMARK.md](BENCHMARK.md) for current results, examples, limits, and improvements. Per-question results and response times are stored in `benchmark/results.json`.

## Methods

The smolagents workflow retrieves CDC records, checks coverage, and analyzes annual values. The app reports missing years without treating them as zero and fits scikit-learn linear regression separately for each comparison group. Year is the input feature; annual mean value is the outcome. The slope describes historical change, not a forecast.

