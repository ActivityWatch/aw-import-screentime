# Repository guidance

## Engineering operating standard

- Understand the existing importer, Apple Biome data model, and ActivityWatch
  side effects before changing behavior.
- Apply relevant engineering practices from project evidence and primary
  documentation; avoid speculative rewrites or new infrastructure.
- Make the smallest safe, reviewable, and reversible change that solves the
  requested problem.
- Validate, document, and self-review every change.
- Work from the latest `origin/master` in a topic branch and deliver repository
  modifications through a pull request. Never push directly to `master`.

## Project map

- `src/aw_import_screentime/__main__.py` contains the Typer CLI, TOML
  configuration, Biome discovery and decoding, interval stitching, ActivityWatch
  sink, persistent watcher state, and long-running file watcher.
- `src/aw_import_screentime/app_in_focus_extended.proto` is the protobuf schema.
  The adjacent `_pb2.py` and `_pb2.pyi` files are generated artifacts.
- `src/aw_import_screentime/ccl_segb_cli.py` is a standalone low-level SEGB
  inspection helper.
- `tests/` covers ActivityWatch deduplication, persisted open intervals and
  watermarks, restart catch-up, and watcher rescan behavior.
- `README.md` is the canonical user and developer guide.

## Supported environment and setup

- This project is macOS-specific at runtime because it reads Screen Time data
  from `~/Library/Biome`.
- Supported Python versions are 3.10 through 3.13; `.python-version` currently
  selects Python 3.13.
- Use `uv` and the checked-in `uv.lock`. Set up the environment with:

  ```bash
  uv sync --locked
  ```

- Do not replace `uv`, loosen runtime constraints, or refresh the lockfile
  unless dependency work is explicitly in scope.

## Verification

Run the checks relevant to the change:

```bash
uv run pytest -q
uv run aw-import-screentime --help
```

- The current test baseline is 10 passing tests on Python 3.13.
- Repository-wide `black --check` and `mypy src tests` are not currently clean.
  Use them as diagnostics, report their exact pre-existing failures, and do not
  reformat or type-fix unrelated files.
- Format human-authored Python files that you change. Do not manually reformat
  generated protobuf artifacts.
- There is no checked-in CI workflow, so record local commands and results in
  every pull request.
- Tests must not depend on a developer's real Biome database, Screen Time
  streams, ActivityWatch production bucket, device IDs, or network access.

## Behavioral invariants

- Apple `CFAbsoluteTime` values must be converted with `APPLE_EPOCH_OFFSET` and
  remain timezone-aware.
- Preserve chronological ordering before interval stitching.
- An open foreground interval must survive watcher restarts and close only when
  a matching transition is observed.
- Advance and persist a device watermark only after its events have been
  processed successfully. Failed ActivityWatch inserts must remain retryable.
- Preserve deduplication across restarts and repeated backfills. App-title
  enrichment must not change event identity.
- Preserve per-device bucket isolation and any configured `bucket_suffix`.
- CLI flags override TOML values; defaults must remain consistent across
  `config show`, `events import`, and `watch`.
- Keep read-only commands (`devices`, `file`, `events preview`, `config show`,
  and `config validate`) free of ActivityWatch writes.

## Side effects, data, and privacy

- `events import` and `watch` write ActivityWatch events. Do not run them against
  the default production server or port 5600 without explicit permission.
- Prefer an `aw-server --testing` instance and the CLI's `--testing` mode
  (port 5666) for integration checks.
- `config init` writes under `~/Library/Application Support` unless given an
  explicit temporary path. Do not modify a user's real configuration in tests.
- Treat Biome paths, device identifiers, app histories, state files, and event
  payloads as private user data. Never commit or paste real values into tests,
  fixtures, logs, issues, or pull requests.
- Do not weaken Full Disk Access requirements, permission handling, retry
  behavior, or data-isolation safeguards merely to make a test pass.

## Change rules

- Add regression tests for changes to stitching, deduplication, state
  persistence, configuration precedence, bucket naming, retry behavior, or time
  handling.
- Use fakes and temporary paths for ActivityWatch, filesystem, and state tests.
- Keep the source `.proto` and generated protobuf files consistent. If schema
  regeneration is required, document the exact generator and version in the
  pull request; do not hand-edit generated output.
- Update `README.md` in the same pull request when CLI options, setup,
  configuration, paths, side effects, or troubleshooting behavior changes.
- Do not mix feature work with broad formatting, dependency upgrades, generated
  file churn, or unrelated refactors.

## Pull-request expectations

- Keep one coherent change per pull request and follow the repository's existing
  commit style.
- Include the reason, scope, tests run, exact results, side effects, compatibility
  notes, risks, and rollback or revert path.
- Call out any checks that were not run and every pre-existing failure.
- Do not merge the pull request or enable auto-merge without explicit approval.

## Definition of done

A change is complete when its behavior is covered by appropriate tests, relevant
documentation is current, local verification is reported honestly, private user
data and production ActivityWatch state were not touched, the full diff has been
self-reviewed, and the change is proposed through a pull request.
