// Unit tests for BrowsePage, the browse feed's model: the one part of the
// feature that needs no widgets and no server.
import 'package:flutter_test/flutter_test.dart';
import 'package:qbit_web/models.dart';

Map<String, dynamic> group() => {
  'gid': '1234',
  'name_en': 'Fauda',
  'name_he': 'פאודה',
  'year': '2015',
  'cover': 'https://example.com/fauda.jpg',
  'cat': '📺 TV',
  'favorite': true,
  'auto': false,
  'default': null,
  'torrents': [
    {
      'id': 1,
      'title': 'Fauda.S05E11.1080p.WEB.H264-NTb',
      'resolution': '1080p',
      'size': 2040109465,
      'seeders': 437,
      'free': true,
      'snatched': false,
      'local': {'status': 'done', 'progress': 1.0},
      'episode': 'S05E11',
      'season': 5,
    },
  ],
};

void main() {
  test('parses a page of the newest-uploads feed', () {
    final page = BrowsePage.fromJson({
      'cat': 'series',
      'page': 2,
      'pages': 7,
      'groups': [group()],
    });

    expect(page.cat, 'series');
    expect(page.page, 2);
    expect(page.pages, 7);
    expect(page.current, 2);
    expect(page.pageCount, 7);
    expect(page.hasMore, isTrue);

    final g = page.groups.single;
    expect(g.gid, '1234');
    expect(g.titleWithYear, 'Fauda (2015)');
    expect(g.favorite, isTrue);
    expect(g.anyFree, isTrue);
    expect(g.anySnatched, isFalse);
    expect(g.bestLocal?.mark, '✅');
    expect(g.isSeries, isTrue);
    expect(g.torrents.single.title, 'Fauda.S05E11.1080p.WEB.H264-NTb');
  });

  test('an empty payload degrades instead of throwing', () {
    final page = BrowsePage.fromJson({});

    expect(page.cat, '');
    expect(page.page, 0);
    expect(page.current, 1); // never below page 1
    expect(page.pageCount, 1); // never below the page we are on
    expect(page.hasMore, isFalse);
    expect(page.groups, isEmpty);
  });

  test('pageCount never drops below the page we are on', () {
    final page = BrowsePage.fromJson({'page': 5, 'pages': 2});

    expect(page.current, 5);
    expect(page.pageCount, 5);
    expect(page.hasMore, isFalse);
  });

  test('the last page has nothing more to load', () {
    final page = BrowsePage.fromJson({'page': 3, 'pages': 3});

    expect(page.hasMore, isFalse);
    expect(BrowsePage.fromJson({'page': 2, 'pages': 3}).hasMore, isTrue);
  });

  test('junk entries in groups are dropped, not fatal', () {
    final page = BrowsePage.fromJson({
      'cat': 'movies',
      'page': 1,
      'pages': 1,
      'groups': ['nope', 42, group()],
    });

    expect(page.groups, hasLength(1));
    expect(page.groups.single.title, 'Fauda');
  });
}
