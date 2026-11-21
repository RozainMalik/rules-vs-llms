"""
Tests for the injector and the rule detectors (no LLM, no network beyond the
cached sample).  Run:  python -m pytest project_b/tests -q
"""

import pandas as pd
import pytest

from project_b.alerts import BATCH_LEVEL, PROBLEMS
from project_b.detectors import rules
from project_b.injector import inject
from project_b.refs import load_data
from project_b.schema import EXPECTED_COLUMNS


@pytest.fixture(scope="module")
def data():
    refs, pool, _, _ = load_data()
    clean = pool.sample(500, random_state=42).reset_index(drop=True)
    return refs, clean


@pytest.mark.parametrize("p", list(PROBLEMS))
def test_injector_is_reproducible(data, p):
    refs, clean = data
    a = inject(p, clean, 0.05, seed=1, refs=refs)
    b = inject(p, clean, 0.05, seed=1, refs=refs)
    pd.testing.assert_frame_equal(a.batch, b.batch)
    assert a.row_labels.equals(b.row_labels)


@pytest.mark.parametrize("p", sorted(set(PROBLEMS) - BATCH_LEVEL - {"c", "e", "f"}))
def test_injector_respects_rate(data, p):
    refs, clean = data
    inj = inject(p, clean, 0.05, seed=3, refs=refs)
    assert 0 < inj.row_labels.sum() <= 0.06 * len(clean) + 1


def test_injector_does_not_touch_input(data):
    refs, clean = data
    before = clean.copy()
    inject("d", clean, 0.1, seed=0, refs=refs)
    pd.testing.assert_frame_equal(before, clean)


def test_duplicates_label_both_members(data):
    refs, clean = data
    inj = inject("e", clean, 0.02, seed=0, refs=refs)
    assert len(inj.batch) == len(clean) + inj.meta["n"]
    assert inj.row_labels.sum() == 2 * inj.meta["n"]


@pytest.mark.parametrize("p", list(PROBLEMS))
def test_rules_silent_on_clean_for_crisp_contracts(data, p):
    """Crisp-contract rules must raise nothing on the clean pool."""
    refs, clean = data
    if p in ("f", "j", "k"):            # fuzzy rules: allowed some noise, measured in evaluate.py
        pytest.skip("fuzzy rule — false-alarm rate is measured, not asserted")
    assert rules.CHECKS[p](clean, refs) == []


@pytest.mark.parametrize("p", list(PROBLEMS))
def test_rules_fire_on_injected(data, p):
    refs, clean = data
    inj = inject(p, clean, 0.05, seed=5, refs=refs)
    alerts = rules.CHECKS[p](inj.batch, refs)
    if p in BATCH_LEVEL:
        assert alerts
    else:
        flagged = {a.row for a in alerts}
        truth = set(inj.row_labels.index[inj.row_labels])
        assert flagged & truth, "rule found none of the injected rows"


def test_schema_rule_names_the_column(data):
    refs, clean = data
    broken = clean.drop(columns=["borough"])
    (alert,) = rules.schema_columns(broken, refs)
    assert "borough" in alert.explanation


def test_pii_rule_ignores_official_311_number(data):
    refs, _ = data
    df = pd.DataFrame({c: [None] for c in EXPECTED_COLUMNS})
    df["resolution_description"] = ["If you are outside of New York City, please call (212) NEW-YORK (212-639-9675)."]
    assert rules.pii_regex(df, refs) == []


def test_pii_rule_catches_personal_phone(data):
    refs, _ = data
    df = pd.DataFrame({c: [None] for c in EXPECTED_COLUMNS})
    df["resolution_description"] = ["Caller can be reached at 917-555-0134."]
    assert len(rules.pii_regex(df, refs)) == 1
