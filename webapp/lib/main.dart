import 'dart:async';

import 'package:flutter/material.dart';

import 'package:qbit_web/screens/activity_screen.dart';
import 'package:qbit_web/screens/browse_screen.dart';
import 'package:qbit_web/screens/connect_screen.dart';
import 'package:qbit_web/screens/favorites_screen.dart';
import 'package:qbit_web/screens/nas_screen.dart';
import 'package:qbit_web/screens/plex_screen.dart';
import 'package:qbit_web/screens/search_screen.dart';
import 'package:qbit_web/screens/settings_screen.dart';
import 'package:qbit_web/screens/torrents_screen.dart';
import 'package:qbit_web/state.dart';

void main() {
  final state = AppState();
  unawaited(state.init());
  runApp(AppScope(state: state, child: const QbitApp()));
}

class QbitApp extends StatelessWidget {
  const QbitApp({super.key});

  @override
  Widget build(BuildContext context) {
    const seed = Color(0xFF3F51B5);
    return MaterialApp(
      title: 'Torrent butler',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(colorSchemeSeed: seed, brightness: Brightness.light),
      darkTheme: ThemeData(colorSchemeSeed: seed, brightness: Brightness.dark),
      home: const _Root(),
    );
  }
}

class _Root extends StatelessWidget {
  const _Root();

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    if (!state.ready) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (!state.connected) return const ConnectScreen();
    return const Shell();
  }
}

class _Destination {
  const _Destination(
    this.label,
    this.page,
    this.icon,
    this.selectedIcon,
    this.builder, {
    this.mobile = true,
  });
  final String label;

  /// Permission key (see AppState.can).
  final String page;
  final IconData icon;
  final IconData selectedIcon;
  final WidgetBuilder builder;
  final bool mobile; // shown in the bottom bar (5 max) — the rail shows all
}

final _destinations = <_Destination>[
  // Browse (newest HeBits content) is the home screen and takes the phone
  // bar's first slot; Search is reached from its app bar on phones (5-slot
  // bar) and is a rail item on wide screens.
  _Destination(
    'Browse',
    'browse',
    Icons.explore_outlined,
    Icons.explore,
    (_) => const BrowseScreen(),
  ),
  _Destination(
    'Search',
    'search',
    Icons.search,
    Icons.search,
    (_) => const SearchScreen(),
    mobile: false,
  ),
  _Destination(
    'Library',
    'library',
    Icons.download_outlined,
    Icons.download,
    (_) => const TorrentsScreen(),
  ),
  _Destination(
    'Favorites',
    'favorites',
    Icons.star_border,
    Icons.star,
    (_) => const FavoritesScreen(),
  ),
  _Destination(
    'Activity',
    'activity',
    Icons.notifications_none,
    Icons.notifications,
    (_) => const ActivityScreen(),
  ),
  _Destination(
    'Plex',
    'plex',
    Icons.movie_filter_outlined,
    Icons.movie_filter,
    (_) => const PlexScreen(),
    mobile: false,
  ),
  _Destination(
    'NAS',
    'nas',
    Icons.storage_outlined,
    Icons.storage,
    (_) => const NasScreen(),
    mobile: false,
  ),
  _Destination(
    'Settings',
    'settings',
    Icons.settings_outlined,
    Icons.settings,
    (_) => const SettingsScreen(),
  ),
];

/// Adaptive shell: bottom navigation on phones, a navigation rail on wide
/// screens. Screens are kept alive in an IndexedStack so search results and
/// scroll positions survive tab switches.
class Shell extends StatefulWidget {
  const Shell({super.key});

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  int _index = 0;

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= 840;
    final state = AppScope.of(context);
    final unread = state.status?.unreadEvents ?? 0;
    // user logins only get the pages the admin enabled
    final allowed = [
      for (final d in _destinations)
        if (state.can(d.page)) d,
    ];
    final visible = wide
        ? allowed
        : [
            for (final d in allowed)
              if (d.mobile) d,
          ];
    if (visible.isEmpty) {
      return Scaffold(
        appBar: AppBar(
          actions: [
            IconButton(
              tooltip: 'Disconnect',
              icon: const Icon(Icons.logout),
              onPressed: state.logout,
            ),
          ],
        ),
        body: const Center(
          child: Padding(
            padding: EdgeInsets.all(32),
            child: Text(
              'No pages are enabled for the user login. Ask the admin to '
              'enable some in Settings → User access.',
              textAlign: TextAlign.center,
            ),
          ),
        ),
      );
    }
    // a page this login may not open (or that just got disabled) falls back
    // to the first allowed one; bar-less pages like Search stay reachable
    if (!allowed.contains(_destinations[_index])) {
      _index = _destinations.indexOf(allowed.first);
    }
    final current = _destinations[_index];
    final selected = visible.indexOf(current).clamp(0, visible.length - 1);

    Widget iconFor(_Destination d, {required bool active}) {
      final icon = Icon(active ? d.selectedIcon : d.icon);
      if (d.label == 'Activity' && unread > 0) {
        return Badge.count(count: unread, child: icon);
      }
      return icon;
    }

    final body = IndexedStack(
      index: _index,
      // IndexedStack keeps every screen mounted; TickerMode lets a screen tell
      // whether it is the visible one (browse defers its first fetch on it).
      children: [
        for (var i = 0; i < _destinations.length; i++)
          TickerMode(
            enabled: i == _index,
            child: _destinations[i].builder(context),
          ),
      ],
    );

    if (wide) {
      return ShellNav(
        goTo: _goTo,
        child: Scaffold(
          body: Row(
            children: [
              NavigationRail(
                selectedIndex: selected,
                labelType: NavigationRailLabelType.all,
                onDestinationSelected: (i) =>
                    setState(() => _index = _destinations.indexOf(visible[i])),
                leading: const Padding(
                  padding: EdgeInsets.symmetric(vertical: 12),
                  child: Image(
                    image: AssetImage('assets/logo.png'),
                    width: 40,
                    height: 40,
                  ),
                ),
                trailing: Expanded(
                  child: Align(
                    alignment: Alignment.bottomCenter,
                    child: Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: IconButton(
                        tooltip: 'Disconnect',
                        icon: const Icon(Icons.logout, size: 20),
                        onPressed: state.logout,
                      ),
                    ),
                  ),
                ),
                destinations: [
                  for (final d in visible)
                    NavigationRailDestination(
                      icon: iconFor(d, active: false),
                      selectedIcon: iconFor(d, active: true),
                      label: Text(d.label),
                    ),
                ],
              ),
              const VerticalDivider(width: 1),
              Expanded(child: body),
            ],
          ),
        ),
      );
    }
    return ShellNav(
      goTo: _goTo,
      child: Scaffold(
        body: body,
        // NavigationBar needs at least two destinations
        bottomNavigationBar: visible.length < 2
            ? null
            : NavigationBar(
                selectedIndex: selected,
                onDestinationSelected: (i) =>
                    setState(() => _index = _destinations.indexOf(visible[i])),
                destinations: [
                  for (final d in visible)
                    NavigationDestination(
                      icon: iconFor(d, active: false),
                      selectedIcon: iconFor(d, active: true),
                      label: d.label,
                    ),
                ],
              ),
      ),
    );
  }

  void _goTo(String label) {
    final i = _destinations.indexWhere((d) => d.label == label);
    if (i >= 0) setState(() => _index = i);
  }
}

/// Lets a screen switch the shell to another destination by label (on phones
/// the Browse and Search app bars use it to reach each other, since only one
/// of them has a slot in the bottom bar).
class ShellNav extends InheritedWidget {
  const ShellNav({required this.goTo, required super.child, super.key});
  final ValueChanged<String> goTo;

  static ShellNav? maybeOf(BuildContext c) =>
      c.getElementForInheritedWidgetOfExactType<ShellNav>()?.widget
          as ShellNav?;

  @override
  bool updateShouldNotify(ShellNav oldWidget) => false;
}
