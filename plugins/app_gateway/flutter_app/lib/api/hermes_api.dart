import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import '../services/http_client.dart';

class HermesApiException implements Exception {
  HermesApiException(this.message, {this.statusCode, this.code});

  final String message;
  final int? statusCode;
  final String? code;

  @override
  String toString() => 'HermesApiException($statusCode): $message';
}

String _errorMessageFromHttpBody(String body, int? statusCode) {
  if (body.trim().isEmpty) {
    return '请求失败${statusCode != null ? ' ($statusCode)' : ''}';
  }
  try {
    final parsed = jsonDecode(body);
    if (parsed is Map) {
      final detail = parsed['detail'];
      if (detail is Map) {
        return detail['message']?.toString() ??
            detail['code']?.toString() ??
            detail.toString();
      }
      if (detail != null) return detail.toString();
      final err = parsed['error'];
      if (err is Map) {
        return err['message']?.toString() ?? err.toString();
      }
      if (err != null) return err.toString();
    }
  } catch (_) {}
  return body.length > 240 ? '${body.substring(0, 240)}…' : body;
}

String? _errorCodeFromHttpBody(String body) {
  try {
    final parsed = jsonDecode(body);
    if (parsed is Map) {
      final detail = parsed['detail'];
      if (detail is Map) return detail['code']?.toString();
    }
  } catch (_) {}
  return null;
}

class ChatStreamEvent {
  ChatStreamEvent.started({required this.runId})
      : type = 'run.start',
        text = null,
        name = null,
        choices = null,
        files = null;

  ChatStreamEvent.text(this.text)
      : type = 'text',
        name = null,
        runId = null,
        choices = null,
        files = null;

  ChatStreamEvent.toolStart({required this.name, this.runId})
      : type = 'tool.start',
        text = null,
        choices = null,
        files = null;

  ChatStreamEvent.toolComplete({
    required this.name,
    this.runId,
    this.files,
  })  : type = 'tool.complete',
        text = null,
        choices = null;

  ChatStreamEvent.approval({
    required this.runId,
    required this.choices,
    this.name,
  })  : type = 'approval.request',
        text = null,
        files = null;

  ChatStreamEvent.done({this.runId, this.text})
      : type = 'chat.done',
        name = null,
        choices = null,
        files = null;

  final String type;
  final String? text;
  final String? name;
  final String? runId;
  final List<String>? choices;
  final List<String>? files;
}

/// HTTP + SSE client for Hermes App Gateway.
class HermesApi {
  HermesApi({
    required this.baseUrl,
    this.accessToken,
    this.refreshToken,
    this.sessionId = 'app',
    this.cookieAuth = false,
    http.Client? client,
    this.onTokensRefreshed,
  }) : _client = client ?? createHermesHttpClient();

  final String baseUrl;
  String? accessToken;
  String? refreshToken;
  String sessionId;
  final bool cookieAuth;
  final http.Client _client;
  final Future<void> Function(String accessToken, String? refreshToken)?
      onTokensRefreshed;

  static const _cookieAuthHeader = 'X-Hermes-Cookie-Auth';

  String get _root => baseUrl.replaceAll(RegExp(r'/+$'), '');

  Map<String, String> _headers({bool jsonBody = true}) {
    final h = <String, String>{};
    if (jsonBody) h['Content-Type'] = 'application/json';
    if (cookieAuth) {
      h[_cookieAuthHeader] = '1';
    }
    final token = accessToken;
    if (token != null && token.isNotEmpty) {
      h['Authorization'] = 'Bearer $token';
      h['X-User-Token'] = token;
    }
    if (sessionId.isNotEmpty) {
      h['X-Hermes-Session-Id'] = sessionId;
    }
    return h;
  }

  Future<Map<String, dynamic>> _decode(http.Response resp) async {
    Map<String, dynamic> body = {};
    if (resp.body.isNotEmpty) {
      try {
        body = jsonDecode(resp.body) as Map<String, dynamic>;
      } catch (_) {
        body = {'raw': resp.body};
      }
    }
    if (resp.statusCode >= 400) {
      final detail = body['detail'];
      String message;
      String? code;
      if (detail is Map) {
        message = '${detail['message'] ?? detail}';
        code = detail['code']?.toString();
      } else {
        message = detail?.toString() ?? body['error']?.toString() ?? resp.body;
      }
      throw HermesApiException(message, statusCode: resp.statusCode, code: code);
    }
    return body;
  }

  Future<bool> _refreshTokens() async {
    final currentRefresh = refreshToken;
    if (!cookieAuth && (currentRefresh == null || currentRefresh.isEmpty)) {
      return false;
    }
    try {
      final data = await refreshAccessToken(
        cookieAuth ? null : currentRefresh,
      );
      final access = data['access_token']?.toString();
      if (access == null || access.isEmpty) {
        if (!cookieAuth) {
          return false;
        }
      } else {
        accessToken = access;
      }
      final nextRefresh = data['refresh_token']?.toString();
      if (nextRefresh != null && nextRefresh.isNotEmpty) {
        refreshToken = nextRefresh;
      }
      final callback = onTokensRefreshed;
      if (callback != null && access != null && access.isNotEmpty) {
        await callback(access, refreshToken);
      }
      return true;
    } catch (_) {
      return false;
    }
  }

  Future<Map<String, dynamic>> _send(
    Future<http.Response> Function() request, {
    bool retryOnUnauthorized = true,
  }) async {
    var resp = await request();
    if (retryOnUnauthorized && resp.statusCode == 401) {
      final canRefresh = cookieAuth ||
          (refreshToken != null && refreshToken!.isNotEmpty);
      if (canRefresh && await _refreshTokens()) {
        resp = await request();
      }
    }
    return _decode(resp);
  }

  Future<Map<String, dynamic>> refreshAccessToken([String? token]) async {
    if (!cookieAuth && (token == null || token.isEmpty)) {
      throw HermesApiException('refresh_token is required', statusCode: 400);
    }
    final body = <String, dynamic>{};
    if (token != null && token.isNotEmpty) {
      body['refresh_token'] = token;
    }
    final resp = await _client.post(
      Uri.parse('$_root/v1/auth/refresh'),
      headers: _headers(),
      body: jsonEncode(body),
    );
    return _decode(resp);
  }

  Future<void> logout({String? token}) async {
    if (!cookieAuth) {
      final refresh = token ?? refreshToken;
      if (refresh == null || refresh.isEmpty) {
        return;
      }
    }
    try {
      final body = <String, dynamic>{};
      final refresh = token ?? refreshToken;
      if (refresh != null && refresh.isNotEmpty) {
        body['refresh_token'] = refresh;
      }
      await _client.post(
        Uri.parse('$_root/v1/auth/logout'),
        headers: _headers(),
        body: jsonEncode(body),
      );
    } catch (_) {
      // Best-effort server-side revoke.
    }
  }

  Future<Map<String, dynamic>> health() async {
    return _send(() => _client.get(Uri.parse('$_root/health')),
        retryOnUnauthorized: false);
  }

  Future<String> fetchLegalDocument(String doc) async {
    final resp = await _client.get(Uri.parse('$_root/v1/legal/$doc'));
    if (resp.statusCode >= 400) {
      throw HermesApiException(resp.body, statusCode: resp.statusCode);
    }
    return resp.body;
  }

  Future<Map<String, dynamic>> sendDeleteAccountSms() async {
    return _send(
      () => _client.post(
        Uri.parse('$_root/v1/me/delete/sms'),
        headers: _headers(),
      ),
    );
  }

  Future<Map<String, dynamic>> deleteAccount({required String code}) async {
    return _send(
      () => _client.delete(
        Uri.parse('$_root/v1/me'),
        headers: _headers(),
        body: jsonEncode({'confirm': true, 'code': code}),
      ),
    );
  }

  Future<void> logoutAllDevices() async {
    await _send(
      () => _client.post(
        Uri.parse('$_root/v1/auth/logout/all'),
        headers: _headers(),
      ),
    );
  }

  Future<Map<String, dynamic>> fetchSmsCaptcha() async {
    return _send(() => _client.get(Uri.parse('$_root/v1/auth/sms/captcha')),
        retryOnUnauthorized: false);
  }

  Future<Map<String, dynamic>> uploadChatAttachment({
    required Uint8List bytes,
    required String filename,
    String mimeType = 'application/octet-stream',
  }) async {
    final req = http.MultipartRequest(
      'POST',
      Uri.parse('$_root/v1/chat/attachments'),
    );
    req.headers.addAll(_headers(jsonBody: false));
    req.files.add(
      http.MultipartFile.fromBytes(
        'file',
        bytes,
        filename: filename,
      ),
    );
    final streamed = await _client.send(req);
    final resp = await http.Response.fromStream(streamed);
    if (resp.statusCode == 401 &&
        refreshToken != null &&
        refreshToken!.isNotEmpty &&
        await _refreshTokens()) {
      final retryReq = http.MultipartRequest(
        'POST',
        Uri.parse('$_root/v1/chat/attachments'),
      );
      retryReq.headers.addAll(_headers(jsonBody: false));
      retryReq.files.add(
        http.MultipartFile.fromBytes(
          'file',
          bytes,
          filename: filename,
        ),
      );
      final retryStreamed = await _client.send(retryReq);
      return _decode(await http.Response.fromStream(retryStreamed));
    }
    return _decode(resp);
  }

  Future<({Uint8List bytes, String filename, String mimeType})>
      downloadWorkspaceFile(String relativePath) async {
    Future<http.Response> request() => _client.get(
          Uri.parse('$_root/v1/workspace/download').replace(
            queryParameters: {'path': relativePath},
          ),
          headers: _headers(jsonBody: false),
        );

    var resp = await request();
    if (resp.statusCode == 401) {
      final canRefresh = cookieAuth ||
          (refreshToken != null && refreshToken!.isNotEmpty);
      if (canRefresh && await _refreshTokens()) {
        resp = await request();
      }
    }
    if (resp.statusCode < 200 || resp.statusCode >= 300) {
      throw HermesApiException(
        _errorMessageFromHttpBody(resp.body, resp.statusCode),
        statusCode: resp.statusCode,
        code: _errorCodeFromHttpBody(resp.body),
      );
    }
    final body = resp.bodyBytes;
    final mimeType =
        resp.headers['content-type']?.split(';').first.trim() ??
            'application/octet-stream';
    final disposition = resp.headers['content-disposition'] ?? '';
    var filename = relativePath.replaceAll('\\', '/').split('/').last;
    final match = RegExp(r'filename="([^"]+)"').firstMatch(disposition);
    if (match != null) {
      filename = match.group(1) ?? filename;
    }
    return (bytes: body, filename: filename, mimeType: mimeType);
  }

  Future<Map<String, dynamic>> sendSms(
    String phone, {
    String? captchaToken,
    String? captchaAnswer,
  }) async {
    final body = <String, dynamic>{'phone': phone};
    if (captchaToken != null && captchaToken.isNotEmpty) {
      body['captcha_token'] = captchaToken;
    }
    if (captchaAnswer != null && captchaAnswer.isNotEmpty) {
      body['captcha_answer'] = captchaAnswer;
    }
    return _send(
      () => _client.post(
        Uri.parse('$_root/v1/auth/sms/send'),
        headers: _headers(),
        body: jsonEncode(body),
      ),
      retryOnUnauthorized: false,
    );
  }

  Future<Map<String, dynamic>> login({
    required String phone,
    required String code,
    String deviceId = 'flutter',
    String sessionId = 'app',
  }) async {
    return _send(
      () => _client.post(
        Uri.parse('$_root/v1/auth/login'),
        headers: _headers(),
        body: jsonEncode({
          'phone': phone,
          'code': code,
          'device_id': deviceId,
          'session_id': sessionId,
        }),
      ),
      retryOnUnauthorized: false,
    );
  }

  Future<Map<String, dynamic>> onboardingStatus() async {
    return _send(
      () => _client.get(
        Uri.parse('$_root/v1/onboarding/status'),
        headers: _headers(jsonBody: false),
      ),
    );
  }

  Future<List<Map<String, dynamic>>> onboardingModels() async {
    final data = await _send(
      () => _client.get(
        Uri.parse('$_root/v1/onboarding/models'),
        headers: _headers(jsonBody: false),
      ),
      retryOnUnauthorized: false,
    );
    final models = data['models'];
    if (models is List) {
      return models.map((e) => Map<String, dynamic>.from(e as Map)).toList();
    }
    return [];
  }

  Future<Map<String, dynamic>> completeOnboarding({
    required String apiKey,
    required String model,
    String provider = 'openrouter',
    String? apiKeyEnv,
  }) async {
    return _send(
      () => _client.post(
        Uri.parse('$_root/v1/onboarding/complete'),
        headers: _headers(),
        body: jsonEncode({
          'api_key': apiKey,
          'model': model,
          'provider': provider,
          if (apiKeyEnv != null && apiKeyEnv.isNotEmpty) 'api_key_env': apiKeyEnv,
        }),
      ),
    );
  }

  Future<Map<String, dynamic>> listSkills() async {
    return _send(
      () => _client.get(
        Uri.parse('$_root/v1/skills'),
        headers: _headers(jsonBody: false),
      ),
    );
  }

  Future<List<Map<String, dynamic>>> listSessions({int limit = 20}) async {
    final data = await _send(
      () => _client.get(
        Uri.parse('$_root/v1/sessions?limit=$limit'),
        headers: _headers(jsonBody: false),
      ),
    );
    final raw = data['sessions'];
    if (raw is List) {
      return raw.map((e) => Map<String, dynamic>.from(e as Map)).toList();
    }
    return [];
  }

  Future<Map<String, dynamic>> createSession({String? sessionId}) async {
    return _send(
      () => _client.post(
        Uri.parse('$_root/v1/sessions'),
        headers: _headers(),
        body: jsonEncode({
          if (sessionId != null && sessionId.isNotEmpty) 'session_id': sessionId,
        }),
      ),
    );
  }

  Future<Map<String, dynamic>> suggestSessionTitle(String logicalSessionId) async {
    return _send(
      () => _client.post(
        Uri.parse('$_root/v1/sessions/$logicalSessionId/title/suggest'),
        headers: _headers(),
      ),
    );
  }

  Future<Map<String, dynamic>> updateSessionTitle(
    String logicalSessionId,
    String title,
  ) async {
    return _send(
      () => _client.patch(
        Uri.parse('$_root/v1/sessions/$logicalSessionId'),
        headers: _headers(),
        body: jsonEncode({'title': title}),
      ),
    );
  }

  Future<Map<String, dynamic>> getInference() async {
    return _send(
      () => _client.get(
        Uri.parse('$_root/v1/me/inference'),
        headers: _headers(jsonBody: false),
      ),
    );
  }

  Future<Map<String, dynamic>> putInference({
    String? apiKey,
    String? model,
    String? provider,
    String? apiKeyEnv,
    String? baseUrl,
  }) async {
    final body = <String, dynamic>{};
    if (apiKey != null) body['api_key'] = apiKey;
    if (model != null) body['model'] = model;
    if (provider != null) body['provider'] = provider;
    if (apiKeyEnv != null) body['api_key_env'] = apiKeyEnv;
    if (baseUrl != null) body['base_url'] = baseUrl;
    return _send(
      () => _client.put(
        Uri.parse('$_root/v1/me/inference'),
        headers: _headers(),
        body: jsonEncode(body),
      ),
    );
  }

  Future<Map<String, dynamic>> usage() async {
    return _send(
      () => _client.get(
        Uri.parse('$_root/v1/me/usage'),
        headers: _headers(jsonBody: false),
      ),
    );
  }

  Future<List<Map<String, dynamic>>> sessionMessages(String logicalSessionId) async {
    final data = await _send(
      () => _client.get(
        Uri.parse('$_root/v1/sessions/$logicalSessionId/messages'),
        headers: _headers(jsonBody: false),
      ),
    );
    final raw = data['messages'];
    if (raw is List) {
      return raw.map((e) => Map<String, dynamic>.from(e as Map)).toList();
    }
    return [];
  }

  Future<Map<String, dynamic>> respondApproval(
    String runId, {
    String choice = 'session',
  }) async {
    return _send(
      () => _client.post(
        Uri.parse('$_root/v1/runs/$runId/approval'),
        headers: _headers(),
        body: jsonEncode({'choice': choice}),
      ),
    );
  }

  Future<Map<String, dynamic>> stopChat(String runId) async {
    return _send(
      () => _client.post(
        Uri.parse('$_root/v1/chat/stop'),
        headers: _headers(),
        body: jsonEncode({'run_id': runId}),
      ),
    );
  }

  Future<Map<String, dynamic>> transcribeBytes(
    List<int> bytes, {
    String filename = 'recording.wav',
  }) async {
    final req = http.MultipartRequest(
      'POST',
      Uri.parse('$_root/v1/audio/transcribe'),
    );
    req.headers.addAll(_headers(jsonBody: false));
    req.files.add(
      http.MultipartFile.fromBytes('file', bytes, filename: filename),
    );
    final streamed = await _client.send(req);
    final resp = await http.Response.fromStream(streamed);
    return _decode(resp);
  }

  Future<Map<String, dynamic>> speech(String text) async {
    return _send(
      () => _client.post(
        Uri.parse('$_root/v1/audio/speech'),
        headers: _headers(),
        body: jsonEncode({'text': text}),
      ),
    );
  }

  Future<http.StreamedResponse> _sendChatRequest(
    List<Map<String, dynamic>> messages, {
    required String model,
    required bool useServerHistory,
  }) {
    final req = http.Request(
      'POST',
      Uri.parse('$_root/v1/chat/completions'),
    );
    req.headers.addAll(_headers());
    req.body = jsonEncode({
      'model': model,
      'messages': messages,
      'stream': true,
      'use_server_history': useServerHistory,
    });
    return _client.send(req).timeout(const Duration(seconds: 300));
  }

  /// SSE stream — text deltas and structured Hermes events (reconnects on transient errors).
  Stream<ChatStreamEvent> chatStream({
    required List<Map<String, dynamic>> messages,
    String model = 'hermes-agent',
    bool useServerHistory = true,
    int maxReconnectAttempts = 5,
  }) async* {
    var attempt = 0;
    var delayMs = 500;

    while (attempt < maxReconnectAttempts) {
      attempt += 1;
      var receivedAny = false;
      try {
        await for (final event in _chatStreamOnce(
          messages,
          model: model,
          useServerHistory: useServerHistory,
        )) {
          receivedAny = true;
          yield event;
          attempt = 0;
          delayMs = 500;
        }
        return;
      } on HermesApiException catch (e) {
        if (receivedAny) rethrow;
        if (e.statusCode == 401) {
          final canRefresh = cookieAuth ||
              (refreshToken != null && refreshToken!.isNotEmpty);
          if (canRefresh && await _refreshTokens()) {
            attempt -= 1;
            continue;
          }
        }
        if (!_isRetryableStreamError(e) || attempt >= maxReconnectAttempts) {
          rethrow;
        }
      } catch (e) {
        if (receivedAny) rethrow;
        if (attempt >= maxReconnectAttempts) {
          rethrow;
        }
      }
      await Future<void>.delayed(Duration(milliseconds: delayMs));
      delayMs = (delayMs * 2).clamp(500, 8000);
    }
  }

  bool _isRetryableStreamError(HermesApiException e) {
    final code = e.statusCode;
    if (code == null) return true;
    return code >= 500 || code == 408 || code == 429;
  }

  Stream<ChatStreamEvent> _chatStreamOnce(
    List<Map<String, dynamic>> messages, {
    required String model,
    required bool useServerHistory,
  }) async* {
    var streamed = await _sendChatRequest(
      messages,
      model: model,
      useServerHistory: useServerHistory,
    );
    if (streamed.statusCode == 401) {
      final canRefresh = cookieAuth ||
          (refreshToken != null && refreshToken!.isNotEmpty);
      if (canRefresh && await _refreshTokens()) {
        streamed = await _sendChatRequest(
          messages,
          model: model,
          useServerHistory: useServerHistory,
        );
      }
    }
    if (streamed.statusCode >= 400) {
      final body = await streamed.stream.bytesToString();
      throw HermesApiException(
        _errorMessageFromHttpBody(body, streamed.statusCode),
        statusCode: streamed.statusCode,
        code: _errorCodeFromHttpBody(body),
      );
    }

    final headerRunId = streamed.headers['x-hermes-run-id'];
    if (headerRunId != null && headerRunId.isNotEmpty) {
      yield ChatStreamEvent.started(runId: headerRunId);
    }

    final lines = streamed.stream
        .transform(utf8.decoder)
        .transform(const LineSplitter());

    await for (final line in lines) {
      if (!line.startsWith('data: ')) continue;
      final payload = line.substring(6).trim();
      if (payload == '[DONE]') break;
      try {
        final data = jsonDecode(payload) as Map<String, dynamic>;
        if (data['object'] == 'hermes.event') {
          final type = data['type']?.toString() ?? '';
          final runId = data['run_id']?.toString();
          if (type == 'tool.start') {
            yield ChatStreamEvent.toolStart(
              name: data['name']?.toString() ?? 'tool',
              runId: runId,
            );
          } else if (type == 'tool.complete') {
            final rawFiles = data['files'];
            final files = rawFiles is List
                ? rawFiles
                    .map((item) {
                      if (item is Map) {
                        return item['path']?.toString();
                      }
                      return item?.toString();
                    })
                    .whereType<String>()
                    .where((p) => p.trim().isNotEmpty)
                    .toList()
                : <String>[];
            yield ChatStreamEvent.toolComplete(
              name: data['name']?.toString() ?? 'tool',
              runId: runId,
              files: files.isEmpty ? null : files,
            );
          } else if (type == 'approval.request') {
            final rawChoices = data['choices'];
            final choices = rawChoices is List
                ? rawChoices.map((c) => c.toString()).toList()
                : <String>['once', 'session', 'always', 'deny'];
            yield ChatStreamEvent.approval(
              runId: runId ?? '',
              choices: choices,
              name: data['tool']?.toString() ?? data['name']?.toString(),
            );
          } else if (type == 'chat.done') {
            final content = data['content']?.toString();
            yield ChatStreamEvent.done(
              runId: runId,
              text: (content != null && content.isNotEmpty) ? content : null,
            );
          } else if (type == 'heartbeat') {
            continue;
          }
          continue;
        }
        final choices = data['choices'] as List?;
        if (choices == null || choices.isEmpty) continue;
        final delta = choices[0]['delta'] as Map<String, dynamic>?;
        final content = delta?['content'];
        if (content is String && content.isNotEmpty) {
          yield ChatStreamEvent.text(content);
        }
      } catch (_) {
        continue;
      }
    }
  }

  void close() => _client.close();
}
