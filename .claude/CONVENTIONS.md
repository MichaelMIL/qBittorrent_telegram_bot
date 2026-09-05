# Flutter Agent Suite — Shared Conventions

> Every agent in this suite reads and enforces this document. It is the single
> source of truth for the stack, architecture, and coding standards. If an
> agent's instructions ever conflict with this file, this file wins.

## 1. Stack baseline

| Concern            | Choice                                  | Notes |
|--------------------|-----------------------------------------|-------|
| State management   | **Riverpod** 3.x (`flutter_riverpod`)   | Generator syntax; auto-dispose by default. |
| Provider codegen   | **riverpod_generator** + **build_runner** | `@riverpod` annotations, no manual `Provider(...)`. |
| Architecture       | **Feature-first Clean Architecture**    | See §2. |
| Navigation         | **go_router**                           | Declarative, deep-link & web friendly. |
| Models / immutability | **freezed** + **json_serializable**  | All DTOs and domain entities are immutable. freezed 3: classes are `sealed` or `abstract`. |
| Networking         | **dio**                                 | Interceptors for auth, logging, retries, error mapping. Skipped if a project uses a BaaS SDK only. |
| Linting            | **very_good_analysis**                  | Baseline ruleset; relax individual rules only with justification. |
| Local storage      | `flutter_secure_storage` for secrets, `shared_preferences`/`hive`/`isar` for non-sensitive data | Never store tokens/PII in plain prefs. |
| Localization       | `flutter_localizations` + `intl`, ARB files in `lib/l10n/`, configured by `l10n.yaml` | Access via `context.l10n`. No inline user-facing strings. |
| Logging            | `logger` package, no `print` in committed code | |
| Min Flutter / Dart | Pinned per project in `pubspec.yaml`    | Null-safety always on. |

## 2. Architecture — feature-first Clean Architecture

```
lib/
  core/                     # cross-cutting: theme, router, di, errors, network, utils
    router/
    theme/
    error/                  # Failure subtypes + Result<T> (see below)
    l10n/                   # context.l10n extension
    network/                # dio client + interceptors
    config/                 # env + backend config (see §3)
  features/
    <feature>/
      data/
        datasources/        # remote (dio/SDK) + local
        models/             # freezed DTOs (json_serializable)
        repositories/       # repository *implementations*
      domain/
        entities/           # freezed domain entities (no json)
        repositories/       # abstract repository interfaces
        usecases/           # one class per use case
      presentation/
        providers/          # riverpod notifiers / providers
        screens/            # full pages
        widgets/            # feature-scoped widgets
  shared/                   # reusable widgets/utils used by 2+ features
  main.dart
```

Layer rules (enforced by Code Review + Architecture agents):

- **Dependency direction:** presentation → domain ← data. The domain layer
  depends on nothing Flutter-specific and nothing in data/presentation.
- **Repositories:** interfaces live in `domain/repositories`, implementations
  in `data/repositories`. Presentation talks to use cases, not data sources.
- **No business logic in widgets.** Widgets read providers and render.
- **Error handling:** data layer throws typed exceptions; repositories catch
  them and return `Result<T>` (`Success<T>` | `Failed<T>`) carrying a `Failure`
  subtype from `core/error/failure.dart`. See "Results and failures" below.
- **DI:** everything is wired through Riverpod providers. No global singletons.

### Results and failures

`core/error/result.dart` and `core/error/failure.dart` are plain sealed Dart
classes (no package, no codegen). The installer scaffolds them.

- **Repositories and use cases** return `Future<Result<T>>`. They never throw.
- **Datasources** throw typed exceptions (`DioException`, SDK errors, your own).
  The repository maps each to a `Failure` subtype: `NetworkFailure`,
  `ServerFailure`, `AuthFailure`, `NotFoundFailure`, `ValidationFailure`,
  `CacheFailure`, `UnknownFailure`. Add feature-specific subtypes only when none
  of these fit.
- **Providers** unwrap with `result.getOrThrow()` inside `@riverpod` async
  bodies, so `AsyncValue.error` holds the `Failure`. Notifiers with explicit
  state use `fold` or a `switch` on the result.
- **UI** matches on the `Failure` subtype to choose the message and whether a
  retry is offered. It never sees raw exceptions.

## 3. Backend-agnostic configuration

The suite does not assume a single backend. Each project declares its backend in
`lib/core/config/backend_config.dart` (and/or `.env`). Supported modes:

- `rest` — custom REST API. dio client + interceptors. Default assumption.
- `graphql` — custom GraphQL API. `graphql_flutter`/`ferry`; dio optional.
- `firebase` — Firebase Auth/Firestore/Functions. dio usually unused.
- `supabase` — Supabase (Postgres + auth + storage) via `supabase_flutter`.

The **API/Backend Contract agent** reads this config and adapts: managing
endpoints+models for `rest`/`graphql`, or schema + security rules (Firestore
rules / Supabase RLS) for the BaaS options. All other agents stay
backend-agnostic and depend only on the repository interfaces in `domain`.

## 4. Coding standards

- Follow `very_good_analysis`. Zero analyzer warnings on committed code.
- Public APIs documented with `///` dartdoc.
- Naming: `UpperCamelCase` types, `lowerCamelCase` members, `snake_case.dart` files.
- Prefer `const` constructors; avoid rebuilding whole trees.
- No `setState` in feature code — state lives in Riverpod.
- Keep widget build methods small; extract sub-widgets over helper methods that
  return `Widget`.
- Colors, dimensions, and typography come from the theme; user-facing strings
  come from `context.l10n` (ARB files). No hardcoded literals in widgets.

## 5. Definition of Done (shared gate)

A feature is "done" only when all of the following pass:

1. `dart format --set-exit-if-changed .` clean and analyzer clean under
   `very_good_analysis`.
2. Unit + widget tests for new logic; meaningful coverage (Test agent gates).
3. Code Review agent approves (architecture + style).
4. Security agent finds no high/critical issues.
5. Dependency/License agent finds no new vulnerable or disallowed packages.
6. Visual Inspection agent confirms screens render correctly (no overflow,
   matches design) across the target breakpoints.
7. Accessibility agent passes contrast / semantics / tap-target checks.

## 6. Handoff format between agents

Agents communicate via structured Markdown reports with this header so the
Orchestrator can route them. Each agent adds its own sections between the
header and the handoff.

```
## <Agent Name> Report
- Status: PASS | NEEDS_CHANGES | NEEDS_INPUT | BLOCKED
- Feature: <feature name>
- Scope: <files / area reviewed>

### Findings
<numbered list; each: severity, location, description, recommendation>

### Handoff
- Next agent: <name or "none">
- Blocking: <yes/no>
```

Status meanings:

- `PASS` — the step is complete and the gate (if any) is met.
- `NEEDS_CHANGES` — the step found defects; the orchestrator routes the findings
  to the responsible agent and re-runs the gate.
- `NEEDS_INPUT` — the agent needs information only the user can give. Subagents
  cannot ask the user directly; the orchestrator collects the questions and ends
  its turn with them.
- `BLOCKED` — the agent could not do its job (missing plan, red test suite,
  environment limitation). The orchestrator resolves the blocker before
  retrying.
