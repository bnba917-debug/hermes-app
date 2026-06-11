import '../theme/app_theme_mode.dart';

/// Runtime settings persisted on device (base URL + JWT).
class AppConfig {
  AppConfig({
    required this.baseUrl,
    this.accessToken,
    this.refreshToken,
    this.userId,
    this.sessionId = 'app',
    this.themeMode = AppThemeMode.system,
    this.cookieAuth = false,
  });

  final String baseUrl;
  final String? accessToken;
  final String? refreshToken;
  final String? userId;
  final String sessionId;
  final AppThemeMode themeMode;
  /// Web: tokens live in HttpOnly cookies; only userId is persisted locally.
  final bool cookieAuth;

  bool get isLoggedIn {
    if (cookieAuth) {
      return (userId ?? '').isNotEmpty;
    }
    return (accessToken ?? '').isNotEmpty || (refreshToken ?? '').isNotEmpty;
  }

  AppConfig copyWith({
    String? baseUrl,
    String? accessToken,
    String? refreshToken,
    String? userId,
    String? sessionId,
    AppThemeMode? themeMode,
    bool? cookieAuth,
    bool clearToken = false,
  }) {
    return AppConfig(
      baseUrl: baseUrl ?? this.baseUrl,
      accessToken: clearToken ? null : (accessToken ?? this.accessToken),
      refreshToken: clearToken ? null : (refreshToken ?? this.refreshToken),
      userId: clearToken ? null : (userId ?? this.userId),
      sessionId: clearToken ? 'app' : (sessionId ?? this.sessionId),
      themeMode: themeMode ?? this.themeMode,
      cookieAuth: cookieAuth ?? this.cookieAuth,
    );
  }

  /// USB 调试时可传: --dart-define=HERMES_DEV_GATEWAY=http://192.168.x.x:8787
  static String get defaultBaseUrl {
    const fromEnv = String.fromEnvironment('HERMES_DEV_GATEWAY');
    if (fromEnv.isNotEmpty) return fromEnv;
    return 'http://127.0.0.1:8787';
  }
}
