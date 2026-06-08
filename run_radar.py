"""Run raw Reddit collection and AI scoring in one command."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch and AI-score Complaint Desk Reddit Radar posts."
    )
    parser.add_argument("--days", type=float, default=7, help="Maximum post age in days.")
    parser.add_argument(
        "--raw", type=Path, default=Path("raw_posts.csv"), help="Raw CSV output path."
    )
    parser.add_argument(
        "--scored",
        type=Path,
        default=Path("scored_posts.csv"),
        help="Scored CSV output path.",
    )
    parser.add_argument("--model", default="gpt-4.1-mini", help="OpenAI model name.")
    parser.add_argument("--max-rows", type=int, help="Only score the first N raw rows.")
    parser.add_argument(
        "--limit-per-subreddit",
        type=int,
        default=100,
        help="Maximum recent posts to inspect per subreddit.",
    )
    return parser


def run_command(command: list[str]) -> int:
    print("+ " + " ".join(command))
    return subprocess.run(command, check=False).returncode


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.days <= 0:
        print("Error: --days must be greater than 0.", file=sys.stderr)
        return 2
    if args.limit_per_subreddit <= 0:
        print("Error: --limit-per-subreddit must be greater than 0.", file=sys.stderr)
        return 2
    if args.max_rows is not None and args.max_rows <= 0:
        print("Error: --max-rows must be greater than 0.", file=sys.stderr)
        return 2

    root = Path(__file__).resolve().parent

    fetch_command = [
        sys.executable,
        str(root / "reddit_radar.py"),
        "--days",
        str(args.days),
        "--output",
        str(args.raw),
        "--limit-per-subreddit",
        str(args.limit_per_subreddit),
    ]
    fetch_status = run_command(fetch_command)
    if fetch_status != 0:
        print("Raw Reddit fetch failed; scoring was not started.", file=sys.stderr)
        return fetch_status

    score_command = [
        sys.executable,
        str(root / "score_posts.py"),
        "--input",
        str(args.raw),
        "--output",
        str(args.scored),
        "--model",
        args.model,
    ]
    if args.max_rows is not None:
        score_command.extend(["--max-rows", str(args.max_rows)])
    return run_command(score_command)


if __name__ == "__main__":
    raise SystemExit(main())
