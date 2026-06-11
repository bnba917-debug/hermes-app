import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';

import '../theme/hermes_palette.dart';
import '../theme/hermes_theme.dart';
import '../widgets/hermes_toast.dart';

Future<void> showMessageActions(
  BuildContext context, {
  required String text,
  required bool isUser,
}) async {
  final trimmed = text.trim();
  if (trimmed.isEmpty) return;

  await showModalBottomSheet<void>(
    context: context,
    backgroundColor: Colors.transparent,
    builder: (ctx) {
      final p = HermesPalette.of(ctx);
      return Container(
        margin: const EdgeInsets.fromLTRB(12, 0, 12, 16),
        decoration: BoxDecoration(
          color: p.surface,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: p.glassBorder),
        ),
        child: SafeArea(
          top: false,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const SizedBox(height: 8),
              Container(
                width: 36,
                height: 4,
                decoration: BoxDecoration(
                  color: p.textMuted.withValues(alpha: 0.35),
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 12, 20, 8),
                child: Text(
                  isUser ? '我的消息' : '助手回复',
                  style: Theme.of(ctx).textTheme.titleSmall?.copyWith(
                        color: p.textPrimary,
                      ),
                ),
              ),
              ListTile(
                leading: Icon(Icons.copy_rounded, color: HermesColors.gold),
                title: Text('复制', style: TextStyle(color: p.textPrimary)),
                onTap: () async {
                  await Clipboard.setData(ClipboardData(text: trimmed));
                  if (ctx.mounted) {
                    Navigator.pop(ctx);
                    showHermesToast(context, '已复制到剪贴板');
                  }
                },
              ),
              ListTile(
                leading: Icon(Icons.share_outlined, color: HermesColors.gold),
                title: Text('分享', style: TextStyle(color: p.textPrimary)),
                onTap: () async {
                  Navigator.pop(ctx);
                  await Share.share(trimmed);
                },
              ),
              const SizedBox(height: 8),
            ],
          ),
        ),
      );
    },
  );
}
