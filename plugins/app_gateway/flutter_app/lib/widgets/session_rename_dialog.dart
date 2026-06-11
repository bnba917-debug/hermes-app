import 'package:flutter/material.dart';

import '../theme/hermes_palette.dart';
import '../theme/hermes_theme.dart';

/// 重命名会话对话框；返回新标题或 null（取消）。
Future<String?> showSessionRenameDialog(
  BuildContext context, {
  required String initialTitle,
  String? hint,
}) {
  final controller = TextEditingController(text: initialTitle);
  final p = HermesPalette.of(context);

  return showDialog<String>(
    context: context,
    builder: (ctx) {
      return AlertDialog(
        backgroundColor: p.surface,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
          side: BorderSide(color: p.glassBorder),
        ),
        title: Text('重命名会话', style: TextStyle(color: p.textPrimary)),
        content: TextField(
          controller: controller,
          autofocus: true,
          maxLength: 80,
          style: TextStyle(color: p.textPrimary),
          decoration: InputDecoration(
            hintText: hint ?? '输入会话标题',
            counterStyle: TextStyle(color: p.textMuted),
          ),
          onSubmitted: (v) {
            final t = v.trim();
            if (t.isNotEmpty) Navigator.pop(ctx, t);
          },
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: Text('取消', style: TextStyle(color: p.textMuted)),
          ),
          FilledButton(
            onPressed: () {
              final t = controller.text.trim();
              if (t.isEmpty) return;
              Navigator.pop(ctx, t);
            },
            style: FilledButton.styleFrom(
              backgroundColor: HermesColors.gold,
              foregroundColor: HermesColors.obsidian,
            ),
            child: const Text('保存'),
          ),
        ],
      );
    },
  );
}
