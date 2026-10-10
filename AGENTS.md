# Agent guide

This repository builds the OpenDefence MediaMTX integration.
Read [README.md](README.md) and [implementation status](docs/implementation-status.md) before feature work.

- Use the `ponytail` skill for every coding task. Use its full level unless the user selects another level.
- Run the `ponytail-audit` skill on the whole repository before every commit.
  Fix problems introduced by the change before committing. Report other findings to the user.
- Write new and changed documentation in Simplified Technical English (STE).
  Use short, active sentences. Use one term for each concept.
  Define abbreviations when they first appear. Avoid idioms and unclear pronouns.

Run `task check` after code changes.
Run `task package:check` after Zarf package or overlay changes.
Keep `zarf.yaml` in sync with overlay changes.
