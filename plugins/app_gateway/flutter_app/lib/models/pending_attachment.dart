import 'dart:typed_data';

enum PendingAttachmentKind { image, file }

/// Attachment staged in the composer before send (image and/or documents).
class PendingAttachment {
  PendingAttachment({
    required this.id,
    required this.bytes,
    required this.name,
    required this.mimeType,
    required this.kind,
  });

  final String id;
  final Uint8List bytes;
  final String name;
  final String mimeType;
  final PendingAttachmentKind kind;

  bool get isImage => kind == PendingAttachmentKind.image;

  static String _newId() =>
      DateTime.now().microsecondsSinceEpoch.toRadixString(36);

  factory PendingAttachment.image({
    required Uint8List bytes,
    required String mimeType,
    String? name,
  }) {
    return PendingAttachment(
      id: _newId(),
      bytes: bytes,
      name: name ?? 'photo.jpg',
      mimeType: mimeType,
      kind: PendingAttachmentKind.image,
    );
  }

  factory PendingAttachment.file({
    required Uint8List bytes,
    required String name,
    required String mimeType,
  }) {
    return PendingAttachment(
      id: _newId(),
      bytes: bytes,
      name: name,
      mimeType: mimeType,
      kind: PendingAttachmentKind.file,
    );
  }
}
