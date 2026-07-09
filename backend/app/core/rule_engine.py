"""
rule_engine.py — a deliberately small, deterministic rule evaluator.

It does NO natural-language reasoning. It reads JSON rules and checks their
`conditions` against the structured AssessmentInput, returning the rules that
match. "Rules decide. Templates explain."

A rule (see domain_packs/<pack>/rules.json):

    {
      "rule_id": "BIO-HUMAN-001",
      "version": "0.1",
      "domain": "biodata",
      "description": "...",
      "conditions": { <field>: <expected>, ... },   # ALL must hold (AND)
      "verdict": "conditionally_allowed",
      "risk_level": "high",
      "reason": "...",
      "required_actions": [...],
      "evidence_ids": ["EV-..."]
    }

Supported condition forms (mapped from the JSON shorthand to the operators the
spec lists — equals / not_equals / in / not_in / boolean_true / boolean_false /
missing_any / missing_all):

    "missing_any": [f1, f2]     → true if ANY listed field is missing
    "missing_all": [f1, f2]     → true if ALL listed fields are missing
    "<field>_not": [..]/scalar  → not_in / not_equals
    "<field>": true|false       → boolean_true / boolean_false (missing != false)
    "<field>": [a, b, ...]      → in  (case-insensitive string membership)
    "<field>": scalar           → equals (case-insensitive for strings)

Field names in conditions are friendly aliases (organism, commercial,
cross_border, ...). Each domain pack supplies a `field_map` translating an alias
to a dotted path into the AssessmentInput (e.g. object.metadata.organism).
"""
from __future__ import annotations

from typing import Any

from ..models.schemas import AssessmentInput, TriggeredRule


# ─────────────────────────── value resolution ───────────────────────────
def resolve_path(root: Any, path: str) -> Any:
    """Walk a dotted path across Pydantic models and plain dicts.

    Returns None if any segment is missing. Never raises.
    """
    cur = root
    for seg in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(seg)
        else:
            cur = getattr(cur, seg, None)
    return cur


def _resolve_alias(assessment: AssessmentInput, alias: str,
                   field_map: dict[str, str]) -> Any:
    """Alias → dotted path (via field_map, else the alias is treated as a path)."""
    path = field_map.get(alias, alias)
    return resolve_path(assessment, path)


def is_missing(value: Any) -> bool:
    """Missing = None, empty string, or empty list. A real False is NOT missing."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, (list, tuple, dict)) and len(value) == 0:
        return True
    return False


def _norm(v: Any) -> Any:
    """Case/space-insensitive normalization for string comparisons."""
    if isinstance(v, str):
        return v.strip().lower()
    return v


def _in_list(actual: Any, expected: list) -> bool:
    if is_missing(actual):
        return False
    na = _norm(actual)
    return any(na == _norm(e) for e in expected)


def _equals(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool):
        # Boolean condition: a missing/None value does NOT satisfy it, so we never
        # clear (or flag) on an assumed-False when the fact is simply unstated.
        return isinstance(actual, bool) and actual == expected
    if is_missing(actual):
        return False
    return _norm(actual) == _norm(expected)


# ─────────────────────────── condition evaluation ───────────────────────────
def _condition_holds(assessment: AssessmentInput, key: str, expected: Any,
                     field_map: dict[str, str]) -> bool:
    if key == "missing_any":
        fields = expected if isinstance(expected, list) else [expected]
        return any(is_missing(_resolve_alias(assessment, f, field_map)) for f in fields)

    if key == "missing_all":
        fields = expected if isinstance(expected, list) else [expected]
        return all(is_missing(_resolve_alias(assessment, f, field_map)) for f in fields)

    if key.endswith("_not"):
        alias = key[:-4]
        actual = _resolve_alias(assessment, alias, field_map)
        # A negative condition can NEVER be confirmed on an unknown value: we must
        # not assume a missing organism is "not human" and clear it. Missing → fail.
        if is_missing(actual):
            return False
        if isinstance(expected, list):
            return not _in_list(actual, expected)
        return not _equals(actual, expected)

    actual = _resolve_alias(assessment, key, field_map)
    if isinstance(expected, list):
        return _in_list(actual, expected)
    return _equals(actual, expected)


def rule_matches(assessment: AssessmentInput, rule: dict,
                 field_map: dict[str, str]) -> bool:
    """A rule matches iff ALL of its conditions hold (logical AND)."""
    conditions = rule.get("conditions") or {}
    if not isinstance(conditions, dict):
        return False
    for key, expected in conditions.items():
        if not _condition_holds(assessment, key, expected, field_map):
            return False
    return True


def evaluate_rules(assessment: AssessmentInput, rules: list[dict],
                   field_map: dict[str, str]) -> list[dict]:
    """Return the raw rule dicts that match, in the order given.

    Raw dicts (not TriggeredRule) so the report generator can also read
    required_actions and evidence_ids. Use triggered_rule_from() to build the
    lightweight TriggeredRule for the report's triggered_rules list.
    """
    return [r for r in rules if rule_matches(assessment, r, field_map)]


def triggered_rule_from(rule: dict) -> TriggeredRule:
    """Project a raw rule dict onto the report's TriggeredRule model."""
    return TriggeredRule(
        rule_id=str(rule.get("rule_id", "")),
        version=str(rule.get("version", "")),
        verdict=str(rule.get("verdict", "")),
        risk_level=str(rule.get("risk_level", "")),
        reason=str(rule.get("reason", "")),
    )
