"""Fetch recent Reddit posts that match Complaint Desk research keywords."""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_SUBREDDITS = [
    "shopify",
    "ecommerce",
    "smallbusiness",
    "FulfillmentByAmazon",
    "EtsySellers",
    "EbaySellerAdvice",
]

DEFAULT_KEYWORDS = [
    "refund",
    "refunds",
    "chargeback",
    "chargebacks",
    "customer complaint",
    "customer complaints",
    "difficult customer",
    "angry customer",
    "unreasonable customer",
    "return request",
    "return requests",
    "damaged item",
    "item arrived damaged",
    "late delivery",
    "delivery complaint",
    "customer service",
    "support ticket",
    "support tickets",
    "Gorgias",
    "Zendesk",
    "Shopify Inbox",
    "inbox chaos",
    "customer support",
    "repeated questions",
    "same questions",
    "negative review",
    "bad review",
    "threatening legal action",
    "legal threat",
    "compensation",
    "missing item",
    "lost parcel",
    "order not received",
]

RAW_COLUMNS = [
    "post_id",
    "subreddit",
    "title",
    "body",
    "url",
    "permalink",
    "created_utc",
    "created_iso",
    "age_hours",
    "score",
    "num_comments",
    "matched_keywords",
]

REQUIRED_REDDIT_ENV_VARS = [
    "REDDIT_CLIENT_ID",
    "REDDIT_CLIENT_SECRET",
    "REDDIT_USER_AGENT",
]


def parse_list_argument(values: Sequence[str] | None, defaults: Sequence[str]) -> list[str]:
    """Accept space-separated and/or comma-separated CLI values."""
    if not values:
        return list(defaults)

    parsed = []
    for value in values:
        parsed.extend(item.strip() for item in value.split(",") if item.strip())
    return parsed


def find_matched_keywords(title: str, body: str, keywords: Sequence[str]) -> list[str]:
    """Return keywords found in title or body, preserving configured order."""
    text = f"{title}\n{body}".casefold()
    return [keyword for keyword in keywords if keyword.casefold() in text]


def post_to_row(submission, keywords: Sequence[str], now: datetime) -> dict[str, object] | None:
    """Convert a PRAW submission to a CSV row when it matches a keyword."""
    title = submission.title or ""
    body = submission.selftext or ""
    matched = find_matched_keywords(title, body, keywords)
    if not matched:
        return None

    created_utc = float(submission.created_utc)
    created = datetime.fromtimestamp(created_utc, tz=timezone.utc)
    age_hours = max(0.0, (now - created).total_seconds() / 3600)
    permalink = f"https://www.reddit.com{submission.permalink}"

    return {
        "post_id": submission.id,
        "subreddit": str(submission.subreddit),
        "title": title,
        "body": body,
        "url": submission.url,
        "permalink": permalink,
        "created_utc": f"{created_utc:.0f}",
        "created_iso": created.isoformat(),
        "age_hours": f"{age_hours:.2f}",
        "score": submission.score,
        "num_comments": submission.num_comments,
        "matched_keywords": " | ".join(matched),
    }


def collect_posts(
    reddit,
    subreddits: Sequence[str],
    keywords: Sequence[str],
    days: float,
    limit_per_subreddit: int,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    """Collect matching recent posts and deduplicate them by Reddit post ID."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    posts_by_id: dict[str, dict[str, object]] = {}
    successful_fetches = 0

    for subreddit_name in subreddits:
        print(f"Fetching r/{subreddit_name} (up to {limit_per_subreddit} recent posts)...")
        try:
            submissions: Iterable = reddit.subreddit(subreddit_name).new(
                limit=limit_per_subreddit
            )
            for submission in submissions:
                created = datetime.fromtimestamp(
                    float(submission.created_utc), tz=timezone.utc
                )
                if created < cutoff:
                    break

                row = post_to_row(submission, keywords, now)
                if row:
                    posts_by_id[str(row["post_id"])] = row
            successful_fetches += 1
        except Exception as exc:
            print(f"Warning: could not fetch r/{subreddit_name}: {exc}", file=sys.stderr)

    if successful_fetches == 0:
        raise RuntimeError(
            "Every subreddit fetch failed. Check Reddit credentials, connectivity, "
            "and subreddit names."
        )

    return sorted(
        posts_by_id.values(),
        key=lambda row: (float(row["age_hours"]), -int(row["num_comments"])),
    )


def write_csv(rows: Sequence[dict[str, object]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=RAW_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency python-dotenv. Run: pip install -r requirements.txt"
        ) from exc
    load_dotenv()


def build_reddit_client():
    missing = [name for name in REQUIRED_REDDIT_ENV_VARS if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            "Missing Reddit credentials: "
            + ", ".join(missing)
            + ". Add them to your environment or .env file."
        )

    try:
        import praw
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency praw. Run: pip install -r requirements.txt"
        ) from exc

    return praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        user_agent=os.environ["REDDIT_USER_AGENT"],
        check_for_async=False,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find recent Reddit posts matching Complaint Desk pain keywords."
    )
    parser.add_argument("--days", type=float, default=7, help="Maximum post age in days.")
    parser.add_argument(
        "--output", type=Path, default=Path("raw_posts.csv"), help="Raw CSV output path."
    )
    parser.add_argument(
        "--subreddits",
        nargs="+",
        help="Subreddits, separated by spaces and/or commas.",
    )
    parser.add_argument(
        "--keywords",
        nargs="+",
        help="Keywords, separated by spaces and/or commas. Quote multi-word phrases.",
    )
    parser.add_argument(
        "--limit-per-subreddit",
        type=int,
        default=100,
        help="Maximum recent posts to inspect per subreddit.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.days <= 0:
        print("Error: --days must be greater than 0.", file=sys.stderr)
        return 2
    if args.limit_per_subreddit <= 0:
        print("Error: --limit-per-subreddit must be greater than 0.", file=sys.stderr)
        return 2

    try:
        load_dotenv_if_available()
        reddit = build_reddit_client()
        subreddits = parse_list_argument(args.subreddits, DEFAULT_SUBREDDITS)
        keywords = parse_list_argument(args.keywords, DEFAULT_KEYWORDS)
        rows = collect_posts(
            reddit,
            subreddits,
            keywords,
            args.days,
            args.limit_per_subreddit,
        )
        write_csv(rows, args.output)
    except (OSError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {len(rows)} matching posts to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
