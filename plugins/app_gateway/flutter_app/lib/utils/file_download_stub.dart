import 'dart:typed_data';

/// Mobile/desktop: caller may use path_provider later; web uses [file_download_web].
void downloadBytes(Uint8List bytes, String filename) {
  throw UnsupportedError('Download not implemented on this platform');
}
