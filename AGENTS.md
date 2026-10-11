# Agent guide

This repository builds the OpenDefence MediaMTX integration.
Read [README.md](README.md) and [implementation status](docs/implementation-status.md) before feature work.

- Use the `ponytail` skill for every coding task. Use its full level unless the user selects another level.
- Run the `ponytail-audit` skill on the whole repository before every commit.
  Fix problems introduced by the change before committing. Report other findings to the user.
- Write new and changed documentation in Simplified Technical English (STE).
  Use short, active sentences. Use one term for each concept.
  Define abbreviations when they first appear. Avoid idioms and unclear pronouns.
- Name each operator when you refer to it. Use `core-operator`,
  `tak-operator`, or `mediamtx-operator` as applicable. Do not use
  "the operator" when the name is known. Apply this rule to code comments,
  documentation, handoffs, and progress reports.
- Treat the projected User roles and memberships in Kubernetes CRD status as
  integration input. Do not require `core-operator` to run during integration
  reconciliation or tests. A test can supply the CRD state directly.
- Treat a User certificate as identity proof only. It grants no Role or Group
  membership. Use the projected User status lists when `mediamtx-operator`
  reconciles MediaMTX access according to this integration's Role meanings.
- Keep approved Users as permanent records. If `spec.approvedAt` is set, revoke
  the User with `spec.revokedAt`; do not delete or recreate that User. Use only
  unapproved Users for tests that delete or recreate User resources.

Run `task check` after code changes.
Run `task package:check` after Zarf package or overlay changes.
Keep `zarf.yaml` in sync with overlay changes.
