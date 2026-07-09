"""
Privacy data-use checker — "can I use this dataset for research / commercial?"

Reframed from the multi-domain engine after the scope research. The spine is:

  de-identification off-ramp  →  contract layer (license / DUA / ToS)  →
  statutory applicability gate (open-world)  →  purpose matrix (research vs commercial)

Key lessons baked in from the research:
  * De-identification is THE master off-ramp, and it is per-regime (HIPAA Safe
    Harbor vs Expert Determination vs state "de-identified" vs aggregate).
  * For a researcher with a *found* dataset, the binding constraint is very often
    the CONTRACT layer (license / DUA / controlled-access repository / ToS), not a
    consumer-privacy statute — and comprehensive state laws often don't even apply
    to a lone researcher or to de-identified data.
  * Human-subjects research is governed by the Common Rule (45 CFR 46) / IRB, not
    (only) consumer privacy law.
  * Open-world default: absence of a modeled trigger is NOT "cleared" — coverage
    is limited to the modeled laws, and unknown facts route to "insufficient".
  * This tool identifies obligations; it does NOT give legal advice (UPL guardrail).
"""
