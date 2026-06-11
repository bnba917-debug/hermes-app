import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/app_state.dart';
import '../theme/hermes_palette.dart';
import '../theme/hermes_theme.dart';
import '../widgets/hermes_motion.dart';
import '../widgets/hermes_shell.dart';
import '../widgets/profile_ui.dart';
import 'legal_document_screen.dart';
import 'model_settings_screen.dart';

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  Map<String, dynamic>? _usage;
  bool _loadingUsage = false;

  @override
  void initState() {
    super.initState();
    _loadUsage();
  }

  Future<void> _loadUsage() async {
    setState(() => _loadingUsage = true);
    try {
      final data = await context.read<AppState>().api.usage();
      if (mounted) setState(() => _usage = data);
    } catch (_) {
      if (mounted) setState(() => _usage = null);
    } finally {
      if (mounted) setState(() => _loadingUsage = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    final p = context.hermes;
    final uid = state.config.userId ?? '—';

    return HermesAmbientBackground(
      animate: false,
      child: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 28),
          children: [
            const HermesBrandHeader(title: '我的', compact: true),
            const SizedBox(height: 20),
            HermesSolidCard(
              padding: const EdgeInsets.all(20),
              child: Row(
                children: [
                  Container(
                    width: 64,
                    height: 64,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      gradient: HermesTheme.goldGradient,
                      boxShadow: [
                        BoxShadow(
                          color: HermesColors.gold.withValues(alpha: 0.35),
                          blurRadius: 16,
                          offset: const Offset(0, 6),
                        ),
                      ],
                    ),
                    child: const Icon(
                      Icons.person_rounded,
                      size: 34,
                      color: HermesColors.obsidian,
                    ),
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Hermes 账户',
                          style: Theme.of(context).textTheme.titleMedium?.copyWith(
                                color: p.textPrimary,
                                fontWeight: FontWeight.w700,
                              ),
                        ),
                        const SizedBox(height: 6),
                        Text(
                          uid,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                                color: p.textSecondary,
                                fontFamily: 'monospace',
                              ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 22),
            const ProfileSectionTitle('设置'),
            HermesSolidCard(
              child: Column(
                children: [
                  ProfileMenuTile(
                    icon: Icons.hub_outlined,
                    title: '模型与 API Key',
                    subtitle: '更换推理模型或更新密钥',
                    onTap: () {
                      Navigator.of(context).push(
                        hermesFadeRoute(const ModelSettingsScreen()),
                      );
                    },
                  ),
                  Divider(height: 1, color: p.cardBorder.withValues(alpha: 0.5)),
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '外观主题',
                          style: Theme.of(context).textTheme.titleSmall?.copyWith(
                                color: p.textPrimary,
                              ),
                        ),
                        const SizedBox(height: 12),
                        ProfileThemeSelector(
                          value: state.themeMode,
                          onChanged: state.setThemeMode,
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 22),
            const ProfileSectionTitle('用量'),
            HermesSolidCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(
                        '今日用量',
                        style: Theme.of(context).textTheme.titleSmall?.copyWith(
                              color: p.textPrimary,
                            ),
                      ),
                      const Spacer(),
                      IconButton(
                        tooltip: '刷新',
                        icon: Icon(Icons.refresh_rounded, color: p.textSecondary),
                        onPressed: _loadingUsage ? null : _loadUsage,
                      ),
                    ],
                  ),
                  if (_loadingUsage)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: 16),
                      child: Center(child: CircularProgressIndicator()),
                    )
                  else if (_usage == null)
                    Text(
                      '暂无数据',
                      style: Theme.of(context).textTheme.bodyMedium,
                    )
                  else ...[
                    ProfileStatTile(
                      label: '今日对话',
                      value:
                          '${_usage!['chats_today'] ?? 0} / ${_usage!['daily_chat_limit'] ?? '∞'}',
                    ),
                    const SizedBox(height: 8),
                    ProfileStatTile(
                      label: '今日 Token',
                      value:
                          '${_usage!['tokens_today'] ?? 0} / ${_usage!['daily_token_limit'] ?? '∞'}',
                    ),
                    const SizedBox(height: 8),
                    ProfileStatTile(
                      label: '进行中会话',
                      value:
                          '${_usage!['active_chats'] ?? 0} / ${_usage!['max_concurrent_chats_per_user'] ?? '—'}',
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(height: 22),
            const ProfileSectionTitle('隐私与条款'),
            HermesSolidCard(
              child: Column(
                children: [
                  ProfileMenuTile(
                    icon: Icons.description_outlined,
                    title: '服务条款',
                    subtitle: 'Terms of Service',
                    onTap: () {
                      Navigator.of(context).push(
                        hermesFadeRoute(
                          LegalDocumentScreen(
                            doc: 'terms',
                            title: '服务条款',
                            api: state.api,
                          ),
                        ),
                      );
                    },
                  ),
                  Divider(height: 1, color: p.cardBorder.withValues(alpha: 0.5)),
                  ProfileMenuTile(
                    icon: Icons.privacy_tip_outlined,
                    title: '隐私政策',
                    subtitle: 'Privacy Policy',
                    onTap: () {
                      Navigator.of(context).push(
                        hermesFadeRoute(
                          LegalDocumentScreen(
                            doc: 'privacy',
                            title: '隐私政策',
                            api: state.api,
                          ),
                        ),
                      );
                    },
                  ),
                  Divider(height: 1, color: p.cardBorder.withValues(alpha: 0.5)),
                  ProfileMenuTile(
                    icon: Icons.schedule_outlined,
                    title: '数据保留说明',
                    subtitle: 'Data retention & deletion',
                    onTap: () {
                      Navigator.of(context).push(
                        hermesFadeRoute(
                          LegalDocumentScreen(
                            doc: 'data-retention',
                            title: '数据保留',
                            api: state.api,
                          ),
                        ),
                      );
                    },
                  ),
                ],
              ),
            ),
            const SizedBox(height: 22),
            const ProfileSectionTitle('账户'),
            HermesSolidCard(
              child: Column(
                children: [
                  ProfileMenuTile(
                    icon: Icons.devices_other_outlined,
                    title: '退出所有设备',
                    subtitle: '撤销全部 refresh token',
                    onTap: () async {
                      final ok = await showDialog<bool>(
                        context: context,
                        builder: (ctx) => AlertDialog(
                          title: const Text('退出所有设备？'),
                          content: const Text('将撤销所有已登录设备的刷新令牌。'),
                          actions: [
                            TextButton(
                              onPressed: () => Navigator.pop(ctx, false),
                              child: const Text('取消'),
                            ),
                            FilledButton(
                              onPressed: () => Navigator.pop(ctx, true),
                              child: const Text('确认'),
                            ),
                          ],
                        ),
                      );
                      if (ok == true && context.mounted) {
                        await state.logoutAllDevices();
                      }
                    },
                  ),
                  Divider(height: 1, color: p.cardBorder.withValues(alpha: 0.5)),
                  ProfileMenuTile(
                    icon: Icons.delete_forever_outlined,
                    title: '注销账户',
                    subtitle: '永久删除数据，不可恢复',
                    onTap: () => _confirmDeleteAccount(context, state),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 24),
            Center(
              child: TextButton.icon(
                onPressed: () async => state.logout(),
                icon: Icon(Icons.logout_rounded, color: p.textSecondary, size: 20),
                label: Text(
                  '退出登录',
                  style: TextStyle(
                    color: p.textSecondary,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _confirmDeleteAccount(BuildContext context, AppState state) async {
    final code = await showDialog<String>(
      context: context,
      builder: (ctx) => _DeleteAccountDialog(state: state),
    );
    if (code == null || code.isEmpty || !context.mounted) return;
    try {
      await state.deleteAccount(code: code);
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('账户已注销')),
        );
      }
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('注销失败: $e')),
        );
      }
    }
  }
}

class _DeleteAccountDialog extends StatefulWidget {
  const _DeleteAccountDialog({required this.state});

  final AppState state;

  @override
  State<_DeleteAccountDialog> createState() => _DeleteAccountDialogState();
}

class _DeleteAccountDialogState extends State<_DeleteAccountDialog> {
  final _codeController = TextEditingController();
  bool _sending = false;
  bool _deleting = false;
  String? _phoneHint;
  String? _error;

  @override
  void dispose() {
    _codeController.dispose();
    super.dispose();
  }

  Future<void> _sendSms() async {
    setState(() {
      _sending = true;
      _error = null;
    });
    try {
      final res = await widget.state.sendDeleteAccountSms();
      if (mounted) {
        setState(() {
          _phoneHint = res['phone']?.toString();
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() => _error = e.toString());
      }
    } finally {
      if (mounted) {
        setState(() => _sending = false);
      }
    }
  }

  Future<void> _submit() async {
    final code = _codeController.text.trim();
    if (code.isEmpty) {
      setState(() => _error = '请输入短信验证码');
      return;
    }
    if (!mounted) return;
    Navigator.pop(context, code);
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('确认注销账户？'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              '将删除您的会话、工作区文件、模型配置与记忆数据。此操作不可撤销。',
            ),
            const SizedBox(height: 16),
            if (_phoneHint != null)
              Text('验证码已发送至 $_phoneHint'),
            TextField(
              controller: _codeController,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                labelText: '短信验证码',
                hintText: '6 位验证码',
              ),
            ),
            if (_error != null) ...[
              const SizedBox(height: 8),
              Text(
                _error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: _deleting ? null : () => Navigator.pop(context),
          child: const Text('取消'),
        ),
        TextButton(
          onPressed: _sending ? null : _sendSms,
          child: Text(_sending ? '发送中…' : '发送验证码'),
        ),
        FilledButton(
          style: FilledButton.styleFrom(
            backgroundColor: HermesColors.errorSoft,
          ),
          onPressed: _deleting ? null : _submit,
          child: const Text('永久注销'),
        ),
      ],
    );
  }
}
