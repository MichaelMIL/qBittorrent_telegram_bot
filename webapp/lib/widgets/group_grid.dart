import 'package:flutter/material.dart';
import 'package:qbit_web/models.dart';
import 'package:qbit_web/screens/group_screen.dart';
import 'package:qbit_web/widgets/common.dart';

/// Poster tiles, one per HeBits group. Shared by search and browse.
class GroupGrid extends StatelessWidget {
  const GroupGrid({
    required this.groups,
    required this.onChanged,
    super.key,
    this.physics,
  });
  final List<Group> groups;

  /// Called after a pushed [GroupScreen] pops (favorite / default may differ).
  final VoidCallback onChanged;

  /// Browse passes [AlwaysScrollableScrollPhysics] so pull-to-refresh works
  /// even when a page is short enough not to scroll.
  final ScrollPhysics? physics;

  @override
  Widget build(BuildContext context) {
    // Group.title reads torrents.first, so a release-less group would throw.
    final items = [
      for (final g in groups)
        if (g.torrents.isNotEmpty) g,
    ];
    return GridView.builder(
      physics: physics,
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 88),
      gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
        maxCrossAxisExtent: 190,
        mainAxisExtent: 320,
        crossAxisSpacing: 12,
        mainAxisSpacing: 12,
      ),
      itemCount: items.length,
      itemBuilder: (ctx, i) => GroupTile(
        group: items[i],
        onTap: () async {
          await Navigator.of(ctx).push(
            MaterialPageRoute<void>(
              builder: (_) => GroupScreen(group: items[i]),
            ),
          );
          onChanged(); // favorite / default may have changed
        },
      ),
    );
  }
}

/// A poster tile summarizing a group (used by search and, later, browse pages).
class GroupTile extends StatelessWidget {
  const GroupTile({required this.group, required this.onTap, super.key});
  final Group group;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final local = group.bestLocal;
    final ts = group.torrents;
    final String detail;
    if (ts.length == 1) {
      final t = ts.first;
      detail = [
        if (t.resolution.isNotEmpty) t.resolution,
        _size(t.size),
        '🌱 ${t.seeders}',
      ].join(' · ');
    } else {
      final reso = group.resolutions.join('/');
      detail =
          '${ts.length} releases${reso.isEmpty ? '' : ' ($reso)'} · 🌱 ${group.totalSeeders}';
    }
    return Card(
      clipBehavior: Clip.antiAlias,
      margin: EdgeInsets.zero,
      child: InkWell(
        onTap: onTap,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(
              child: Stack(
                fit: StackFit.expand,
                children: [
                  Poster(url: group.cover, radius: 0),
                  Positioned(
                    left: 6,
                    top: 6,
                    child: Wrap(
                      spacing: 4,
                      children: [
                        if (local != null)
                          Mark(local.mark, tooltip: local.label),
                        if (group.anyFree)
                          const Mark('🆓', tooltip: 'Freeleech'),
                        if (group.anySnatched)
                          const Mark('✔️', tooltip: 'Snatched on HeBits'),
                      ],
                    ),
                  ),
                  if (group.favorite)
                    Positioned(
                      right: 6,
                      top: 6,
                      child: Mark(group.auto ? '⭐⚡' : '⭐', tooltip: 'Favorite'),
                    ),
                  if (group.cat.isNotEmpty)
                    Positioned(
                      left: 6,
                      bottom: 6,
                      child: Mark(group.cat),
                    ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(10, 8, 10, 10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    group.titleWithYear,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.titleSmall,
                  ),
                  if (group.nameHe.isNotEmpty && group.nameHe != group.title)
                    Text(
                      group.nameHe,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.bodySmall,
                    ),
                  const SizedBox(height: 2),
                  Text(
                    detail,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  static String _size(int n) {
    var v = n.toDouble();
    for (final u in const ['B', 'KiB', 'MiB', 'GiB', 'TiB']) {
      if (v < 1024) return '${v.toStringAsFixed(1)} $u';
      v /= 1024;
    }
    return '${v.toStringAsFixed(1)} PiB';
  }
}
