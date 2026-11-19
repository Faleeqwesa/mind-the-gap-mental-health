# Mind the Gap

Live app: https://mind-the-gap-mental-health.streamlit.app/  
Project site: https://faleeqwesa.github.io/mind-the-gap-mental-health/  
Source: https://github.com/Faleeqwesa/mind-the-gap-mental-health

Use the controls in the app to select a CDC mental health question, demographic factor and groups, locations, and year range. Year appears in Compare by only when you select a single year. The bar graph follows the filters, then the AI summary. The portfolio embeds the explorer on the same page.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

The supplied `mental_health_cdi.csv` is the Mental Health topic subset from `U.S._Chronic_Disease_Indicators_20260930.csv`. Rebuild the extract with `python data/extract.py path/to/full_CDC_file.csv` in the source package.

## AI agent

The app calls the Render API at `https://cdc-mental-health-agent-api.onrender.com`. Its `/analyze` workflow uses smolagents with CDC retrieval, coverage checks, and analysis tools. The LLM key stays in Render’s private environment; the Streamlit app does not need an OpenAI key in its Secrets.

## Methods and evaluation

The app groups duplicate source rows by year, location, and selected group; reports missing years without filling them as zero; and fits a scikit-learn linear regression slope as a descriptive trend. `benchmark.py` reproduces 20 exact-value and missing-year cases against a simple overall-only baseline. Current results are 20/20 pipeline matches and 7/20 baseline matches. This evaluates retrieval/coverage calculations, not LLM response quality.

The project site explains the audience, product purpose, workflow, source, benchmark, and limitations. Add a walkthrough recording there to complete that portfolio element. See `BENCHMARK.md` for the benchmark scope.
