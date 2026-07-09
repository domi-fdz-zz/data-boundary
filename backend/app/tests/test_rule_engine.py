"""Rule-engine operator semantics — the subtle, safety-relevant bits."""
from __future__ import annotations

from app.core.rule_engine import rule_matches, is_missing

from .factories import make_input

FM = {
    "organism": "object.metadata.organism",
    "data_type": "object.metadata.data_type",
    "commercial": "use_case.commercial",
    "clinical": "use_case.clinical",
    "cross_border": "data_flow.cross_border",
}


def test_is_missing():
    assert is_missing(None)
    assert is_missing("")
    assert is_missing("   ")
    assert is_missing([])
    assert is_missing({})
    assert not is_missing(False)   # a real False is a value, not missing
    assert not is_missing(0)
    assert not is_missing("x")


def test_boolean_condition_missing_never_matches_false():
    # commercial unknown (None) must NOT satisfy commercial:false
    unknown = make_input(use_case={"category": "x"})
    assert not rule_matches(unknown, {"conditions": {"commercial": False}}, FM)
    explicit = make_input(use_case={"category": "x", "commercial": False})
    assert rule_matches(explicit, {"conditions": {"commercial": False}}, FM)


def test_not_condition_fails_on_missing():
    # unknown organism must NOT be treated as "not human"
    missing = make_input(object={"object_type": "dataset", "metadata": {}})
    assert not rule_matches(missing, {"conditions": {"organism_not": ["Homo sapiens", "human"]}}, FM)
    mouse = make_input(object={"object_type": "dataset", "metadata": {"organism": "Mus musculus"}})
    assert rule_matches(mouse, {"conditions": {"organism_not": ["Homo sapiens", "human"]}}, FM)
    human = make_input(object={"object_type": "dataset", "metadata": {"organism": "Homo sapiens"}})
    assert not rule_matches(human, {"conditions": {"organism_not": ["Homo sapiens", "human"]}}, FM)


def test_in_is_case_insensitive():
    inp = make_input(object={"object_type": "dataset", "metadata": {"organism": "HOMO SAPIENS"}})
    assert rule_matches(inp, {"conditions": {"organism": ["Homo sapiens", "human"]}}, FM)


def test_missing_any_and_all():
    inp = make_input(
        object={"object_type": "dataset", "metadata": {"organism": "human"}},
        use_case={"category": "x", "commercial": True, "clinical": False},
        data_flow={"cross_border": True},
    )  # data_type missing
    crit = ["organism", "data_type", "commercial", "clinical", "cross_border"]
    assert rule_matches(inp, {"conditions": {"missing_any": crit}}, FM)
    assert not rule_matches(inp, {"conditions": {"missing_all": crit}}, FM)


def test_all_conditions_must_hold():
    inp = make_input(
        object={"object_type": "dataset", "metadata": {"organism": "Homo sapiens"}},
        use_case={"category": "x", "commercial": False},
    )
    # organism matches but commercial:true does not → whole rule fails
    assert not rule_matches(
        inp, {"conditions": {"organism": ["Homo sapiens"], "commercial": True}}, FM)
