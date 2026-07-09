# Release Guide

## Release Target

Current planned release: `v0.1.0-alpha.1`.

This release is an alpha build for review and testing. The macOS app is ad-hoc signed. Apple Developer ID signing and notarization are not included yet.

## What to Upload

Use only files generated under:

```text
release/github/
```

Do not upload the full development workspace. The workspace contains local build artifacts, screenshots, task notes, browser automation traces, caches, and other files that are not release materials.

## Prepare a Release

1. Run tests:

```bash
cd backend
python3 -m pytest -q
```

2. Build the DMG:

```bash
./scripts/package_macos_dmg.sh
```

3. Prepare the independent GitHub release folder:

```bash
./scripts/prepare_github_release.sh
```

4. Inspect:

```bash
find release/github -maxdepth 3 -type f | sort
```

5. Upload the DMG and checksum from `release/github/assets/` to the GitHub Release.

## Release Notes Template

Title:

```text
Data Boundary v0.1.0-alpha.1
```

Body:

```text
Alpha release for preliminary U.S. privacy and data-use assessment.

Highlights:
- English desktop UI for scenario intake, fact confirmation, preliminary assessment, and report follow-up.
- Configurable model-service provider; no API key is bundled.
- Source-backed assessment basis and supplemental official-source research path.
- macOS DMG build.

Notes:
- This is not legal advice.
- The app is ad-hoc signed only; Apple notarization is not included in this alpha.
- Users must configure their own model-service API key.

Download:
- Data Boundary.dmg
- SHA256SUMS.txt
```
