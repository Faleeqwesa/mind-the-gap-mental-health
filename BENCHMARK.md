# Benchmark protocols

The project has two separate evaluations. Their scores must not be combined.

## Interactive AI-summary benchmark

In the embedded Streamlit explorer, select an indicator, unit, estimate, year range, locations, demographic category, and groups. After the normal **Generate graph and AI summary** action returns, the app evaluates that exact summary against 20 questions generated from those selected filters. It reuses the same `/analyze` response and sends no additional API request or benchmark prompts.

For each check, the app displays the question, pass/fail, the full answer returned by the agent, expected evidence, the scoring rule, and an explanation of the result. Checks require exact selected names or expected values where appropriate, together with relevant context such as record/coverage labels. The filters-only baseline can answer the nine selection questions from the controls (9/20); it has no retrieved CDC evidence for the other eleven. The baseline is a deliberately limited reference, not another AI system.

Expected annual values, year coverage, and other evidence facts are currently taken from the structured data in the same API response. Thus this is a check of what the summary communicates about the response's evidence, not independent validation against the original CDC source. Scoring is deterministic text and number matching, not an LLM judge. It can miss valid paraphrases, and text matching cannot reliably detect every contradiction or establish usefulness. The UI and downloadable JSON/CSV preserve the summary, criteria, expected evidence, result, and rationale for a run.

The API accepts filter inputs rather than free-form evaluator questions. These 20 items are scoring criteria applied after the response; they are not 20 questions sent to the agent. To evaluate repeated filter combinations or failure injection (API outage, malformed response, very large response), run separate cases in a future benchmark harness. The current interactive score should not be presented as evidence of clinical validity or individual medical advice.

## Offline retrieval and coverage benchmark

`benchmark.py` separately tests 20 fixed representative filter cases against the bundled `mental_health_cdi.csv` snapshot. It compares annual means and missing-year sets with direct calculations from matching source rows. Cases include multiple indicators, locations, demographic groups, empty selections, and year ranges. The checked-in `cases.csv`, `summary.json`, and `benchmark.svg` are artifacts from the most recent committed script run; the portfolio labels them as a repository snapshot, not a live AI evaluation. Re-run the script after changing the benchmark or CDC snapshot to refresh these artifacts.

This deterministic benchmark currently reports 20/20 matching pipeline calculations and 7/20 exact matches for the overall-only baseline. It tests data calculation and coverage only. It does not evaluate AI writing, summary quality, clinical usefulness, or the Render agent.

## Concrete next steps

1. Add independently reviewed expected values pinned to a named CDC snapshot and compare the API-returned series and AI summary against those references.
2. Add reproducible failure cases for API errors, malformed responses, and empty result sets, with success and latency reported per case.
3. Have a second reviewer spot-check both passing and failing summary checks for factual accuracy and public-health usefulness; revise deterministic rules where the spot-check finds false positives or false negatives.

## Backend boundary

The GitHub repository contains the Streamlit caller but not the Render `/analyze` implementation, smolagents tools, or agent prompt. Improving the agent's actual reasoning requires the backend source files that define the route, agent/tools, prompt, and response schema. The front end, API URL, request shape, API key, and Render configuration are not changed by this benchmark work.
