#!/usr/bin/env python3
"""Create the prepared mental-health dataset from a full CDC indicator CSV."""
import argparse
import csv
from pathlib import Path

COLUMNS = [
    "YearStart", "LocationAbbr", "LocationDesc", "Question", "DataValueType",
    "DataValueUnit", "DataValue", "LowConfidenceLimit", "HighConfidenceLimit",
    "DataValueFootnote", "StratificationCategory1", "Stratification1",
]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source",type=Path,help="Full CDC U.S. Chronic Disease Indicators CSV")
    parser.add_argument("--output",type=Path,default=Path("data/mental_health_cdi.csv"))
    args=parser.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.source.open(encoding="utf-8-sig",newline="") as source:
        reader=csv.DictReader(source)
        if "Topic" not in (reader.fieldnames or []) or any(k not in (reader.fieldnames or []) for k in COLUMNS):
            raise ValueError("Source is missing required CDC columns.")
        with args.output.open("w",encoding="utf-8",newline="") as output:
            writer=csv.DictWriter(output,fieldnames=COLUMNS,extrasaction="ignore",lineterminator="\r\n")
            writer.writeheader();count=0
            for row in reader:
                if (row.get("Topic") or "").strip()=="Mental Health":
                    writer.writerow({key:row.get(key,"") for key in COLUMNS});count+=1
    print(f"Wrote {count:,} Mental Health records to {args.output}")

if __name__=="__main__": main()
