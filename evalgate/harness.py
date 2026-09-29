"""Grading + baseline comparison for the offline eval harness.

Design constraints (v1, honest about what it proves):
- ``grade(case, artifact)`` is PURE and environment-independent: the score is
  computed only from the case's expectations + the artifact's shape, so a
  baseline built on one machine compares cleanly on another.
- The pipeline's REAL parser/sanitizer/validators are used where importable
  (the production ``lib.code_gen_pipeline``, which is not part of this repo); when
  they aren't, we degrade to a local fallback parser and REPORT that — static
  validator findings are informational, never part of the score.
- Aggregation + the regression gate reuse ``outcome_corpus`` — the same pure
  functions the production scoreboard uses — so offline and online quality are
  scored identically. An offline number that the online system would disagree
  with is worthless.
"""
from __future__ import annotations

import json
import re

from evalgate.outcome_corpus import aggregate_build_outcomes, detect_quality_regression

from evalgate.cases import CASES
from evalgate import stub_llm

# Gate thresholds. 14 deterministic cases: one case flipping to failed moves
# verified_rate by ~0.071, so drop must sit below that; min_n must sit below 14
# (outcome_corpus's default of 20 would make the gate abstain forever here).
EVAL_REGRESSION_DROP = 0.05
EVAL_REGRESSION_MIN_N = 10

BASELINE_SCHEMA_VERSION = 1


# ── pipeline access (degrade honestly when its deps are missing) ─────────────
def pipeline_module():
    """The real pipeline module, or None when its deps (httpx/tenacity) are
    absent in this environment. Callers must not fake what didn't run."""
    try:
        import lib.code_gen_pipeline as cgp
        return cgp
    except Exception:  # noqa: BLE001 — any import failure → honest fallback
        return None


_FENCE_RE = re.compile(r"^```(?:json|JSON)?\s*|\s*```\s*$")


def parse_stage_text(text: str) -> dict:
    """Parse a stage response. Uses the pipeline's real _extract_json when
    importable (fence-stripping + balanced-brace walker + repair tiers);
    falls back to a minimal fence-strip + strict json.loads otherwise."""
    cgp = pipeline_module()
    if cgp is not None:
        return cgp._extract_json(text)
    stripped = _FENCE_RE.sub("", (text or "").strip())
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("stage output is not a JSON object")
    return parsed


def _sanitize_files(maybe_files):
    """Pipeline's file normaliser when available; a faithful local mirror
    (dict + non-empty string path required) otherwise."""
    cgp = pipeline_module()
    if cgp is not None:
        return cgp._sanitize_files(maybe_files)
    out = []
    for f in (maybe_files or []):
        if isinstance(f, dict) and isinstance(f.get("path"), str) and f["path"].strip():
            out.append({"path": f["path"].strip(), "content": f.get("content") or "",
                        "language": f.get("language") or "text"})
    return out


# ── stub artifact assembly ───────────────────────────────────────────────────
def build_stub_artifact(case: dict) -> dict:
    """Assemble a build artifact from the deterministic stub stage outputs,
    routed through the REAL stage-response parser. Shape mirrors what
    run_build_pipeline returns: {name, files, nodes, edges, has_ui, frontend}.

    This is NOT a live pipeline run — no LLM, no smoke execution — and the
    artifact carries graded_via so downstream output can say which parser ran.
    """
    architect = parse_stage_text(stub_llm.stub_text(case, "architect"))
    planner = parse_stage_text(stub_llm.stub_text(case, "planner"))
    builder = parse_stage_text(stub_llm.stub_text(case, "builder"))
    polisher = parse_stage_text(stub_llm.stub_text(case, "polisher"))

    files = _sanitize_files(builder.get("files"))
    # Merge the polisher's README exactly like the pipeline does (by path).
    by_path = {f["path"]: f for f in files}
    for rf in _sanitize_files(polisher.get("files")):
        by_path[rf["path"]] = rf
    files = list(by_path.values())

    frontend = None
    if architect.get("has_ui"):
        ui = parse_stage_text(stub_llm.stub_text(case, "ui_builder"))
        frontend = {"app_jsx": ui.get("app_jsx") or "", "manifest": ui.get("manifest") or {}}

    return {
        "name": architect.get("name"),
        "stack": architect.get("stack"),
        "files": files,
        "nodes": planner.get("nodes") or [],
        "edges": planner.get("edges") or [],
        "has_ui": bool(architect.get("has_ui")),
        "frontend": frontend,
        "graded_via": "pipeline_parsers" if pipeline_module() is not None else "local_fallback",
    }


# ── grading (pure) ───────────────────────────────────────────────────────────
def grade(case: dict, artifact: dict) -> dict:
    """Grade one artifact against one case's expectations. PURE: no I/O, no
    imports beyond stdlib, deterministic. Returns pass/fail per expectation
    plus a score in [0,1] (fraction of checks passed)."""
    expect = case.get("expect") or {}
    files = [f for f in (artifact.get("files") or []) if isinstance(f, dict)]
    paths = [str(f.get("path") or "") for f in files]
    blob = "\n".join(str(f.get("content") or "") for f in files).lower()
    checks = []

    def _check(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    # Structural: mirrors the pipeline's own hard-fail on empty files/nodes.
    _check("structural:files_and_nodes_nonempty",
           bool(files) and bool(artifact.get("nodes")),
           f"{len(files)} files, {len(artifact.get('nodes') or [])} nodes")

    # Structural: the UI contract — a has_ui case must ship a wired frontend
    # (tfApi.run + the __TF_APP mount marker); a headless case must ship none.
    fe = artifact.get("frontend") or {}
    app_jsx = str(fe.get("app_jsx") or "")
    if case.get("has_ui"):
        ui_ok = bool(app_jsx) and "window.__TF_APP" in app_jsx and "tfApi.run" in app_jsx
        _check("structural:ui_contract", ui_ok,
               "frontend present, mounts window.__TF_APP and calls tfApi.run" if ui_ok
               else "missing or unwired frontend for a has_ui case")
    else:
        _check("structural:ui_contract", not app_jsx,
               "headless case ships no frontend" if not app_jsx
               else "headless case unexpectedly shipped a frontend")

    mf = int(expect.get("min_files") or 0)
    _check("min_files", len(files) >= mf, f"{len(files)} >= {mf}")

    for p in (expect.get("must_paths") or []):
        hit = any(p in path for path in paths)
        _check(f"must_path:{p}", hit,
               "present" if hit else f"no file path contains {p!r}")

    for s in (expect.get("must_mention") or []):
        hit = s.lower() in blob
        _check(f"must_mention:{s}", hit,
               "mentioned in generated files" if hit else f"{s!r} absent from all file contents")

    for s in (expect.get("forbid") or []):
        clean = s.lower() not in blob
        _check(f"forbid:{s}", clean,
               "absent" if clean else f"forbidden marker {s!r} found in generated files")

    passed_n = sum(1 for c in checks if c["passed"])
    return {
        "case_id": case["id"],
        "score": round(passed_n / len(checks), 3) if checks else 0.0,
        "passed": passed_n == len(checks),
        "checks": checks,
    }


def static_scan(artifact: dict) -> dict:
    """Run the pipeline's REAL static validators over the artifact —
    INFORMATIONAL only (never part of the score, so scores stay comparable
    across environments). Returns {available, issues} and never raises."""
    cgp = pipeline_module()
    if cgp is None:
        return {"available": False, "issues": [],
                "note": "production pipeline not present in this repo - static validators skipped"}
    try:
        issues = list(cgp.validate_all_files(artifact.get("files") or []))
        app_jsx = str((artifact.get("frontend") or {}).get("app_jsx") or "")
        if app_jsx:
            issues += [{"path": "App.jsx", "kind": i.get("kind", "ui"), "detail": i.get("detail", "")}
                       for i in (cgp.scan_for_a11y(app_jsx) + cgp.scan_for_ai_slop(app_jsx))]
        return {"available": True, "issues": issues}
    except Exception as e:  # noqa: BLE001 — a scanner crash must not kill an eval run
        return {"available": True, "issues": [],
                "note": f"static scan crashed: {type(e).__name__}: {str(e)[:120]}"}


# ── aggregation + regression gate (reuses the online scoreboard's math) ──────
def results_to_outcome_rows(results: list) -> list:
    """Map graded eval results into build_outcome-SHAPED rows so the online
    scoreboard's pure aggregator can read them. model='stub-deterministic'
    marks them unambiguously as offline eval rows, never real builds."""
    return [{
        "outcome": "verified" if r.get("passed") else "failed",
        "quality_score": float(r.get("score") or 0.0),
        "clean_first_pass": bool(r.get("passed")),
        "model": "stub-deterministic",
    } for r in (results or [])]


def aggregate_results(results: list) -> dict:
    return aggregate_build_outcomes(results_to_outcome_rows(results))


def compare_to_baseline(results: list, baseline: dict, *, full_set: bool = True) -> dict:
    """Regression check vs a committed baseline. Three independent signals:
    1. per-case score drops (deterministic stubs → any drop is a regression),
    2. cases present in the baseline but missing from this run (only when the
       full set ran — a filtered --case run legitimately skips cases),
    3. the aggregate gate via outcome_corpus.detect_quality_regression.
    """
    baseline = baseline or {}
    cur = {r["case_id"]: float(r["score"]) for r in results}
    base_scores = {k: float(v) for k, v in (baseline.get("per_case") or {}).items()}

    dropped = [f"{cid}: {base_scores[cid]} -> {cur[cid]}"
               for cid in sorted(base_scores)
               if cid in cur and cur[cid] < base_scores[cid] - 1e-9]
    missing = ([cid for cid in sorted(base_scores) if cid not in cur] if full_set else [])
    agg = aggregate_results(results)
    agg_check = detect_quality_regression(
        agg, baseline.get("aggregate") or {},
        drop=EVAL_REGRESSION_DROP, min_n=EVAL_REGRESSION_MIN_N)

    reasons = []
    if dropped:
        reasons.append("per-case score dropped: " + "; ".join(dropped))
    if missing:
        reasons.append("cases in baseline but missing from this run: " + ", ".join(missing))
    if agg_check.get("regressed"):
        reasons.append("aggregate: " + str(agg_check.get("reason")))
    return {
        "regressed": bool(dropped or missing or agg_check.get("regressed")),
        "reasons": reasons,
        "aggregate_check": agg_check,
        "aggregate": agg,
    }


def make_baseline(results: list, *, generated_at: str) -> dict:
    """The committed baseline document for the current graded results."""
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "mode": "stub",
        "generated_at": generated_at,
        "grading": ("expectation-based scores over deterministic stub artifacts; "
                    "NOT a live pipeline run"),
        "per_case": {r["case_id"]: r["score"] for r in results},
        "aggregate": aggregate_results(results),
    }


__all__ = ["CASES", "build_stub_artifact", "grade", "static_scan",
           "results_to_outcome_rows", "aggregate_results",
           "compare_to_baseline", "make_baseline", "parse_stage_text",
           "pipeline_module", "EVAL_REGRESSION_DROP", "EVAL_REGRESSION_MIN_N"]
