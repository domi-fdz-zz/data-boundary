# Product Workflow

This document describes the current workflow implemented by Data Boundary.

## 1. Scenario Intake

The user describes the proposed data use in one text area. A good input states the dataset, source, identifiability, subject location, license or source terms, sensitive categories, and intended use.

Example:

> A California biotech company plans to use a public human gene-expression dataset from a repository to train a commercial cancer-risk model; the dataset includes age range, disease status, and gene-expression values, but the license and consent terms are unclear.

## 2. Fact Review Before Assessment

The right-side Fact Review panel can help the user organize facts before assessment. It must not make a final conclusion about whether the proposed use is permitted.

## 3. Structured Fact Extraction

The backend calls the configured model service to convert free text into structured fields. The extracted fields are not treated as final until the user reviews them.

## 4. User Confirmation

The user reviews and edits extracted facts. This step matters because the preliminary assessment depends on the confirmed facts, not only on the original paragraph.

## 5. Preliminary Assessment

The backend applies modeled assessment logic and returns:

- a preliminary result
- reasons for the result
- open facts that may affect the result
- evaluated source basis
- detailed decision information

## 6. Supplemental Source Research

The source discovery path searches for additional official authorities that may be relevant to the facts. A validation step checks whether each source has enough scenario-specific facts to enter structured assessment.

Sources in this section do not automatically change the top-level result unless they have been converted into modeled decision logic or otherwise surfaced as a clear assessment dependency.

## 7. Report-Grounded Follow-Up

After assessment, the Fact Review assistant can explain the displayed result and source basis. It does not override the assessment. If the user changes a material fact, the assistant should direct the user to update the facts and rerun the assessment.
