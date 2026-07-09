"""Core engine — the universal, domain-agnostic machinery.

    normalizer  → (optional LLM) free-text scenario → structured AssessmentInput
    router      → pick the domain pack
    rule_engine → evaluate a domain pack's JSON rules against the input
    evidence    → load evidence (v0.1: local JSON fixtures; interface for later)
    report_generator → merge triggered rules into one ClearanceReport
    engine      → orchestrate all of the above
"""
