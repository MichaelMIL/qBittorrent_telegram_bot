// Shared plumbing for the widget tests: they drive the real app against
// `FakeServer`, an in-process HTTP server, so there is no DI seam to fake.
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:qbit_web/main.dart';
import 'package:qbit_web/state.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_server.dart';

/// Let real network calls (to the in-process fake server) complete, then
/// rebuild. Widget tests run under fake async, so I/O needs runAsync.
/// Each round trip needs real time (I/O) followed by a pump (microtasks
/// queued in the fake zone), so alternate the two a number of times.
Future<void> settle(WidgetTester tester, [int rounds = 12]) async {
  for (var i = 0; i < rounds; i++) {
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 40)),
    );
    await tester.pump();
  }
  await tester.pump(const Duration(milliseconds: 400));
}

Future<AppState> boot(
  WidgetTester tester,
  FakeServer server, {
  Size size = const Size(390, 844),
}) async {
  HttpOverrides.global = null; // flutter_test blocks HTTP by default
  SharedPreferences.setMockInitialValues({'baseUrl': server.url});
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final state = AppState();
  await tester.runAsync(state.init);
  await tester.pumpWidget(AppScope(state: state, child: const QbitApp()));
  await tester.pump();
  return state;
}

/// Tear the tree down, then the state (its poll timer would otherwise count
/// as a pending timer when the test ends).
Future<void> finish(WidgetTester tester, AppState state) async {
  await settle(tester); // let in-flight requests finish
  await tester.pumpWidget(const SizedBox());
  state.dispose(); // closes the HTTP client → no keep-alive timers
  await tester.pump(
    const Duration(minutes: 5),
  ); // flush whatever fake timers remain
}

Future<void> login(
  WidgetTester tester,
  AppState state,
  FakeServer server,
) async {
  expect(find.text('Connect'), findsOneWidget);
  await tester.enterText(find.byType(TextField).last, server.password);
  await tester.tap(find.text('Connect'));
  await settle(tester);
  expect(state.connected, isTrue);
}

/// Switch the shell to Search: the rail item on a wide window, the search
/// action in the Browse app bar on a phone (Search has no bottom-bar slot).
Future<void> openSearch(WidgetTester tester) async {
  final rail = find.text('Search');
  if (isVisible(rail)) {
    await tester.tap(rail);
  } else {
    await tester.tap(find.byTooltip('Search HeBits'));
  }
  await tester.pump();
}

/// Whether at least one widget matched by [finder] is actually shown.
///
/// The shell (and the browse screen's category tabs) keep every child mounted
/// inside an `IndexedStack`, which hides the unselected ones with an invisible
/// `Visibility` rather than unmounting them. `find.text` therefore matches
/// screens the user cannot see; these helpers assert what is on screen.
bool isVisible(Finder finder) {
  for (final element in finder.evaluate()) {
    var hidden = false;
    element.visitAncestorElements((ancestor) {
      final widget = ancestor.widget;
      if ((widget is Visibility && !widget.visible) ||
          (widget is Offstage && widget.offstage)) {
        hidden = true;
      }
      return !hidden;
    });
    if (!hidden) return true;
  }
  return false;
}

/// Expect [finder] to match something the user can actually see.
void expectVisible(Finder finder) {
  expect(finder, findsWidgets, reason: 'no match for $finder');
  expect(isVisible(finder), isTrue, reason: '$finder is mounted but hidden');
}

/// Expect [finder] to match nothing the user can see (it may stay mounted).
void expectNotVisible(Finder finder) {
  expect(isVisible(finder), isFalse, reason: '$finder is visible');
}
