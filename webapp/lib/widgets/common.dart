import 'dart:async';

import 'package:flutter/material.dart';

import 'package:qbit_web/api/client.dart';
import 'package:qbit_web/state.dart';

void showSnack(BuildContext context, String text, {bool error = false}) {
  final messenger = ScaffoldMessenger.maybeOf(context);
  if (messenger == null) return;
  messenger
    ..hideCurrentSnackBar()
    ..showSnackBar(
      SnackBar(
        content: Text(text),
        backgroundColor: error ? Theme.of(context).colorScheme.error : null,
        duration: Duration(seconds: error ? 6 : 4),
      ),
    );
}

/// Run an API call, surfacing failures as a snackbar. Returns null on error.
Future<T?> guard<T>(BuildContext context, Future<T> Function() fn) async {
  try {
    return await fn();
  } on ApiException catch (e) {
    if (e.unauthorized && context.mounted) {
      unawaited(AppScope.read(context).connect());
    }
    if (e.settingsLocked && context.mounted) {
      AppScope.read(context).lockSettings();
    }
    if (context.mounted) showSnack(context, '❌ ${e.message}', error: true);
    return null;
  } on Exception catch (e) {
    if (context.mounted) showSnack(context, '❌ $e', error: true);
    return null;
  }
}

/// Simple text prompt dialog; returns null when cancelled or empty.
Future<String?> promptText(
  BuildContext context, {
  required String title,
  String? hint,
  String initial = '',
  String confirm = 'OK',
  bool multiline = false,
}) {
  final controller = TextEditingController(text: initial);
  return showDialog<String>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(title),
      content: TextField(
        controller: controller,
        autofocus: true,
        decoration: InputDecoration(hintText: hint),
        maxLines: multiline ? 6 : 1,
        minLines: multiline ? 3 : 1,
        onSubmitted: multiline ? null : (v) => Navigator.pop(ctx, v.trim()),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(ctx),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(ctx, controller.text.trim()),
          child: Text(confirm),
        ),
      ],
    ),
  ).then((v) => (v == null || v.isEmpty) ? null : v);
}

Future<bool> confirm(
  BuildContext context, {
  required String title,
  String? body,
  String yes = 'OK',
  bool destructive = false,
}) async {
  final res = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(title),
      content: body == null ? null : Text(body),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(ctx, false),
          child: const Text('Cancel'),
        ),
        FilledButton(
          style: destructive
              ? FilledButton.styleFrom(
                  backgroundColor: Theme.of(ctx).colorScheme.error,
                )
              : null,
          onPressed: () => Navigator.pop(ctx, true),
          child: Text(yes),
        ),
      ],
    ),
  );
  return res == true;
}

/// Poster image via the backend proxy, with a neutral placeholder.
class Poster extends StatelessWidget {
  const Poster({required this.url, super.key, this.radius = 12});
  final String url;
  final double radius;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final placeholder = Container(
      color: scheme.surfaceContainerHighest,
      alignment: Alignment.center,
      child: Icon(
        Icons.movie_outlined,
        size: 40,
        color: scheme.onSurfaceVariant,
      ),
    );
    return ClipRRect(
      borderRadius: BorderRadius.circular(radius),
      child: url.isEmpty
          ? placeholder
          : Image.network(
              AppScope.of(context).api.coverUrl(url),
              fit: BoxFit.cover,
              gaplessPlayback: true,
              errorBuilder: (_, _, _) => placeholder,
              loadingBuilder: (ctx, child, progress) =>
                  progress == null ? child : placeholder,
            ),
    );
  }
}

/// Centered message with an optional retry button.
class EmptyView extends StatelessWidget {
  const EmptyView({
    required this.icon,
    required this.text,
    super.key,
    this.onRetry,
    this.retryLabel = 'Retry',
  });
  final IconData icon;
  final String text;
  final VoidCallback? onRetry;
  final String retryLabel;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 56, color: scheme.onSurfaceVariant),
            const SizedBox(height: 16),
            Text(
              text,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodyLarge,
            ),
            if (onRetry != null) ...[
              const SizedBox(height: 16),
              FilledButton.tonal(onPressed: onRetry, child: Text(retryLabel)),
            ],
          ],
        ),
      ),
    );
  }
}

/// Small pill used for markers (freeleech, snatched, downloaded) on tiles.
class Mark extends StatelessWidget {
  const Mark(this.text, {super.key, this.tooltip, this.color});
  final String text;
  final String? tooltip;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final chip = Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: color ?? Colors.black.withValues(alpha: 0.65),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        text,
        style: const TextStyle(color: Colors.white, fontSize: 12),
      ),
    );
    return tooltip == null ? chip : Tooltip(message: tooltip, child: chip);
  }
}

/// Prev / “page / pages” / next, used by search and browse.
class Pager extends StatelessWidget {
  const Pager({
    required this.page,
    required this.pages,
    required this.onPage,
    super.key,
  });
  final int page;
  final int pages;
  final ValueChanged<int> onPage;

  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      IconButton(
        icon: const Icon(Icons.chevron_left),
        onPressed: page > 1 ? () => onPage(page - 1) : null,
      ),
      Text('$page / $pages'),
      IconButton(
        icon: const Icon(Icons.chevron_right),
        onPressed: page < pages ? () => onPage(page + 1) : null,
      ),
    ],
  );
}

/// Section header inside lists.
class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key, this.trailing});
  final String text;
  final Widget? trailing;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(16, 20, 16, 8),
    child: Row(
      children: [
        Expanded(
          child: Text(text, style: Theme.of(context).textTheme.titleMedium),
        ),
        ?trailing,
      ],
    ),
  );
}

/// Wraps content to a comfortable reading width on big screens.
class Constrained extends StatelessWidget {
  const Constrained({required this.child, super.key, this.maxWidth = 900});
  final Widget child;
  final double maxWidth;
  @override
  Widget build(BuildContext context) => Center(
    child: ConstrainedBox(
      constraints: BoxConstraints(maxWidth: maxWidth),
      child: child,
    ),
  );
}
