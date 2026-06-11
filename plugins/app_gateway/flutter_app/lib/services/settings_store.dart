import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../config/app_config.dart';
import '../theme/app_theme_mode.dart';

/// Persists gateway URL + JWT (secure on mobile, prefs on web).
class SettingsStore {
  static const _keyToken = 'hermes_access_token';
  static const _keyRefreshToken = 'hermes_refresh_token';
  static const _keyUserId = 'hermes_user_id';
  static const _keySessionId = 'hermes_session_id';
  static const _keyThemeMode = 'hermes_theme_mode';

  final FlutterSecureStorage _secure = const FlutterSecureStorage();

  Future<AppConfig> load() async {
    final prefs = await SharedPreferences.getInstance();
    final sessionId = prefs.getString(_keySessionId) ?? 'app';
    final themeMode =
        AppThemeMode.fromStorage(prefs.getString(_keyThemeMode));
    final cookieAuth = kIsWeb;

    if (kIsWeb) {
      return AppConfig(
        baseUrl: AppConfig.defaultBaseUrl,
        accessToken: cookieAuth ? null : prefs.getString(_keyToken),
        refreshToken: cookieAuth ? null : prefs.getString(_keyRefreshToken),
        userId: prefs.getString(_keyUserId),
        sessionId: sessionId,
        themeMode: themeMode,
        cookieAuth: cookieAuth,
      );
    }

    final token = await _secure.read(key: _keyToken);
    final refreshToken = await _secure.read(key: _keyRefreshToken);
    final userId = await _secure.read(key: _keyUserId);
    return AppConfig(
      baseUrl: AppConfig.defaultBaseUrl,
      accessToken: token,
      refreshToken: refreshToken,
      userId: userId,
      sessionId: sessionId,
      themeMode: themeMode,
      cookieAuth: false,
    );
  }

  Future<void> save(AppConfig config) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_keySessionId, config.sessionId);
    await prefs.setString(_keyThemeMode, config.themeMode.storageValue);

    if (kIsWeb) {
      if (!config.cookieAuth) {
        if (config.accessToken != null) {
          await prefs.setString(_keyToken, config.accessToken!);
        } else {
          await prefs.remove(_keyToken);
        }
        if (config.refreshToken != null) {
          await prefs.setString(_keyRefreshToken, config.refreshToken!);
        } else {
          await prefs.remove(_keyRefreshToken);
        }
      } else {
        await prefs.remove(_keyToken);
        await prefs.remove(_keyRefreshToken);
      }
      if (config.userId != null) {
        await prefs.setString(_keyUserId, config.userId!);
      } else {
        await prefs.remove(_keyUserId);
      }
      return;
    }

    if (config.accessToken != null) {
      await _secure.write(key: _keyToken, value: config.accessToken!);
    } else {
      await _secure.delete(key: _keyToken);
    }
    if (config.refreshToken != null) {
      await _secure.write(key: _keyRefreshToken, value: config.refreshToken!);
    } else {
      await _secure.delete(key: _keyRefreshToken);
    }
    if (config.userId != null) {
      await _secure.write(key: _keyUserId, value: config.userId!);
    } else {
      await _secure.delete(key: _keyUserId);
    }
  }

  Future<void> clearSession() async {
    final prefs = await SharedPreferences.getInstance();
    if (kIsWeb) {
      await prefs.remove(_keyToken);
      await prefs.remove(_keyRefreshToken);
      await prefs.remove(_keyUserId);
      await prefs.remove(_keySessionId);
    } else {
      await _secure.delete(key: _keyToken);
      await _secure.delete(key: _keyRefreshToken);
      await _secure.delete(key: _keyUserId);
    }
    await prefs.remove(_keySessionId);
  }
}
