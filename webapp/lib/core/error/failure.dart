/// Base type for every domain-level failure.
///
/// Datasources throw typed exceptions; repositories catch them and return a
/// `Failed` result carrying one of these. The UI matches on the subtype to pick
/// a message. Add feature-specific subtypes only when none of these fit.
sealed class Failure {
  const Failure(this.message, {this.cause});

  /// Developer-facing description. UI text comes from localization, keyed on
  /// the runtime type, not from this string.
  final String message;

  /// The original exception, if any, for logging.
  final Object? cause;

  @override
  String toString() => 'Failure($message)';
}

/// No connectivity, DNS failure, timeout.
final class NetworkFailure extends Failure {
  const NetworkFailure({String message = 'Network unavailable', Object? cause})
    : super(message, cause: cause);
}

/// The backend answered with an error (5xx, malformed payload, etc.).
final class ServerFailure extends Failure {
  const ServerFailure({
    String message = 'Server error',
    this.statusCode,
    Object? cause,
  }) : super(message, cause: cause);

  final int? statusCode;
}

/// Not signed in, token expired, or forbidden (401/403).
final class AuthFailure extends Failure {
  const AuthFailure({String message = 'Not authorized', Object? cause})
    : super(message, cause: cause);
}

/// The requested resource does not exist (404).
final class NotFoundFailure extends Failure {
  const NotFoundFailure({String message = 'Not found', Object? cause})
    : super(message, cause: cause);
}

/// Input rejected by the backend or by local validation (400/422).
final class ValidationFailure extends Failure {
  const ValidationFailure({
    String message = 'Invalid input',
    this.fieldErrors = const {},
    Object? cause,
  }) : super(message, cause: cause);

  /// Field name → error message, when the backend provides them.
  final Map<String, String> fieldErrors;
}

/// Local storage or cache read/write failed.
final class CacheFailure extends Failure {
  const CacheFailure({String message = 'Local storage error', Object? cause})
    : super(message, cause: cause);
}

/// Anything not classified above. Always attach [cause].
final class UnknownFailure extends Failure {
  const UnknownFailure({String message = 'Unexpected error', Object? cause})
    : super(message, cause: cause);
}
