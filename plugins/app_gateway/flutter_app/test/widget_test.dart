import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hermes_app/main.dart';

void main() {
  testWidgets('Hermes app boots to loading or login', (WidgetTester tester) async {
    await tester.pumpWidget(const HermesApp());
    await tester.pump();
    final isLoading = find.byType(CircularProgressIndicator).evaluate().isNotEmpty;
    final isLogin = find.text('获取验证码').evaluate().isNotEmpty;
    expect(isLoading || isLogin, isTrue);
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
