import 'package:http/http.dart' as http;

/// Shared HTTP client — default for mobile/desktop.
http.Client createHermesHttpClient() => http.Client();
