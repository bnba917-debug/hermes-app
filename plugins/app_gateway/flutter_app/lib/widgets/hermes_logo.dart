import 'package:flutter/material.dart';

import '../theme/hermes_theme.dart';

class HermesLogoMark extends StatelessWidget {
  const HermesLogoMark({
    super.key,
    this.size = 48,
    this.pulse = false,
  });

  final double size;
  final bool pulse;

  @override
  Widget build(BuildContext context) {
    final core = Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: HermesTheme.goldGradient,
        boxShadow: [
          BoxShadow(
            color: HermesColors.gold.withValues(alpha: pulse ? 0.55 : 0.4),
            blurRadius: pulse ? 36 : 24,
            spreadRadius: pulse ? 6 : 2,
          ),
        ],
      ),
      child: Icon(
        Icons.auto_awesome,
        color: HermesColors.obsidian,
        size: size * 0.48,
      ),
    );
    if (!pulse) return core;
    return _PulsingLogo(size: size, child: core);
  }
}

class _PulsingLogo extends StatefulWidget {
  const _PulsingLogo({required this.child, required this.size});

  final Widget child;
  final double size;

  @override
  State<_PulsingLogo> createState() => _PulsingLogoState();
}

class _PulsingLogoState extends State<_PulsingLogo>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c;

  @override
  void initState() {
    super.initState();
    _c = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 2200),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _c,
      builder: (context, child) {
        final scale = 1.0 + _c.value * 0.06;
        return Transform.scale(scale: scale, child: child);
      },
      child: widget.child,
    );
  }
}
