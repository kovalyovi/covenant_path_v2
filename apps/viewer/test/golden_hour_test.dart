import 'package:flutter_test/flutter_test.dart';
import 'package:covenant_path_viewer/golden_hour.dart';

// Pure-logic tests for the Golden Hour milestones — the single source of truth the
// dashboard, detail page, and completion stats all read.
void main() {
  Map<String, dynamic> member({
    String friends = 'No', String calling = 'No', String hasMin = 'No',
    String givesMin = 'No', String baptism = '', String recommend = 'No',
    String patriarchal = 'No', String endowed = 'No', String aaronic = 'N/A',
    String melch = 'N/A', String sex = 'F',
  }) => {
        'friends': friends, 'calling': calling, 'ministering_brothers_sisters': hasMin,
        'ministering_assignment': givesMin, 'baptism_date': baptism, 'temple_recommend': recommend,
        'patriarchal_blessing': patriarchal, 'living_ordinance': endowed,
        'aaronic_priesthood': aaronic, 'melchizedek_priesthood': melch, 'sex': sex,
      };

  group('milestone predicates', () {
    test('friends Yes is complete, No is not', () {
      final f = milestones.firstWhere((m) => m.abbr == 'F');
      expect(f.complete(member(friends: 'Yes')), isTrue);
      expect(f.complete(member(friends: 'No')), isFalse);
    });

    test('baptism is NOT a Golden Hour milestone (integration only)', () {
      // A new member is already baptized; it doesn't measure integration.
      expect(milestones.any((m) => m.abbr == 'B'), isFalse);
      expect(milestones.any((m) => m.label == 'Baptized'), isFalse);
    });

    test('milestones are the integration set', () {
      expect(milestones.map((m) => m.abbr).toSet(), {'F', 'C', 'M', 'MA', 'AP', 'MP'});
    });
  });

  group('milestonesFor (demographic filtering)', () {
    test('priesthood chips only apply to males', () {
      final abbrsF = milestonesFor(member(sex: 'F')).map((m) => m.abbr).toSet();
      final abbrsM = milestonesFor(member(sex: 'M')).map((m) => m.abbr).toSet();
      expect(abbrsF.contains('AP'), isFalse);
      expect(abbrsF.contains('MP'), isFalse);
      expect(abbrsM.contains('AP'), isTrue);
      expect(abbrsM.contains('MP'), isTrue);
    });
  });

  test('a fully-integrated member completes all applicable milestones', () {
    final m = member(friends: 'Yes', calling: 'Yes', hasMin: 'Yes', givesMin: 'Yes',
        baptism: '1 Jan 2025', recommend: 'Active', patriarchal: 'Yes', endowed: 'Yes', sex: 'F');
    final applicable = milestonesFor(m);
    expect(applicable.where((x) => x.complete(m)).length, applicable.length);
  });
}
