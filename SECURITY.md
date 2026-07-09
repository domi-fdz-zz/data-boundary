# Security Policy

## Supported Version

This repository is currently prepared as `v0.1.0-alpha.1`. The alpha build is intended for review and testing before a broader release.

## API Keys

The app must not ship with a model-service API key. Users provide their own key through Settings or environment variables. Saved keys are stored locally and are not returned by the settings API.

Before publishing a release, run the release staging script and inspect the generated `release/github/` directory. Do not upload the full workspace.

## Reporting Security Issues

If this repository is published on GitHub, report vulnerabilities through GitHub Security Advisories when available. If advisories are not enabled, open a minimal issue that does not include exploit details or private credentials.

## Release Checks

The CI workflow runs tests and basic release hygiene checks. A maintainer should also verify that staged release files do not contain:

- API keys or bearer tokens
- local config files
- `.pytest_cache`, `__pycache__`, `.DS_Store`, or Playwright logs
- screenshots or task notes that are not intended for release
