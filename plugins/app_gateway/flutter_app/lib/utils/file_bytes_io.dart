import 'dart:io';

import 'package:path_provider/path_provider.dart';

Future<List<int>> readFileBytes(String path) => File(path).readAsBytes();

Future<String> tempDirPath() async {
  final dir = await getTemporaryDirectory();
  return dir.path;
}
