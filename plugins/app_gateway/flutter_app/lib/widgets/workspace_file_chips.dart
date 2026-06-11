import 'package:flutter/material.dart';

import '../models/chat_message.dart';
import '../theme/hermes_palette.dart';
import '../theme/hermes_theme.dart';

class WorkspaceFileChips extends StatelessWidget {
  const WorkspaceFileChips({
    super.key,
    required this.files,
    required this.onOpen,
    this.busyPath,
  });

  final List<WorkspaceFileRef> files;
  final Future<void> Function(String path) onOpen;
  final String? busyPath;

  @override
  Widget build(BuildContext context) {
    if (files.isEmpty) return const SizedBox.shrink();
    final p = HermesPalette.of(context);
    final theme = Theme.of(context);

    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Wrap(
        spacing: 8,
        runSpacing: 8,
        children: files.map((file) {
          final opening = busyPath == file.path;
          return ActionChip(
            avatar: opening
                ? SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: HermesColors.gold,
                    ),
                  )
                : Icon(
                    _iconForPath(file.path),
                    size: 16,
                    color: HermesColors.gold,
                  ),
            label: Text(
              file.displayName,
              style: theme.textTheme.labelLarge?.copyWith(
                color: p.textPrimary,
              ),
            ),
            backgroundColor: p.surface.withValues(alpha: 0.7),
            side: BorderSide(color: p.glassBorder),
            onPressed: opening ? null : () => onOpen(file.path),
          );
        }).toList(),
      ),
    );
  }

  IconData _iconForPath(String path) {
    final lower = path.toLowerCase();
    if (lower.endsWith('.md') || lower.endsWith('.txt')) {
      return Icons.description_outlined;
    }
    if (lower.endsWith('.xlsx') ||
        lower.endsWith('.xls') ||
        lower.endsWith('.csv')) {
      return Icons.table_chart_outlined;
    }
    if (lower.endsWith('.png') ||
        lower.endsWith('.jpg') ||
        lower.endsWith('.jpeg') ||
        lower.endsWith('.webp') ||
        lower.endsWith('.gif')) {
      return Icons.image_outlined;
    }
    if (lower.endsWith('.pdf')) return Icons.picture_as_pdf_outlined;
    if (lower.endsWith('.zip') || lower.endsWith('.tar') || lower.endsWith('.gz')) {
      return Icons.folder_zip_outlined;
    }
    return Icons.insert_drive_file_outlined;
  }
}
