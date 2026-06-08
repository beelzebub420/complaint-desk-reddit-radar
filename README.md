# Complaint Desk Reddit Radar

Complaint Desk Reddit Radar is a lightweight local command-line research tool.
It finds recent public Reddit posts from ecommerce operators and small business
owners who may be struggling with customer complaints, refunds, chargebacks,
returns, difficult customers, repetitive questions, support tools, or inbox
chaos.

The tool produces CSV files for manual research and prospecting. It is not a
dashboard, SaaS product, outreach bot, or comment automation system.

## What It Does

1. Fetches recent posts from a focused list of ecommerce and seller subreddits.
2. Keeps posts whose title or body matches a relevant pain keyword.
3. Exports a deduplicated, newest-first raw CSV.
4. Scores and classifies each post using OpenAI or deterministic local keyword
   rules.

Default subreddits:

- `shopify`
- `ecommerce`
- `smallbusiness`
- `FulfillmentByAmazon`
- `EtsySellers`
- `EbaySellerAdvice`

## Setup

Requires Python 3.10 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
```

On Windows, activate the environment with:

```powershell
.venv\Scripts\activate
```

### Reddit API Credentials

Create a Reddit script app at
[reddit.com/prefs/apps](https://www.reddit.com/prefs/apps):

1. Sign in and choose **create another app**.
2. Select the **script** application type.
3. Use any valid redirect URI, such as `http://localhost:8080`.
4. Copy the app ID shown under the app name into `REDDIT_CLIENT_ID`.
5. Copy the secret into `REDDIT_CLIENT_SECRET`.
6. Set a descriptive `REDDIT_USER_AGENT` containing your Reddit username.

Add the values to `.env`:

```dotenv
REDDIT_CLIENT_ID=your_app_id
REDDIT_CLIENT_SECRET=your_app_secret
REDDIT_USER_AGENT=complaint-desk-reddit-radar/0.1 by your_reddit_username
```

### OpenAI API Key

Create an API key in the
[OpenAI platform](https://platform.openai.com/api-keys), then add it to `.env`:

```dotenv
OPENAI_API_KEY=your_openai_api_key
```

The raw Reddit fetch does not need an OpenAI key. AI scoring does not need
Reddit credentials. Rule-based scoring with `--no-ai` needs neither.

## Commands

Fetch posts from the last seven days:

```bash
python3 reddit_radar.py --days 7 --output raw_posts.csv
```

Inspect fewer recent posts per subreddit or override the search targets:

```bash
python3 reddit_radar.py \
  --days 3 \
  --output raw_posts.csv \
  --limit-per-subreddit 50 \
  --subreddits shopify ecommerce \
  --keywords refund chargeback "difficult customer"
```

AI-score a raw CSV:

```bash
python3 score_posts.py --input raw_posts.csv --output scored_posts.csv
```

Score locally with deterministic keyword rules and no OpenAI API key:

```bash
python3 score_posts.py \
  --input raw_posts.csv \
  --output scored_posts.csv \
  --no-ai
```

The rule-based fallback assigns high relevance to direct complaint pain such as
refunds, chargebacks, difficult customers, support tickets, damaged items,
late delivery, Gorgias, or Zendesk. It assigns medium relevance to customer
service, returns, inbox, or repeated-question matches, and low relevance
otherwise.

Score only the first 50 input rows or override the default model:

```bash
python3 score_posts.py \
  --input raw_posts.csv \
  --output scored_posts.csv \
  --max-rows 50 \
  --model gpt-4.1-mini
```

Run fetching and scoring together:

```bash
python3 run_radar.py \
  --days 7 \
  --raw raw_posts.csv \
  --scored scored_posts.csv \
  --max-rows 100
```

## CSV Outputs

The raw CSV contains:

```text
post_id, subreddit, title, body, url, permalink, created_utc, created_iso,
age_hours, score, num_comments, matched_keywords
```

It is sorted by newest post first, then by comment count descending.

The scored CSV includes every raw column plus:

```text
relevance_score_1_10, pain_category, urgency, current_tool_mentioned,
is_potential_beta_user, dm_research_worthy, suggested_comment_angle, reason
```

It is sorted by relevance score descending, then by newest post first.

`sample_raw_posts.csv` contains two fake rows for trying the scorer format:

```bash
python3 score_posts.py \
  --input sample_raw_posts.csv \
  --output sample_scored_posts.csv \
  --no-ai
```

## Testing

The unit tests are offline and do not call Reddit or OpenAI:

```bash
python3 -m unittest discover -v
python3 reddit_radar.py --help
python3 score_posts.py --help
python3 run_radar.py --help
```

The scripts report which environment variables are missing when credentials
have not been configured.

## Responsible Reddit Usage

This tool is for research and finding public conversations where you may be
able to contribute helpful answers. Do not spam, mass-DM, automate comments,
scrape aggressively, or violate Reddit rules.

AI and rule-based scores are research aids, not facts. Review every post
yourself before commenting or sending a polite research message.
