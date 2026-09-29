# evalgate

A deterministic evaluation gate for LLM code generation.

It answers one question in CI: **did the model get worse?** — and it is built so that
the answer cannot be faked by a test suite that silently did nothing.

```
$ python3 -m evalgate.run

  [PASS] slack_standup_bot      score=1.000 (15/15 checks, static-scan=unavailable)
  [PASS] web_scraper_prices     score=1.000 (14/14 checks, static-scan=unavailable)
  ...
  [PASS] deploy_notifier        score=1.000 (13/13 checks, static-scan=unavailable)

aggregate: total=14 verified_rate=1.0 avg_quality=1.0 clean_first_pass=1.0

NOTE: graded via LOCAL FALLBACK — the production code-gen pipeline is not part of this
repository, so its real parsers/validators were NOT exercised. Scores here gate the
grading contract, not the pipeline.
no regression vs baseline (no material drop vs baseline)
```

Exit code 0 on no regression, 1 on regression, 2 on refusal. Drop it in front of a merge.

## Why it exists

I was running an AI platform that turns a plain-English task into generated, sandboxed,
executable code. CI was green. The green proved nothing: no services were provisioned, so
every fixture skipped, and a skipped test reports success. The suite had been passing for
weeks without asserting anything about the thing that mattered.

So I rebuilt it in two halves:

1. **A service-free unit gate** — runs with no database, no Redis, no network, so it cannot
   skip its way to green.
2. **An eval-regression gate** — 14 deterministic cases scored against a committed baseline,
   with the scoring shared byte-for-byte with the production scoreboard.

After the rebuild, one prompt revision moved strict pass from **0/10 to 9/10**. The number
was worth something only because the gate was capable of failing.

## The three design rules

**1. Grading is pure.** `grade(case, artifact)` computes a score from the case's expectations
and the artifact's shape — no clock, no network, no environment. A baseline built on a laptop
compares cleanly against one built in CI.

**2. Never claim what didn't run.** The production pipeline is not in this repository, so the
harness degrades to a local parser and *says so in its output* — see the NOTE in the run above.
`--strict` turns that notice into a hard failure, so a CI job can refuse to pass on a
degraded run. Static-validator findings are reported as informational and never silently
folded into the score. A harness that hides its own degradation is worse than no harness.

**3. Abstain instead of false-alarming.** The gate needs volume on both sides before it will
judge. Below the threshold it returns `insufficient volume to judge` with `confident: False`
rather than failing someone's merge on four data points.

```python
>>> from evalgate.outcome_corpus import detect_quality_regression as d
>>> base = {"total": 14, "verified_rate": 1.0, "avg_quality": 1.0}

>>> d({"total": 14, "verified_rate": 0.99, "avg_quality": 1.0}, base, drop=0.05, min_n=10)
{'regressed': False, 'reason': 'no material drop vs baseline', 'confident': True}

>>> d({"total": 14, "verified_rate": 0.78, "avg_quality": 1.0}, base, drop=0.05, min_n=10)
{'regressed': True, 'confident': True,
 'reason': 'verified rate dropped 0.22 (1.0→0.78)', 'metric': 'verified_rate'}

>>> d({"total": 4, "verified_rate": 0.10, "avg_quality": 0.1}, base, drop=0.05, min_n=10)
{'regressed': False, 'reason': 'insufficient volume to judge', 'confident': False}
```

## What's in here

| File | What it does |
|---|---|
| `evalgate/cases.py` | 14 deterministic eval cases — Slack bot, scraper, Stripe checkout, cron, webhook relay, CRM integrator, dashboard… each with explicit expectations |
| `evalgate/stub_llm.py` | A deterministic stand-in model. Same input, same artifact, every time — so a score change means the *grader* changed, not the weather |
| `evalgate/harness.py` | Grading, aggregation, baseline comparison, the regression gate |
| `evalgate/outcome_corpus.py` | Pure scoring/labelling/aggregation. Standard library only |
| `evalgate/run.py` | CLI and exit codes |
| `evalgate/baseline.json` | The committed baseline the gate compares against |

## Usage

```bash
python3 -m evalgate.run                      # run the gate
python3 -m evalgate.run --case webhook_relay # one case
python3 -m evalgate.run --update-baseline    # re-commit the baseline
python3 -m evalgate.run --strict             # stricter scoring
```

No dependencies. Python 3.9+. `pytest` only if you want to run `tests/`.

## Honest scope

This gates the **grading contract, the stage formats and the validators**. It does not run a
live model — that lane exists in the original system and is not published here, because it
spends real money and carries provider keys. So: this repo proves the gate is real and that
regressions are caught. It does not prove any particular model is good.

That distinction is the whole point. A harness that blurs it is how you end up with a green
CI that means nothing.

## Provenance

Extracted from a production AI code-generation platform I built and ran. The MongoDB
persistence layer was removed for publication; it contributed nothing to scoring. No
credentials, no customer data, no proprietary prompts. The `env_var` names in `cases.py`
(`STRIPE_SECRET_KEY`, `TELEGRAM_BOT_TOKEN`, …) are *specifications* the generated code must
read from the environment — they are not values.

MIT licensed.
