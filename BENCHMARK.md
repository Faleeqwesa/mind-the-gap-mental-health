# Official AI-summary benchmark

## Method

The Streamlit app's existing deterministic checker is the only official evaluation. Its 20 criteria and scoring logic are shared from `evaluation.py`; the app and `benchmark/run.py` call the same `score_benchmark_summary` function unchanged.

The fixed test set runs 20 distinct filter scenarios through the existing Render `/analyze` endpoint. Each generated summary is scored against the same B01–B20 checks. The filters-only baseline remains 9/20 (45%) per scenario, since it can satisfy B01–B09 from the filters but has no summary evidence for B10–B20. Over 20 scenarios, that is 180/400.

Run `python benchmark/run.py --dry-run` to verify all filter combinations have data in the bundled CDC snapshot. Run `python benchmark/run.py` to make a fresh set of 20 API calls. The runner stores inputs, generated summaries and the structured response evidence used by the scorer, question-level results, baseline scores, and response times in `benchmark/results.json`. The portfolio chart is `benchmark/summary.svg`.

## Current results

Run completed 2026-11-22 UTC.

| Measure | AI summary | Filters-only baseline |
|---|---:|---:|
| Scenarios | 20 | 20 |
| Checks passed | 318/400 (79.5%) | 180/400 (45.0%) |
| Mean per summary | 15.9/20 | 9/20 |
| Response time | Median 10.757s; p95 12.370s | — |

Scores across individual AI summaries ranged from 10/20 to 18/20.

![AI-summary score by scenario compared with the 9/20 filters-only baseline](benchmark/summary.svg)

## Examples and lessons

- **Highest score, A11 (18/20):** U.S. current poor mental health among high school students, 2019–2023. It described available/missing years and annual values. It missed explicit wording for shared years and the number of returned series.
- **Lowest score, A17 (10/20):** North Carolina postpartum depressive symptoms, 2020–2022. The summary explained that three records had no numeric estimates, but spelled counts as words, which the exact-number checks missed. Checks B17–B20 also expected annual numeric series that were not available.

Improvements based on these results:

1. Guide summaries to state record counts as numerals and explicitly name returned series and shared years.
2. After human review, refine a future evaluator version to recognize number words and mark annual trend checks not applicable when no numeric series exists. The current benchmark preserves the existing questions and scoring rules.

## Limits

This deterministic score measures whether expected evidence appears in text. It does not establish semantic accuracy, clinical safety, usefulness, or independent CDC source accuracy; expected facts are drawn from the same response being scored. Human review is needed before interpreting check misses as factual omissions. The optional in-app checkbox remains available for reviewing one generated summary with the same questions and baseline.


