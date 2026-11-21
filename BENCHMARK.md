# Benchmark protocols

## Interactive filter-based summary benchmark

In the Streamlit explorer, choose the measure, unit, estimate type, year range, location(s), demographic category, and group(s). When **Score the existing AI summary with 20 filter-based questions** is checked, clicking the existing **Generate graph and AI summary** button scores the summary returned by that same `/analyze` request. It does not send extra prompts, make a second API call, or change the Render API contract. `benchmark_questions.json` documents the 20 checks.

The checks cover whether the summary names selected filters, record counts, year coverage, missing years, annual values, and direction of change. Expected facts are derived from structured data in the same API response. Scoring is deterministic text/number matching; paraphrases may be marked incorrect, and a match does not prove the full statement is accurate. No LLM judge is used. The baseline knows only the submitted filter values and can answer B01–B09 (9/20); it has no CDC retrieval for B10–B20. The page reports summary-coverage rate and latency for the existing API request and offers CSV/JSON case downloads.

The current API accepts filters, not free-form benchmark questions. These are evaluator questions applied to the returned summary, not 20 separate prompts given to the agent. The benchmark evaluates how much relevant information the current summary communicates. It does not establish that CDC source records are correct, that the agent is clinically useful, or that the system is safe for individual care. Because the expected facts use the same response's tool evidence, this checks summary coverage against retrieved evidence rather than independently validating CDC.

## Offline calculation check

`benchmark.py` retains a separate deterministic 20-case check over the included CDC snapshot. It covers ordinary filter combinations and two empty-selection edge cases, and compares annual means and missing-year sets against direct source-row calculations. `cases.csv`, `summary.json`, and `benchmark.svg` preserve its case-level and aggregate results. This offline calculation check is not a run of the AI agent and must not be presented as an agent quality score.

## Improvements to pursue

1. Add independently hand-reviewed expected outputs from a pinned CDC snapshot to reduce dependence on the API response as the sole reference.
2. Add API outage, malformed tool response, and very large result-set cases; report latency and failures by case.
3. Have a second reviewer spot-check a sample of exact-match scores and assess whether the answers are clear and useful to the intended public-health audience.
