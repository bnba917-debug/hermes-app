import 'package:flutter/material.dart';

enum AppThemeMode {
  system,
  dark,
  light;

  ThemeMode get themeMode => switch (this) {
        AppThemeMode.system => ThemeMode.system,
        AppThemeMode.dark => ThemeMode.dark,
        AppThemeMode.light => ThemeMode.light,
      };

  static AppThemeMode fromStorage(String? raw) {
    switch (raw) {
      case 'light':
        return AppThemeMode.light;
      case 'dark':
        return AppThemeMode.dark;
      default:
        return AppThemeMode.system;
    }
  }

  String get storageValue => name;
}
