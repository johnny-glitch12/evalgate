"""Golden build cases — the offline eval corpus.

Each case is a plain dict:
    id          — stable, unique slug (baseline.json keys on it)
    prompt      — the user request the pipeline would receive
    has_ui      — expected UI decision (mirrors the Architect's default-true
                  rule: headless ONLY for cron / inbound-webhook / batch jobs)
    complexity  — simple | medium | complex (mirrors the Architect enum)
    expect      — the graded contract:
        min_files     — artifact must ship at least this many files
        must_paths    — every entry must be a substring of SOME file path
        must_mention  — every entry must appear (case-insensitive) in SOME
                        generated file's content
        forbid        — no entry may appear (case-insensitive) anywhere
    stub        — hints the deterministic stub generator uses to synthesize a
                  plausible artifact for this case (NOT part of the graded
                  contract): purpose text, declared inputs, integration +
                  env var + endpoint, ui_kind.

The 14 cases cover the real product surface seen in vibe builds: bots
(slack/telegram/discord-shaped), scrapers, payments, dashboards, digests,
reports, webhooks, retrieval Q&A, schedulers, forms, API sync, data cleaning,
and notifiers. v1 deliberately locks every case to the python_agent stack —
the only stack the platform can execution-verify — and says so; non-Python
stacks are a known gap, not silently skipped.
"""
from __future__ import annotations

# Forbidden in EVERY case: the classic placeholder/stub tells. Substring,
# case-insensitive — mirrors the pipeline's scan_for_stubs signals.
_FORBID = ["TODO", "FIXME", "lorem ipsum", "NotImplementedError", "your-api-key-here"]


def _case(id, prompt, has_ui, complexity, expect, stub):
    """Tiny constructor so every case carries the same keys in the same order."""
    expect.setdefault("forbid", list(_FORBID))
    return {"id": id, "prompt": prompt, "has_ui": has_ui,
            "complexity": complexity, "expect": expect, "stub": stub}


CASES = [
    _case(
        "slack_standup_bot",
        "Build a Slack bot that posts our team's daily standup summary to a channel I pick.",
        has_ui=True, complexity="medium",
        expect={
            "min_files": 5,
            "must_paths": ["main.py", "handlers.py", "requirements.txt", "README.md"],
            "must_mention": ["slack", "standup", "def run("],
        },
        stub={
            "name": "Slack Standup Bot",
            "purpose": "Post a formatted daily standup summary to a chosen Slack channel.",
            "integration": "slack", "env_var": "SLACK_BOT_TOKEN",
            "endpoint": "https://slack.com/api/chat.postMessage", "action": True,
            "ui_kind": "form",
            "inputs": [
                {"name": "channel", "type": "string", "description": "Slack channel to post to"},
                {"name": "summary_text", "type": "string", "description": "The standup summary text"},
            ],
        },
    ),
    _case(
        "web_scraper_prices",
        "I want a web scraper that pulls product prices from a page URL I give it.",
        has_ui=True, complexity="medium",
        expect={
            "min_files": 5,
            "must_paths": ["main.py", "requirements.txt", "README.md"],
            "must_mention": ["price", "httpx.get", "scrape"],
        },
        stub={
            "name": "Price Scraper",
            "purpose": "Scrape product prices from a given page URL and list what was found.",
            "integration": None, "env_var": None, "endpoint": None, "action": False,
            "ui_kind": "form",
            "inputs": [
                {"name": "url", "type": "string", "description": "The product page URL to scrape"},
            ],
        },
    ),
    _case(
        "stripe_checkout_link",
        "Build an app that creates a Stripe checkout session for a product name, amount and currency.",
        has_ui=True, complexity="complex",
        expect={
            "min_files": 5,
            "must_paths": ["main.py", "handlers.py", ".env.example", "README.md"],
            "must_mention": ["stripe", "checkout", "dry_run"],
        },
        stub={
            "name": "Stripe Checkout Creator",
            "purpose": "Create a Stripe checkout session for a product, amount and currency.",
            "integration": "stripe", "env_var": "STRIPE_API_KEY",
            "endpoint": "https://api.stripe.com/v1/checkout/sessions", "action": True,
            "ui_kind": "form",
            "inputs": [
                {"name": "product_name", "type": "string", "description": "What the customer is buying"},
                {"name": "amount", "type": "number", "description": "Price in cents"},
                {"name": "currency", "type": "string", "description": "ISO currency code, e.g. usd"},
            ],
        },
    ),
    _case(
        "metrics_dashboard",
        "Make me a dashboard that shows totals and averages for the metric readings I paste in.",
        has_ui=True, complexity="medium",
        expect={
            "min_files": 5,
            "must_paths": ["main.py", "README.md"],
            "must_mention": ["metric", "average"],
        },
        stub={
            "name": "Metrics Dashboard",
            "purpose": "Aggregate pasted metric readings into totals and averages for a dashboard view.",
            "integration": None, "env_var": None, "endpoint": None, "action": False,
            "ui_kind": "dashboard",
            "inputs": [
                {"name": "stats_json", "type": "object", "description": "JSON array of {name, value} readings"},
            ],
        },
    ),
    _case(
        "email_digest_cron",
        "Every morning, email me a digest of the new items collected overnight. Runs on a schedule, no UI needed.",
        has_ui=False, complexity="simple",
        expect={
            "min_files": 5,
            "must_paths": ["main.py", ".env.example", "README.md"],
            "must_mention": ["digest", "subject", "sendgrid"],
        },
        stub={
            "name": "Daily Email Digest",
            "purpose": "Compile overnight items into one digest email and send it each morning.",
            "integration": "sendgrid", "env_var": "SENDGRID_API_KEY",
            "endpoint": "https://api.sendgrid.com/v3/mail/send", "action": True,
            "ui_kind": "none", "headless_reason": "scheduled cron",
            "inputs": [
                {"name": "items", "type": "object", "description": "List of item titles collected since the last run"},
            ],
        },
    ),
    _case(
        "telegram_alert_bot",
        "A Telegram bot that sends an alert message to a chat when I trigger it.",
        has_ui=True, complexity="simple",
        expect={
            "min_files": 5,
            "must_paths": ["main.py", "requirements.txt", "README.md"],
            "must_mention": ["telegram", "sendmessage"],
        },
        stub={
            "name": "Telegram Alert Bot",
            "purpose": "Send an alert message to a Telegram chat on demand.",
            "integration": "telegram", "env_var": "TELEGRAM_BOT_TOKEN",
            # Telegram puts the token in the URL path, not a header.
            "endpoint_expr": '"https://api.telegram.org/bot" + secret + "/sendMessage"',
            "action": True, "ui_kind": "trigger_button",
            "inputs": [
                {"name": "chat_id", "type": "string", "description": "Target Telegram chat id"},
                {"name": "alert_text", "type": "string", "description": "The alert message to send"},
            ],
        },
    ),
    _case(
        "csv_sales_report",
        "Take a CSV of sales rows and give me a report with the row count and total amount.",
        has_ui=True, complexity="simple",
        expect={
            "min_files": 4,
            "must_paths": ["main.py", "README.md"],
            "must_mention": ["csv", "total"],
        },
        stub={
            "name": "CSV Sales Report",
            "purpose": "Parse a pasted CSV of sales rows and report the row count and total amount.",
            "integration": None, "env_var": None, "endpoint": None, "action": False,
            "ui_kind": "form",
            "inputs": [
                {"name": "csv_text", "type": "string", "description": "Raw CSV with an 'amount' column"},
            ],
        },
    ),
    _case(
        "webhook_relay",
        "Receive webhooks and forward the payload to another endpoint. Pure background service, no UI.",
        has_ui=False, complexity="medium",
        expect={
            "min_files": 5,
            "must_paths": ["main.py", ".env.example", "README.md"],
            "must_mention": ["webhook", "forward"],
        },
        stub={
            "name": "Webhook Relay",
            "purpose": "Relay an inbound webhook payload — validate it, then forward it to the configured target endpoint.",
            "integration": "webhook", "env_var": "TARGET_WEBHOOK_URL",
            # The env var IS the destination URL.
            "endpoint_expr": "secret",
            "action": True, "ui_kind": "none", "headless_reason": "inbound webhook handler",
            "inputs": [
                {"name": "payload_json", "type": "object", "description": "The inbound webhook body as JSON"},
            ],
        },
    ),
    _case(
        "docs_qa_agent",
        "Q&A over my docs: I give it a question plus a set of documents and it answers from the most relevant passages.",
        has_ui=True, complexity="complex",
        expect={
            "min_files": 5,
            "must_paths": ["main.py", "handlers.py", "README.md"],
            "must_mention": ["question", "answer", "sources"],
        },
        stub={
            "name": "Docs Q&A Agent",
            "purpose": "Answer a question from the most relevant passages of the supplied documents (extractive, keyword-ranked retrieval).",
            "integration": None, "env_var": None, "endpoint": None, "action": False,
            "ui_kind": "chat",
            "inputs": [
                {"name": "question", "type": "string", "description": "The question to answer"},
                {"name": "documents", "type": "object", "description": "List of document texts to search"},
            ],
        },
    ),
    _case(
        "cron_task_scheduler",
        "A scheduled job that checks my task list and reports which tasks are due versus upcoming. Background cron, no UI.",
        has_ui=False, complexity="simple",
        expect={
            "min_files": 5,
            "must_paths": ["main.py", "README.md"],
            "must_mention": ["due", "schedule"],
        },
        stub={
            "name": "Task Due Checker",
            "purpose": "On each scheduled run, split the provided task list into due and upcoming.",
            "integration": None, "env_var": None, "endpoint": None, "action": False,
            "ui_kind": "none", "headless_reason": "scheduled cron",
            "inputs": [
                {"name": "tasks", "type": "object", "description": "List of {name, due_at} tasks"},
                {"name": "now_iso", "type": "string", "description": "Override for the current time (ISO); defaults to now"},
            ],
        },
    ),
    _case(
        "feedback_form_app",
        "A simple form app where people submit feedback and it gets categorized automatically.",
        has_ui=True, complexity="simple",
        expect={
            "min_files": 4,
            "must_paths": ["main.py", "README.md"],
            "must_mention": ["feedback", "category"],
        },
        stub={
            "name": "Feedback Categorizer",
            "purpose": "Collect a feedback message and categorize it (bug report / usability / praise / general).",
            "integration": None, "env_var": None, "endpoint": None, "action": False,
            "ui_kind": "form",
            "inputs": [
                {"name": "feedback_text", "type": "string", "description": "The feedback message"},
            ],
        },
    ),
    _case(
        "crm_api_integrator",
        "Sync a contact (name, email, company) into our HubSpot CRM via its API.",
        has_ui=True, complexity="medium",
        expect={
            "min_files": 5,
            "must_paths": ["main.py", ".env.example", "README.md"],
            "must_mention": ["contact", "hubspot"],
        },
        stub={
            "name": "CRM Contact Sync",
            "purpose": "Create or update a contact record in HubSpot from name, email and company.",
            "integration": "hubspot", "env_var": "HUBSPOT_API_KEY",
            "endpoint": "https://api.hubapi.com/crm/v3/objects/contacts", "action": True,
            "ui_kind": "form",
            "inputs": [
                {"name": "full_name", "type": "string", "description": "Contact full name"},
                {"name": "email", "type": "string", "description": "Contact email address"},
                {"name": "company", "type": "string", "description": "Company the contact belongs to"},
            ],
        },
    ),
    _case(
        "data_cleaner",
        "Clean a messy list of records: trim whitespace and drop rows with duplicate emails within the batch.",
        has_ui=True, complexity="simple",
        expect={
            "min_files": 4,
            "must_paths": ["main.py", "README.md"],
            "must_mention": ["clean", "duplicate"],
        },
        stub={
            "name": "Record Cleaner",
            "purpose": "Clean and normalize submitted records — trim string fields and drop duplicate emails within the batch.",
            "integration": None, "env_var": None, "endpoint": None, "action": False,
            "ui_kind": "data_table",
            "inputs": [
                {"name": "records_json", "type": "object", "description": "JSON array of record objects to clean"},
            ],
        },
    ),
    _case(
        "deploy_notifier",
        "One-tap notifier: when a deploy finishes, ping our ops webhook with the service name and status.",
        has_ui=True, complexity="simple",
        expect={
            "min_files": 5,
            "must_paths": ["main.py", ".env.example", "README.md"],
            "must_mention": ["deploy", "webhook"],
        },
        stub={
            "name": "Deploy Notifier",
            "purpose": "Notify the ops channel webhook that a deploy finished, with service name and status.",
            "integration": "webhook", "env_var": "OPS_WEBHOOK_URL",
            "endpoint_expr": "secret",
            "action": True, "ui_kind": "trigger_button",
            "inputs": [
                {"name": "service", "type": "string", "description": "The service that was deployed"},
                {"name": "status", "type": "string", "description": "Deploy status, e.g. succeeded or failed"},
            ],
        },
    ),
]


def case_by_id(case_id: str):
    """Return the case with this id, or None."""
    for c in CASES:
        if c["id"] == case_id:
            return c
    return None


__all__ = ["CASES", "case_by_id"]
