import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../models/pending_attachment.dart';
import '../theme/hermes_theme.dart';

/// Bottom sheet: gallery / camera / file (豆包-style).
Future<void> showAttachmentPickerSheet({
  required BuildContext context,
  required VoidCallback onGallery,
  required VoidCallback onCamera,
  required VoidCallback onFile,
}) {
  return showModalBottomSheet<void>(
    context: context,
    backgroundColor: HermesColors.charcoal,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
    ),
    builder: (ctx) {
      return SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 40,
                height: 4,
                margin: const EdgeInsets.only(bottom: 16),
                decoration: BoxDecoration(
                  color: HermesColors.muted.withValues(alpha: 0.5),
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
              _SheetTile(
                icon: Icons.photo_library_outlined,
                label: '相册',
                onTap: () {
                  Navigator.pop(ctx);
                  onGallery();
                },
              ),
              if (!kIsWeb)
                _SheetTile(
                  icon: Icons.photo_camera_outlined,
                  label: '拍照',
                  onTap: () {
                    Navigator.pop(ctx);
                    onCamera();
                  },
                ),
              _SheetTile(
                icon: Icons.attach_file_rounded,
                label: '文件',
                onTap: () {
                  Navigator.pop(ctx);
                  onFile();
                },
              ),
            ],
          ),
        ),
      );
    },
  );
}

class ComposerAttachmentStrip extends StatelessWidget {
  const ComposerAttachmentStrip({
    super.key,
    required this.attachments,
    required this.onRemove,
    this.enabled = true,
  });

  final List<PendingAttachment> attachments;
  final void Function(String id) onRemove;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    if (attachments.isEmpty) return const SizedBox.shrink();
    return SizedBox(
      height: 92,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(4, 0, 4, 8),
        itemCount: attachments.length,
        separatorBuilder: (_, __) => const SizedBox(width: 10),
        itemBuilder: (context, i) {
          final att = attachments[i];
          return _AttachmentChip(
            attachment: att,
            enabled: enabled,
            onRemove: () => onRemove(att.id),
          );
        },
      ),
    );
  }
}

class _AttachmentChip extends StatelessWidget {
  const _AttachmentChip({
    required this.attachment,
    required this.onRemove,
    required this.enabled,
  });

  final PendingAttachment attachment;
  final VoidCallback onRemove;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    return Stack(
      clipBehavior: Clip.none,
      children: [
        Container(
          width: 80,
          height: 80,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: HermesColors.goldDim),
            color: HermesColors.stone,
          ),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(11),
            child: attachment.isImage
                ? Image.memory(attachment.bytes, fit: BoxFit.cover)
                : _FileThumb(name: attachment.name),
          ),
        ),
        Positioned(
          top: -6,
          right: -6,
          child: Material(
            color: HermesColors.charcoal,
            shape: const CircleBorder(),
            child: InkWell(
              customBorder: const CircleBorder(),
              onTap: enabled ? onRemove : null,
              child: const Padding(
                padding: EdgeInsets.all(4),
                child: Icon(Icons.close, size: 16, color: HermesColors.ivory),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _FileThumb extends StatelessWidget {
  const _FileThumb({required this.name});

  final String name;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(8),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const Icon(Icons.description_outlined, color: HermesColors.gold, size: 28),
          const SizedBox(height: 6),
          Text(
            name,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: HermesColors.ivory,
                  fontSize: 10,
                  height: 1.2,
                ),
          ),
        ],
      ),
    );
  }
}

class _SheetTile extends StatelessWidget {
  const _SheetTile({
    required this.icon,
    required this.label,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: Icon(icon, color: HermesColors.gold),
      title: Text(label, style: const TextStyle(color: HermesColors.ivory)),
      onTap: onTap,
    );
  }
}
