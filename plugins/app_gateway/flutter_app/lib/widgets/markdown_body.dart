import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:url_launcher/url_launcher.dart';

import '../theme/hermes_palette.dart';
import '../theme/hermes_theme.dart';

/// 助手消息 Markdown 渲染（代码块、列表、链接等）。
class HermesMarkdownBody extends StatelessWidget {
  const HermesMarkdownBody({
    super.key,
    required this.data,
    this.streaming = false,
  });

  final String data;
  final bool streaming;

  @override
  Widget build(BuildContext context) {
    final p = HermesPalette.of(context);
    final body = data + (streaming ? '▌' : '');

    return MarkdownBody(
      data: body,
      selectable: !streaming,
      shrinkWrap: true,
      styleSheet: MarkdownStyleSheet(
        p: GoogleFonts.jost(
          fontSize: 15,
          height: 1.5,
          color: p.textPrimary,
        ),
        h1: GoogleFonts.cormorantGaramond(
          fontSize: 22,
          fontWeight: FontWeight.w600,
          color: p.textPrimary,
        ),
        h2: GoogleFonts.cormorantGaramond(
          fontSize: 19,
          fontWeight: FontWeight.w600,
          color: p.textPrimary,
        ),
        h3: GoogleFonts.jost(
          fontSize: 16,
          fontWeight: FontWeight.w600,
          color: p.textPrimary,
        ),
        strong: GoogleFonts.jost(
          fontWeight: FontWeight.w700,
          color: p.textPrimary,
        ),
        em: GoogleFonts.jost(
          fontStyle: FontStyle.italic,
          color: p.textMuted,
        ),
        blockquote: GoogleFonts.jost(
          color: p.textMuted,
          fontStyle: FontStyle.italic,
        ),
        blockquoteDecoration: BoxDecoration(
          border: Border(
            left: BorderSide(color: HermesColors.gold, width: 3),
          ),
        ),
        code: GoogleFonts.robotoMono(
          fontSize: 13,
          color: HermesColors.goldLight,
          backgroundColor: p.isDark
              ? HermesColors.obsidian.withValues(alpha: 0.6)
              : p.surfaceElevated,
        ),
        codeblockDecoration: BoxDecoration(
          color: p.isDark
              ? HermesColors.obsidian.withValues(alpha: 0.85)
              : p.surfaceElevated,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: p.glassBorder),
        ),
        codeblockPadding: const EdgeInsets.all(12),
        a: GoogleFonts.jost(
          color: HermesColors.gold,
          decoration: TextDecoration.underline,
          decorationColor: HermesColors.gold.withValues(alpha: 0.5),
        ),
        listBullet: GoogleFonts.jost(color: HermesColors.gold, fontSize: 14),
        horizontalRuleDecoration: BoxDecoration(
          border: Border(
            top: BorderSide(color: p.glassBorder, width: 1),
          ),
        ),
      ),
      onTapLink: (_, href, __) async {
        if (href == null) return;
        final uri = Uri.tryParse(href);
        if (uri != null && await canLaunchUrl(uri)) {
          await launchUrl(uri, mode: LaunchMode.externalApplication);
        }
      },
    );
  }
}
