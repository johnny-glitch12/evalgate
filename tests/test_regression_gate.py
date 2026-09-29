"""The gate must be capable of failing. These tests assert exactly that."""
from evalgate.outcome_corpus import detect_quality_regression as detect

BASE = {"total": 14, "verified_rate": 1.0, "avg_quality": 1.0}


def test_passes_when_quality_holds():
    out = detect({"total": 14, "verified_rate": 0.99, "avg_quality": 1.0},
                 BASE, drop=0.05, min_n=10)
    assert out["regressed"] is False and out["confident"] is True


def test_fires_on_a_material_drop_and_says_why():
    out = detect({"total": 14, "verified_rate": 0.78, "avg_quality": 1.0},
                 BASE, drop=0.05, min_n=10)
    assert out["regressed"] is True
    assert out["metric"] == "verified_rate"
    assert "0.22" in out["reason"]


def test_abstains_rather_than_false_alarming_on_thin_data():
    out = detect({"total": 4, "verified_rate": 0.10, "avg_quality": 0.1},
                 BASE, drop=0.05, min_n=10)
    assert out["regressed"] is False
    assert out["confident"] is False
    assert "insufficient volume" in out["reason"]


def test_grading_is_pure_same_input_same_score():
    from evalgate import cases, harness
    case = cases.CASES[0]
    a = harness.grade(case, harness.build_stub_artifact(case))
    b = harness.grade(case, harness.build_stub_artifact(case))
    assert a["score"] == b["score"]
