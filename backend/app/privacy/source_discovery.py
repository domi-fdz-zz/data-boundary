"""
source_discovery.py - prompt guide for dynamic legal source discovery.

This module gives the Research Agent a concrete map of official places and
topic-to-source directions to check. It does not evaluate legality and it does
not change verdicts; it only makes source discovery more complete and less
dependent on whatever the model happens to remember.
"""

from __future__ import annotations

import json


EXTRA_OFFICIAL_HOSTS = {
    "www.flsenate.gov",
    "www.leg.state.fl.us",
    "www.azleg.gov",
    "le.utah.gov",
    "www.ilga.gov",
}


OFFICIAL_SOURCE_GUIDE = """
Official-source priority map:

Federal primary sources:
- U.S. Code: uscode.house.gov, govinfo.gov
- Federal regulations: ecfr.gov
- FTC statutes, rules, and enforcement material: ftc.gov
- HHS / OCR HIPAA material: hhs.gov
- CFPB consumer-finance regulations: consumerfinance.gov
- NIH policy pages and controlled-access genomic data material: sharing.nih.gov, genomicdatasharing.nih.gov, ncbi.nlm.nih.gov

State primary sources and agencies:
- California statutes and privacy agencies: leginfo.legislature.ca.gov, oag.ca.gov, privacy.ca.gov
- Washington statutes and AG: app.leg.wa.gov, atg.wa.gov
- Illinois statutes: ilga.gov
- Texas statutes: statutes.capitol.texas.gov
- New York statutes: nysenate.gov
- Virginia statutes: law.lis.virginia.gov
- Florida statutes: leg.state.fl.us, flsenate.gov
- Arizona statutes: azleg.gov
- Utah statutes: le.utah.gov

Topic map:
- health data outside HIPAA: FTC Health Breach Notification Rule, WA MHMDA, Nevada consumer health data law, California CMIA, other state consumer health laws.
- HIPAA context: HIPAA Privacy Rule, de-identification standards, limited data set / DUA, covered entity / business associate status.
- genetic data: GINA, California GIPA, Florida / Arizona / Utah genetic privacy laws, state genetic testing consent laws.
- biometric data: Illinois BIPA, Texas CUBI, Washington biometric identifiers, state comprehensive sensitive-data rules.
- children or students: COPPA, FERPA, PPRA, state age-appropriate design or student data laws.
- education records: FERPA, PPRA, school contract or audit/research exceptions.
- financial or credit data: GLBA, FCRA, Regulation V, CFPB rules, state privacy laws.
- video viewing: VPPA, state privacy laws, consent requirements.
- precise location or health inference: state sensitive-data rules and consumer health data laws.
- AI training / commercial productization: FTC Act Section 5, state privacy laws, consent / opt-out / sensitive data obligations, source terms.
- scraping or public web data: source terms, CFAA, FTC Act Section 5, state unfair/deceptive or anti-scraping provisions.
- controlled-access research data: DUA terms, NIH Genomic Data Sharing Policy, Common Rule / IRB, HIPAA if PHI is involved.

Reject or down-rank:
- blogs, law firms, Wikipedia, secondary summaries, vendor explainers, and non-official mirrors.
- a source that is only generally related but cannot be tied to a specific fact in the scenario.
- duplicate sections from the same law unless the section adds a distinct obligation.
"""


DISCOVERY_SYSTEM_PROMPT = f"""You are the Research Agent for a U.S. data-use compliance
product. Your task is source discovery only.

Find official primary legal sources that may be relevant to the exact scenario,
including sources outside a fixed checklist. Use the guide below to avoid missing
important directions, but only return sources tied to the provided facts.

{OFFICIAL_SOURCE_GUIDE}

Hard rules:
- Do not decide the final assessment.
- Do not say the use is allowed, not allowed, lawful, or unlawful.
- Use official government, legislature, court, or agency sources only.
- Return at most 8 sources, highest relevance first.
- Prefer one consolidated item per law unless separate sections create distinct obligations.
- Return JSON only, with this shape:
{{
  "sources": [
    {{
      "title": "official law, regulation, policy, or binding authority name",
      "citation": "specific section if known",
      "source_url": "official primary-source URL only",
      "authority_type": "statute|regulation|agency_rule|agency_guidance|policy|contractual_terms|other",
      "jurisdiction": "federal|state name|agency|other",
      "topic": "short topic label",
      "why_it_may_matter": "one concise sentence tied to scenario facts",
      "triggering_facts": ["facts from the scenario that made you identify this source"],
      "quote": "verbatim excerpt from the source, <=18 words, or empty if unsure"
    }}
  ]
}}"""


VALIDATION_SYSTEM_PROMPT = """You are the Validation Agent for a U.S. data-use compliance
product. You receive one source discovered by a Research Agent and the scenario
facts. Decide whether this source can be converted into a structured rule for
preliminary assessment.

Do not give legal advice. Do not decide final legality. Be conservative.

Return JSON only:
{
  "law_id": "stable lowercase id",
  "title": "source title",
  "source_url": "official source URL",
  "evaluation_status": "can_enter_assessment|needs_more_facts|do_not_use",
  "status_reason": "plain English explanation",
  "required_facts": ["facts needed to decide applicability"],
  "matched_facts": ["scenario facts that match the rule"],
  "missing_facts": ["facts not currently known"],
  "applicability_test": "plain English rule-like test",
  "research_effect": "allowed|conditionally_allowed|requires_approval|restricted|insufficient|none",
  "commercial_effect": "allowed|conditionally_allowed|requires_approval|restricted|insufficient|none",
  "effect_reason": "why those effects would follow if applicability is established",
  "confidence": "high|medium|low"
}

Use can_enter_assessment only when the current facts are enough to make a
structured applicability decision. Use needs_more_facts when the source may
matter but key applicability facts are missing. Use do_not_use if the source is
irrelevant, unofficial, duplicative without added obligation, or too vague.
"""


def discovery_user_prompt(facts_summary: str, modeled_law_names: list[str]) -> str:
    modeled = "\n- ".join(modeled_law_names) if modeled_law_names else "None"
    return (
        f"SCENARIO FACTS:\n{facts_summary}\n\n"
        "Built-in evaluated sources already considered by the product:\n"
        f"- {modeled}\n\n"
        "Find additional or more specific official sources that may matter. You may include a built-in source only if a specific section or authority adds a distinct obligation not already captured."
    )


def validation_user_prompt(facts_summary: str, source: dict, official: bool,
                           quote_status: str) -> str:
    payload = {
        "scenario_facts": facts_summary,
        "source": source,
        "source_official": official,
        "quote_status": quote_status,
    }
    return json.dumps(payload, ensure_ascii=False)
