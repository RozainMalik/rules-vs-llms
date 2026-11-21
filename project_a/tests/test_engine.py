"""
pytest suite for implementation (a), the hand-coded rules engine.

Run:  python -m pytest project_a/tests -q
"""

import csv
import json
from pathlib import Path

import pytest

from project_a.impl_rules.engine import RulesEngine
from project_a.models import Clarification, TaxInput, TaxResult

HERE = Path(__file__).resolve().parent
CASES = json.loads((HERE / "cases.json").read_text())
ENGINE = RulesEngine("2024-25")


def test_suite_size():
    assert len(CASES) >= 200


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_rupee_exact(case):
    """Engine must match the independent oracle to the rupee, both regimes."""
    res = ENGINE.compute(TaxInput(**case["input"]))
    assert isinstance(res, TaxResult), res
    assert res.old.tax_payable == case["expected"]["old"], case["description"]
    assert res.new.tax_payable == case["expected"]["new"], case["description"]
    assert res.old.total_income == case["expected_total_income"]["old"]
    assert res.new.total_income == case["expected_total_income"]["new"]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_every_rupee_traces_to_a_clause(case):
    res = ENGINE.compute(TaxInput(**case["input"]))
    for rr in (res.old, res.new):
        tax_lines = [l for l in rr.trace if l.kind == "tax"]
        assert sum(l.amount for l in tax_lines) == rr.tax_payable
        assert all(l.clause for l in rr.trace)


def test_deterministic():
    inp = TaxInput(**CASES[0]["input"])
    first = ENGINE.compute(inp)
    assert all(ENGINE.compute(inp) == first for _ in range(10))


# --- clarification behaviour ------------------------------------------------
def test_missing_salary_asks():
    res = ENGINE.compute(TaxInput(age=30))
    assert isinstance(res, Clarification) and "salary" in res.questions[0].lower()


def test_rent_without_hra_info_asks_about_hra():
    res = ENGINE.compute(TaxInput(gross_salary=1500000, age=30, rent_paid=240000))
    assert isinstance(res, Clarification) and "hra_received" in res.reason


def test_hra_without_details_asks_for_rent_basic_city():
    res = ENGINE.compute(TaxInput(gross_salary=1500000, age=30, hra_received=300000))
    assert isinstance(res, Clarification)
    for f in ("rent_paid", "basic_plus_da", "rent_city_is_metro"):
        assert f in res.reason


def test_rent_but_no_hra_computes():
    res = ENGINE.compute(TaxInput(gross_salary=1500000, age=30, rent_paid=240000, hra_received=0))
    assert isinstance(res, TaxResult)


def test_contradiction_asks():
    res = ENGINE.compute(TaxInput(gross_salary=500000, age=30, hra_received=900000))
    assert isinstance(res, Clarification)


def test_unstated_deductions_are_disclosed():
    res = ENGINE.compute(TaxInput(gross_salary=1500000, age=30))
    assert isinstance(res, TaxResult)
    assert any("sec_80c" in a for a in res.assumptions)


# --- official calculator cross-check ------------------------------------------
def _official_rows():
    path = HERE / "official_checks.csv"
    if not path.exists():
        return []
    return [r for r in csv.DictReader(open(path)) if r["official_old"] and r["official_new"]]


@pytest.mark.parametrize("row", _official_rows() or [None])
def test_matches_official_calculator(row):
    if row is None:
        pytest.skip("official_checks.csv not filled in yet")
    res = ENGINE.compute(TaxInput(**json.loads(row["input_json"])))
    assert res.old.tax_payable == int(row["official_old"]), row["id"]
    assert res.new.tax_payable == int(row["official_new"]), row["id"]
