import 'package:flutter/material.dart';

import 'hermes_theme.dart';

/// Semantic colors that adapt to light / dark theme.
@immutable
class HermesPalette extends ThemeExtension<HermesPalette> {
  const HermesPalette({
    required this.background,
    required this.surface,
    required this.surfaceElevated,
    required this.cardFill,
    required this.textPrimary,
    required this.textMuted,
    required this.textSecondary,
    required this.glassBorder,
    required this.glassFill,
    required this.cardBorder,
    required this.ambientTop,
    required this.isDark,
  });

  final Color background;
  final Color surface;
  final Color surfaceElevated;
  /// Opaque card background (settings / profile — high readability).
  final Color cardFill;
  final Color textPrimary;
  final Color textMuted;
  /// Slightly brighter than [textMuted] for labels on dark cards.
  final Color textSecondary;
  final Color glassBorder;
  final Color glassFill;
  final Color cardBorder;
  final Color ambientTop;
  final bool isDark;

  static const dark = HermesPalette(
    background: HermesColors.obsidian,
    surface: HermesColors.charcoal,
    surfaceElevated: HermesColors.stone,
    cardFill: Color(0xFF1F1C1A),
    textPrimary: HermesColors.ivory,
    textMuted: HermesColors.muted,
    textSecondary: Color(0xFFD6D3D1),
    glassBorder: HermesColors.glassBorder,
    glassFill: HermesColors.glassFill,
    cardBorder: Color(0x4DCA8A04),
    ambientTop: Color(0xFF141210),
    isDark: true,
  );

  static const light = HermesPalette(
    background: Color(0xFFFAFAF9),
    surface: Color(0xFFFFFFFF),
    surfaceElevated: Color(0xFFF5F5F4),
    cardFill: Color(0xFFFFFFFF),
    textPrimary: Color(0xFF0C0A09),
    textMuted: Color(0xFF57534E),
    textSecondary: Color(0xFF78716C),
    glassBorder: Color(0x1A0C0A09),
    glassFill: Color(0x0D0C0A09),
    cardBorder: Color(0x33CA8A04),
    ambientTop: Color(0xFFF5F0E6),
    isDark: false,
  );

  static HermesPalette of(BuildContext context) {
    return Theme.of(context).extension<HermesPalette>() ?? dark;
  }

  @override
  HermesPalette copyWith({
    Color? background,
    Color? surface,
    Color? surfaceElevated,
    Color? cardFill,
    Color? textPrimary,
    Color? textMuted,
    Color? textSecondary,
    Color? glassBorder,
    Color? glassFill,
    Color? cardBorder,
    Color? ambientTop,
    bool? isDark,
  }) {
    return HermesPalette(
      background: background ?? this.background,
      surface: surface ?? this.surface,
      surfaceElevated: surfaceElevated ?? this.surfaceElevated,
      cardFill: cardFill ?? this.cardFill,
      textPrimary: textPrimary ?? this.textPrimary,
      textMuted: textMuted ?? this.textMuted,
      textSecondary: textSecondary ?? this.textSecondary,
      glassBorder: glassBorder ?? this.glassBorder,
      glassFill: glassFill ?? this.glassFill,
      cardBorder: cardBorder ?? this.cardBorder,
      ambientTop: ambientTop ?? this.ambientTop,
      isDark: isDark ?? this.isDark,
    );
  }

  @override
  HermesPalette lerp(ThemeExtension<HermesPalette>? other, double t) {
    if (other is! HermesPalette) return this;
    return HermesPalette(
      background: Color.lerp(background, other.background, t)!,
      surface: Color.lerp(surface, other.surface, t)!,
      surfaceElevated: Color.lerp(surfaceElevated, other.surfaceElevated, t)!,
      cardFill: Color.lerp(cardFill, other.cardFill, t)!,
      textPrimary: Color.lerp(textPrimary, other.textPrimary, t)!,
      textMuted: Color.lerp(textMuted, other.textMuted, t)!,
      textSecondary: Color.lerp(textSecondary, other.textSecondary, t)!,
      glassBorder: Color.lerp(glassBorder, other.glassBorder, t)!,
      glassFill: Color.lerp(glassFill, other.glassFill, t)!,
      cardBorder: Color.lerp(cardBorder, other.cardBorder, t)!,
      ambientTop: Color.lerp(ambientTop, other.ambientTop, t)!,
      isDark: t < 0.5 ? isDark : other.isDark,
    );
  }
}

extension HermesPaletteContext on BuildContext {
  HermesPalette get hermes => HermesPalette.of(this);
}
