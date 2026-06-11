import 'dart:ui';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:file_picker/file_picker.dart';
import 'package:image_picker/image_picker.dart';
import 'package:provider/provider.dart';
import 'package:record/record.dart';

import '../models/pending_attachment.dart';
import '../api/hermes_api.dart';
import '../state/app_state.dart';
import '../theme/hermes_palette.dart';
import '../theme/hermes_theme.dart';
import '../utils/file_bytes.dart';
import '../widgets/approval_dialog.dart';
import '../widgets/chat_bubble.dart';
import '../widgets/composer_attachments.dart';
import '../widgets/hermes_motion.dart';
import '../widgets/message_actions.dart';
import '../widgets/session_drawer.dart';
import '../widgets/session_rename_dialog.dart';
import '../widgets/hermes_toast.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final _recorder = AudioRecorder();
  final _player = AudioPlayer();
  final _scaffoldKey = GlobalKey<ScaffoldState>();
  bool _recording = false;
  final List<PendingAttachment> _pendingAttachments = [];
  final _imagePicker = ImagePicker();
  bool _approvalDialogOpen = false;

  void _maybeShowApprovalDialog(AppState state) {
    final pending = state.pendingApproval;
    if (pending == null || _approvalDialogOpen) return;
    _approvalDialogOpen = true;
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) {
        _approvalDialogOpen = false;
        return;
      }
      final choice = await showToolApprovalDialog(
        context,
        choices: pending.choices,
        toolName: pending.toolName,
      );
      await state.respondToApproval(choice ?? 'deny');
      if (mounted) {
        setState(() => _approvalDialogOpen = false);
      } else {
        _approvalDialogOpen = false;
      }
    });
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      final state = context.read<AppState>();
      await state.refreshOnboardingStatus();
      await state.refreshSessions();
    });
  }

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    _recorder.dispose();
    _player.dispose();
    super.dispose();
  }

  void _scrollToEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scroll.hasClients) return;
      _scroll.animateTo(
        _scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 200),
        curve: Curves.easeOut,
      );
    });
  }

  void _addAttachment(PendingAttachment att) {
    setState(() => _pendingAttachments.add(att));
  }

  void _removeAttachment(String id) {
    setState(() => _pendingAttachments.removeWhere((a) => a.id == id));
  }

  Future<void> _pickImageFromGallery() async {
    final file = await _imagePicker.pickImage(
      source: ImageSource.gallery,
      imageQuality: 85,
    );
    if (file == null) return;
    final bytes = await file.readAsBytes();
    if (!mounted) return;
    _addAttachment(
      PendingAttachment.image(
        bytes: bytes,
        mimeType: file.mimeType ?? 'image/jpeg',
        name: file.name,
      ),
    );
  }

  Future<void> _pickImageFromCamera() async {
    final file = await _imagePicker.pickImage(
      source: ImageSource.camera,
      imageQuality: 85,
    );
    if (file == null) return;
    final bytes = await file.readAsBytes();
    if (!mounted) return;
    _addAttachment(
      PendingAttachment.image(
        bytes: bytes,
        mimeType: file.mimeType ?? 'image/jpeg',
        name: file.name,
      ),
    );
  }

  Future<void> _pickDocument() async {
    final result = await FilePicker.platform.pickFiles(
      withData: true,
      allowMultiple: true,
    );
    if (result == null) return;
    for (final f in result.files) {
      final bytes = f.bytes;
      if (bytes == null || bytes.isEmpty) continue;
      final name = f.name;
      final mime = _mimeFromName(name, f.extension);
      if (_looksLikeImage(name, mime)) {
        _addAttachment(
          PendingAttachment.image(bytes: bytes, mimeType: mime, name: name),
        );
      } else {
        _addAttachment(
          PendingAttachment.file(bytes: bytes, name: name, mimeType: mime),
        );
      }
    }
    if (mounted) setState(() {});
  }

  static bool _looksLikeImage(String name, String mime) {
    if (mime.startsWith('image/')) return true;
    final lower = name.toLowerCase();
    return lower.endsWith('.jpg') ||
        lower.endsWith('.jpeg') ||
        lower.endsWith('.png') ||
        lower.endsWith('.gif') ||
        lower.endsWith('.webp') ||
        lower.endsWith('.bmp');
  }

  static String _mimeFromName(String name, String? ext) {
    final e = (ext ?? name.split('.').last).toLowerCase();
    return switch (e) {
      'jpg' || 'jpeg' => 'image/jpeg',
      'png' => 'image/png',
      'gif' => 'image/gif',
      'webp' => 'image/webp',
      'pdf' => 'application/pdf',
      'txt' => 'text/plain',
      'md' => 'text/markdown',
      'json' => 'application/json',
      'csv' => 'text/csv',
      _ => 'application/octet-stream',
    };
  }

  void _showAttachmentSheet() {
    showAttachmentPickerSheet(
      context: context,
      onGallery: _pickImageFromGallery,
      onCamera: _pickImageFromCamera,
      onFile: _pickDocument,
    );
  }

  Future<void> _submitMessage() async {
    final text = _input.text;
    if (text.trim().isEmpty && _pendingAttachments.isEmpty) return;

    final state = context.read<AppState>();
    if (state.chatBusy) {
      await state.stopChat();
      if (!mounted) return;
    }

    final attachments = List<PendingAttachment>.from(_pendingAttachments);
    try {
      await state.sendUserMessage(text: text, attachments: attachments);
      if (!mounted) return;
      _input.clear();
      setState(() => _pendingAttachments.clear());
      _scrollToEnd();
    } catch (e) {
      if (mounted) {
        final msg = e is HermesApiException ? e.message : e.toString();
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('发送失败: $msg')),
        );
      }
    }
  }

  Future<void> _submitSuggestion(String text) async {
    final state = context.read<AppState>();
    if (state.chatBusy) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('上一条消息仍在处理中，请稍候或点停止')),
        );
      }
      return;
    }
    if (!state.readyForChat) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('请先在「我的」中完成模型与 API Key 配置'),
          ),
        );
      }
      return;
    }
    try {
      await state.sendUserMessage(text: text);
      if (mounted) _scrollToEnd();
    } catch (e) {
      if (mounted) {
        final msg = e is HermesApiException ? e.message : e.toString();
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('发送失败: $msg')),
        );
      }
    }
  }

  Future<void> _toggleRecord() async {
    if (_recording) {
      final path = await _recorder.stop();
      setState(() => _recording = false);
      if (path == null) return;
      if (kIsWeb) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Web 端录音上传即将支持，请先用文字输入')),
          );
        }
        return;
      }
      final bytes = await readPathBytes(path);
      final state = context.read<AppState>();
      try {
        final res = await state.api.transcribeBytes(bytes);
        final text = (res['transcript'] as String?)?.trim() ?? '';
        if (text.isNotEmpty) {
          await state.sendTranscript(text);
          _scrollToEnd();
        }
      } catch (e) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('语音识别失败: $e')),
          );
        }
      }
      return;
    }

    if (!await _recorder.hasPermission()) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('需要麦克风权限')),
        );
      }
      return;
    }
    final outPath = kIsWeb ? '' : await tempWavPath();
    await _recorder.start(
      const RecordConfig(encoder: AudioEncoder.wav),
      path: outPath,
    );
    setState(() => _recording = true);
  }

  Future<void> _speak() async {
    final state = context.read<AppState>();
    try {
      final path = await state.speakLastReply();
      if (path != null && !kIsWeb) {
        await _player.play(DeviceFileSource(path));
      } else if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('TTS 完成（Web 请查看返回路径）')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('TTS 失败: $e')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    _maybeShowApprovalDialog(state);
    _scrollToEnd();

    final p = context.hermes;

    return Scaffold(
      key: _scaffoldKey,
      backgroundColor: p.background,
      drawer: const HermesSessionDrawer(),
      onDrawerChanged: (open) {
        if (open) context.read<AppState>().refreshSessions();
      },
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.menu_rounded),
          onPressed: () => _scaffoldKey.currentState?.openDrawer(),
        ),
        title: Row(
          children: [
            Container(
              width: 32,
              height: 32,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                gradient: HermesTheme.goldGradient,
              ),
              child: const Icon(
                Icons.auto_awesome,
                size: 16,
                color: HermesColors.obsidian,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: GestureDetector(
                onTap: state.chatBusy
                    ? null
                    : () async {
                        final title = await showSessionRenameDialog(
                          context,
                          initialTitle: state.currentSessionLabel,
                        );
                        if (title == null || !context.mounted) return;
                        await state.renameSession(
                            state.config.sessionId, title);
                        if (context.mounted) {
                          showHermesToast(context, '会话已重命名');
                        }
                      },
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      state.currentSessionLabel,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    Text(
                      '点击重命名 · Hermes',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            fontSize: 11,
                            color: HermesColors.muted,
                          ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
        actions: [
          _AppBarAction(
            icon: Icons.add_comment_outlined,
            tooltip: '新会话',
            onPressed: state.chatBusy
                ? null
                : () async {
                    try {
                      await state.newChatSession();
                    } catch (e) {
                      if (context.mounted) {
                        showHermesToast(context, '新建会话失败: $e');
                      }
                    }
                  },
          ),
          _AppBarAction(
            icon: Icons.logout_rounded,
            tooltip: '退出',
            onPressed: () async {
              await state.logout();
            },
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: Column(
        children: [
          if (state.error != null)
            Container(
              width: double.infinity,
              margin: const EdgeInsets.fromLTRB(12, 8, 12, 0),
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              decoration: BoxDecoration(
                color: const Color(0xFF7F1D1D).withValues(alpha: 0.5),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                    color: HermesColors.errorSoft.withValues(alpha: 0.3)),
              ),
              child: Text(
                state.error!,
                style: const TextStyle(
                    fontSize: 12, color: HermesColors.errorSoft),
              ),
            ),
          if (state.activityLabel != null)
            HermesActivityStrip(label: state.activityLabel!),
          Expanded(
            child: state.messages.isEmpty
                ? _EmptyChatHint(
                    chatBusy: state.chatBusy,
                    readyForChat: state.readyForChat,
                    onSuggestion: _submitSuggestion,
                  )
                : ListView.builder(
                    controller: _scroll,
                    padding: const EdgeInsets.fromLTRB(12, 12, 12, 8),
                    itemCount: state.messages.length,
                    itemBuilder: (context, i) {
                      final m = state.messages[i];
                      final isUser = m.role.name == 'user';
                      return HermesFadeSlideIn(
                        key: ValueKey('msg-$i-${m.role.name}'),
                        delay: Duration(milliseconds: i < 6 ? i * 35 : 0),
                        child: GestureDetector(
                          onLongPress: m.displayText.trim().isEmpty
                              ? null
                              : () => showMessageActions(
                                    context,
                                    text: m.displayText,
                                    isUser: isUser,
                                  ),
                          child: ChatMessageBubble(
                            message: m,
                            onOpenWorkspaceFile: state.openWorkspaceFile,
                            openingWorkspacePath: state.openingWorkspacePath,
                          ),
                        ),
                      );
                    },
                  ),
          ),
          _ChatComposer(
            controller: _input,
            chatBusy: state.chatBusy,
            recording: _recording,
            attachments: _pendingAttachments,
            onRemoveAttachment: _removeAttachment,
            onSend: _submitMessage,
            onAddAttachment: _showAttachmentSheet,
            onToggleRecord: _toggleRecord,
            onSpeak: _speak,
            onStop: state.stopChat,
          ),
        ],
      ),
    );
  }
}

class _AppBarAction extends StatelessWidget {
  const _AppBarAction({
    required this.icon,
    required this.tooltip,
    required this.onPressed,
  });

  final IconData icon;
  final String tooltip;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return IconButton(
      tooltip: tooltip,
      onPressed: onPressed,
      icon: Icon(
        icon,
        size: 22,
        color: HermesPalette.of(context).textPrimary.withValues(alpha: 0.9),
      ),
    );
  }
}

class _EmptyChatHint extends StatelessWidget {
  const _EmptyChatHint({
    required this.onSuggestion,
    required this.chatBusy,
    required this.readyForChat,
  });

  final Future<void> Function(String) onSuggestion;
  final bool chatBusy;
  final bool readyForChat;

  static const _suggestions = [
    '帮我总结今天的待办',
    '武汉今天天气怎么样？',
    '写一封专业的商务邮件',
  ];

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              Icons.wb_twilight_outlined,
              size: 48,
              color: HermesColors.gold.withValues(alpha: 0.6),
            ),
            const SizedBox(height: 20),
            Text(
              '随时为您服务',
              style: Theme.of(context).textTheme.headlineSmall,
            ),
            const SizedBox(height: 8),
            Text(
              '选择下方建议，或直接输入您的问题',
              style: Theme.of(context).textTheme.bodyMedium,
              textAlign: TextAlign.center,
            ),
            if (!readyForChat) ...[
              const SizedBox(height: 16),
              Text(
                '请先在「我的」中配置模型与 API Key',
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: HermesColors.gold,
                    ),
                textAlign: TextAlign.center,
              ),
            ],
            const SizedBox(height: 28),
            Wrap(
              spacing: 10,
              runSpacing: 10,
              alignment: WrapAlignment.center,
              children: _suggestions.map((s) {
                final enabled = readyForChat && !chatBusy;
                return ActionChip(
                  label: Text(s),
                  labelStyle: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: enabled
                            ? HermesColors.ivory
                            : HermesColors.ivory.withValues(alpha: 0.45),
                      ),
                  backgroundColor: HermesColors.charcoal,
                  side: BorderSide(
                    color: enabled
                        ? HermesColors.glassBorder
                        : HermesColors.glassBorder.withValues(alpha: 0.35),
                  ),
                  onPressed: enabled ? () => onSuggestion(s) : null,
                );
              }).toList(),
            ),
          ],
        ),
      ),
    );
  }
}

class _ChatComposer extends StatefulWidget {
  const _ChatComposer({
    required this.controller,
    required this.chatBusy,
    required this.recording,
    required this.attachments,
    required this.onRemoveAttachment,
    required this.onSend,
    required this.onAddAttachment,
    required this.onToggleRecord,
    required this.onSpeak,
    required this.onStop,
  });

  final TextEditingController controller;
  final bool chatBusy;
  final bool recording;
  final List<PendingAttachment> attachments;
  final void Function(String id) onRemoveAttachment;
  final Future<void> Function() onSend;
  final VoidCallback onAddAttachment;
  final VoidCallback onToggleRecord;
  final VoidCallback onSpeak;
  final VoidCallback onStop;

  @override
  State<_ChatComposer> createState() => _ChatComposerState();
}

class _ChatComposerState extends State<_ChatComposer> {
  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_onInputChanged);
  }

  @override
  void dispose() {
    widget.controller.removeListener(_onInputChanged);
    super.dispose();
  }

  void _onInputChanged() => setState(() {});

  bool get _canSend {
    return widget.controller.text.trim().isNotEmpty ||
        widget.attachments.isNotEmpty;
  }

  @override
  Widget build(BuildContext context) {
    final p = HermesPalette.of(context);
    return ClipRRect(
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 12, sigmaY: 12),
        child: Container(
          decoration: BoxDecoration(
            color: p.surface.withValues(alpha: 0.95),
            border: Border(top: BorderSide(color: p.glassBorder)),
          ),
          child: SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(8, 10, 12, 10),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  ComposerAttachmentStrip(
                    attachments: widget.attachments,
                    enabled: !widget.chatBusy,
                    onRemove: widget.onRemoveAttachment,
                  ),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      _ComposerIcon(
                        icon: Icons.add_circle_outline,
                        onPressed:
                            widget.chatBusy ? null : widget.onAddAttachment,
                      ),
                      _ComposerIcon(
                        icon: widget.recording
                            ? Icons.stop_circle
                            : Icons.mic_none_outlined,
                        color: widget.recording ? Colors.redAccent : null,
                        onPressed:
                            widget.chatBusy ? null : widget.onToggleRecord,
                      ),
                      _ComposerIcon(
                        icon: Icons.volume_up_outlined,
                        onPressed: widget.chatBusy ? null : widget.onSpeak,
                      ),
                      if (widget.chatBusy)
                        _ComposerIcon(
                          icon: Icons.stop_circle_outlined,
                          color: Colors.redAccent,
                          onPressed: widget.onStop,
                        ),
                      Expanded(
                        child: TextField(
                          controller: widget.controller,
                          minLines: 1,
                          maxLines: 5,
                          style: TextStyle(color: p.textPrimary),
                          decoration: InputDecoration(
                            hintText: widget.chatBusy
                                ? '输入新消息将停止当前回复并发送…'
                                : widget.attachments.isNotEmpty
                                    ? '输入消息，与附件一起发送…'
                                    : '输入消息，点 + 添加图片或文件…',
                            filled: true,
                            fillColor: p.background.withValues(alpha: 0.65),
                            contentPadding: const EdgeInsets.symmetric(
                              horizontal: 16,
                              vertical: 12,
                            ),
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(22),
                              borderSide: BorderSide.none,
                            ),
                          ),
                          onSubmitted: _canSend ? (_) => widget.onSend() : null,
                        ),
                      ),
                      const SizedBox(width: 8),
                      Material(
                        color: Colors.transparent,
                        child: InkWell(
                          onTap: _canSend ? () => widget.onSend() : null,
                          borderRadius: BorderRadius.circular(24),
                          child: Ink(
                            width: 48,
                            height: 48,
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              gradient:
                                  _canSend ? HermesTheme.goldGradient : null,
                              color: _canSend ? null : HermesColors.stone,
                            ),
                            child: Icon(
                              Icons.arrow_upward_rounded,
                              color: _canSend
                                  ? HermesColors.obsidian
                                  : HermesColors.muted,
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _ComposerIcon extends StatelessWidget {
  const _ComposerIcon({
    required this.icon,
    required this.onPressed,
    this.color,
  });

  final IconData icon;
  final VoidCallback? onPressed;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    return IconButton(
      onPressed: onPressed,
      icon: Icon(icon, size: 22, color: color ?? HermesColors.muted),
      visualDensity: VisualDensity.compact,
    );
  }
}
