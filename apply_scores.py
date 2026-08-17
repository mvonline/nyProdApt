"""Apply a batch of agent-researched scores/comments to the DB.
Usage: python3 apply_scores.py apply_scores_batch0.json
Each entry: {id, score_location, score_safety, score_price, score_investment, score_quality, comment}
"""
import json
import sys

from db import get_conn, update_project_fields, add_comment

SCORE_KEYS = ["score_location", "score_safety", "score_price", "score_investment", "score_quality"]


def apply_file(path):
    data = json.loads(open(path, encoding="utf-8").read())
    with get_conn() as conn:
        for rec in data:
            pid = rec["id"]
            fields = {k: rec[k] for k in SCORE_KEYS if k in rec}
            update_project_fields(conn, pid, fields)
            if rec.get("comment"):
                add_comment(conn, pid, rec["comment"], author="research-agent")
    print(f"Applied {len(data)} records from {path}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        apply_file(p)
