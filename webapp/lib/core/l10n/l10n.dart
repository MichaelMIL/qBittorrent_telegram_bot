import 'package:flutter/widgets.dart';
import 'package:qbit_web/l10n/app_localizations.dart';

export 'package:qbit_web/l10n/app_localizations.dart';

/// Shorthand for the generated localizations: `context.l10n.appTitle`.
extension L10nX on BuildContext {
  AppLocalizations get l10n => AppLocalizations.of(this);
}
