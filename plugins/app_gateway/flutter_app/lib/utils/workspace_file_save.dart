import 'dart:typed_data';

import 'workspace_file_save_io.dart'
    if (dart.library.html) 'workspace_file_save_web.dart' as impl;

Future<void> saveWorkspaceFile({
  required Uint8List bytes,
  required String filename,
  required String mimeType,
}) =>
    impl.saveWorkspaceFile(
      bytes: bytes,
      filename: filename,
      mimeType: mimeType,
    );
