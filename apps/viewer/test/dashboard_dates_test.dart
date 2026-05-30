import 'package:flutter_test/flutter_test.dart';
import 'package:covenant_path_viewer/dashboard_page.dart';
import 'package:covenant_path_viewer/golden_hour.dart';

// The On Date / Golden Hour tabs group + filter by baptism date, so date parsing across
// LCR's several string formats is the part most likely to silently misbehave.
void main() {
  group('parseMemberDate', () {
    test('parses "6 Feb 2026" and "06 Feb 2026"', () {
      expect(parseMemberDate('6 Feb 2026'), DateTime(2026, 2, 6));
      expect(parseMemberDate('06 Feb 2026'), DateTime(2026, 2, 6));
    });
    test('parses ISO and MM/dd/yy', () {
      expect(parseMemberDate('2026-02-06'), DateTime(2026, 2, 6));
      expect(parseMemberDate('02/06/26'), DateTime(2026, 2, 6));
    });
    test('returns null for blanks and sentinels', () {
      expect(parseMemberDate(null), isNull);
      expect(parseMemberDate(''), isNull);
      expect(parseMemberDate('N/A'), isNull);
      expect(parseMemberDate('needs-profile-api'), isNull);
    });
  });

  test('fmtLong is a full human-readable date', () {
    expect(fmtLong(DateTime(2026, 2, 6)), 'Friday, February 6, 2026');
    expect(fmtLong(null), '');
  });

  // Baptism tenure label shown next to the date ("February 6, 2026 (2 months 3 days)").
  group('monthsDaysAgo', () {
    test('null and future dates return empty', () {
      expect(monthsDaysAgo(null), '');
      expect(monthsDaysAgo(DateTime.now().add(const Duration(days: 10))), '');
    });
    test('recent dates read in days', () {
      final r = monthsDaysAgo(DateTime.now().subtract(const Duration(days: 3)));
      expect(r, contains('day'));
      expect(r, isNot(contains('month')));
    });
    test('older dates include months, with correct pluralization', () {
      expect(monthsDaysAgo(DateTime.now().subtract(const Duration(days: 75))), contains('month'));
      // exactly today reads "0 days" (never empty/negative)
      expect(monthsDaysAgo(DateTime.now()), contains('day'));
    });
  });
}
