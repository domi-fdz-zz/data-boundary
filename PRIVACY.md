# Privacy Notes

Data Boundary is designed as a local-first desktop and localhost web application.

## Data Sent to Model Providers

When a user runs fact extraction, assessment narration, source discovery, validation, or Fact Review, the app sends relevant user-provided scenario text and structured facts to the configured model-service endpoint.

The endpoint, model, and key are controlled by the user in Settings or by environment variables.

## Local Storage

The app may store model-service settings in the local user configuration directory. The API key is stored locally, masked in the UI, and can be cleared from Settings.

## Telemetry

This project does not include product telemetry or analytics. Local development logs and browser automation traces may exist in a developer workspace, but they are excluded from the release staging folder.

## Legal Assessment Data

Assessment inputs and outputs can contain sensitive business, legal, or personal-data information. Users should avoid entering confidential material unless the configured model-service endpoint and organizational policy permit it.
