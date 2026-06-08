import csv
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from reddit_radar import RAW_COLUMNS, collect_posts, find_matched_keywords, write_csv
import score_posts
from score_posts import (
    SCORING_COLUMNS,
    fallback_score,
    sort_scored_rows,
    validate_score,
    write_scored_csv,
)


class FakeSubmission:
    def __init__(self, post_id, title, body, created_utc, comments=0):
        self.id = post_id
        self.title = title
        self.selftext = body
        self.created_utc = created_utc
        self.num_comments = comments
        self.score = 5
        self.url = f"https://example.com/{post_id}"
        self.permalink = f"/r/shopify/comments/{post_id}/sample/"
        self.subreddit = "shopify"


class FakeSubreddit:
    def __init__(self, submissions):
        self.submissions = submissions

    def new(self, limit):
        return self.submissions[:limit]


class FakeReddit:
    def __init__(self, submissions):
        self.submissions = submissions

    def subreddit(self, name):
        return FakeSubreddit(self.submissions)


class FailingReddit:
    def subreddit(self, name):
        raise RuntimeError("offline")


class RedditRadarTests(unittest.TestCase):
    def test_keyword_matching_is_case_insensitive(self):
        matches = find_matched_keywords(
            "A CHARGEBACK problem", "Nothing else", ["refund", "chargeback"]
        )
        self.assertEqual(matches, ["chargeback"])

    def test_collect_posts_filters_deduplicates_and_sorts(self):
        now = datetime(2026, 6, 8, 12, tzinfo=timezone.utc)
        submissions = [
            FakeSubmission("older", "Refund help", "", now.timestamp() - 7200, 20),
            FakeSubmission("newer", "Refund help", "", now.timestamp() - 3600, 1),
            FakeSubmission("irrelevant", "A normal post", "", now.timestamp(), 50),
        ]
        rows = collect_posts(
            FakeReddit(submissions),
            ["shopify", "ecommerce"],
            ["refund"],
            days=7,
            limit_per_subreddit=100,
            now=now,
        )
        self.assertEqual([row["post_id"] for row in rows], ["newer", "older"])

    def test_collect_posts_fails_when_every_subreddit_fails(self):
        with self.assertRaisesRegex(RuntimeError, "Every subreddit fetch failed"):
            collect_posts(FailingReddit(), ["shopify"], ["refund"], 7, 100)

    def test_raw_csv_has_exact_columns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "raw.csv"
            write_csv([], output)
            with output.open(newline="", encoding="utf-8") as csv_file:
                self.assertEqual(next(csv.reader(csv_file)), RAW_COLUMNS)


class ScorePostsTests(unittest.TestCase):
    def test_validate_score_and_sort(self):
        valid = fallback_score("test")
        valid["relevance_score_1_10"] = 8
        valid["pain_category"] = "General customer service"
        self.assertEqual(validate_score(valid)["relevance_score_1_10"], 8)

        rows = [
            {"relevance_score_1_10": "7", "age_hours": "1"},
            {"relevance_score_1_10": "9", "age_hours": "5"},
            {"relevance_score_1_10": "9", "age_hours": "2"},
        ]
        sort_scored_rows(rows)
        self.assertEqual([row["age_hours"] for row in rows], ["2", "5", "1"])

    def test_scored_csv_appends_exact_scoring_columns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "scored.csv"
            write_scored_csv(output, RAW_COLUMNS, [])
            with output.open(newline="", encoding="utf-8") as csv_file:
                self.assertEqual(next(csv.reader(csv_file)), RAW_COLUMNS + SCORING_COLUMNS)

    def test_sample_csv_scores_without_reddit_credentials(self):
        scoring = fallback_score("Mocked sample score")
        scoring["relevance_score_1_10"] = 8
        scoring["pain_category"] = "Repetitive questions"

        class FakeResponse:
            output_text = json.dumps(scoring)

        class FakeResponses:
            def create(self, **kwargs):
                return FakeResponse()

        class FakeClient:
            responses = FakeResponses()

        sample_path = Path(__file__).resolve().parents[1] / "sample_raw_posts.csv"
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "scored.csv"
            clean_environment = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith("REDDIT_")
            }
            with patch.dict(os.environ, clean_environment, clear=True):
                with patch.object(score_posts, "load_dotenv_if_available"):
                    with patch.object(
                        score_posts, "build_openai_client", return_value=FakeClient()
                    ):
                        exit_code = score_posts.main(
                            ["--input", str(sample_path), "--output", str(output)]
                        )

            self.assertEqual(exit_code, 0)
            with output.open(newline="", encoding="utf-8") as csv_file:
                rows = list(csv.DictReader(csv_file))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["relevance_score_1_10"], "8")


if __name__ == "__main__":
    unittest.main()
