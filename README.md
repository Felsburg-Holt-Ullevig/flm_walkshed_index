# FLM Walkshed Index

A web application in development for evaluating first/last mile walking access around transit stops and stations in Colorado.

The intended workflow is to create or upload station locations, generate network walksheds, examine individual metrics and index scores, and export results. This repository currently contains the development foundation and a Hello World placeholder. GIS data, analysis, scoring, session storage, and reporting are future work.

## Maintainer entry points

- [Developer guide](DEVELOPER.md): setup, commands, reviewing changes, CI, and releases.
- [Requirements](docs/requirements.md): what the finished application must do.
- [Architecture overview](architecture_overview.md): implemented boundaries and open technical decisions.
- [Shared agent instructions](AGENTS.md): policy used by Codex and Claude Code.
- [Validation policy](docs/validation.md): checks and analytical acceptance.
- [Methodology status](docs/methodology.md): decisions required before calculations are implemented.
- [Data contract status](docs/data-contract.md): preparation/runtime boundaries and versioning requirements.
- [Preparation pipeline](pipeline/README.md): where offline data work will live.

## Development

Setup, commands, and the review process are in the [developer guide](DEVELOPER.md). Development uses AI coding agents under human review; a project lead approves every change merged to `main`.

## Development preview

A [development preview](https://felsburg-holt-ullevig.github.io/flm_walkshed_index/) is built from `main`. It is not a CDOT service and has no analytical content yet. CDOT production hosting, methodology, accessibility evidence, data publication, branding, and final distribution requirements remain open.

## Data and distribution

Large GIS inputs and output archives belong in approved external storage, with small reviewed fixtures and metadata in Git. Keep client/background documents, credentials, and personal session files outside public source history. This repository does not yet establish a code license or grant rights to CDOT branding or third-party data.
