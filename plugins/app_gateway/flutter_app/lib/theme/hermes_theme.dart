import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import 'hermes_palette.dart';

/// 暗金奢华 — Obsidian + Champagne Gold（Hermes 品牌气质）
abstract final class HermesColors {
  static const obsidian = Color(0xFF0C0A09);
  static const charcoal = Color(0xFF1C1917);
  static const stone = Color(0xFF292524);
  static const muted = Color(0xFFA8A29E);
  static const ivory = Color(0xFFFAFAF9);
  static const gold = Color(0xFFCA8A04);
  static const goldLight = Color(0xFFE8C547);
  static const goldDim = Color(0xFF92700A);
  static const glassBorder = Color(0x33FFFFFF);
  static const glassFill = Color(0x1AFFFFFF);
  static const errorSoft = Color(0xFFFCA5A5);
}

class HermesTheme {
  static ThemeData dark() => _build(HermesPalette.dark);

  static ThemeData light() => _build(HermesPalette.light);

  static ThemeData _build(HermesPalette palette) {
    final isDark = palette.isDark;
    final base = ThemeData(
      useMaterial3: true,
      brightness: isDark ? Brightness.dark : Brightness.light,
      scaffoldBackgroundColor: palette.background,
      colorScheme: isDark
          ? const ColorScheme.dark(
              primary: HermesColors.gold,
              onPrimary: HermesColors.obsidian,
              secondary: HermesColors.goldLight,
              onSecondary: HermesColors.obsidian,
              surface: HermesColors.charcoal,
              onSurface: HermesColors.ivory,
              error: Color(0xFFF87171),
              onError: HermesColors.obsidian,
            )
          : const ColorScheme.light(
              primary: HermesColors.gold,
              onPrimary: HermesColors.ivory,
              secondary: HermesColors.goldDim,
              onSecondary: HermesColors.ivory,
              surface: Color(0xFFFFFFFF),
              onSurface: Color(0xFF0C0A09),
              error: Color(0xFFB91C1C),
              onError: HermesColors.ivory,
            ),
    );

    final body = GoogleFonts.jostTextTheme(base.textTheme).apply(
      bodyColor: palette.textPrimary,
      displayColor: palette.textPrimary,
    );

    final display = GoogleFonts.cormorantGaramondTextTheme(base.textTheme);

    return base.copyWith(
      extensions: [palette],
      textTheme: body.copyWith(
        displayLarge: display.displayLarge?.copyWith(
          fontWeight: FontWeight.w600,
          letterSpacing: -0.5,
          color: palette.textPrimary,
        ),
        displayMedium: display.displayMedium?.copyWith(
          fontWeight: FontWeight.w600,
          color: palette.textPrimary,
        ),
        headlineSmall: display.headlineSmall?.copyWith(
          fontWeight: FontWeight.w600,
          color: palette.textPrimary,
        ),
        titleLarge: body.titleLarge?.copyWith(
          fontWeight: FontWeight.w600,
          letterSpacing: 0.2,
        ),
        titleMedium: body.titleMedium?.copyWith(fontWeight: FontWeight.w500),
        bodyMedium: body.bodyMedium?.copyWith(
          color: palette.textSecondary,
          height: 1.45,
        ),
        bodySmall: body.bodySmall?.copyWith(
          color: palette.textSecondary,
          height: 1.35,
          fontSize: 13,
        ),
        titleSmall: body.titleSmall?.copyWith(
          color: palette.textPrimary,
          fontWeight: FontWeight.w600,
        ),
        labelLarge: body.labelLarge?.copyWith(
          fontWeight: FontWeight.w600,
          letterSpacing: 0.8,
        ),
      ),
      appBarTheme: AppBarTheme(
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        backgroundColor: Colors.transparent,
        foregroundColor: palette.textPrimary,
        titleTextStyle: GoogleFonts.cormorantGaramond(
          fontSize: 22,
          fontWeight: FontWeight.w600,
          color: palette.textPrimary,
        ),
      ),
      navigationBarTheme: NavigationBarThemeData(
        height: 68,
        elevation: 8,
        shadowColor: Colors.black.withValues(alpha: isDark ? 0.45 : 0.12),
        backgroundColor: isDark ? const Color(0xFF161412) : palette.surface,
        surfaceTintColor: Colors.transparent,
        indicatorColor: HermesColors.gold.withValues(alpha: isDark ? 0.28 : 0.2),
        labelTextStyle: WidgetStateProperty.resolveWith((states) {
          final selected = states.contains(WidgetState.selected);
          return GoogleFonts.jost(
            fontSize: 11,
            fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
            color: selected ? HermesColors.gold : palette.textMuted,
          );
        }),
        iconTheme: WidgetStateProperty.resolveWith((states) {
          final selected = states.contains(WidgetState.selected);
          return IconThemeData(
            color: selected ? HermesColors.gold : palette.textMuted,
            size: 22,
          );
        }),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: palette.glassFill,
        hintStyle: GoogleFonts.jost(color: palette.textMuted.withValues(alpha: 0.7)),
        labelStyle: GoogleFonts.jost(
          color: palette.textMuted,
          fontSize: 13,
          fontWeight: FontWeight.w500,
        ),
        contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: BorderSide(color: palette.glassBorder),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: BorderSide(color: palette.glassBorder),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: HermesColors.gold, width: 1.2),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: HermesColors.gold,
          foregroundColor: HermesColors.obsidian,
          padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 16),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
          textStyle: GoogleFonts.jost(
            fontWeight: FontWeight.w600,
            fontSize: 15,
            letterSpacing: 0.3,
          ),
        ),
      ),
      snackBarTheme: SnackBarThemeData(
        backgroundColor: palette.surfaceElevated,
        contentTextStyle: GoogleFonts.jost(color: palette.textPrimary),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        behavior: SnackBarBehavior.floating,
      ),
      dividerTheme: DividerThemeData(
        color: palette.glassBorder,
        thickness: 1,
      ),
      progressIndicatorTheme: const ProgressIndicatorThemeData(
        color: HermesColors.gold,
      ),
      iconTheme: IconThemeData(color: palette.textPrimary),
      segmentedButtonTheme: SegmentedButtonThemeData(
        style: ButtonStyle(
          backgroundColor: WidgetStateProperty.resolveWith((states) {
            if (states.contains(WidgetState.selected)) {
              return HermesColors.gold.withValues(alpha: isDark ? 0.22 : 0.16);
            }
            return palette.surfaceElevated;
          }),
          foregroundColor: WidgetStateProperty.resolveWith((states) {
            if (states.contains(WidgetState.selected)) {
              return isDark ? HermesColors.goldLight : HermesColors.goldDim;
            }
            return palette.textSecondary;
          }),
          side: WidgetStateProperty.resolveWith((states) {
            return BorderSide(
              color: states.contains(WidgetState.selected)
                  ? HermesColors.gold
                  : palette.cardBorder,
            );
          }),
        ),
      ),
    );
  }

  static LinearGradient get goldGradient => const LinearGradient(
        colors: [HermesColors.goldLight, HermesColors.gold, HermesColors.goldDim],
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
      );

  static LinearGradient get ambientGlow => LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [
          HermesColors.gold.withValues(alpha: 0.12),
          Colors.transparent,
          HermesColors.goldDim.withValues(alpha: 0.06),
        ],
      );
}
