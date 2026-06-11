import 'package:flutter/services.dart';

/// Keep only digits, optionally stripping a leading ``86`` country code.
String phoneDigitsOnly(String input) {
  var digits = input.replaceAll(RegExp(r'\D'), '');
  if (digits.startsWith('86') && digits.length > 11) {
    digits = digits.substring(2);
  }
  if (digits.length > 11) {
    digits = digits.substring(0, 11);
  }
  return digits;
}

/// ``true`` when input is a valid mainland China mobile (11 digits, starts with 1).
bool isValidCnMobile(String input) {
  final d = phoneDigitsOnly(input);
  return d.length == 11 && d.startsWith('1');
}

/// Normalized 11-digit local mobile for API, or ``null`` if invalid.
String? normalizePhoneForApi(String input) {
  if (!isValidCnMobile(input)) return null;
  return phoneDigitsOnly(input);
}

/// Plain digit-only input — no auto-spacing (avoids Flutter Web duplicate keystrokes).
class CnPhoneInputFormatter extends TextInputFormatter {
  const CnPhoneInputFormatter();

  @override
  TextEditingValue formatEditUpdate(
    TextEditingValue oldValue,
    TextEditingValue newValue,
  ) {
    final digits = phoneDigitsOnly(newValue.text);
    if (digits == newValue.text) {
      return newValue;
    }
    final offset = newValue.selection.end.clamp(0, digits.length);
    return TextEditingValue(
      text: digits,
      selection: TextSelection.collapsed(offset: offset),
      composing: TextRange.empty,
    );
  }
}
