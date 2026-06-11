import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hermes_app/utils/phone_input.dart';

void main() {
  test('phoneDigitsOnly strips non-digits and caps length', () {
    expect(phoneDigitsOnly('138 0013-9999'), '13800139999');
    expect(phoneDigitsOnly('8613800139999'), '13800139999');
    expect(phoneDigitsOnly('138001399991234'), '13800139999');
  });

  test('normalizePhoneForApi validates CN mobile', () {
    expect(normalizePhoneForApi('13800139999'), '13800139999');
    expect(normalizePhoneForApi('8613800139999'), '13800139999');
    expect(normalizePhoneForApi('12345'), isNull);
    expect(normalizePhoneForApi('23800139999'), isNull);
  });

  test('CnPhoneInputFormatter keeps digits only without duplicating', () {
    const formatter = CnPhoneInputFormatter();
    var value = const TextEditingValue(text: '');

    for (final digit in '13800139999'.split('')) {
      final start = value.selection.start;
      final nextText = value.text + digit;
      value = formatter.formatEditUpdate(
        value,
        TextEditingValue(
          text: nextText,
          selection: TextSelection.collapsed(offset: start + 1),
        ),
      );
    }

    expect(value.text, '13800139999');
  });

  test('CnPhoneInputFormatter ignores extra digits beyond 11', () {
    const formatter = CnPhoneInputFormatter();
    const old = TextEditingValue(
      text: '13800139999',
      selection: TextSelection.collapsed(offset: 11),
    );
    final value = formatter.formatEditUpdate(
      old,
      const TextEditingValue(
        text: '138001399991',
        selection: TextSelection.collapsed(offset: 12),
      ),
    );
    expect(value.text, '13800139999');
  });
}
