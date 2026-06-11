import 'dart:convert';
import 'dart:typed_data';

enum ChatRole { user, assistant, system }

class WorkspaceFileRef {
  WorkspaceFileRef({required this.path});

  final String path;

  String get displayName {
    final normalized = path.replaceAll('\\', '/');
    final idx = normalized.lastIndexOf('/');
    return idx >= 0 ? normalized.substring(idx + 1) : normalized;
  }
}

class ChatMessage {
  ChatMessage({
    required this.role,
    required this.content,
    this.isStreaming = false,
    List<WorkspaceFileRef>? workspaceFiles,
  }) : workspaceFiles = workspaceFiles ?? <WorkspaceFileRef>[];

  final ChatRole role;
  /// String text or List multimodal parts for API (mutable while streaming).
  dynamic content;
  bool isStreaming;
  final List<WorkspaceFileRef> workspaceFiles;

  void addWorkspaceFile(String path) {
    final normalized = path.trim().replaceAll('\\', '/');
    if (normalized.isEmpty) return;
    if (workspaceFiles.any((f) => f.path == normalized)) return;
    workspaceFiles.add(WorkspaceFileRef(path: normalized));
  }

  String get displayText {
    final c = content;
    if (c is String) return c;
    if (c is List) {
      final buf = StringBuffer();
      for (final part in c) {
        if (part is Map && part['type'] == 'text') {
          final t = part['text']?.toString().trim() ?? '';
          if (t.isNotEmpty) buf.writeln(t);
        }
      }
      return buf.toString().trim();
    }
    return c.toString();
  }

  /// First embedded image as bytes (for bubble preview), when content uses data URLs.
  Uint8List? get imagePreviewBytes {
    final url = firstImageDataUrl;
    if (url == null || !url.startsWith('data:')) return null;
    try {
      final headerEnd = url.indexOf(',');
      if (headerEnd < 0) return null;
      return base64Decode(url.substring(headerEnd + 1));
    } catch (_) {
      return null;
    }
  }

  List<String> get imageDataUrls {
    final c = content;
    if (c is! List) return const [];
    final urls = <String>[];
    for (final part in c) {
      if (part is! Map || part['type'] != 'image_url') continue;
      final ref = part['image_url'];
      if (ref is Map) {
        final url = ref['url']?.toString();
        if (url != null && url.isNotEmpty) urls.add(url);
      } else if (ref is String && ref.isNotEmpty) {
        urls.add(ref);
      }
    }
    return urls;
  }

  String? get firstImageDataUrl =>
      imageDataUrls.isEmpty ? null : imageDataUrls.first;

  List<Uint8List> get imagePreviewBytesList {
    return imageDataUrls
        .map((url) {
          if (!url.startsWith('data:')) return null;
          try {
            final i = url.indexOf(',');
            if (i < 0) return null;
            return base64Decode(url.substring(i + 1));
          } catch (_) {
            return null;
          }
        })
        .whereType<Uint8List>()
        .toList();
  }

  bool get hasImage => imageDataUrls.isNotEmpty;

  Map<String, dynamic> toApiJson() {
    final roleName = switch (role) {
      ChatRole.user => 'user',
      ChatRole.assistant => 'assistant',
      ChatRole.system => 'system',
    };
    return {'role': roleName, 'content': content};
  }
}
