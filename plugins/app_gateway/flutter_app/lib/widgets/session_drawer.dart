import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../state/app_state.dart';
import '../theme/hermes_palette.dart';
import '../theme/hermes_theme.dart';
import 'hermes_toast.dart';
import 'hermes_logo.dart';
import 'hermes_shell.dart';
import 'session_rename_dialog.dart';

class HermesSessionDrawer extends StatelessWidget {
  const HermesSessionDrawer({super.key});

  String _formatTime(dynamic raw) {
    if (raw == null) return '';
    final ms = raw is int ? raw : int.tryParse(raw.toString());
    if (ms == null) return '';
    final dt = DateTime.fromMillisecondsSinceEpoch(
      ms > 1e12 ? ms : ms * 1000,
      isUtc: true,
    ).toLocal();
    final now = DateTime.now();
    if (now.difference(dt).inDays == 0) {
      return DateFormat.Hm().format(dt);
    }
    if (now.difference(dt).inDays < 7) {
      return DateFormat.E().add_Hm().format(dt);
    }
    return DateFormat.Md().format(dt);
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    final current = state.config.sessionId;

    final p = HermesPalette.of(context);

    return Drawer(
      backgroundColor: p.surface,
      child: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 16, 20, 12),
              child: Row(
                children: [
                  const HermesLogoMark(size: 40),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '对话',
                          style: Theme.of(context).textTheme.titleLarge,
                        ),
                        Text(
                          state.config.userId ?? '已登录',
                          style: Theme.of(context).textTheme.bodySmall,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: HermesGoldButton(
                label: '新对话',
                icon: Icons.add,
                onPressed: state.chatBusy
                    ? null
                    : () async {
                        Navigator.pop(context);
                        try {
                          await state.newChatSession();
                          await state.refreshSessions();
                        } catch (e) {
                          if (context.mounted) {
                            showHermesToast(context, '新建会话失败: $e');
                          }
                        }
                      },
              ),
            ),
            const SizedBox(height: 16),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20),
              child: Text(
                '历史会话',
                style: Theme.of(context).textTheme.labelLarge?.copyWith(
                      color: HermesColors.muted,
                      fontSize: 11,
                    ),
              ),
            ),
            const SizedBox(height: 8),
            Expanded(
              child: state.sessionsLoading
                  ? const Center(child: CircularProgressIndicator())
                  : state.sessions.isEmpty
                      ? Center(
                          child: Text(
                            '暂无历史会话',
                            style: Theme.of(context).textTheme.bodyMedium,
                          ),
                        )
                      : ListView.builder(
                          padding: const EdgeInsets.symmetric(horizontal: 12),
                          itemCount: state.sessions.length,
                          itemBuilder: (context, i) {
                            final s = state.sessions[i];
                            final sid = s['session_id']?.toString() ?? '';
                            final title = (s['title']?.toString() ?? '').trim();
                            final preview =
                                (s['preview']?.toString() ?? '').trim();
                            final selected = sid == current;
                            final label = title.isNotEmpty
                                ? title
                                : (preview.isNotEmpty
                                    ? preview
                                    : sid);
                            return Padding(
                              padding: const EdgeInsets.only(bottom: 6),
                              child: Material(
                                color: Colors.transparent,
                                child: InkWell(
                                  borderRadius: BorderRadius.circular(14),
                                  onTap: state.chatBusy || selected
                                      ? null
                                      : () async {
                                          Navigator.pop(context);
                                          try {
                                            await state.switchToSession(sid);
                                          } catch (e) {
                                            if (context.mounted) {
                                              showHermesToast(
                                                context,
                                                '切换会话失败: $e',
                                              );
                                            }
                                          }
                                        },
                                  child: AnimatedContainer(
                                    duration: const Duration(milliseconds: 200),
                                    padding: const EdgeInsets.all(14),
                                    decoration: BoxDecoration(
                                      borderRadius: BorderRadius.circular(14),
                                      color: selected
                                          ? HermesColors.gold
                                              .withValues(alpha: 0.12)
                                          : Colors.transparent,
                                      border: Border.all(
                                        color: selected
                                            ? HermesColors.gold
                                            : Colors.transparent,
                                      ),
                                    ),
                                    child: Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        Row(
                                          children: [
                                            Expanded(
                                              child: Text(
                                                label,
                                                maxLines: 1,
                                                overflow: TextOverflow.ellipsis,
                                                style: Theme.of(context)
                                                    .textTheme
                                                    .titleSmall
                                                    ?.copyWith(
                                                      color: p.textPrimary,
                                                      fontWeight: selected
                                                          ? FontWeight.w600
                                                          : FontWeight.w500,
                                                    ),
                                              ),
                                            ),
                                            Text(
                                              _formatTime(s['last_active']),
                                              style: Theme.of(context)
                                                  .textTheme
                                                  .bodySmall
                                                  ?.copyWith(fontSize: 10),
                                            ),
                                            PopupMenuButton<String>(
                                              icon: Icon(
                                                Icons.more_horiz,
                                                size: 18,
                                                color: p.textMuted,
                                              ),
                                              color: p.surfaceElevated,
                                              onSelected: (action) async {
                                                if (action == 'rename') {
                                                  final initial = title.isNotEmpty
                                                      ? title
                                                      : label;
                                                  final next =
                                                      await showSessionRenameDialog(
                                                    context,
                                                    initialTitle: initial,
                                                  );
                                                  if (next == null) return;
                                                  await state.renameSession(
                                                    sid,
                                                    next,
                                                  );
                                                  if (context.mounted) {
                                                    showHermesToast(
                                                      context,
                                                      '已重命名',
                                                    );
                                                  }
                                                } else if (action == 'ai_title') {
                                                  try {
                                                    await state
                                                        .suggestSessionTitleFor(sid);
                                                    if (context.mounted) {
                                                      showHermesToast(
                                                        context,
                                                        '已生成标题',
                                                      );
                                                    }
                                                  } catch (e) {
                                                    if (context.mounted) {
                                                      showHermesToast(
                                                        context,
                                                        '生成失败: $e',
                                                      );
                                                    }
                                                  }
                                                }
                                              },
                                              itemBuilder: (_) => [
                                                PopupMenuItem(
                                                  value: 'rename',
                                                  child: Text(
                                                    '重命名',
                                                    style: TextStyle(
                                                      color: p.textPrimary,
                                                    ),
                                                  ),
                                                ),
                                                PopupMenuItem(
                                                  value: 'ai_title',
                                                  child: Text(
                                                    'AI 生成标题',
                                                    style: TextStyle(
                                                      color: p.textPrimary,
                                                    ),
                                                  ),
                                                ),
                                              ],
                                            ),
                                          ],
                                        ),
                                        if (preview.isNotEmpty &&
                                            title.isNotEmpty) ...[
                                          const SizedBox(height: 4),
                                          Text(
                                            preview,
                                            maxLines: 2,
                                            overflow: TextOverflow.ellipsis,
                                            style: Theme.of(context)
                                                .textTheme
                                                .bodySmall,
                                          ),
                                        ],
                                      ],
                                    ),
                                  ),
                                ),
                              ),
                            );
                          },
                        ),
            ),
          ],
        ),
      ),
    );
  }
}
