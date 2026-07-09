# Data Boundary

Data Boundary is a local-first tool for preliminary data-use review across U.S. privacy, consent, source-term, and data-use restrictions. It helps a user describe a proposed data use, extract structured facts, review open issues, and generate a preliminary assessment with cited source materials.

This project is not a law firm, lawyer, or legal-advice system. The output is a structured product assessment aid and must be reviewed by a qualified professional before it is relied on.

## What It Does

- Captures the proposed data-use scenario in plain English.
- Uses a configurable model service to extract structured facts from the scenario.
- Lets the user confirm or correct extracted facts before assessment.
- Runs deterministic assessment logic against modeled rules and source materials.
- Shows open facts that may affect the result.
- Displays the basis for the assessment, including primary sources and decision details.
- Runs supplemental source discovery to surface additional official authorities that may require follow-up.
- Provides a report-grounded Fact Review assistant that can explain the displayed result without changing it.

## Current Workflow

1. Describe the proposed data use: dataset, source, identifiability, sensitive categories, subject location, license or terms, and intended use.
2. Optional fact review: ask the right-side assistant to help organize missing facts before running the assessment.
3. Fact extraction: the configured model service converts the scenario into structured fields.
4. User confirmation: the user reviews and edits the extracted facts.
5. Preliminary assessment: the backend applies modeled rules and retrieves source-backed decision details.
6. Supplemental source discovery: a research path looks for additional official authorities and validates whether they can enter a structured assessment.
7. Report follow-up: the assistant can explain the result, cite the displayed basis, and route material fact changes back to reassessment.

## Desktop App

The macOS desktop build is distributed as a DMG through GitHub Releases. It starts a local FastAPI service inside the app and opens the UI in a native webview window.

The current build is ad-hoc signed only. Apple Developer ID signing and notarization are intentionally outside this release until a signing decision is made.

## Local Development

Requirements:

- Python 3.10 or newer
- macOS for DMG packaging
- A model-service API key for extraction and assessment paths

Install and run:

```bash
cd backend
python3 -m pip install -r requirements.txt
PYTHONPATH=. python3 -m uvicorn app.main:app --host 127.0.0.1 --port 7788
```

Open `http://localhost:7788/`.

Run tests:

```bash
cd backend
python3 -m pytest -q
```

Build a local macOS DMG:

```bash
./scripts/package_macos_dmg.sh
```

Prepare the GitHub release staging folder:

```bash
./scripts/prepare_github_release.sh
```

The staging output is written under `release/github/`. Only that folder should be used when preparing a GitHub release upload.

## Model Service Settings

The app ships with no API key. Users must configure a provider in Settings or via environment variables:

- `CCA_LLM_ENDPOINT`
- `CCA_LLM_MODEL`
- `CCA_LLM_API_KEY`

Saved keys are stored locally under the user's config directory and are never returned by the settings API. The Settings panel also includes a clear-key action.

## Repository Layout

- `backend/app`: FastAPI app, assessment logic, source discovery, and UI assets.
- `backend/app/data/datause.html`: current single-page UI.
- `backend/app/privacy`: data-use assessment pipeline and source discovery prompts.
- `backend/app/domain_packs`: existing deterministic rule-pack framework.
- `docs`: product workflow and release documentation.
- `scripts`: macOS packaging and release staging scripts.
- `.github/workflows`: CI checks.

## Release Policy

Release artifacts are prepared in an independent staging directory. The full development workspace, local screenshots, task notes, caches, generated build directories, and local model configuration are not release materials.

## License

Apache License 2.0. See `LICENSE`.
