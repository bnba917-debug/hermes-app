import 'file_bytes_io.dart' if (dart.library.html) 'file_bytes_web.dart' as impl;

Future<List<int>> readPathBytes(String path) => impl.readFileBytes(path);

Future<String> tempWavPath() async {
  final dir = await impl.tempDirPath();
  if (dir.isEmpty) return '';
  return '$dir/hermes_${DateTime.now().millisecondsSinceEpoch}.wav';
}
