"""Pure scoring, aggregation and regression detection for build outcomes.

Extracted from a production AI code-generation platform. Every function here is
pure: same input, same output, no I/O, no database, standard library only. That
is deliberate — the offline gate and the online scoreboard must score a build
the same way, or the offline number means nothing.

The persistence layer that wrote these labels to MongoDB has been removed for
publication; it added nothing to the scoring logic.
"""

from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("outcome_corpus")

# v2 — adds the security-review signals (security_scanned/findings/high/score)
# from STAGE 8.5. A schema-pinned reader must handle both, so the bump is
# mechanical-but-required (old rows read as v1 with the fields absent).
SCHEMA_VERSION = 2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tri(v) -> Optional[bool]:
    """Three-valued: True / False / None (gate did not run)."""
    return None if v is None else bool(v)


# ── BUILD outcomes ───────────────────────────────────────────────────────────
def _classify_build_outcome(s: dict) -> str:
    """Ground-truth-ish build label, mirroring the finalize verify-note logic."""
    if not s.get("smoke_passed"):
        return "failed"
    if s.get("non_python_stack"):
        return "built_unverified"      # ran in its own runtime, not verifiable in-platform
    if s.get("smoke_skipped"):
        # Nothing was executable (pure-UI build, no main.py) — same honesty
        # class as non-python: built, but never run. Without this, the
        # smoke_ok gate below demoted every pure-UI build to review_needed
        # (self-audit 2026-07-11: skipped ≠ suspect, and ≠ verified either).
        return "built_unverified"
    if s.get("runtime_bug"):
        return "runtime_bug"
    if s.get("needs_config") and not s.get("smoke_ok"):
        return "needs_config"          # built fine, just unconfigured (expected, not a defect)
    if s.get("review_needed"):
        return "review_needed"
    # A build shipping an unrepaired critical/high security finding can NEVER be
    # corpus-labeled `verified` — same anti-fake-green invariant as spec_gaps_high
    # (review_needed already carries this in the pipeline, but classify off the raw
    # signal too so the corpus label holds even if that flag wasn't threaded).
    if int(s.get("security_high") or 0) > 0:
        return "review_needed"
    if not s.get("smoke_ok"):
        # Ran but the output was never confirmed OK — e.g. an empty/odd result
        # the deterministic needs_config narrow (G3) declined to excuse as "just
        # config". This must NEVER fall through to "verified": it would score
        # quality 1.0 and the few-shot feedback loop would then PREFER the
        # unconfirmed build as inspiration — a fabricated verification label.
        return "review_needed"
    return "verified"


def _build_quality_score(outcome: str, repair: int, a11y: list, slop: list, s: dict) -> float:
    """Transparent HEURISTIC in [0,1] (not an ML label) — a starting signal for
    filtering/ranking the corpus. needs_config is barely penalised (it's expected,
    not a quality defect); failures and runtime bugs are penalised hard."""
    if outcome == "failed":
        return 0.0
    score = 1.0
    if outcome == "runtime_bug":
        score -= 0.5
    elif outcome == "review_needed":
        score -= 0.3
    elif outcome == "built_unverified":
        score -= 0.15   # built but never executed — an execute-verified build
                        # of similar relevance must outrank it in the few-shot loop
    elif outcome == "needs_config":
        score -= 0.1
    score -= 0.05 * min(repair, 4)
    score -= 0.05 * len(a11y or [])
    score -= 0.05 * len(slop or [])
    score -= 0.05 * min(int(s.get("spec_gaps_high") or 0), 3)
    # Residual critical/high security findings are a real quality defect — weight
    # them like spec_gaps_high so a build that ships a known HIGH vuln can't score
    # as clean, even if some other axis looked fine.
    score -= 0.1 * min(int(s.get("security_high") or 0), 3)
    return round(max(0.0, min(1.0, score)), 3)


def derive_build_label(s: dict) -> dict:
    """PURE: distil build-finalize signals into a stable labeled record."""
    outcome = _classify_build_outcome(s)
    repair = int(s.get("repair_rounds") or 0)
    a11y = list(s.get("a11y_markers") or [])
    slop = list(s.get("slop_markers") or [])
    clean_first_pass = (outcome == "verified" and repair == 0 and not a11y
                        and not slop and not int(s.get("spec_gaps_high") or 0))
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "build",
        # ── features
        "model": s.get("model"),
        "complexity": s.get("complexity"),
        "has_ui": bool(s.get("has_ui")),
        "ui_kind": s.get("ui_kind"),
        "integration_count": len(s.get("integrations") or []),
        "integrations": [str(x) for x in (s.get("integrations") or [])][:12],
        "file_count": int(s.get("file_count") or 0),
        "node_count": int(s.get("node_count") or 0),
        "credits": int(s.get("total_credits") or 0),
        "repair_rounds": repair,
        # ── verify-gate signals
        "spec_verified": _tri(s.get("spec_verified")),
        "plan_verified": _tri(s.get("plan_verified")),
        "design_aligned": _tri(s.get("design_aligned")),
        "a11y_flags": a11y[:8],
        "slop_flags": slop[:8],
        "spec_gaps_high": int(s.get("spec_gaps_high") or 0),
        "needs_config": bool(s.get("needs_config")),
        # ── security-review signals (STAGE 8.5, POST-repair)
        "security_scanned": _tri(s.get("security_scanned")),
        "security_findings": int(s.get("security_findings") or 0),
        "security_high": int(s.get("security_high") or 0),   # residual critical+high
        "security_score": (float(s["security_score"])
                           if isinstance(s.get("security_score"), (int, float)) else None),
        # ── derived labels
        "outcome": outcome,
        "clean_first_pass": clean_first_pass,
        "quality_score": _build_quality_score(outcome, repair, a11y, slop, s),
    }


def _classify_run_error(success: bool, err: str, needs_config: bool) -> str:
    """Bucket a run failure into an analysable class."""
    if success:
        return "ok"
    if needs_config:
        return "needs_config"
    e = (err or "").upper()
    if any(k in e for k in ("INSUFFICIENT_CREDITS", "OUT_OF_CREDITS", "LIMIT_REACHED")):
        return "billing"
    if _DEP_RE.search(e):
        return "dependency"
    if "FORBIDDEN_IMPORT" in e or "AST_REJECT" in e or "FORBIDDEN" in e:
        return "policy"
    if "TIMEOUT" in e or "TIMED OUT" in e:
        return "timeout"
    if "SANDBOX" in e or "MISCONFIGURED" in e or "PLATFORM" in e:
        return "platform"
    return "runtime_error"


def derive_run_label(s: dict) -> dict:
    """PURE: distil a run's completion signals into a stable labeled record."""
    success = bool(s.get("success"))
    needs_config = bool(s.get("needs_config"))
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "run",
        "success": success,
        "error_class": _classify_run_error(success, str(s.get("error") or ""), needs_config),
        "latency_ms": int(s.get("latency_ms") or 0),
        "needs_config": needs_config,
        "trigger": s.get("trigger") or "manual",
    }


_GOOD_OUTCOMES = frozenset({"verified", "needs_config"})


def aggregate_build_outcomes(rows: list) -> dict:
    """PURE: a list of build_outcome rows → a quality scoreboard. Everything is
    derived from real labeled builds — no fabricated numbers."""
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    n = len(rows)
    if not n:
        return {"total": 0, "verified_rate": None, "good_rate": None,
                "avg_quality": None, "clean_first_pass_rate": None,
                "outcome_breakdown": {}, "by_model": {}, "by_prompt_version": {}}
    from collections import Counter
    outcomes = Counter(str(r.get("outcome") or "unknown") for r in rows)
    verified = sum(1 for r in rows if r.get("outcome") == "verified")
    good = sum(1 for r in rows if r.get("outcome") in _GOOD_OUTCOMES)
    clean = sum(1 for r in rows if r.get("clean_first_pass"))
    quals = [float(r["quality_score"]) for r in rows
             if isinstance(r.get("quality_score"), (int, float))]
    by_model: dict = {}
    # P3: segment by the prompt bundle that built each row, mirroring by_model,
    # so a prompt change shows up as a measurable quality delta. Rows written
    # before stamping existed (or when the stamp failed open) group honestly
    # under "unknown" rather than being folded into any real version.
    by_prompt_version: dict = {}
    for r in rows:
        m = str(r.get("model") or "unknown")
        b = by_model.setdefault(m, {"builds": 0, "verified": 0})
        b["builds"] += 1
        b["verified"] += int(r.get("outcome") == "verified")
        pv = str(r.get("prompt_version") or "unknown")
        p = by_prompt_version.setdefault(pv, {"builds": 0, "verified": 0})
        p["builds"] += 1
        p["verified"] += int(r.get("outcome") == "verified")
    return {
        "total": n,
        "verified_rate": round(verified / n, 3),
        "good_rate": round(good / n, 3),               # verified OR expected needs-config
        "avg_quality": round(sum(quals) / len(quals), 3) if quals else None,
        "clean_first_pass_rate": round(clean / n, 3),
        "outcome_breakdown": dict(outcomes),
        "by_model": by_model,
        "by_prompt_version": by_prompt_version,
    }


def detect_quality_regression(recent: dict, baseline: dict, *,
                              drop: float = 0.1, min_n: int = 20) -> dict:
    """PURE regression gate: has verified-rate or avg-quality dropped materially
    versus a baseline? A release/eval gate can fail on this. Needs enough volume
    on both sides or it abstains (never a false alarm on thin data)."""
    r_n, b_n = int((recent or {}).get("total") or 0), int((baseline or {}).get("total") or 0)
    if r_n < min_n or b_n < min_n:
        return {"regressed": False, "reason": "insufficient volume to judge", "confident": False}
    for key, label in (("verified_rate", "verified rate"), ("avg_quality", "avg quality")):
        rv, bv = recent.get(key), baseline.get(key)
        if isinstance(rv, (int, float)) and isinstance(bv, (int, float)) and (bv - rv) >= drop:
            return {"regressed": True, "confident": True,
                    "reason": f"{label} dropped {round(bv - rv, 3)} ({bv}→{rv})", "metric": key}
    return {"regressed": False, "reason": "no material drop vs baseline", "confident": True}


__all__ = ["derive_build_label", "record_build_outcome",
           "derive_run_label", "record_run_outcome", "SCHEMA_VERSION",
           "aggregate_build_outcomes", "build_quality_scoreboard",
           "detect_quality_regression"]
