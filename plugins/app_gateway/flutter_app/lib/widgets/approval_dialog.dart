import 'package:flutter/material.dart';

import '../theme/hermes_palette.dart';
import '../theme/hermes_theme.dart';

/// Tool approval choices returned by the gateway SSE stream.
Future<String?> showToolApprovalDialog(
  BuildContext context, {
  required List<String> choices,
  String? toolName,
}) {
  final labels = <String, String>{
    'once': '仅本次',
    'session': '本会话',
    'always': '始终允许',
    'deny': '拒绝',
  };
  final options = choices.where((c) => labels.containsKey(c)).toList();
  if (options.isEmpty) {
    options.addAll(['once', 'session', 'always', 'deny']);
  }

  return showDialog<String>(
    context: context,
    barrierDismissible: false,
    builder: (ctx) {
      final p = HermesPalette.of(ctx);
      final title = toolName != null && toolName.isNotEmpty
          ? '允许工具：$toolName？'
          : '允许 Agent 执行工具操作？';
      return AlertDialog(
        backgroundColor: p.surface,
        title: Text(title, style: TextStyle(color: p.textPrimary)),
        content: Text(
          '请选择授权范围。拒绝将中止当前工具调用。',
          style: TextStyle(color: p.textSecondary),
        ),
        actions: [
          for (final choice in options)
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(choice),
              child: Text(
                labels[choice] ?? choice,
                style: TextStyle(
                  color: choice == 'deny'
                      ? HermesColors.errorSoft
                      : HermesColors.gold,
                ),
              ),
            ),
        ],
      );
    },
  );
}
