#!/usr/bin/env python3
"""Run the existing Streamlit summary scorer on 20 live agent responses."""
import argparse, json, math, os, statistics, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from evaluation import score_benchmark_summary
CASE_FILE=Path(__file__).with_name("cases.json")
RESULT_FILE=Path(__file__).with_name("results.json")
SVG_FILE=Path(__file__).with_name("summary.svg")
DEFAULT_API="https://cdc-mental-health-agent-api.onrender.com"

def load_cases():
    cases=json.loads(CASE_FILE.read_text(encoding="utf-8"))["cases"]
    ids=[c["id"] for c in cases]
    sigs=[json.dumps(c["filters"],sort_keys=True) for c in cases]
    if len(cases)!=20 or len(set(ids))!=20 or len(set(sigs))!=20:
        raise ValueError("Expected 20 unique scenarios and filter combinations.")
    return cases

def validate_snapshot(cases):
    import csv
    with (ROOT/"data"/"mental_health_cdi.csv").open(encoding="utf-8-sig",newline="") as f:
        rows=list(csv.DictReader(f))
    for c in cases:
        x=c["filters"]
        matched=[r for r in rows if r.get("Question")==x["question"] and r.get("DataValueUnit")==x["data_unit"]
          and r.get("DataValueType")==x["estimate_type"] and r.get("LocationDesc") in x["locations"]
          and (r.get("StratificationCategory1") or "Overall") in x["demographic_categories"]
          and (r.get("Stratification1") or "Overall") in x["demographic_groups"]
          and r.get("YearStart","").isdigit() and x["start_year"]<=int(r["YearStart"])<=x["end_year"]]
        if not matched: raise ValueError(f"{c['id']} has no matching snapshot records.")
    return len(rows)

def post(api,filters,timeout):
    req=urllib.request.Request(api.rstrip("/")+"/analyze",data=json.dumps(filters).encode(),
      headers={"Content-Type":"application/json"},method="POST")
    t=time.perf_counter()
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r: status,body=r.status,r.read().decode("utf-8",errors="replace")
    except urllib.error.HTTPError as e: status,body=e.code,e.read().decode("utf-8",errors="replace")
    except Exception as e: return None,None,round(time.perf_counter()-t,3),f"{type(e).__name__}: {e}"
    elapsed=round(time.perf_counter()-t,3)
    try:return status,json.loads(body),elapsed,None
    except json.JSONDecodeError:return status,None,elapsed,"Response was not valid JSON."

def aggregate(results):
    scored=[c for c in results if c.get("score") is not None]
    times=[c["latency_seconds"] for c in results if c.get("latency_seconds") is not None]
    passed=sum(c["score"]["passed"] for c in scored); total=len(scored)*20; baseline=len(scored)*9
    return {"scenarios_planned":20,"scenarios_scored":len(scored),"summary_checks_passed":passed,
      "summary_checks_total":total,"mean_checks_per_summary":round(passed/len(scored),2) if scored else None,
      "filters_only_baseline_passed":baseline,"filters_only_baseline_total":total,
      "filters_only_baseline_per_summary":"9/20","summary_pass_rate":round(passed/total,4) if total else None,
      "baseline_pass_rate":round(baseline/total,4) if total else None,
      "response_time_median_seconds":round(statistics.median(times),3) if times else None,
      "response_time_p95_seconds":sorted(times)[max(0,math.ceil(.95*len(times))-1)] if times else None,
      "cases":[{"id":c["id"],"scenario":c["scenario"],
        "score":f"{c['score']['passed']}/20" if c.get("score") else None,
        "latency_seconds":c.get("latency_seconds"),"status":c.get("status")} for c in results]}

def write_svg(summary):
    scored=[(c["id"],int(c["score"].split("/")[0])) for c in summary["cases"] if c["score"]]
    w,h=920,370; left,top,cw,ch=60,48,820,235; gap=8; bw=(cw-gap*19)/20
    bars=[]
    for i,(cid,value) in enumerate(scored):
        x=left+i*(bw+gap); bh=ch*value/20; y=top+ch-bh
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="4" fill="#2878b8"><title>{cid}: {value}/20</title></rect><text x="{x+bw/2:.1f}" y="{top+ch+19}" text-anchor="middle" font-size="10">{cid[-2:]}</text>')
    by=top+ch-ch*9/20
    svg=f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" aria-label="AI summary checks passed in each scenario; dashed line is the 9 of 20 filters-only baseline">
<rect width="100%" height="100%" fill="#f3f8fc"/>
<text x="{left}" y="26" font-family="Arial,sans-serif" font-size="18" font-weight="700" fill="#17354e">AI-summary checks passed per scenario</text>
<line x1="{left}" y1="{by:.1f}" x2="{left+cw}" y2="{by:.1f}" stroke="#143c5b" stroke-width="2" stroke-dasharray="7 5"/>
<text x="{left+cw-2}" y="{by-7:.1f}" text-anchor="end" font-family="Arial,sans-serif" font-size="12" fill="#143c5b">Filters-only baseline 9/20</text>
<line x1="{left}" y1="{top+ch}" x2="{left+cw}" y2="{top+ch}" stroke="#8299aa"/>
{''.join(bars)}
<text x="{left}" y="{h-14}" font-family="Arial,sans-serif" font-size="12" fill="#526b7e">Scenario A01–A20 · deterministic evidence coverage, not semantic accuracy</text></svg>'''
    SVG_FILE.write_text(svg,encoding="utf-8")

def compact_evidence(answer):
    """Keep only fields consumed by the shared scorer for a compact replay file."""
    if not isinstance(answer,dict): return None
    retrieval=answer.get("retrieval") or {}
    quality=answer.get("quality") or {}
    analysis=answer.get("analysis") or {}
    keep_rows=("LocationDesc","StratificationCategory1","Stratification1","YearStart","mean_value")
    return {
      "retrieval":{k:retrieval.get(k) for k in ("matching_rows","rows_with_values","rows_missing_values")},
      "quality":{k:quality.get(k) for k in ("years_by_location","missing_years_by_location","years_shared_by_all_selected_locations")},
      "analysis":{"valid_rows_used":analysis.get("valid_rows_used"),
        "summary_by_location_and_year":[{k:row.get(k) for k in keep_rows}
          for row in analysis.get("summary_by_location_and_year",[])]}}

def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--api-base",default=os.getenv("RENDER_API_BASE",DEFAULT_API))
    p.add_argument("--timeout",type=int,default=180); p.add_argument("--dry-run",action="store_true")
    p.add_argument("--resume",action="store_true"); args=p.parse_args()
    cases=load_cases(); rows=validate_snapshot(cases)
    if args.dry_run:
        print(json.dumps({"status":"validated_no_requests_sent","scenarios":len(cases),"unique_filters":len(cases),
          "matching_snapshot_records":rows,"scorer":"evaluation.score_benchmark_summary","criteria_per_summary":20,
          "baseline_per_summary":"9/20"},indent=2)); return
    old={}
    if args.resume and RESULT_FILE.exists():
        old={c["id"]:c for c in json.loads(RESULT_FILE.read_text(encoding="utf-8")).get("results",[])}
    started=datetime.now(timezone.utc).isoformat()
    results=[old[c["id"]] for c in cases if c["id"] in old]
    done={c["id"] for c in results}
    for case in cases:
        if case["id"] in done: continue
        status,answer,latency,error=post(args.api_base,case["filters"],args.timeout)
        explanation=(answer or {}).get("explanation","") if isinstance(answer,dict) else ""
        score_rows=None
        if status is not None and 200<=status<300 and isinstance(answer,dict) and explanation.strip():
            score_rows=score_benchmark_summary(case["filters"],answer,explanation)
        item={"id":case["id"],"scenario":case["scenario"],"filters":case["filters"],"status":status,
          "latency_seconds":latency,"transport_error":error,"explanation":explanation,
          "score":{"passed":sum(bool(x["pass"]) for x in score_rows),"total":len(score_rows)} if score_rows else None,
          "baseline":{"passed":sum(bool(x["baseline_pass"]) for x in score_rows),"total":len(score_rows)} if score_rows else None,
          "checks":[{"id":x["id"],"pass":bool(x["pass"])} for x in (score_rows or [])],
          "response_evidence":compact_evidence(answer)}
        results.append(item); results.sort(key=lambda x:x["id"])
        doc={"benchmark":"Official AI-summary evaluation across 20 scenarios",
          "scorer":"Exact evaluation.score_benchmark_summary function shared with app.py",
          "started_utc":started,"updated_utc":datetime.now(timezone.utc).isoformat(),
          "endpoint":args.api_base.rstrip("/")+"/analyze","scenarios":cases,"summary":aggregate(results),"results":results}
        RESULT_FILE.write_text(json.dumps(doc,indent=2,ensure_ascii=False),encoding="utf-8")
        write_svg(doc["summary"])
        score=f"{item['score']['passed']}/20" if item["score"] else "no summary"
        print(f"{item['id']}: HTTP {status}; {score}; {latency:.2f}s",flush=True)
    doc=json.loads(RESULT_FILE.read_text(encoding="utf-8")); doc["updated_utc"]=datetime.now(timezone.utc).isoformat()
    doc["summary"]=aggregate(doc["results"]); RESULT_FILE.write_text(json.dumps(doc,indent=2,ensure_ascii=False),encoding="utf-8")
    write_svg(doc["summary"]); print(json.dumps(doc["summary"],indent=2),flush=True)

if __name__=="__main__": main()

