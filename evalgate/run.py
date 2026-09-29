"""Eval runner CLI — the offline regression gate for the code-gen brain.

Usage (from backend/):
    python3 -m evals.run                       # stub eval + baseline gate
    python3 -m evals.run --case slack_standup_bot
    python3 -m evals.run --update-baseline     # regenerate evals/baseline.json
    python3 -m evals.run --mode live           # live Base44-parity lane (real spend)
    python3 -m evals.run --mode live --dry-run # live-lane wiring check, zero spend

Exit codes (CI-gate usable):
    0 — no regression vs the committed baseline (or baseline just updated;
        in live mode: the measurement completed)
    1 — regression detected vs baseline (live: a case hit a harness error)
    2 — refused: unknown --case, or live mode with prerequisites missing

HONESTY: stub mode grades DETERMINISTIC stub artifacts through the pipeline's
real JSON parser + file sanitizer + static validators where importable. It
does NOT execute the live LLM pipeline — it regression-tests the grading
contract, the stage formats, and the validators, and its output says so.
Live mode delegates to evals.live_run (the Base44-parity lane) and keeps the
refusal semantics: missing API keys → exit 2 with a clear message, never a
fabricated result.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from evalgate import harness
from evalgate.cases import CASES, case_by_id

BASELINE_PATH = Path(__file__).resolve().parent / "baseline.json"


def run_stub_eval(case_ids=None) -> list:
    """Build + grade the stub artifact for each selected case. Deterministic."""
    selected = [c for c in CASES if not case_ids or c["id"] in set(case_ids)]
    results = []
    for case in selected:
        artifact = harness.build_stub_artifact(case)
        graded = harness.grade(case, artifact)
        graded["graded_via"] = artifact.get("graded_via")
        graded["static"] = harness.static_scan(artifact)
        results.append(graded)
    return results


def _print_results(results: list) -> None:
    print("MODE: stub — grading deterministic stub artifacts (no live LLM run; "
          "this gates the eval contract + pipeline parsers/validators, not model quality).")
    via = {r.get("graded_via") for r in results}
    print(f"parser: {', '.join(sorted(v for v in via if v))}")
    print()
    for r in results:
        failed = [c for c in r["checks"] if not c["passed"]]
        status = "PASS" if r["passed"] else "FAIL"
        static = r.get("static") or {}
        n_static = len(static.get("issues") or [])
        static_note = (f", static-issues={n_static}" if static.get("available")
                       else ", static-scan=unavailable")
        print(f"  [{status}] {r['case_id']:<22} score={r['score']:.3f} "
              f"({len(r['checks']) - len(failed)}/{len(r['checks'])} checks{static_note})")
        for c in failed:
            print(f"         - {c['name']}: {c['detail']}")
    agg = harness.aggregate_results(results)
    print()
    print(f"aggregate: total={agg['total']} verified_rate={agg['verified_rate']} "
          f"avg_quality={agg['avg_quality']} clean_first_pass={agg['clean_first_pass_rate']}")


def _mode_stub(args) -> int:
    if args.case:
        unknown = [cid for cid in args.case if case_by_id(cid) is None]
        if unknown:
            print(f"error: unknown case id(s): {', '.join(unknown)}", file=sys.stderr)
            print("known ids: " + ", ".join(c["id"] for c in CASES), file=sys.stderr)
            return 2
    results = run_stub_eval(args.case)
    _print_results(results)
    full_set = not args.case

    if args.update_baseline:
        if not full_set:
            print("\nerror: --update-baseline requires the FULL case set "
                  "(a partial baseline would silently un-gate the skipped cases).",
                  file=sys.stderr)
            return 2
        baseline = harness.make_baseline(
            results, generated_at=datetime.now(timezone.utc).isoformat())
        args.baseline.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n")
        print(f"\nbaseline written: {args.baseline}")
        return 0

    if not args.baseline.exists():
        print(f"\nWARNING: no baseline at {args.baseline} — nothing to gate against. "
              "Run with --update-baseline and commit the file.")
        return 0
    baseline = json.loads(args.baseline.read_text())
    cmp = harness.compare_to_baseline(results, baseline, full_set=full_set)
    print()
    if cmp["regressed"]:
        print("REGRESSION vs baseline:")
        for reason in cmp["reasons"]:
            print(f"  - {reason}")
        return 1
    # When the production pipeline isn't importable — which is always the case
    # in this repo, since it isn't published here — grading falls back to a LOCAL
    # parser. A green exit could then be read as "the real parsers are fine" when
    # they were never exercised. --strict makes a CI gate FAIL LOUD on that;
    # without it we still pass, but we say so plainly rather than hiding it.
    on_fallback = any(r.get("graded_via") == "local_fallback" for r in results)
    if on_fallback:
        msg = ("graded via LOCAL FALLBACK — the production code-gen pipeline is not "
               "part of this repository, so its real parsers/validators were NOT "
               "exercised. Scores here gate the grading contract, not the pipeline.")
        if args.strict:
            print(f"FAIL (--strict): {msg}\nRun inside the full platform, where the pipeline module is importable, to gate the real parsers.")
            return 3
        print(f"NOTE: {msg}")
    print(f"no regression vs baseline ({cmp['aggregate_check'].get('reason')})")
    return 0


def _mode_live(args) -> int:
    """Delegate to the live Base44-parity lane (evals.live_run).

    Refusal semantics preserved: missing API keys → exit 2 with a clear
    message, never a fabricated result. MONGO_URL is no longer a prerequisite
    because the live runner brings its own in-memory fake DB (spec, move 2).
    --case ids here are LIVE case ids (evals/live_cases.py), not stub ids.
    """
    from evalgate import live_run
    argv = []
    for cid in (args.case or []):
        argv += ["--case", cid]
    if args.dry_run:
        argv.append("--dry-run")
    if args.max_cases is not None:
        argv += ["--max-cases", str(args.max_cases)]
    return live_run.main(argv)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m evals.run",
        description="Offline eval harness for the code-gen brain (exit 1 on regression).")
    parser.add_argument("--mode", choices=("stub", "live"), default="stub")
    parser.add_argument("--case", action="append",
                        help="run only this case id (repeatable)")
    parser.add_argument("--update-baseline", action="store_true",
                        help="rewrite the committed baseline from this run")
    parser.add_argument("--baseline", type=Path, default=BASELINE_PATH,
                        help=f"baseline path (default: {BASELINE_PATH})")
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero if grading fell back to the local parser "
                             "(the real pipeline parsers were not importable) — for CI gates")
    parser.add_argument("--dry-run", action="store_true",
                        help="live mode only: walk the full live-lane wiring against "
                             "stub artifacts at zero model spend")
    parser.add_argument("--max-cases", type=int, default=None,
                        help="live mode only: run at most N of the live cases (default: all)")
    args = parser.parse_args(argv)
    if args.mode == "live":
        return _mode_live(args)
    return _mode_stub(args)


if __name__ == "__main__":
    sys.exit(main())
