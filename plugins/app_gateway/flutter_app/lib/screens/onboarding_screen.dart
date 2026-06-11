import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/app_state.dart';
import '../theme/hermes_palette.dart';
import '../theme/hermes_theme.dart';
import '../widgets/hermes_form.dart';
import '../widgets/hermes_shell.dart';

class OnboardingScreen extends StatefulWidget {
  const OnboardingScreen({super.key});

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> {
  final _apiKey = TextEditingController();
  String? _selectedModel;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _ensureModels());
  }

  Future<void> _ensureModels() async {
    final state = context.read<AppState>();
    if (state.onboardingModels.isEmpty) {
      try {
        state.onboardingModels = await state.api.onboardingModels();
        if (mounted) setState(() {});
      } catch (_) {}
    }
  }

  @override
  void dispose() {
    _apiKey.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final model = _selectedModel;
    if (model == null || _apiKey.text.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('请选择模型并填写 API Key')),
      );
      return;
    }
    Map<String, dynamic>? entry;
    for (final m in context.read<AppState>().onboardingModels) {
      if (m['id'] == model) {
        entry = m;
        break;
      }
    }
    final provider = (entry?['provider'] as String?) ?? 'openrouter';
    final apiKeyEnv = entry?['api_key_env'] as String?;
    setState(() => _busy = true);
    final state = context.read<AppState>();
    try {
      await state.finishOnboarding(
        apiKey: _apiKey.text.trim(),
        model: model,
        provider: provider,
        apiKeyEnv: apiKeyEnv,
      );
      if (!mounted) return;
      // RootGate switches to ChatScreen when readyForChat becomes true.
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('入驻失败: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    final models = state.onboardingModels;
    if (_selectedModel == null && models.isNotEmpty) {
      _selectedModel = models.first['id'] as String?;
    }

    return Scaffold(
      body: HermesAmbientBackground(
        animate: true,
        child: SafeArea(
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(8, 8, 16, 0),
                child: Row(
                  children: [
                    IconButton(
                      onPressed: () async {
                        await state.logout();
                      },
                      icon: const Icon(Icons.arrow_back_ios_new, size: 20),
                    ),
                    Text(
                      '模型入驻',
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                  ],
                ),
              ),
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(24, 8, 24, 32),
                  children: [
                    const HermesBrandHeader(
                      title: '连接您的模型',
                      subtitle:
                          'BYOK — 密钥仅存于您的独立空间。DeepSeek 官方 Key 请选择「DeepSeek Chat（官方 API）」。',
                      compact: true,
                    ),
                    const SizedBox(height: 24),
                    if (models.isEmpty)
                      const Center(
                        child: Padding(
                          padding: EdgeInsets.all(32),
                          child: CircularProgressIndicator(),
                        ),
                      )
                    else
                      ...models.map((m) {
                        final id = m['id'] as String? ?? '';
                        final label = m['label'] as String? ?? id;
                        final selected = _selectedModel == id;
                        return Padding(
                          padding: const EdgeInsets.only(bottom: 10),
                          child: _ModelTile(
                            label: label,
                            id: id,
                            selected: selected,
                            onTap: () => setState(() => _selectedModel = id),
                          ),
                        );
                      }),
                    const SizedBox(height: 16),
                    HermesFormCard(
                      padding: const EdgeInsets.all(16),
                      child: TextField(
                        controller: _apiKey,
                        obscureText: true,
                        style: hermesFormTextStyle(context),
                        cursorColor: HermesColors.gold,
                        decoration: hermesFormDecoration(
                          context,
                          labelText: 'API Key',
                          hintText: 'sk-...',
                          prefixIcon: Icons.key_outlined,
                        ),
                      ),
                    ),
                    const SizedBox(height: 28),
                    HermesGoldButton(
                      label: '完成并开始对话',
                      icon: Icons.chat_bubble_outline,
                      loading: _busy,
                      onPressed: _busy || models.isEmpty ? null : _submit,
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ModelTile extends StatelessWidget {
  const _ModelTile({
    required this.label,
    required this.id,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final String id;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final p = HermesPalette.of(context);
    final tileBorder =
        p.isDark ? const Color(0xFF78716C) : const Color(0xFFD6D3D1);

    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(16),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            border: Border.all(
              color: selected ? HermesColors.gold : tileBorder,
              width: selected ? 1.5 : 1,
            ),
            color: selected
                ? HermesColors.gold.withValues(alpha: 0.1)
                : (p.isDark
                    ? const Color(0xFF3A3532)
                    : p.surfaceElevated.withValues(alpha: 0.8)),
          ),
          child: Row(
            children: [
              Icon(
                selected
                    ? Icons.radio_button_checked
                    : Icons.radio_button_off,
                color: selected ? HermesColors.gold : HermesColors.muted,
                size: 22,
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      label,
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                            color: p.textPrimary,
                          ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      id,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
