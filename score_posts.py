"""Score raw Complaint Desk Reddit Radar CSV rows with AI or keyword rules."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence


DEFAULT_MODEL = "gpt-4.1-mini"

SCORING_COLUMNS = [
    "relevance_score_1_10",
    "pain_category",
    "urgency",
    "current_tool_mentioned",
    "is_potential_beta_user",
    "dm_research_worthy",
    "suggested_comment_angle",
    "reason",
]

PAIN_CATEGORIES = [
    "Inbox chaos",
    "Refund outside policy",
    "Chargeback threat",
    "Damaged item complaint",
    "Late delivery complaint",
    "Difficult customer",
    "Support tools too expensive",
    "Repetitive questions",
    "Staff inconsistency",
    "No ticket tracking",
    "General customer service",
    "Negative review",
    "Missing/lost item",
    "Other relevant",
    "Not relevant",
]

WEIGHTED_KEYWORDS = [
    ("chargeback", 4),
    ("refund", 3),
    ("damaged item", 3),
    ("difficult customer", 3),
    ("support ticket", 2),
    ("repeated questions", 2),
    ("complaint", 2),
    ("late delivery", 2),
    ("customer service", 1),
    ("returns", 1),
    ("inbox", 1),
]

EXPENSE_KEYWORDS = ["expensive", "cost", "pricing", "price", "afford", "too much"]

KNOWN_TOOLS = [
    "Gorgias",
    "Zendesk",
    "Shopify Inbox",
    "Gmail",
    "HelpScout",
    "Freshdesk",
]

CATEGORY_RULES = [
    ("chargeback", "Chargeback threat"),
    ("refund", "Refund outside policy"),
    ("damaged item", "Damaged item complaint"),
    ("late delivery", "Late delivery complaint"),
    ("difficult customer", "Difficult customer"),
    ("support ticket", "No ticket tracking"),
    ("inbox", "Inbox chaos"),
    ("repeated questions", "Repetitive questions"),
    ("customer service", "General customer service"),
    ("returns", "Other relevant"),
    ("complaint", "General customer service"),
]

COMMENT_ANGLES = {
    "Chargeback threat": "Suggest documenting the timeline, policy, and evidence before responding.",
    "Refund outside policy": "Suggest using a consistent refund decision checklist and recording the exception.",
    "Damaged item complaint": "Suggest collecting photos and order details before deciding the remedy.",
    "Late delivery complaint": "Suggest separating carrier evidence from the customer response and next action.",
    "Difficult customer": "Suggest keeping replies factual, calm, and tied to a clearly documented policy.",
    "No ticket tracking": "Suggest treating each issue as a case with an owner, status, and next action.",
    "Support tools too expensive": "Suggest listing the essential support workflow before comparing tool costs.",
    "Inbox chaos": "Suggest assigning each conversation a status, owner, and next action.",
    "Repetitive questions": "Suggest turning repeated answers into reusable templates with room for context.",
    "General customer service": "Suggest documenting the issue, desired outcome, and next action before replying.",
    "Other relevant": "Suggest recording the issue and applying a consistent response process.",
    "Not relevant": "",
}

SYSTEM_PROMPT = """You classify Reddit posts for Complaint Desk research.

Complaint Desk is a tool for small ecommerce businesses to handle customer
complaints, refund requests, chargeback threats, damaged-item complaints,
delivery complaints, difficult customers, and support inbox chaos more
consistently and safely.

Scoring:
- 9-10: Direct pain. Clearly struggling with complaints, refunds, chargebacks,
  customer support organisation, ticketing, difficult customers, expensive
  support software, or repeated customer issues. Worth commenting on and
  possibly a polite research DM.
- 7-8: Relevant ecommerce/customer support pain, but not urgent or not directly
  complaint-focused. Worth monitoring/commenting.
- 5-6: Related but weak. Useful for research only.
- 1-4: Mostly irrelevant.

is_potential_beta_user is true only when the poster appears to be a store
owner/operator or small business person currently feeling relevant pain.
dm_research_worthy is true only when a polite research DM, not a sales DM,
would be reasonable.
current_tool_mentioned should extract named support tools such as Gorgias,
Zendesk, Shopify Inbox, Gmail, HelpScout, or Freshdesk, and otherwise be None.
suggested_comment_angle must be one short helpful public-comment angle with no
pitch, links, or direct selling. Keep reason brief."""

SCORING_SCHEMA = {
    "type": "object",
    "properties": {
        "relevance_score_1_10": {"type": "integer", "minimum": 1, "maximum": 10},
        "pain_category": {"type": "string", "enum": PAIN_CATEGORIES},
        "urgency": {"type": "string", "enum": ["high", "medium", "low"]},
        "current_tool_mentioned": {"type": "string"},
        "is_potential_beta_user": {"type": "boolean"},
        "dm_research_worthy": {"type": "boolean"},
        "suggested_comment_angle": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": SCORING_COLUMNS,
    "additionalProperties": False,
}


def fallback_score(reason: str) -> dict[str, Any]:
    return {
        "relevance_score_1_10": 1,
        "pain_category": "Not relevant",
        "urgency": "low",
        "current_tool_mentioned": "None",
        "is_potential_beta_user": False,
        "dm_research_worthy": False,
        "suggested_comment_angle": "",
        "reason": reason,
    }


def weighted_matches(text: str) -> list[tuple[str, int]]:
    """Return each configured pain signal once with its weight."""
    matches = [(keyword, weight) for keyword, weight in WEIGHTED_KEYWORDS if keyword in text]
    has_expense_signal = any(keyword in text for keyword in EXPENSE_KEYWORDS)
    if has_expense_signal:
        for tool in ["gorgias", "zendesk"]:
            if tool in text:
                matches.append((f"{tool} expensive", 4))
    return matches


def relevance_from_points(points: int) -> int:
    """Map accumulated rule points onto the shared 1-10 relevance scale."""
    if points >= 8:
        return 10
    if points >= 6:
        return 9
    if points >= 5:
        return 8
    if points >= 4:
        return 7
    if points >= 3:
        return 6
    if points >= 2:
        return 4
    if points >= 1:
        return 3
    return 1


def rule_based_score(row: dict[str, str]) -> dict[str, Any]:
    """Score one row deterministically without using OpenAI."""
    text = "\n".join(
        [
            row.get("title", ""),
            row.get("body", ""),
            row.get("matched_keywords", ""),
        ]
    ).casefold()
    matches = weighted_matches(text)
    points = sum(weight for _, weight in matches)
    score = relevance_from_points(points)
    urgency = "high" if score >= 8 else "medium" if score >= 5 else "low"

    expensive_tool_match = any(label.endswith(" expensive") for label, _ in matches)
    if expensive_tool_match:
        category = "Support tools too expensive"
    else:
        category = next(
            (category for keyword, category in CATEGORY_RULES if keyword in text),
            "Not relevant",
        )
    tools = [tool for tool in KNOWN_TOOLS if tool.casefold() in text]
    match_summary = (
        ", ".join(f"{label} (+{weight})" for label, weight in matches)
        if matches
        else "no configured weighted signals"
    )

    return {
        "relevance_score_1_10": score,
        "pain_category": category,
        "urgency": urgency,
        "current_tool_mentioned": ", ".join(tools) if tools else "None",
        "is_potential_beta_user": score >= 5,
        "dm_research_worthy": score >= 8,
        "suggested_comment_angle": COMMENT_ANGLES[category],
        "reason": f"Weighted rule score {points}: {match_summary}.",
    }


def validate_score(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("model response was not a JSON object")

    score = int(data["relevance_score_1_10"])
    category = str(data["pain_category"])
    urgency = str(data["urgency"])
    if not 1 <= score <= 10:
        raise ValueError("relevance score was outside 1-10")
    if category not in PAIN_CATEGORIES:
        raise ValueError("pain category was not allowed")
    if urgency not in {"high", "medium", "low"}:
        raise ValueError("urgency was not allowed")
    if not isinstance(data["is_potential_beta_user"], bool):
        raise ValueError("is_potential_beta_user was not boolean")
    if not isinstance(data["dm_research_worthy"], bool):
        raise ValueError("dm_research_worthy was not boolean")

    return {
        "relevance_score_1_10": score,
        "pain_category": category,
        "urgency": urgency,
        "current_tool_mentioned": str(data["current_tool_mentioned"] or "None"),
        "is_potential_beta_user": data["is_potential_beta_user"],
        "dm_research_worthy": data["dm_research_worthy"],
        "suggested_comment_angle": str(data["suggested_comment_angle"]),
        "reason": str(data["reason"]),
    }


def score_post(client, model: str, row: dict[str, str]) -> dict[str, Any]:
    post_text = {
        "subreddit": row.get("subreddit", ""),
        "title": row.get("title", ""),
        "body": row.get("body", ""),
        "matched_keywords": row.get("matched_keywords", ""),
        "age_hours": row.get("age_hours", ""),
        "num_comments": row.get("num_comments", ""),
    }
    response = client.responses.create(
        model=model,
        instructions=SYSTEM_PROMPT,
        input="Classify this Reddit post:\n" + json.dumps(post_text, ensure_ascii=False),
        text={
            "format": {
                "type": "json_schema",
                "name": "complaint_desk_post_score",
                "strict": True,
                "schema": SCORING_SCHEMA,
            }
        },
    )
    return validate_score(json.loads(response.output_text))


def read_csv(input_path: Path, max_rows: int | None) -> tuple[list[str], list[dict[str, str]]]:
    with input_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if not reader.fieldnames:
            raise ValueError("input CSV has no header row")
        rows = []
        for row in reader:
            rows.append(dict(row))
            if max_rows is not None and len(rows) >= max_rows:
                break
        return list(reader.fieldnames), rows


def write_scored_csv(
    output_path: Path, original_columns: Sequence[str], rows: Sequence[dict[str, Any]]
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(original_columns) + [
        column for column in SCORING_COLUMNS if column not in original_columns
    ]
    with output_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def sort_scored_rows(rows: list[dict[str, Any]]) -> None:
    rows.sort(
        key=lambda row: (
            -safe_float(row.get("relevance_score_1_10"), 0),
            safe_float(row.get("age_hours"), float("inf")),
        )
    )


def load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency python-dotenv. Run: pip install -r requirements.txt"
        ) from exc
    load_dotenv()


def build_openai_client():
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "Missing OPENAI_API_KEY. Add it to your environment or .env file."
        )
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency openai. Run: pip install -r requirements.txt"
        ) from exc
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Score raw Complaint Desk Reddit Radar CSV rows."
    )
    parser.add_argument(
        "--input", type=Path, default=Path("raw_posts.csv"), help="Raw CSV input path."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("scored_posts.csv"),
        help="Scored CSV output path.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenAI model name.")
    parser.add_argument(
        "--max-rows", type=int, help="Only score the first N input rows."
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Use deterministic keyword rules instead of OpenAI.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_rows is not None and args.max_rows <= 0:
        print("Error: --max-rows must be greater than 0.", file=sys.stderr)
        return 2
    if not args.input.exists():
        print(f"Error: input CSV does not exist: {args.input}", file=sys.stderr)
        return 1

    try:
        original_columns, raw_rows = read_csv(args.input, args.max_rows)
        print(f"Raw rows read: {len(raw_rows)}")
        if not raw_rows:
            write_scored_csv(args.output, original_columns, [])
            print("Rows scored: 0")
            print("Rows failed: 0")
            print(f"Output: {args.output.resolve()}")
            return 0

        client = None
        if not args.no_ai:
            load_dotenv_if_available()
            client = build_openai_client()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    scored_rows = []
    failed = 0
    for index, row in enumerate(raw_rows, start=1):
        try:
            if args.no_ai:
                scoring = rule_based_score(row)
                method = "Rule-scored"
            else:
                scoring = score_post(client, args.model, row)
                method = "AI-scored"
            print(f"{method} {index}/{len(raw_rows)}: {row.get('post_id', 'unknown')}")
        except Exception as exc:
            failed += 1
            scoring = fallback_score(f"Scoring failed: {type(exc).__name__}")
            print(
                f"Warning: failed to score row {index} "
                f"({row.get('post_id', 'unknown')}): {exc}",
                file=sys.stderr,
            )
        scored_rows.append({**row, **scoring})

    sort_scored_rows(scored_rows)
    try:
        write_scored_csv(args.output, original_columns, scored_rows)
    except OSError as exc:
        print(f"Error: could not write output CSV: {exc}", file=sys.stderr)
        return 1

    print(f"Rows scored: {len(scored_rows) - failed}")
    print(f"Rows failed: {failed}")
    print(f"Output: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
