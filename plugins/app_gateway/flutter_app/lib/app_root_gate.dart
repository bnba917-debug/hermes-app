import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'screens/home_shell.dart';
import 'screens/login_screen.dart';
import 'state/app_state.dart';
import 'widgets/hermes_splash.dart';

enum RootDestination { login, home }

RootDestination resolveRootDestination({
  required bool isLoggedIn,
  required bool readyForChat,
}) {
  return isLoggedIn ? RootDestination.home : RootDestination.login;
}

/// After auth succeeds, return to [HermesRootGate] so logged-in UI can render.
///
/// Logout previously used `pushReplacementNamed('/login')`, which replaced
/// [HermesRootGate] with a standalone login route. In that stack `popUntil`
/// cannot reach the root gate, so login API success still leaves the user on
/// the login page until a full refresh.
void navigateToRootAfterLogin(BuildContext context) {
  final routeName = ModalRoute.of(context)?.settings.name;
  if (routeName == '/login') {
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => const HermesRootGate()),
    );
  }
}

class HermesRootGate extends StatelessWidget {
  const HermesRootGate({super.key});

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();

    return HermesSplashGate(
      ready: !state.loading,
      child: AnimatedSwitcher(
        duration: const Duration(milliseconds: 400),
        switchInCurve: Curves.easeOutCubic,
        switchOutCurve: Curves.easeInCubic,
        child: _routeForState(state),
      ),
    );
  }

  Widget _routeForState(AppState state) {
    switch (resolveRootDestination(
      isLoggedIn: state.config.isLoggedIn,
      readyForChat: state.readyForChat,
    )) {
      case RootDestination.login:
        return const LoginScreen(key: ValueKey('login'));
      case RootDestination.home:
        return const HomeShell(key: ValueKey('home'));
    }
  }
}
