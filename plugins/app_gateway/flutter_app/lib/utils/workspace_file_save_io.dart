import 'dart:io';
import 'dart:typed_data';

import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

Future<void> saveWorkspaceFile({
  required Uint8List bytes,
  required String filename,
  required String mimeType,
}) async {
  final dir = await getTemporaryDirectory();
  final safeName = filename.replaceAll(RegExp(r'[\\/]'), '_');
  final file = File('${dir.path}/$safeName');
  await file.writeAsBytes(bytes, flush: true);
  await Share.shareXFiles(
    [XFile(file.path, mimeType: mimeType, name: safeName)],
    text: safeName,
  );
}
