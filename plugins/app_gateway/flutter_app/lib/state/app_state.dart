import 'dart:async';

import 'package:flutter/foundation.dart';

import '../api/hermes_api.dart';
import '../config/app_config.dart';
import '../config/gateway_config.dart';
import '../models/chat_message.dart';
import '../models/pending_attachment.dart';
import '../services/settings_store.dart';
import '../theme/app_theme_mode.dart';
import '../utils/skill_catalog.dart';
import '../utils/workspace_file_save.dart';

bool _isAuthFailure(Object error) {
  if (error is HermesApiException) {
    final code = error.statusCode;
    return code == 401 || code == 403;
  }
  final text = error.toString().toLowerCase();
  return text.contains('401') ||
      text.contains('403') ||
      text.contains('jwt') ||
      text.contains('unauthorized');
}

class PendingApprovalRequest {
  PendingApprovalRequest({
    required this.runId,
    required this.choices,
    this.toolName,
  });

  final String runId;
  final List<String> choices;
  final String? toolName;
  final Completer<String> completer = Completer<String>();
}

class AppState extends ChangeNotifier {
  AppState(this._store);

  final SettingsStore _store;

  AppConfig config = AppConfig(
    baseUrl: AppConfig.defaultBaseUrl,
    cookieAuth: kIsWeb,
  );
  HermesApi? _api;
  bool loading = true;
  String? error;

  final List<ChatMessage> messages = [];
  bool chatBusy = false;
  String? activeRunId;
  String? activityLabel;

  List<Map<String, dynamic>> onboardingModels = [];
  bool readyForChat = false;

  List<Map<String, dynamic>> sessions = [];
  bool sessionsLoading = false;

  List<Map<String, dynamic>> skills = [];
  bool skillsLoading = false;
  String? skillsError;

  PendingApprovalRequest? pendingApproval;
  String? openingWorkspacePath;

  AppThemeMode get themeMode => config.themeMode;

  HermesApi get api {
    return _api ??= HermesApi(
      baseUrl: config.baseUrl,
      accessToken: config.accessToken,
      sessionId: config.sessionId,
    );
  }

  Future<void> bootstrap() async {
    loading = true;
    error = null;
    notifyListeners();
    try {
      final gatewayUrl = await GatewayConfig.resolve();
      config = (await _store.load()).copyWith(baseUrl: gatewayUrl);
      _syncApi();
      if (config.isLoggedIn) {
        try {
          final st = await api.onboardingStatus();
          readyForChat = st['ready_for_chat'] == true;
          if (readyForChat) {
            await loadSessionHistory();
            await refreshSessions();
            unawaited(refreshSkills());
          }
        } on HermesApiException catch (e) {
          if (_isAuthFailure(e)) {
            final recovered = await _tryRefreshSession();
            if (!recovered) {
              await logout();
            }
          } else {
            error = e.message;
          }
        }
      }
    } catch (e) {
      if (_isAuthFailure(e)) {
        final recovered = await _tryRefreshSession();
        if (!recovered) {
          await logout();
        }
      } else {
        error = e.toString();
      }
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<void> setThemeMode(AppThemeMode mode) async {
    config = config.copyWith(themeMode: mode);
    await _store.save(config);
    notifyListeners();
  }

  bool smsCaptchaEnabled = true;
  String? smsCaptchaToken;
  double? smsCaptchaTargetRatio;
  int smsCaptchaToleranceBp = 35;

  Future<void> refreshSmsCaptcha() async {
    final res = await api.fetchSmsCaptcha();
    smsCaptchaEnabled = res['enabled'] != false;
    if (smsCaptchaEnabled) {
      smsCaptchaToken = res['captcha_token']?.toString();
      final ratio = res['target_ratio'];
      smsCaptchaTargetRatio = ratio is num ? ratio.toDouble() : null;
      final tol = res['tolerance_bp'];
      if (tol is num) {
        smsCaptchaToleranceBp = tol.toInt();
      }
    } else {
      smsCaptchaToken = null;
      smsCaptchaTargetRatio = null;
    }
    notifyListeners();
  }

  Future<Map<String, dynamic>> sendLoginSms(
    String phone, {
    String? captchaToken,
    String? captchaAnswer,
  }) async {
    error = null;
    notifyListeners();
    try {
      final result = await api.sendSms(
        phone,
        captchaToken: smsCaptchaEnabled
            ? (captchaToken ?? smsCaptchaToken)
            : null,
        captchaAnswer: captchaAnswer,
      );
      if (smsCaptchaEnabled) {
        await refreshSmsCaptcha();
      }
      return result;
    } catch (e) {
      error = e.toString();
      rethrow;
    } finally {
      notifyListeners();
    }
  }

  Future<void> login(String phone, String code) async {
    error = null;
    notifyListeners();
    try {
      final data = await api.login(phone: phone, code: code, sessionId: config.sessionId);
      await _applyAuthResponse(data);
      if (!readyForChat) {
        try {
          onboardingModels = await api.onboardingModels();
        } catch (_) {
          onboardingModels = [];
        }
      } else {
        await loadSessionHistory();
        await refreshSessions();
        unawaited(refreshSkills());
      }
    } catch (e) {
      error = e.toString();
      rethrow;
    } finally {
      notifyListeners();
    }
  }

  Future<void> refreshOnboardingStatus() async {
    if (!config.isLoggedIn) return;
    try {
      final st = await api.onboardingStatus();
      readyForChat = st['ready_for_chat'] == true;
      notifyListeners();
    } catch (_) {}
  }

  Future<void> finishOnboarding({
    required String apiKey,
    required String model,
    String provider = 'openrouter',
    String? apiKeyEnv,
  }) async {
    await api.completeOnboarding(
      apiKey: apiKey,
      model: model,
      provider: provider,
      apiKeyEnv: apiKeyEnv,
    );
    readyForChat = true;
    await _store.save(config);
    await loadSessionHistory();
    await refreshSessions();
    await refreshSkills();
    notifyListeners();
  }

  Future<void> refreshSessions() async {
    if (!config.isLoggedIn || !readyForChat) return;
    sessionsLoading = true;
    notifyListeners();
    try {
      sessions = await api.listSessions(limit: 30);
    } catch (_) {
      sessions = [];
    } finally {
      sessionsLoading = false;
      notifyListeners();
    }
  }

  Future<void> refreshSkills() async {
    if (!config.isLoggedIn || !readyForChat) return;
    skillsLoading = true;
    skillsError = null;
    notifyListeners();
    try {
      final data = await api.listSkills();
      final raw = data['skills'];
      if (raw is List) {
        skills = raw
            .map((e) => Map<String, dynamic>.from(e as Map))
            .toList(growable: false);
      } else {
        skills = const [];
      }
    } catch (e) {
      skillsError = e is HermesApiException ? e.message : e.toString();
    } finally {
      skillsLoading = false;
      notifyListeners();
    }
  }

  String get currentSessionLabel {
    for (final s in sessions) {
      if (s['session_id']?.toString() == config.sessionId) {
        final title = (s['title']?.toString() ?? '').trim();
        if (title.isNotEmpty) return title;
        final preview = (s['preview']?.toString() ?? '').trim();
        if (preview.isNotEmpty) {
          return preview.length > 28 ? '${preview.substring(0, 28)}…' : preview;
        }
      }
    }
    return config.sessionId;
  }

  Future<void> renameSession(String sessionId, String title) async {
    final cleaned = title.trim();
    if (cleaned.isEmpty) return;
    await api.updateSessionTitle(sessionId, cleaned);
    await refreshSessions();
    notifyListeners();
  }

  Future<void> suggestSessionTitleFor(String sessionId) async {
    await api.suggestSessionTitle(sessionId);
    await refreshSessions();
    notifyListeners();
  }

  Future<void> switchToSession(String sessionId) async {
    if (sessionId.isEmpty || sessionId == config.sessionId || chatBusy) return;
    try {
      config = config.copyWith(sessionId: sessionId);
      _syncApi();
      messages.clear();
      await _store.save(config);
      await loadSessionHistory();
    } on HermesApiException catch (e) {
      if (_isAuthFailure(e)) {
        await logout();
      } else {
        error = e.message;
      }
      rethrow;
    }
    notifyListeners();
  }

  Future<void> logout() async {
    final refresh = config.refreshToken ?? api.refreshToken;
    await api.logout(token: refresh);
    await _store.clearSession();
    config = config.copyWith(clearToken: true);
    _syncApi();
    messages.clear();
    readyForChat = false;
    sessions = [];
    skills = const [];
    skillsError = null;
    skillsLoading = false;
    activeRunId = null;
    activityLabel = null;
    notifyListeners();
  }

  Future<void> logoutAllDevices() async {
    try {
      await api.logoutAllDevices();
    } catch (_) {}
    await logout();
  }

  Future<void> deleteAccount({required String code}) async {
    await api.deleteAccount(code: code);
    await _store.clearSession();
    config = config.copyWith(clearToken: true);
    _syncApi();
    messages.clear();
    readyForChat = false;
    sessions = [];
    skills = const [];
    skillsError = null;
    skillsLoading = false;
    notifyListeners();
  }

  Future<Map<String, dynamic>> sendDeleteAccountSms() async {
    return api.sendDeleteAccountSms();
  }

  Future<void> loadSessionHistory() async {
    try {
      final raw = await api.sessionMessages(config.sessionId);
      messages.clear();
      for (final m in raw) {
        final role = m['role']?.toString() ?? 'user';
        final content = m['content'];
        if (content == null) continue;
        final text = content is String
            ? content
            : content is List || content is Map
                ? ChatMessage(role: ChatRole.user, content: content).displayText
                : content.toString();
        if (text.trim().isEmpty) continue;
        messages.add(
          ChatMessage(
            role: role == 'assistant' ? ChatRole.assistant : ChatRole.user,
            content: text,
          ),
        );
      }
    } catch (_) {
      // New session or empty history — not fatal.
    }
    notifyListeners();
  }

  Future<void> newChatSession() async {
    try {
      final data = await api.createSession();
      final sid = data['session_id']?.toString() ?? 'app';
      config = config.copyWith(sessionId: sid);
      _syncApi();
      messages.clear();
      await _store.save(config);
      await refreshSessions();
    } on HermesApiException catch (e) {
      if (_isAuthFailure(e)) {
        await logout();
      } else {
        error = e.message;
      }
      rethrow;
    }
    notifyListeners();
  }

  Future<void> sendText(String text) async {
    await sendUserMessage(text: text);
  }

  /// Send user text plus staged images/files in one turn (豆包-style composer).
  Future<void> sendUserMessage({
    required String text,
    List<PendingAttachment> attachments = const [],
  }) async {
    final trimmed = text.trim();
    if (chatBusy) {
      throw HermesApiException(
        '上一条消息仍在处理中，请稍候或点停止按钮',
        statusCode: 409,
      );
    }
    if (!readyForChat) {
      await refreshOnboardingStatus();
    }
    if (!readyForChat) {
      throw HermesApiException('请先完成模型与 API Key 配置', statusCode: 403);
    }
    if (trimmed.isEmpty && attachments.isEmpty) return;

    final images = attachments.where((a) => a.isImage).toList();
    final files = attachments.where((a) => !a.isImage).toList();

    final buf = StringBuffer();
    if (trimmed.isNotEmpty) buf.writeln(trimmed);

    Future<void> appendUploadedAttachment(Map<String, dynamic> meta) async {
      final name = meta['filename']?.toString() ?? 'upload';
      final path = meta['path']?.toString() ?? '';
      final kind = meta['kind']?.toString() ?? 'file';
      final inline = meta['inline_text']?.toString();
      if (inline != null && inline.isNotEmpty) {
        buf.writeln('\n--- $name ---\n$inline');
      } else if (path.isNotEmpty) {
        if (kind == 'image') {
          buf.writeln(
            '\n[图片「$name」已保存至工作区路径 `$path`，请使用 vision_analyze 分析图片内容并回答]',
          );
        } else {
          buf.writeln(
            '\n[附件「$name」已保存至工作区路径 `$path`，请使用 read_file 读取并回答]',
          );
        }
      }
    }

    for (final file in files) {
      final meta = await api.uploadChatAttachment(
        bytes: file.bytes,
        filename: file.name,
        mimeType: file.mimeType,
      );
      await appendUploadedAttachment(meta);
    }

    // Upload images to workspace instead of embedding base64 in chat payloads.
    // DeepSeek and other non-vision models reject image_url parts; large data URLs
    // also stall the gateway while vision fallback runs on the event loop.
    for (final img in images) {
      final meta = await api.uploadChatAttachment(
        bytes: img.bytes,
        filename: img.name,
        mimeType: img.mimeType,
      );
      await appendUploadedAttachment(meta);
    }

    var textBody = buf.toString().trim();
    if (textBody.isEmpty) {
      textBody = '请根据附件内容回答。';
    }

    await _sendMessage(ChatMessage(role: ChatRole.user, content: textBody), hadAttachments: true);
  }

  Future<void> sendTranscript(String transcript) async {
    final t = transcript.trim();
    if (t.isEmpty) return;
    await sendText(t);
  }

  Future<void> openWorkspaceFile(String relativePath) async {
    final path = relativePath.trim().replaceAll('\\', '/');
    if (path.isEmpty || openingWorkspacePath != null) return;
    openingWorkspacePath = path;
    error = null;
    notifyListeners();
    try {
      final payload = await api.downloadWorkspaceFile(path);
      await saveWorkspaceFile(
        bytes: payload.bytes,
        filename: payload.filename,
        mimeType: payload.mimeType,
      );
    } catch (e) {
      error = e is HermesApiException ? e.message : e.toString();
    } finally {
      openingWorkspacePath = null;
      notifyListeners();
    }
  }

  Future<void> stopChat() async {
    final runId = activeRunId;
    if (runId != null && runId.isNotEmpty) {
      try {
        await api.stopChat(runId);
      } catch (_) {}
    }
    if (messages.isNotEmpty && messages.last.isStreaming) {
      messages.last.isStreaming = false;
    }
    chatBusy = false;
    activeRunId = null;
    activityLabel = null;
    notifyListeners();
  }

  Future<void> _sendMessage(ChatMessage userMsg, {bool hadAttachments = false}) async {
    chatBusy = true;
    error = null;
    activeRunId = null;
    activityLabel = '正在思考…';
    messages.add(userMsg);
    final assistant = ChatMessage(role: ChatRole.assistant, content: '', isStreaming: true);
    messages.add(assistant);
    notifyListeners();

    final payload = [userMsg.toApiJson()];
    var toolsUsedThisTurn = false;
    var skillCatalogMutatedThisTurn = false;

    try {
      final buffer = StringBuffer();
      var lastUiUpdate = DateTime.fromMillisecondsSinceEpoch(0);
      Future<void> maybeNotify({bool force = false}) async {
        final now = DateTime.now();
        if (force ||
            now.difference(lastUiUpdate) >= const Duration(milliseconds: 80)) {
          lastUiUpdate = now;
          notifyListeners();
        }
      }

      await for (final event in api.chatStream(messages: payload, useServerHistory: true)) {
        if (event.type == 'run.start' && event.runId != null) {
          activeRunId = event.runId;
        } else if (event.type == 'text' && event.text != null) {
          buffer.write(event.text);
          assistant.content = buffer.toString();
        } else if (event.type == 'tool.start') {
          toolsUsedThisTurn = true;
          if (isSkillCatalogMutatingTool(event.name)) {
            skillCatalogMutatedThisTurn = true;
          }
          activityLabel = '工具: ${event.name}';
        } else if (event.type == 'tool.complete') {
          if (isSkillCatalogMutatingTool(event.name)) {
            skillCatalogMutatedThisTurn = true;
          }
          for (final path in event.files ?? const <String>[]) {
            assistant.addWorkspaceFile(path);
          }
          activityLabel = null;
        } else if (event.type == 'approval.request') {
          activityLabel = '等待工具操作确认…';
          final rid = event.runId;
          if (rid != null && rid.isNotEmpty) {
            final req = PendingApprovalRequest(
              runId: rid,
              choices: event.choices ?? const ['once', 'session', 'always', 'deny'],
              toolName: event.name,
            );
            pendingApproval = req;
            notifyListeners();
            var choice = 'deny';
            try {
              choice = await req.completer.future.timeout(
                const Duration(minutes: 10),
              );
            } catch (_) {
              choice = 'deny';
            } finally {
              pendingApproval = null;
              activityLabel = null;
              notifyListeners();
            }
            try {
              await api.respondApproval(rid, choice: choice);
            } catch (_) {}
          }
        } else if (event.type == 'chat.done') {
          activeRunId = event.runId;
          if ((event.text ?? '').isNotEmpty && buffer.isEmpty) {
            buffer.write(event.text);
            assistant.content = buffer.toString();
          }
        }
        await maybeNotify();
      }
      assistant.isStreaming = false;
      final text = buffer.toString().trim();
      assistant.content = text.isEmpty
          ? '未收到模型回复。可能原因：Gateway 超时、网络搜索失败或 API Key 无效。请刷新后重试，或先问简单问题（如「1+1等于几」）。'
          : buffer.toString();
      await maybeNotify(force: true);
      // Simple Q&A keeps local transcript; sync from server when tools/attachments
      // may reshape messages or when we had to show a fallback reply.
      final needsHistorySync =
          toolsUsedThisTurn || hadAttachments || text.isEmpty;
      if (needsHistorySync) {
        await loadSessionHistory();
      }
      if (skillCatalogMutatedThisTurn) {
        await refreshSkills();
      }
    } catch (e) {
      error = e is HermesApiException ? e.message : e.toString();
      if (messages.isNotEmpty && messages.last.role == ChatRole.assistant) {
        messages.removeLast();
      }
      if (messages.isNotEmpty &&
          messages.last.role == ChatRole.user &&
          messages.last == userMsg) {
        messages.removeLast();
      }
      rethrow;
    } finally {
      chatBusy = false;
      activityLabel = null;
      notifyListeners();
      if (readyForChat) {
        unawaited(refreshSessions());
        unawaited(_maybeAutoTitleSession(userMsg));
      }
    }
  }

  Future<void> _maybeAutoTitleSession(ChatMessage userMsg) async {
    final userCount =
        messages.where((m) => m.role == ChatRole.user).length;
    if (userCount > 2) return;
    try {
      await api.suggestSessionTitle(config.sessionId);
      await refreshSessions();
    } catch (_) {}
  }

  Future<String?> speakLastReply() async {
    ChatMessage? last;
    for (final m in messages.reversed) {
      if (m.role == ChatRole.assistant && m.displayText.isNotEmpty) {
        last = m;
        break;
      }
    }
    if (last == null) return null;
    final res = await api.speech(last.displayText);
    return res['file_path'] as String?;
  }

  void _syncApi() {
    _api = HermesApi(
      baseUrl: config.baseUrl,
      accessToken: config.accessToken,
      refreshToken: config.refreshToken,
      sessionId: config.sessionId,
      cookieAuth: config.cookieAuth,
      onTokensRefreshed: config.cookieAuth ? null : _persistTokens,
    );
  }

  Future<void> respondToApproval(String choice) async {
    final pending = pendingApproval;
    if (pending == null || pending.completer.isCompleted) return;
    pending.completer.complete(choice);
  }

  Future<void> _persistTokens(String accessToken, String? refreshToken) async {
    config = config.copyWith(
      accessToken: accessToken,
      refreshToken: refreshToken ?? config.refreshToken,
    );
    await _store.save(config);
  }

  Future<void> _applyAuthResponse(Map<String, dynamic> data) async {
    final token = data['access_token']?.toString();
    final refresh = data['refresh_token']?.toString();
    final userId = data['user_id']?.toString();
    if (!config.cookieAuth && (token == null || token.isEmpty)) {
      throw HermesApiException('登录成功但未返回 access_token', statusCode: 502);
    }
    config = config.copyWith(
      accessToken: config.cookieAuth ? null : token,
      refreshToken: config.cookieAuth ? null : refresh,
      userId: userId,
    );
    _syncApi();
    if (config.cookieAuth) {
      _api?.accessToken = token;
      _api?.refreshToken = refresh;
    }
    await _store.save(config);
    readyForChat = data['ready_for_chat'] == true;
  }

  Future<bool> _tryRefreshSession() async {
    if (!config.cookieAuth &&
        (config.refreshToken == null || config.refreshToken!.isEmpty)) {
      return false;
    }
    try {
      final data = await api.refreshAccessToken(
        config.cookieAuth ? null : config.refreshToken,
      );
      if (!config.cookieAuth) {
        await _applyAuthResponse({
          ...data,
          'user_id': config.userId,
          'ready_for_chat': readyForChat,
        });
      } else {
        final access = data['access_token']?.toString();
        final refresh = data['refresh_token']?.toString();
        if (access != null && access.isNotEmpty) {
          api.accessToken = access;
        }
        if (refresh != null && refresh.isNotEmpty) {
          api.refreshToken = refresh;
        }
      }
      final st = await api.onboardingStatus();
      readyForChat = st['ready_for_chat'] == true;
      if (readyForChat) {
        await loadSessionHistory();
        await refreshSessions();
      }
      notifyListeners();
      return true;
    } catch (_) {
      return false;
    }
  }
}
