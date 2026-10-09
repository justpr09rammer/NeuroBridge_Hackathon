"""Initialise the database and load the fictional demo scenario (idempotent).

Usage: python -m scripts.seed [--reset] [--evaluate]
"""
from __future__ import annotations

import argparse

from talentlens.core import db
from talentlens.demo.seed import reset_demo, run_and_store_evaluation, seed_demo


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="delete demo data first, then reseed")
    ap.add_argument("--evaluate", action="store_true", help="also run the quality & fairness evaluation")
    args = ap.parse_args()
    db.configure()
    with db.session_scope() as s:
        out = reset_demo(s) if args.reset else seed_demo(s)
        print(f"Resources added: {out['resources_added']}; demo vacancy id: {out['vacancy_id']} (created: {out['vacancy_created']})")
        for m in out["messages"]:
            print("  ", m)
        if args.evaluate:
            run = run_and_store_evaluation(s)
            print(f"Evaluation run {run.id} ({run.pipeline}) in {run.duration_s}s")
            for k, m in run.metrics.items():
                print(f"   {m['label']}: {m['value']:.1%} (n={m['n']})")


if __name__ == "__main__":
    main()
