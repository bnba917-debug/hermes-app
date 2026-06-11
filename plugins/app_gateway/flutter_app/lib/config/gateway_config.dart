import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

import 'app_config.dart';

/// 网关地址仅从配置文件 / 编译参数解析，不在登录页暴露。
///
/// 优先级（高 → 低）：
/// 1. `--dart-define=HERMES_DEV_GATEWAY=http://...`
/// 2. Web：`/config.json`（[web/config.json]）
/// 3. 打包资源：[assets/app_config.json]
/// 4. [AppConfig.defaultBaseUrl]
class GatewayConfig {
  static String? _resolved;

  static Future<String> resolve() async {
    if (_resolved != null && _resolved!.isNotEmpty) {
      return _resolved!;
    }

    const fromEnv = String.fromEnvironment('HERMES_DEV_GATEWAY');
    if (fromEnv.isNotEmpty) {
      return _resolved = _normalize(fromEnv);
    }

    if (kIsWeb) {
      final fromWeb = await _loadWebConfig();
      if (fromWeb != null) return _resolved = fromWeb;
    }

    final fromAsset = await _loadAssetConfig();
    if (fromAsset != null) return _resolved = fromAsset;

    return _resolved = AppConfig.defaultBaseUrl;
  }

  static Future<String?> _loadWebConfig() async {
    try {
      final uri = Uri.base.resolve('config.json');
      final resp = await http
          .get(uri)
          .timeout(const Duration(seconds: 5));
      if (resp.statusCode != 200) return null;
      return _parseGatewayUrl(resp.body);
    } catch (_) {
      return null;
    }
  }

  static Future<String?> _loadAssetConfig() async {
    try {
      final raw = await rootBundle.loadString('assets/app_config.json');
      return _parseGatewayUrl(raw);
    } catch (_) {
      return null;
    }
  }

  static String? _parseGatewayUrl(String raw) {
    try {
      final data = jsonDecode(raw);
      if (data is! Map) return null;
      final url = data['gateway_url']?.toString().trim();
      if (url == null || url.isEmpty) return null;
      return _normalize(url);
    } catch (_) {
      return null;
    }
  }

  static String _normalize(String url) {
    return url.trim().replaceAll(RegExp(r'/+$'), '');
  }
}
