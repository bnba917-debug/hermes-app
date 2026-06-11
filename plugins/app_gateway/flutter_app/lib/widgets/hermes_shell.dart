import 'dart:math' as math;
import 'dart:ui';

import 'package:flutter/material.dart';

import '../theme/hermes_palette.dart';
import '../theme/hermes_theme.dart';

/// 全屏暗色渐变 + 金色光晕背景（可选缓慢漂移动画）。
class HermesAmbientBackground extends StatefulWidget {
  const HermesAmbientBackground({
    super.key,
    required this.child,
    this.animate = false,
  });

  final Widget child;
  final bool animate;

  @override
  State<HermesAmbientBackground> createState() => _HermesAmbientBackgroundState();
}

class _HermesAmbientBackgroundState extends State<HermesAmbientBackground>
    with SingleTickerProviderStateMixin {
  AnimationController? _drift;

  @override
  void initState() {
    super.initState();
    if (widget.animate) {
      _drift = AnimationController(
        vsync: this,
        duration: const Duration(seconds: 14),
      )..repeat();
    }
  }

  @override
  void didUpdateWidget(HermesAmbientBackground oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.animate && _drift == null) {
      _drift = AnimationController(
        vsync: this,
        duration: const Duration(seconds: 14),
      )..repeat();
    } else if (!widget.animate && _drift != null) {
      _drift!.dispose();
      _drift = null;
    }
  }

  @override
  void dispose() {
    _drift?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = HermesPalette.of(context);
    Widget orbs = Stack(
      clipBehavior: Clip.none,
      children: [
        Positioned(
          top: -120,
          right: -80,
          child: _GlowOrb(
            size: 280,
            color: HermesColors.gold.withValues(alpha: 0.18),
          ),
        ),
        Positioned(
          bottom: 80,
          left: -100,
          child: _GlowOrb(
            size: 220,
            color: HermesColors.goldDim.withValues(alpha: 0.12),
          ),
        ),
      ],
    );

    if (_drift != null) {
      orbs = AnimatedBuilder(
        animation: _drift!,
        builder: (context, _) {
          final t = _drift!.value * 2 * 3.14159265;
          return Stack(
            clipBehavior: Clip.none,
            children: [
              Positioned(
                top: -120 + 24 * math.sin(t),
                right: -80 + 18 * math.cos(t * 0.9),
                child: _GlowOrb(
                  size: 280,
                  color: HermesColors.gold.withValues(alpha: 0.2),
                ),
              ),
              Positioned(
                bottom: 80 + 20 * math.cos(t * 1.1),
                left: -100 + 16 * math.sin(t * 0.85),
                child: _GlowOrb(
                  size: 220,
                  color: HermesColors.goldDim.withValues(alpha: 0.14),
                ),
              ),
            ],
          );
        },
      );
    }

    return Stack(
      fit: StackFit.expand,
      children: [
        DecoratedBox(
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [p.ambientTop, p.background],
            ),
          ),
        ),
        orbs,
        widget.child,
      ],
    );
  }
}

class _GlowOrb extends StatelessWidget {
  const _GlowOrb({required this.size, required this.color});

  final double size;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        boxShadow: [BoxShadow(color: color, blurRadius: 80, spreadRadius: 20)],
      ),
    );
  }
}

/// 不透明设置页卡片（高对比，避免毛玻璃导致文字发虚）。
class HermesSolidCard extends StatelessWidget {
  const HermesSolidCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(18),
    this.margin,
  });

  final Widget child;
  final EdgeInsetsGeometry padding;
  final EdgeInsetsGeometry? margin;

  @override
  Widget build(BuildContext context) {
    final p = HermesPalette.of(context);
    return Container(
      margin: margin,
      decoration: BoxDecoration(
        color: p.cardFill,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: p.cardBorder, width: 1),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: p.isDark ? 0.35 : 0.06),
            blurRadius: 20,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: Padding(padding: padding, child: child),
    );
  }
}

/// 毛玻璃卡片容器。
class HermesGlassCard extends StatelessWidget {
  const HermesGlassCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(20),
    this.margin,
  });

  final Widget child;
  final EdgeInsetsGeometry padding;
  final EdgeInsetsGeometry? margin;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: margin,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: HermesPalette.of(context).glassBorder),
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            HermesPalette.of(context).glassFill.withValues(alpha: 0.9),
            HermesPalette.of(context).glassFill.withValues(alpha: 0.3),
          ],
        ),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.35),
            blurRadius: 24,
            offset: const Offset(0, 12),
          ),
        ],
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(20),
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 16, sigmaY: 16),
          child: Padding(padding: padding, child: child),
        ),
      ),
    );
  }
}

/// 金色渐变主按钮。
class HermesGoldButton extends StatelessWidget {
  const HermesGoldButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.loading = false,
    this.icon,
  });

  final String label;
  final VoidCallback? onPressed;
  final bool loading;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final disabled = onPressed == null || loading;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: disabled ? null : onPressed,
        borderRadius: BorderRadius.circular(14),
        child: Ink(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(14),
            gradient: disabled
                ? LinearGradient(
                    colors: [
                      HermesColors.stone,
                      HermesColors.stone.withValues(alpha: 0.8),
                    ],
                  )
                : HermesTheme.goldGradient,
            boxShadow: disabled
                ? null
                : [
                    BoxShadow(
                      color: HermesColors.gold.withValues(alpha: 0.35),
                      blurRadius: 20,
                      offset: const Offset(0, 8),
                    ),
                  ],
          ),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 16),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                if (loading)
                  const SizedBox(
                    width: 22,
                    height: 22,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: HermesColors.obsidian,
                    ),
                  )
                else ...[
                  if (icon != null) ...[
                    Icon(icon, size: 20, color: HermesColors.obsidian),
                    const SizedBox(width: 8),
                  ],
                  Text(
                    label,
                    style: Theme.of(context).textTheme.labelLarge?.copyWith(
                          color: HermesColors.obsidian,
                          fontWeight: FontWeight.w700,
                        ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// 品牌标题区（Cormorant + 金色细线）。
class HermesBrandHeader extends StatelessWidget {
  const HermesBrandHeader({
    super.key,
    required this.title,
    this.subtitle,
    this.compact = false,
  });

  final String title;
  final String? subtitle;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (!compact) ...[
          Container(
            width: 40,
            height: 3,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(2),
              gradient: HermesTheme.goldGradient,
            ),
          ),
          const SizedBox(height: 16),
        ],
        ShaderMask(
          shaderCallback: (bounds) => HermesTheme.goldGradient.createShader(bounds),
          child: Text(
            title,
            style: theme.textTheme.displayMedium?.copyWith(
              fontSize: compact ? 28 : 36,
              color: Colors.white,
              height: 1.1,
            ),
          ),
        ),
        if (subtitle != null) ...[
          const SizedBox(height: 10),
          Text(subtitle!, style: theme.textTheme.bodyMedium),
        ],
      ],
    );
  }
}
