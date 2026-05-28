import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:covenant_path_viewer/person_detail_page.dart';

// Renders the LCR-style detail page from a `details` fixture and verifies the
// sections show up; also checks the pre-`details` flat fallback still renders.
void main() {
  Map<String, dynamic> withDetails() => {
        'name': 'Traxton Millner',
        'sex': 'M',
        'friends': 'Yes',
        'calling': 'No',
        'details': {
          'memberSince': 'Member for 3 months',
          'sacramentMissed': '2',
          'sacrament': [
            {'label': '26 Apr', 'attended': true},
            {'label': '03 May', 'attended': false},
          ],
          'friends': [
            {'name': 'Clayton Adam Blater', 'unit': 'Bond Park Ward', 'inStake': true},
          ],
          'priesthoodOrdinations': ['Eligible to receive Aaronic Priesthood - 1 Jan 2028'],
          'callings': [],
          'ministeringBrothers': ['Pinard, Jean-Pierre'],
          'ministeringSisters': [],
          'ministeringAssignments': [],
          'templeOrdinances': ['Not yet endowed'],
          'templeExperiences': [
            {'name': 'Prepare a Family Name for the Temple', 'done': false},
          ],
          'lessons': [
            {
              'name': 'Heavenly Father\'s Plan of Salvation',
              'taught': '7 of 7',
              'principles': [
                {'name': 'A', 'memberPresent': true, 'taughtLevel': '30'},
                {'name': 'B', 'memberPresent': false, 'taughtLevel': null},
              ],
            },
          ],
          'selfReliance': [
            {'name': 'Emotional Resilience', 'done': false},
          ],
          'tags': ['Needs a call or visit from a member'],
        },
      };

  Future<void> pump(WidgetTester t, Map<String, dynamic> m) async {
    await t.binding.setSurfaceSize(const Size(1200, 2400)); // wide -> two columns
    await t.pumpWidget(MaterialApp(home: PersonDetailPage(member: m)));
    await t.pumpAndSettle();
  }

  testWidgets('rich detail renders all sections', (t) async {
    await pump(t, withDetails());
    expect(find.text('Traxton Millner'), findsWidgets); // appbar + header
    expect(find.text('Member for 3 months'), findsOneWidget);
    expect(find.text('Attended Sacrament Meeting'), findsOneWidget);
    expect(find.text('2 sacrament meetings missed'), findsOneWidget);
    expect(find.text('Friends in the Church'), findsOneWidget);
    expect(find.text('Clayton Adam Blater'), findsOneWidget);
    expect(find.text('Not yet been given a calling.'), findsOneWidget);
    expect(find.text('Ministering Brothers & Sisters'), findsOneWidget);
    expect(find.text('Pinard, Jean-Pierre'), findsOneWidget);
    expect(find.text('Temple Ordinances and Experiences'), findsOneWidget);
    expect(find.text('Prepare a Family Name for the Temple'), findsOneWidget);
    expect(find.text('Principles Taught'), findsOneWidget);
    expect(find.text('Self-Reliance Classes Completed'), findsOneWidget);
    expect(find.text('Emotional Resilience'), findsOneWidget);
    expect(find.text('Needs a call or visit from a member'), findsOneWidget);
  });

  testWidgets('falls back to flat fields when details is null', (t) async {
    await pump(t, {
      'name': 'No Details',
      'unit_name': 'Bond Park Ward',
      'baptism_date': '1 Jan 2025',
      'calling': 'Yes',
    });
    expect(find.text('No Details'), findsWidgets); // appbar + header
    expect(find.text('Baptism date'), findsOneWidget);
    // no rich section headers when there's no details blob
    expect(find.text('Attended Sacrament Meeting'), findsNothing);
  });
}
