import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../models/chat_message.dart';
import '../theme/hermes_palette.dart';
import '../theme/hermes_theme.dart';
import 'markdown_body.dart';
import 'workspace_file_chips.dart';

class ChatMessageBubble extends StatelessWidget {
  const ChatMessageBubble({
    super.key,
    required this.message,
    this.onOpenWorkspaceFile,
    this.openingWorkspacePath,
  });

  final ChatMessage message;
  final Future<void> Function(String path)? onOpenWorkspaceFile;
  final String? openingWorkspacePath;

  bool get isUser => message.role == ChatRole.user;
  bool get streaming => message.isStreaming;
  String get text => message.displayText;
  List<Uint8List> get imageBytesList => message.imagePreviewBytesList;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final p = HermesPalette.of(context);
    final maxW = MediaQuery.sizeOf(context).width * 0.82;

    if (isUser) {
      return Align(
        alignment: Alignment.centerRight,
        child: Container(
          constraints: BoxConstraints(maxWidth: maxW),
          margin: const EdgeInsets.symmetric(vertical: 6),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          decoration: BoxDecoration(
            borderRadius: const BorderRadius.only(
              topLeft: Radius.circular(18),
              topRight: Radius.circular(18),
              bottomLeft: Radius.circular(18),
              bottomRight: Radius.circular(4),
            ),
            gradient: HermesTheme.goldGradient,
            boxShadow: [
              BoxShadow(
                color: HermesColors.gold.withValues(alpha: 0.2),
                blurRadius: 12,
                offset: const Offset(0, 4),
              ),
            ],
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            mainAxisSize: MainAxisSize.min,
            children: [
              if (imageBytesList.isNotEmpty) ...[
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: imageBytesList.map((bytes) {
                    return ClipRRect(
                      borderRadius: BorderRadius.circular(12),
                      child: ConstrainedBox(
                        constraints: const BoxConstraints(
                          maxWidth: 160,
                          maxHeight: 160,
                        ),
                        child: Image.memory(bytes, fit: BoxFit.cover),
                      ),
                    );
                  }).toList(),
                ),
                if (text.isNotEmpty) const SizedBox(height: 10),
              ],
              if (text.isNotEmpty)
                Text(
                  text + (streaming ? '▌' : ''),
                  style: theme.textTheme.bodyLarge?.copyWith(
                    color: HermesColors.obsidian,
                    height: 1.45,
                  ),
                ),
            ],
          ),
        ),
      );
    }

    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        constraints: BoxConstraints(maxWidth: maxW),
        margin: const EdgeInsets.symmetric(vertical: 6),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        decoration: BoxDecoration(
          color: p.surface.withValues(alpha: 0.92),
          borderRadius: const BorderRadius.only(
            topLeft: Radius.circular(18),
            topRight: Radius.circular(18),
            bottomRight: Radius.circular(18),
            bottomLeft: Radius.circular(4),
          ),
          border: Border.all(color: p.glassBorder),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 28,
              height: 28,
              margin: const EdgeInsets.only(right: 10),
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                gradient: HermesTheme.goldGradient,
              ),
              child: const Icon(
                Icons.auto_awesome,
                size: 14,
                color: HermesColors.obsidian,
              ),
            ),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (streaming && text.isEmpty)
                    const _TypingIndicator()
                  else if (streaming)
                    Text(
                      text + '▌',
                      style: theme.textTheme.bodyLarge?.copyWith(
                        height: 1.5,
                        color: p.textPrimary,
                      ),
                    )
                  else
                    HermesMarkdownBody(data: text),
                  if (!isUser &&
                      message.workspaceFiles.isNotEmpty &&
                      onOpenWorkspaceFile != null)
                    WorkspaceFileChips(
                      files: message.workspaceFiles,
                      busyPath: openingWorkspacePath,
                      onOpen: onOpenWorkspaceFile!,
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 工具活动 / 思考中指示条。
class _TypingIndicator extends StatefulWidget {
  const _TypingIndicator();

  @override
  State<_TypingIndicator> createState() => _TypingIndicatorState();
}

class _TypingIndicatorState extends State<_TypingIndicator>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c;

  @override
  void initState() {
    super.initState();
    _c = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat();
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
      builder: (context, _) {
        return Row(
          mainAxisSize: MainAxisSize.min,
          children: List.generate(3, (i) {
            final phase = (_c.value + i * 0.2) % 1.0;
            final opacity = 0.35 + 0.65 * (phase < 0.5 ? phase * 2 : (1 - phase) * 2);
            return Container(
              margin: EdgeInsets.only(right: i < 2 ? 6 : 0),
              width: 7,
              height: 7,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: HermesColors.goldLight.withValues(alpha: opacity),
              ),
            );
          }),
        );
      },
    );
  }
}

class HermesActivityStrip extends StatelessWidget {
  const HermesActivityStrip({super.key, required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      child: Row(
        children: [
          SizedBox(
            width: 14,
            height: 14,
            child: CircularProgressIndicator(
              strokeWidth: 2,
              color: HermesColors.gold.withValues(alpha: 0.9),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              label,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: HermesColors.goldLight,
                    letterSpacing: 0.2,
                  ),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }
}
