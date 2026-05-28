import 'package:flutter_test/flutter_test.dart';
import 'package:covenant_path_viewer/dashboard_page.dart';

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

  test('fmtDate is human-readable', () {
    expect(fmtDate(DateTime(2026, 2, 6)), '6 Feb 2026');
  });
}
