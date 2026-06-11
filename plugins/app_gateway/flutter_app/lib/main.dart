import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import 'app_root_gate.dart';
import 'screens/login_screen.dart';
import 'screens/onboarding_screen.dart';
import 'services/settings_store.dart';
import 'state/app_state.dart';
import 'theme/hermes_palette.dart';
import 'theme/hermes_theme.dart';
import 'widgets/hermes_motion.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const HermesApp());
}

class HermesApp extends StatelessWidget {
  const HermesApp({super.key});

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
      create: (_) => AppState(SettingsStore())..bootstrap(),
      child: const _HermesAppView(),
    );
  }
}

class _HermesAppView extends StatelessWidget {
  const _HermesAppView();

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    final themeMode = state.themeMode.themeMode;
    final isDark = themeMode == ThemeMode.dark ||
        (themeMode == ThemeMode.system &&
            WidgetsBinding.instance.platformDispatcher.platformBrightness ==
                Brightness.dark);

    SystemChrome.setSystemUIOverlayStyle(
      SystemUiOverlayStyle(
        statusBarColor: Colors.transparent,
        statusBarIconBrightness: isDark ? Brightness.light : Brightness.dark,
        systemNavigationBarColor:
            isDark ? HermesColors.obsidian : HermesPalette.light.background,
        systemNavigationBarIconBrightness:
            isDark ? Brightness.light : Brightness.dark,
      ),
    );

    return MaterialApp(
      title: 'Hermes',
      debugShowCheckedModeBanner: false,
      theme: HermesTheme.light(),
      darkTheme: HermesTheme.dark(),
      themeMode: themeMode,
      onGenerateRoute: (settings) {
        switch (settings.name) {
          case '/login':
            return hermesFadeRoute(const LoginScreen());
          case '/onboarding':
            return hermesFadeRoute(const OnboardingScreen());
          default:
            return null;
        }
      },
      home: const HermesRootGate(),
    );
  }
}
