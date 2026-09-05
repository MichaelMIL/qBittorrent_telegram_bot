import 'package:qbit_web/core/error/failure.dart';

/// Outcome of a repository or use-case call: [Success] or [Failed].
///
/// Repositories and use cases return `Future<Result<T>>` and never throw.
/// Inside a `@riverpod` async provider, unwrap with [getOrThrow] so that
/// `AsyncValue.error` carries the [Failure] for the UI to match on.
sealed class Result<T> {
  const Result();

  const factory Result.success(T value) = Success<T>;
  const factory Result.failed(Failure failure) = Failed<T>;

  bool get isSuccess => this is Success<T>;
  bool get isFailure => this is Failed<T>;

  T? get valueOrNull => switch (this) {
    Success(:final value) => value,
    Failed() => null,
  };

  Failure? get failureOrNull => switch (this) {
    Success() => null,
    Failed(:final failure) => failure,
  };

  /// Collapse both branches into one value.
  R fold<R>(
    R Function(Failure failure) onFailure,
    R Function(T value) onSuccess,
  ) => switch (this) {
    Success(:final value) => onSuccess(value),
    Failed(:final failure) => onFailure(failure),
  };

  /// Transform the success value, passing failures through unchanged.
  Result<R> map<R>(R Function(T value) transform) => switch (this) {
    Success(:final value) => Success(transform(value)),
    Failed(:final failure) => Failed(failure),
  };

  /// Chain another result-producing step.
  Future<Result<R>> flatMap<R>(
    Future<Result<R>> Function(T value) next,
  ) async => switch (this) {
    Success(:final value) => await next(value),
    Failed(:final failure) => Failed(failure),
  };

  /// Return the value or throw the [Failure]. Use inside `@riverpod` async
  /// bodies so `AsyncValue.error` holds the `Failure`.
  T getOrThrow() => switch (this) {
    Success(:final value) => value,
    // Failure is deliberately not an Exception: providers rethrow it so
    // AsyncValue.error carries the typed failure for the UI to match on.
    // ignore: only_throw_errors
    Failed(:final failure) => throw failure,
  };
}

/// Successful outcome carrying [value].
final class Success<T> extends Result<T> {
  const Success(this.value);
  final T value;
}

/// Failed outcome carrying [failure].
final class Failed<T> extends Result<T> {
  const Failed(this.failure);
  final Failure failure;
}
