// Widget tests for the "🆕 New on HeBits" browse feed: lazy first load,
// paging (including the stale-response guard), refresh, per-category and
// per-tab state, error/empty states and the tile → detail round trip.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:qbit_web/screens/browse_screen.dart';
import 'package:qbit_web/state.dart';

import 'fake_server.dart';
import 'harness.dart';

/// Scope a finder to the browse screen: every other screen stays mounted in
/// the shell's IndexedStack, and several of them also own a 'Reload' button,
/// a '⭐' or an EmptyView.
Finder inBrowse(Finder finder) =>
    find.descendant(of: find.byType(BrowseScreen), matching: finder);

Finder get prevPage =>
    inBrowse(find.widgetWithIcon(IconButton, Icons.chevron_left));
Finder get nextPage =>
    inBrowse(find.widgetWithIcon(IconButton, Icons.chevron_right));
Finder get reload => inBrowse(find.byTooltip('Reload'));

bool enabled(WidgetTester tester, Finder button) =>
    tester.widget<IconButton>(button).onPressed != null;

/// Boot and log in: Browse is the home screen on every width, so it is on
/// screen — and loading — as soon as the shell appears.
Future<AppState> openBrowse(
  WidgetTester tester,
  FakeServer server, {
  Size size = const Size(1200, 800),
}) async {
  final state = await boot(tester, server, size: size);
  await login(tester, state, server);
  await settle(tester);
  return state;
}

/// Go to the next page and wait for it.
Future<void> tapNext(WidgetTester tester) async {
  await tester.tap(nextPage);
  await settle(tester);
}

void main() {
  late FakeServer server;

  setUp(() async {
    server = FakeServer();
    await server.start();
  });
  tearDown(() => server.stop());

  testWidgets('browse is home: it loads once and other tabs leave it alone', (
    tester,
  ) async {
    final state = await boot(tester, server);
    await login(tester, state, server);
    expectVisible(inBrowse(find.text('🆕 New on HeBits')));
    expect(find.text('Search'), findsNothing); // no slot in the phone bar
    await settle(tester); // first fetch fires once the shell is on screen
    expect(server.browseCalls, ['series/1']);
    expectVisible(inBrowse(find.text('Series Top 1 (2015)')));
    expectVisible(inBrowse(find.text('Series Pick 1 (2025)')));
    expectVisible(inBrowse(find.text('Series')));
    expectVisible(inBrowse(find.text('Movies')));

    await tester.tap(find.text('Library'));
    await settle(tester);
    expectNotVisible(find.text('🆕 New on HeBits'));
    expect(server.browseCalls, ['series/1']); // no refetch on leaving

    await finish(tester, state);
  });

  testWidgets('the rail shows browse first and keeps its content', (
    tester,
  ) async {
    final state = await boot(tester, server, size: const Size(1200, 800));
    await login(tester, state, server);
    await settle(tester);
    expect(server.browseCalls, ['series/1']);
    expectVisible(inBrowse(find.text('Series Top 1 (2015)')));

    await tester.tap(find.text('Search'));
    await tester.pump();
    expectVisible(find.text('Search HeBits…'));
    await tester.tap(find.text('Browse'));
    await tester.pump();
    expectVisible(inBrowse(find.text('Series Top 1 (2015)')));
    expect(server.browseCalls, ['series/1']);

    await finish(tester, state);
  });

  testWidgets('browse and search reach each other on a phone', (tester) async {
    final state = await boot(tester, server);
    await login(tester, state, server);
    await settle(tester);
    expectVisible(inBrowse(find.text('🆕 New on HeBits')));

    await tester.tap(find.byTooltip('Search HeBits'));
    await tester.pump();
    expectVisible(find.text('Search HeBits…'));
    expectNotVisible(find.text('🆕 New on HeBits'));

    await tester.tap(find.byTooltip('New on HeBits'));
    await tester.pump();
    expectVisible(inBrowse(find.text('🆕 New on HeBits')));
    expectVisible(inBrowse(find.text('Series Top 1 (2015)')));

    await finish(tester, state);
  });

  testWidgets('genre filter: pick Comedy, page resets, title shows it, clear', (
    tester,
  ) async {
    final state = await openBrowse(tester, server);
    expect(server.browseGenres, ['']);

    await tester.tap(find.byTooltip('Filter by genre'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400)); // sheet animation
    expectVisible(find.text('All genres'));
    await tester.tap(find.text('Comedy'));
    await settle(tester);
    expect(server.browseGenres.last, 'קומדיה');
    expect(server.browseCalls.last, 'series/1');
    expectVisible(inBrowse(find.text('🆕 Comedy')));

    await tester.tap(find.byTooltip('Filter by genre'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    await tester.tap(find.text('All genres'));
    await settle(tester);
    expect(server.browseGenres.last, '');
    expectVisible(inBrowse(find.text('🆕 New on HeBits')));

    await finish(tester, state);
  });

  testWidgets('tiles show the favorite, freeleech, snatched and local marks', (
    tester,
  ) async {
    final state = await openBrowse(tester, server);

    expectVisible(inBrowse(find.text('⭐'))); // favorite, not auto-added
    expect(inBrowse(find.text('⭐')), findsOneWidget);
    expect(inBrowse(find.text('🆓')), findsOneWidget); // freeleech release
    expect(inBrowse(find.text('✔️')), findsOneWidget); // snatched on HeBits
    expect(inBrowse(find.text('✅')), findsOneWidget); // downloaded locally
    expect(inBrowse(find.text('⏬42%')), findsOneWidget); // downloading now
    expect(inBrowse(find.text('📺 TV')), findsOneWidget); // category pill
    // the summary line of a multi-release group and of a single-release one
    expect(
      inBrowse(find.text('4 releases (1080p/720p) · 🌱 707')),
      findsOneWidget,
    );
    expect(inBrowse(find.text('1080p · 1.9 GiB · 🌱 9')), findsOneWidget);

    await finish(tester, state);
  });

  testWidgets('the pager walks pages and disables both ends', (tester) async {
    final state = await openBrowse(tester, server);
    expectVisible(inBrowse(find.text('1 / 3')));
    expect(enabled(tester, prevPage), isFalse); // nothing before page 1
    expect(enabled(tester, nextPage), isTrue);

    await tapNext(tester);
    expect(server.browseCalls, ['series/1', 'series/2']);
    expectVisible(inBrowse(find.text('2 / 3')));
    expectVisible(inBrowse(find.text('Series Top 2 (2015)')));
    expect(inBrowse(find.text('Series Top 1 (2015)')), findsNothing);
    expect(enabled(tester, prevPage), isTrue);

    await tapNext(tester);
    expectVisible(inBrowse(find.text('3 / 3')));
    expectVisible(inBrowse(find.text('Series Top 3 (2015)')));
    expect(enabled(tester, nextPage), isFalse); // last page

    await tester.tap(prevPage);
    await settle(tester);
    expect(server.browseCalls, [
      'series/1',
      'series/2',
      'series/3',
      'series/2',
    ]);
    expectVisible(inBrowse(find.text('2 / 3')));

    await finish(tester, state);
  });

  testWidgets('a superseded page response is dropped', (tester) async {
    // page 2 crawls, page 3 is instant → the responses arrive out of order
    server.browseDelay['series/2'] = const Duration(milliseconds: 600);
    final state = await openBrowse(tester, server);

    await tester.tap(nextPage); // asks for page 2
    await tester.pump();
    // the pager tracks the requested page, not the loaded one
    expectVisible(inBrowse(find.text('2 / 3')));
    await tester.tap(nextPage); // asks for page 3 before 2 lands
    await settle(tester, 40);

    expect(server.browseCalls, ['series/1', 'series/2', 'series/3']);
    expectVisible(inBrowse(find.text('3 / 3')));
    expectVisible(inBrowse(find.text('Series Top 3 (2015)')));
    expect(inBrowse(find.text('Series Top 2 (2015)')), findsNothing);
    expect(inBrowse(find.text('Series Top 1 (2015)')), findsNothing);

    await finish(tester, state);
  });

  testWidgets('reload refetches the page being viewed, grid stays put', (
    tester,
  ) async {
    final state = await openBrowse(tester, server);
    await tapNext(tester);
    expect(server.browseCalls, ['series/1', 'series/2']);

    await tester.tap(reload);
    await tester.pump();
    // the grid keeps rendering; only the app bar shows the spinner
    expectVisible(inBrowse(find.text('Series Top 2 (2015)')));
    expect(inBrowse(find.byType(CircularProgressIndicator)), findsOneWidget);
    await settle(tester);

    expect(server.browseCalls, ['series/1', 'series/2', 'series/2']);
    expect(server.browseCalls.last, 'series/2'); // not back to page 1
    expectVisible(inBrowse(find.text('2 / 3')));
    expectVisible(inBrowse(find.text('Series Top 2 (2015)')));

    await finish(tester, state);
  });

  testWidgets('pull to refresh reloads the page being viewed', (tester) async {
    final state = await openBrowse(tester, server);
    await tapNext(tester);

    final grid = tester.getCenter(inBrowse(find.byType(GridView)));
    final drag = await tester.startGesture(grid);
    for (var i = 0; i < 8; i++) {
      await drag.moveBy(const Offset(0, 50));
      await tester.pump();
    }
    await drag.up();
    // the indicator has to animate into place before it calls onRefresh, and
    // settle() only pumps zero-duration frames between its I/O windows
    await tester.pump(const Duration(milliseconds: 100));
    await tester.pump(const Duration(seconds: 1));
    await settle(tester, 20);

    expect(server.browseCalls, ['series/1', 'series/2', 'series/2']);
    expectVisible(inBrowse(find.text('Series Top 2 (2015)')));
    expectVisible(inBrowse(find.text('2 / 3')));

    await finish(tester, state);
  });

  testWidgets('a failed page shows the server detail and retries the same '
      'page', (tester) async {
    final state = await openBrowse(tester, server);
    await tapNext(tester);

    server.browseStatus = 502;
    await tester.tap(reload);
    await settle(tester);
    expectVisible(inBrowse(find.text(server.browseDetail)));
    expect(inBrowse(find.text('Series Top 2 (2015)')), findsNothing);
    expect(inBrowse(find.text('Retry')), findsOneWidget);

    await tester.tap(inBrowse(find.text('Retry')));
    await settle(tester);
    expect(server.browseCalls, [
      'series/1',
      'series/2',
      'series/2',
      'series/2', // retry reuses cat + page
    ]);
    expectVisible(inBrowse(find.text(server.browseDetail)));

    server.browseStatus = 200;
    await tester.tap(inBrowse(find.text('Retry')));
    await settle(tester);
    expect(server.browseCalls.last, 'series/2');
    expectVisible(inBrowse(find.text('Series Top 2 (2015)')));
    expect(inBrowse(find.text(server.browseDetail)), findsNothing);

    await finish(tester, state);
  });

  testWidgets('an empty page offers a reload', (tester) async {
    server.browseEmpty = true;
    final state = await openBrowse(tester, server);

    expectVisible(inBrowse(find.text('HeBits had nothing new on page 1.')));
    expect(inBrowse(find.text('Reload')), findsOneWidget);
    expect(inBrowse(find.text('Retry')), findsNothing);

    server.browseEmpty = false;
    await tester.tap(inBrowse(find.text('Reload')));
    await settle(tester);
    expect(server.browseCalls, ['series/1', 'series/1']);
    expectVisible(inBrowse(find.text('Series Top 1 (2015)')));

    await finish(tester, state);
  });

  testWidgets('a group with no releases is skipped, not rendered', (
    tester,
  ) async {
    server.browseGhost = true;
    final state = await openBrowse(tester, server);

    expect(inBrowse(find.text('Series Ghost 1 (2025)')), findsNothing);
    expectVisible(inBrowse(find.text('Series Top 1 (2015)')));
    expectVisible(inBrowse(find.text('Series Pick 1 (2025)')));
    expect(tester.takeException(), isNull);

    await finish(tester, state);
  });

  testWidgets('each category keeps its own page and groups', (tester) async {
    final state = await openBrowse(tester, server);
    await tapNext(tester); // series is on page 2

    await tester.tap(inBrowse(find.text('Movies')));
    await settle(tester);
    expect(server.browseCalls, ['series/1', 'series/2', 'movies/1']);
    expectVisible(inBrowse(find.text('Movies Top 1 (2015)')));
    expectVisible(inBrowse(find.text('1 / 3')));
    expectNotVisible(find.text('Series Top 2 (2015)'));
    // the series grid is only hidden — its page and groups are still there
    expect(
      find.text('Series Top 2 (2015)', skipOffstage: false),
      findsOneWidget,
    );

    await tester.tap(inBrowse(find.text('Series')));
    await settle(tester);
    expect(server.browseCalls, [
      'series/1',
      'series/2',
      'movies/1',
    ]); // no refetch
    expectVisible(inBrowse(find.text('Series Top 2 (2015)')));
    expectVisible(inBrowse(find.text('2 / 3')));
    expectNotVisible(find.text('Movies Top 1 (2015)'));
    expect(
      find.text('Movies Top 1 (2015)', skipOffstage: false),
      findsOneWidget,
    );

    await finish(tester, state);
  });

  testWidgets('leaving and re-entering the tab keeps the feed', (tester) async {
    final state = await openBrowse(tester, server);
    await tapNext(tester);

    await tester.tap(find.text('Library'));
    await settle(tester);
    expectNotVisible(find.text('Series Top 2 (2015)'));
    // still mounted with its page-2 groups, just not on screen
    expect(
      find.text('Series Top 2 (2015)', skipOffstage: false),
      findsOneWidget,
    );

    await tester.tap(find.text('Browse'));
    await settle(tester);
    expect(server.browseCalls, ['series/1', 'series/2']); // no refetch
    expectVisible(inBrowse(find.text('Series Top 2 (2015)')));
    expectVisible(inBrowse(find.text('2 / 3')));

    await finish(tester, state);
  });

  testWidgets('a tile opens the group screen and the grid picks up the '
      'favorite', (tester) async {
    final state = await openBrowse(tester, server);
    expect(inBrowse(find.text('⭐')), findsOneWidget); // only the "Top" group

    await tester.tap(inBrowse(find.text('Series Pick 1 (2025)')));
    await settle(tester);
    expect(find.text('Series Pick 1'), findsOneWidget); // detail app bar
    expect(find.text('Series.Pick.1.1080p.WEB.H264-NTb'), findsOneWidget);

    await tester.tap(find.text('Add to favorites'));
    await settle(tester);
    expect(server.favAdded, ['pick-series-1']);
    expect(find.text('Favorite'), findsOneWidget);

    await tester.pageBack();
    await settle(tester);
    expectVisible(inBrowse(find.text('Series Top 1 (2015)')));
    expect(server.browseCalls, ['series/1']); // popping does not refetch
    expect(inBrowse(find.text('⭐')), findsNWidgets(2)); // marker repainted

    await finish(tester, state);
  });

  for (final size in const [Size(390, 844), Size(1200, 800)]) {
    final label = '${size.width.toInt()}x${size.height.toInt()}';
    testWidgets('every state lays out at $label without overflow', (
      tester,
    ) async {
      server.browseEmpty = true;
      final state = await openBrowse(tester, server, size: size);
      expectVisible(inBrowse(find.text('HeBits had nothing new on page 1.')));
      expect(tester.takeException(), isNull);

      server
        ..browseEmpty = false
        ..browseStatus = 502;
      await tester.tap(inBrowse(find.text('Reload')));
      await settle(tester);
      expectVisible(inBrowse(find.text(server.browseDetail)));
      expect(tester.takeException(), isNull);

      server.browseStatus = 200;
      await tester.tap(inBrowse(find.text('Retry')));
      await settle(tester);
      expectVisible(inBrowse(find.text('Series Top 1 (2015)')));
      await tapNext(tester);
      expectVisible(inBrowse(find.text('Series Top 2 (2015)')));
      expect(tester.takeException(), isNull);

      await finish(tester, state);
    });
  }
}
