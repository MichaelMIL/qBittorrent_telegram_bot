---
name: flutter-feature
description: >-
  Start the Flutter agent pipeline for a feature, bug fix, refactor, or release
  by briefing the flutter-orchestrator agent. Use when the user asks to build,
  add, fix, refactor, or ship something in a Flutter project.
argument-hint: <what to build, fix, refactor, or release>
disable-model-invocation: true
---

Run the Flutter agent suite for this request:

> $ARGUMENTS

Steps:

1. Read `CONVENTIONS.md` (project root or `.claude/`) and
   `lib/core/config/backend_config.dart` so the brief carries the backend mode.
2. Delegate to the `flutter-orchestrator` subagent with the Agent tool
   (`subagent_type: flutter-orchestrator`). The brief must contain, verbatim:
   the request above, the backend mode, the project root path, and the
   instruction to run the appropriate pipeline (new feature, bug fix, refactor,
   or release) and enforce the Definition of Done in `CONVENTIONS.md §5`.
3. Do not implement anything yourself while the orchestrator runs.
4. When it returns, relay its status table, any blocking issues, and any open
   questions for the user. If the report contains open questions, stop and wait
   for the user's answers, then re-brief the orchestrator with them.
