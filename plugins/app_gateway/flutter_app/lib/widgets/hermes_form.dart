import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../theme/hermes_palette.dart';
import '../theme/hermes_theme.dart';

/// 登录/入驻等表单用实心卡片（比毛玻璃更易读）。
class HermesFormCard extends StatelessWidget {
  const HermesFormCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(22),
  });

  final Widget child;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    final p = context.hermes;
    final cardColor = p.isDark
        ? const Color(0xFF2E2A27)
        : Colors.white;
    final borderColor = p.isDark
        ? const Color(0xFF57534E)
        : const Color(0xFFE7E5E4);

    return Container(
      padding: padding,
      decoration: BoxDecoration(
        color: cardColor,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: borderColor, width: 1),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: p.isDark ? 0.35 : 0.08),
            blurRadius: 28,
            offset: const Offset(0, 12),
          ),
        ],
      ),
      child: child,
    );
  }
}

/// 高对比度输入框样式（登录、入驻共用）。
InputDecoration hermesFormDecoration(
  BuildContext context, {
  required String labelText,
  String? hintText,
  String? helperText,
  IconData? prefixIcon,
}) {
  final p = context.hermes;
  final fill = p.isDark ? const Color(0xFF44403C) : const Color(0xFFF5F5F4);
  final border = p.isDark ? const Color(0xFF78716C) : const Color(0xFFD6D3D1);
  final labelColor = p.isDark ? const Color(0xFFE7E5E4) : const Color(0xFF44403C);
  final hintColor = p.isDark ? const Color(0xFFA8A29E) : const Color(0xFF78716C);

  return InputDecoration(
    labelText: labelText,
    hintText: hintText,
    helperText: helperText,
    filled: true,
    fillColor: fill,
    labelStyle: GoogleFonts.jost(
      color: labelColor,
      fontSize: 14,
      fontWeight: FontWeight.w500,
    ),
    hintStyle: GoogleFonts.jost(color: hintColor, fontSize: 14),
    helperStyle: GoogleFonts.jost(
      color: hintColor,
      fontSize: 12,
    ),
    prefixIcon: prefixIcon != null
        ? Icon(prefixIcon, color: HermesColors.gold, size: 22)
        : null,
    contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
    border: OutlineInputBorder(
      borderRadius: BorderRadius.circular(14),
      borderSide: BorderSide(color: border, width: 1.2),
    ),
    enabledBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(14),
      borderSide: BorderSide(color: border, width: 1.2),
    ),
    focusedBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(14),
      borderSide: const BorderSide(color: HermesColors.gold, width: 1.8),
    ),
    focusedErrorBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(14),
      borderSide: const BorderSide(color: Color(0xFFF87171), width: 1.5),
    ),
  );
}

TextStyle hermesFormTextStyle(BuildContext context) {
  final p = context.hermes;
  return GoogleFonts.jost(
    fontSize: 16,
    fontWeight: FontWeight.w500,
    color: p.isDark ? const Color(0xFFFAFAF9) : p.textPrimary,
    height: 1.35,
  );
}
