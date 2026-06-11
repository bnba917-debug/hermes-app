import 'package:http/browser_client.dart';
import 'package:http/http.dart' as http;

/// Web: BrowserClient with credentials for HttpOnly auth cookies.
http.Client createHermesHttpClient() {
  return BrowserClient()..withCredentials = true;
}
