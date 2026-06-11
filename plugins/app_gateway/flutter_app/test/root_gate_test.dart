import 'package:flutter_test/flutter_test.dart';
import 'package:hermes_app/app_root_gate.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:hermes_app/services/settings_store.dart';
import 'package:hermes_app/state/app_state.dart';

void main() {
  test('logged-in users land on home even before model onboarding', () {
    expect(
      resolveRootDestination(isLoggedIn: true, readyForChat: false),
      RootDestination.home,
    );
  });

  testWidgets('login success replaces standalone /login route with root gate', (tester) async {
    final navKey = GlobalKey<NavigatorState>();
    final state = AppState(SettingsStore())..loading = false;
    await tester.pumpWidget(
      ChangeNotifierProvider.value(
        value: state,
        child: MaterialApp(
          navigatorKey: navKey,
          home: const HermesRootGate(),
          routes: {
            '/login': (_) => const Scaffold(body: Text('login')),
          },
        ),
      ),
    );

    navKey.currentState!.pushReplacementNamed('/login');
    await tester.pumpAndSettle();
    expect(find.text('login'), findsOneWidget);
    expect(find.byType(HermesRootGate), findsNothing);

    navigateToRootAfterLogin(tester.element(find.text('login')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));

    expect(find.byType(HermesRootGate), findsOneWidget);
    expect(find.text('login'), findsNothing);
  });
}
