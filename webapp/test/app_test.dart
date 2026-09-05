import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fake_server.dart';
import 'harness.dart';

void main() {
  late FakeServer server;

  setUp(() async {
    server = FakeServer();
    await server.start();
  });
  tearDown(() => server.stop());

  testWidgets('wrong password is rejected, right one logs in', (tester) async {
    final state = await boot(tester, server);
    await tester.enterText(find.byType(TextField).last, 'nope');
    await tester.tap(find.text('Connect'));
    await settle(tester);
    expect(find.text('Wrong password'), findsOneWidget);
    expect(state.connected, isFalse);
    await login(tester, state, server);
    expectVisible(find.text('🆕 New on HeBits')); // Browse is the home screen
    await openSearch(tester);
    expectVisible(find.text('Search HeBits…'));
    await finish(tester, state);
  });

  testWidgets('search shows tiles, detail card has seasons and releases', (
    tester,
  ) async {
    final state = await boot(tester, server);
    await login(tester, state, server);
    await openSearch(tester);
    await tester.enterText(find.byType(TextField).first, 'fauda');
    await tester.testTextInput.receiveAction(TextInputAction.search);
    await settle(tester);
    expect(find.text('Fauda (2015)'), findsOneWidget);
    expect(find.text('Some Movie (2025)'), findsOneWidget);
    expect(find.text('1 / 2'), findsOneWidget); // pager

    await tester.tap(find.text('Fauda (2015)'));
    await settle(tester);
    expect(find.text('S05'), findsOneWidget);
    expect(find.text('S04'), findsOneWidget);
    expect(find.textContaining('3 releases'), findsOneWidget);
    expect(find.text('Fauda.S05E11.1080p.WEB.H264-NTb'), findsOneWidget);
    expect(find.text('Favorite'), findsOneWidget);
    expect(
      find.textContaining('📌 Default: 🏷 michael + 📁 tv + 📐 1080p'),
      findsOneWidget,
    );

    // switch season
    await tester.tap(find.text('S04'));
    await tester.pump();
    expect(find.text('Fauda.S04E12.1080p.WEB.H264-NTb'), findsOneWidget);
    await tester.tap(find.text('S05'));
    await tester.pump();

    // add flow with a series default → "use default" dialog → add
    await tester.tap(find.text('Fauda.S05E11.1080p.WEB.H264-NTb'));
    await tester.pump();
    expect(find.textContaining('This series has a default'), findsOneWidget);
    await tester.tap(find.text('Use default'));
    await settle(tester, 20);
    expect(server.calls, contains('POST /api/add/hebits'));
    expect(find.textContaining('✅ Added Fauda.S05E11'), findsOneWidget);
    await finish(tester, state);
  });

  testWidgets('manual add flow: tag sheet → category sheet → offer default', (
    tester,
  ) async {
    server.seriesDefault = null;
    final state = await boot(tester, server);
    await login(tester, state, server);
    await openSearch(tester);
    await tester.enterText(find.byType(TextField).first, 'fauda');
    await tester.testTextInput.receiveAction(TextInputAction.search);
    await settle(tester);
    await tester.tap(find.text('Fauda (2015)'));
    await settle(tester);
    await tester.tap(find.text('Fauda.S05E11.1080p.WEB.H264-NTb'));
    await settle(tester);
    expect(find.text('michael'), findsOneWidget); // tag sheet
    await tester.tap(find.text('michael'));
    await settle(tester);
    expect(find.text('tv'), findsOneWidget); // category sheet
    await tester.tap(find.text('tv'));
    await settle(tester, 20);
    expect(server.calls, contains('POST /api/add/hebits'));
    expect(find.textContaining('Make 📁 “tv” the default'), findsOneWidget);
    await tester.tap(find.text('1080p'));
    await settle(tester);
    expect(server.calls, contains('PUT /api/defaults/1234'));
    expect(server.seriesDefault?['resolution'], '1080p');
    await finish(tester, state);
  });

  testWidgets('library, favorites, activity, settings render', (tester) async {
    // tall phone so the settings list needs no scrolling past the nav bar
    final state = await boot(tester, server, size: const Size(390, 1500));
    await login(tester, state, server);

    await tester.tap(find.text('Library'));
    await settle(tester);
    expect(find.text('Fauda.S05E10.1080p.WEB.H264-NTb'), findsOneWidget);
    expect(find.text('42.0%'), findsOneWidget);
    expect(find.text('100%'), findsOneWidget);
    await tester.tap(find.text('Fauda.S05E10.1080p.WEB.H264-NTb'));
    await settle(tester);
    expect(find.text('Pause'), findsOneWidget);
    expect(find.text('/Volumes/Media/TV'), findsOneWidget);
    await tester.tap(find.text('Pause'));
    await settle(tester);
    expect(server.calls, contains('POST /api/torrents/aaa/pause'));
    await tester.pageBack();
    await settle(tester);

    await tester.tap(find.text('Favorites'));
    await settle(tester);
    expect(find.text('Fauda (2015)'), findsOneWidget);
    expect(find.textContaining('🆕 S05E10'), findsOneWidget);
    await tester.tap(find.byType(Switch));
    await settle(tester);
    expect(server.favAuto, isTrue);
    expect(find.textContaining('⚡ Auto-add on'), findsOneWidget);

    await tester.tap(find.text('Activity'));
    await settle(tester);
    expect(
      find.textContaining('The Bear (2022) — new episode: S04E03'),
      findsOneWidget,
    );
    expect(find.text('The.Bear.S04E03.1080p.WEB.H264-NTb'), findsOneWidget);
    expect(find.textContaining('Fauda (2015) — auto-added'), findsOneWidget);
    expect(find.textContaining('Stalled at 42%'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('Scan Plex now'), 200);
    expect(find.text('Scan Plex now'), findsOneWidget);
    await tester.tap(find.text('Mark all read'));
    await settle(tester);
    expect(server.calls, contains('POST /api/events/read'));

    await tester.tap(find.text('Settings'));
    await settle(tester);
    expect(find.textContaining('42 torrents'), findsOneWidget);
    // let the snackbar expire and finish its exit animation (it eats taps)
    await tester.pump(const Duration(seconds: 6));
    await tester.pump(const Duration(seconds: 1));
    await tester.pump(const Duration(seconds: 1));
    await tester.scrollUntilVisible(
      find.text('Auto-scan Plex after downloads'),
      200,
    );
    expect(find.text('Auto-scan Plex after downloads'), findsOneWidget);
    await tester.tap(find.text('Auto-scan Plex after downloads'));
    await settle(tester);
    expect(server.calls, contains('PATCH /api/settings'));
    expect(server.settings['auto_plex_scan'], isTrue);
    await tester.scrollUntilVisible(find.text('Validate HeBits cookie'), 200);
    await tester.tap(find.text('Validate HeBits cookie'));
    await settle(tester, 20);
    expect(find.textContaining('logged in as “michael”'), findsOneWidget);
    await finish(tester, state);
  });

  testWidgets('settings lock: unlock with the password, clear cache, relock', (
    tester,
  ) async {
    server.settingsLocked = true;
    final state = await boot(tester, server, size: const Size(390, 1500));
    await login(tester, state, server);
    await tester.tap(find.text('Settings'));
    await settle(tester);
    expectVisible(find.text('Settings are locked'));
    expect(find.text('Auto-scan Plex after downloads'), findsNothing);

    await tester.enterText(find.byType(TextField).last, 'nope');
    await tester.tap(find.text('Unlock'));
    await settle(tester);
    expectVisible(find.text('Wrong settings password'));

    await tester.enterText(find.byType(TextField).last, 'lock');
    await tester.tap(find.text('Unlock'));
    await settle(tester);
    expectVisible(find.text('7 posters · 120.6 KiB on disk'));
    expectVisible(find.text('limit 1.00 GiB · cleared every 7 d'));

    await tester.tap(find.text('Clear cache'));
    await settle(tester, 20);
    expect(server.cacheClears, 1);
    expectVisible(find.textContaining('Cache cleared — 7 posters'));

    // the server would refuse a change without the token; with it, it works
    await tester.pump(const Duration(seconds: 6)); // snackbar out of the way
    await tester.pump(const Duration(seconds: 1));
    await tester.scrollUntilVisible(
      find.text('Auto-scan Plex after downloads'),
      200,
    );
    await tester.tap(find.text('Auto-scan Plex after downloads'));
    await settle(tester);
    expect(server.settings['auto_plex_scan'], isTrue);

    await tester.tap(find.byTooltip('Lock settings'));
    await tester.pump();
    expectVisible(find.text('Settings are locked'));
    await finish(tester, state);
  });

  testWidgets('user login sees only the enabled pages and can disconnect', (
    tester,
  ) async {
    final state = await boot(tester, server);
    expect(find.text('Connect'), findsOneWidget);
    await tester.enterText(find.byType(TextField).last, 'user');
    await tester.tap(find.text('Connect'));
    await settle(tester);
    expect(state.connected, isTrue);
    expect(state.role, 'user');

    // phone bar: Browse only (search is an icon), no Library/Settings
    expectVisible(find.text('🆕 New on HeBits'));
    expect(find.text('Library'), findsNothing);
    expect(find.text('Favorites'), findsNothing);
    expect(find.text('Settings'), findsNothing);
    expect(find.byTooltip('Search HeBits'), findsOneWidget);

    // detail card: no favorites button, but adding is allowed
    await settle(tester);
    await tester.tap(find.text('Series Pick 1 (2025)'));
    await settle(tester);
    expect(find.text('Add to favorites'), findsNothing);
    expect(find.text('Favorite'), findsNothing);
    await tester.pageBack();
    await settle(tester);
    await tester.pump(const Duration(seconds: 1)); // route transition done

    await tester.tap(find.widgetWithIcon(IconButton, Icons.logout));
    await settle(tester);
    expect(state.connected, isFalse);
    expect(find.text('Connect'), findsOneWidget);
    await finish(tester, state);
  });

  testWidgets('admin toggles user pages in Settings', (tester) async {
    final state = await boot(tester, server, size: const Size(390, 1800));
    await login(tester, state, server);
    expect(state.role, 'admin');
    await tester.tap(find.text('Settings'));
    await settle(tester);
    await tester.pump(const Duration(seconds: 6));
    await tester.pump(const Duration(seconds: 1));
    await tester.scrollUntilVisible(
      find.widgetWithText(SwitchListTile, 'Library'),
      200,
    );
    await tester.tap(find.widgetWithText(SwitchListTile, 'Library'));
    await settle(tester);
    expect(server.userPages['library'], isTrue);
    expect(server.calls, contains('PATCH /api/settings'));
    await finish(tester, state);
  });

  testWidgets('NAS page shows the agent report: disks, volumes, alerts', (
    tester,
  ) async {
    final state = await boot(tester, server, size: const Size(1200, 900));
    await login(tester, state, server);
    await tester.tap(find.text('NAS'));
    await settle(tester);
    expectVisible(find.text('Media NAS · TS-464'));
    expectVisible(find.textContaining('2 alerts · reported'));
    expectVisible(find.text('Slot 2 · WD Red 8TB'));
    expectVisible(find.text('61 °C'));
    expectVisible(find.text('DataVol1'));
    expectVisible(find.textContaining('93.6% used'));
    expectVisible(find.text('vol DataVol1 usage'));

    await tester.tap(find.text('Refresh now'));
    await tester.pump();
    expectVisible(find.text('Waiting for agent…'));
    await settle(tester, 20);
    await tester.pump(const Duration(seconds: 3)); // the 2 s wait between polls
    await settle(tester, 20);
    expect(server.nasRefreshRequests, 1);
    expectVisible(find.text('✅ Fresh report received.'));
    await finish(tester, state);
  });

  testWidgets(
    'wide layout uses a rail with Plex; Plex screen lists libraries',
    (tester) async {
      final state = await boot(tester, server, size: const Size(1200, 800));
      await login(tester, state, server);
      expect(find.byType(NavigationRail), findsOneWidget);
      await tester.tap(find.text('Plex'));
      await settle(tester);
      expect(find.text('TV Shows'), findsOneWidget);
      expect(find.text('⏳ scanning…'), findsOneWidget);
      await tester.tap(find.text('Movies'));
      await settle(tester);
      expect(server.calls, contains('POST /api/plex/scan'));
      expect(find.textContaining('Plex is scanning'), findsOneWidget);
      await finish(tester, state);
    },
  );
}
