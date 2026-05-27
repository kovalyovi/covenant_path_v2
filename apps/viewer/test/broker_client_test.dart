import 'package:flutter_test/flutter_test.dart';
import 'package:covenant_path_viewer/broker_client.dart';

// Parsing logic only (no network): the broker's two response shapes must map correctly.
void main() {
  group('BrokerFactor.fromJson', () {
    test('uses label when present', () {
      final f = BrokerFactor.fromJson({'id': 'a1', 'label': 'Text •••1234', 'method': 'sms'});
      expect(f.id, 'a1');
      expect(f.label, 'Text •••1234');
      expect(f.method, 'sms');
    });

    test('falls back to method then a default for the label', () {
      expect(BrokerFactor.fromJson({'id': 'a2', 'method': 'email'}).label, 'email');
      expect(BrokerFactor.fromJson({'id': 'a3'}).label, 'Code');
    });
  });

  group('BrokerResult.mfaRequired', () {
    test('true when a login_id is present without an otp', () {
      final r = BrokerResult(loginId: 'L1', factors: [BrokerFactor('a', 'Email', 'email')]);
      expect(r.mfaRequired, isTrue);
      expect(r.factors.length, 1);
    });

    test('false once a session (email+otp) is present', () {
      final r = BrokerResult(email: 'a@b.com', otp: '12345678');
      expect(r.mfaRequired, isFalse);
    });
  });
}
