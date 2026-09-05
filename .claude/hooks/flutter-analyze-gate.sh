#!/usr/bin/env bash
#
# Flutter Agent Suite — Stop hook for code-writing agents.
#
# Runs `flutter analyze` when a coding agent tries to finish. If the analyzer
# reports issues, the hook exits 2 and feeds the output back to the agent so it
# fixes them before reporting PASS. It blocks at most once per session so it can
# never trap an agent in a loop (subagent Stop hooks are not given
# `stop_hook_active`).
#
# Exit codes: 0 = let the agent stop, 2 = block and return stderr to the agent.
set -u

input="$(cat 2>/dev/null || true)"

# Only meaningful inside a Flutter project with the toolchain available.
command -v flutter >/dev/null 2>&1 || exit 0
# The Flutter project of this repo lives in webapp/ (the root is the Python backend).
[ -f pubspec.yaml ] || { [ -f webapp/pubspec.yaml ] && cd webapp; }
[ -f pubspec.yaml ] || exit 0

session="$(printf '%s' "$input" | sed -n 's/.*"session_id" *: *"\([^"]*\)".*/\1/p' | head -n1)"
marker="${TMPDIR:-/tmp}/flutter-analyze-gate-${session:-nosession}"

# Second stop in the same session: we already blocked once, let it through.
if [ -f "$marker" ]; then
  rm -f "$marker"
  exit 0
fi

if out="$(flutter analyze --no-pub 2>&1)"; then
  exit 0
fi

: > "$marker"
{
  echo "flutter analyze reported issues. Fix them before finishing:"
  echo
  printf '%s\n' "$out" | tail -n 60
} >&2
exit 2
