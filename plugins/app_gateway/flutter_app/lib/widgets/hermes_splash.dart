import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../theme/hermes_theme.dart';
import 'hermes_logo.dart';
import 'hermes_shell.dart';

/// 启动页：bootstrap 完成后淡出，露出主界面。
class HermesSplashGate extends StatefulWidget {
  const HermesSplashGate({
    super.key,
    required this.ready,
    required this.child,
  });

  final bool ready;
  final Widget child;

  @override
  State<HermesSplashGate> createState() => _HermesSplashGateState();
}

class _HermesSplashGateState extends State<HermesSplashGate>
    with SingleTickerProviderStateMixin {
  late final AnimationController _exit;
  late final Animation<double> _fade;
  bool _dismissed = false;

  @override
  void initState() {
    super.initState();
    _exit = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 650),
    );
    _fade = CurvedAnimation(parent: _exit, curve: Curves.easeInOut);
  }

  @override
  void didUpdateWidget(HermesSplashGate oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.ready && !oldWidget.ready && !_dismissed) {
      _exit.forward().then((_) {
        if (mounted) setState(() => _dismissed = true);
      });
    }
  }

  @override
  void dispose() {
    _exit.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Stack(
      fit: StackFit.expand,
      children: [
        widget.child,
        if (!_dismissed)
          FadeTransition(
            opacity: Tween<double>(begin: 1, end: 0).animate(_fade),
            child: IgnorePointer(
              ignoring: _exit.isAnimating || _exit.isCompleted,
              child: const _HermesSplashView(),
            ),
          ),
      ],
    );
  }
}

class _HermesSplashView extends StatelessWidget {
  const _HermesSplashView();

  @override
  Widget build(BuildContext context) {
    return HermesAmbientBackground(
      animate: true,
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const HermesLogoMark(size: 88, pulse: true),
            const SizedBox(height: 28),
            ShaderMask(
              shaderCallback: (b) => HermesTheme.goldGradient.createShader(b),
              child: Text(
                'HERMES',
                style: GoogleFonts.cormorantGaramond(
                  fontSize: 42,
                  fontWeight: FontWeight.w600,
                  letterSpacing: 8,
                  color: Colors.white,
                ),
              ),
            ),
            const SizedBox(height: 12),
            Text(
              '私人 AI 助理',
              style: GoogleFonts.jost(
                color: HermesColors.muted,
                fontSize: 14,
                letterSpacing: 2,
              ),
            ),
            const SizedBox(height: 40),
            SizedBox(
              width: 120,
              child: LinearProgressIndicator(
                minHeight: 2,
                borderRadius: BorderRadius.circular(2),
                backgroundColor: HermesColors.glassBorder,
                color: HermesColors.gold,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
