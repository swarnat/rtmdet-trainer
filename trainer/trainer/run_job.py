"""Run one job in a fresh interpreter.

RQ forks a work horse per job. CUDA cannot be (re)initialised in a forked
process, so the horse only launches this module as a subprocess. That also
releases all GPU memory after each job and isolates crashes (e.g. OOM kills).

    python -m trainer.run_job train <run-id>
    python -m trainer.run_job bootstrap [--force]
"""
from __future__ import annotations

import argparse
import logging
import sys


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("run_id", type=int)
    b = sub.add_parser("bootstrap")
    b.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.cmd == "train":
        from .train import run_training

        run_training(args.run_id)
    else:
        from .bootstrap import run_bootstrap

        version = run_bootstrap(force=args.force)
        print(f"bootstrap result: {version or 'skipped'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
