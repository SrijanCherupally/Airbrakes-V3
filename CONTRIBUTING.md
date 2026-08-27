# Contributing to Airbrakes V3

Thanks for contributing. This repository contains embedded firmware, desktop software, simulation utilities, and data tooling, so keeping changes focused and documented helps everyone review them safely.

## Before you start

1. Read the top-level [`README.md`](README.md) to understand the repository layout and quick-start commands.
2. Check [`APP_INSTRUCTIONS.md`](APP_INSTRUCTIONS.md) for ground-station installation and usage.
3. Check [`DATA.md`](DATA.md) before changing logging, serialization, or data-analysis behavior.
4. Review [`sim/README.md`](sim/README.md) if your change involves the coast-table generator or generated lookup data.
5. Review the existing code and documentation around the component you intend to change.

## Branches and commits

Create a topic branch from `main` for each logical change. Prefer short, descriptive branch names such as:

```text
docs/clarify-data-format
fix/desktop-log-import
refactor/estimator-module
```

Keep commits focused. A useful commit message explains the intent, for example:

```text
docs: clarify flight-data format
```

## Pull requests

Pull requests should include:

- a concise description of the problem or goal;
- a summary of the important changes;
- the files or subsystems affected;
- tests or validation performed;
- any known limitations or follow-up work.

Documentation-only changes should say so explicitly when no executable tests are applicable.

## Code and documentation changes

### Firmware

Keep shared interfaces in `include/` and implementations in `src/`. When changing a public interface, update all affected callers and the relevant documentation.

### C++ formatting

The repository uses the checked-in [`.clang-format`](.clang-format) configuration for C/C++ source and headers. Format changes with `clang-format` before opening a PR. Avoid mixing large formatting-only changes with behavioral changes unless the formatting is necessary for the change.

The repository also provides a conservative [`.clang-tidy`](.clang-tidy) configuration for maintainability and bug-pattern checks. Treat diagnostics as review prompts; do not apply automated fixes blindly to embedded or hardware-facing code.

Editors should respect the repository-wide [`.editorconfig`](.editorconfig) settings for line endings, whitespace, indentation, and final newlines.

### Desktop application

Keep Electron main-process responsibilities separate from renderer code. When changing a user-facing workflow, update [`APP_INSTRUCTIONS.md`](APP_INSTRUCTIONS.md) as appropriate.

### Data formats

Treat serialized records and file formats as interfaces. If a format changes, update the writer, reader, tests, and [`DATA.md`](DATA.md) together. Consider compatibility with existing data before removing or renaming fields.

### Documentation

Prefer concise, task-oriented documentation. Link to the existing source of truth instead of duplicating long procedures across multiple files.

## Validation

For firmware changes, run the project's available PlatformIO build/tests that are appropriate for the affected code.

For C++ formatting-only changes, run `clang-format --dry-run --Werror` on the affected source/header files where supported by the installed clang-format version.

For static-analysis changes, run the configured `clang-tidy` checks against a valid compilation database when one is available. Review diagnostics manually before applying fixes.

For desktop changes, run the application locally and exercise the affected UI path when practical.

For documentation-only changes, check Markdown formatting, links, code fences, and consistency with the current repository layout.

## Safety and hardware testing

Software changes that interact with physical hardware should be reviewed and tested according to the team's applicable safety procedures, competition rules, and adult-supervision requirements. Do not use this contribution guide as a replacement for those procedures.

## Keep pull requests reviewable

Avoid mixing unrelated refactors with a feature or bug fix. If a cleanup is useful but independent, consider submitting it as a separate pull request.
