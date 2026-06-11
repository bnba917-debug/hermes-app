import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/app_state.dart';
import '../theme/hermes_palette.dart';
import '../theme/hermes_theme.dart';
import '../widgets/hermes_shell.dart';
import '../widgets/hermes_toast.dart';

class ModelSettingsScreen extends StatefulWidget {
  const ModelSettingsScreen({super.key});

  @override
  State<ModelSettingsScreen> createState() => _ModelSettingsScreenState();
}

class _ModelSettingsScreenState extends State<ModelSettingsScreen> {
  Map<String, dynamic>? _status;
  List<Map<String, dynamic>> _models = [];
  String? _selectedModelId;
  final _apiKey = TextEditingController();
  bool _loading = true;
  bool _saving = false;
  bool _obscureKey = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _apiKey.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    final state = context.read<AppState>();
    try {
      final status = await state.api.getInference();
      if (state.onboardingModels.isEmpty) {
        state.onboardingModels = await state.api.onboardingModels();
      }
      _models = state.onboardingModels;
      _status = status;
      final currentModel = status['model']?.toString();
      if (currentModel != null && currentModel.isNotEmpty) {
        _selectedModelId = currentModel;
        final match = _models.where((m) => m['id'] == currentModel);
        if (match.isEmpty && _models.isNotEmpty) {
          _selectedModelId = _models.first['id'] as String?;
        }
      } else if (_models.isNotEmpty) {
        _selectedModelId = _models.first['id'] as String?;
      }
    } catch (e) {
      if (mounted) showHermesToast(context, '加载失败: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Map<String, dynamic>? _modelEntry(String? id) {
    if (id == null) return null;
    for (final m in _models) {
      if (m['id'] == id) return m;
    }
    return null;
  }

  Future<void> _save() async {
    final modelId = _selectedModelId;
    if (modelId == null) {
      showHermesToast(context, '请选择模型');
      return;
    }
    final entry = _modelEntry(modelId);
    final key = _apiKey.text.trim();
    if (key.isEmpty && _status?['api_key_configured'] != true) {
      showHermesToast(context, '请填写 API Key');
      return;
    }

    setState(() => _saving = true);
    try {
      final state = context.read<AppState>();
      final data = await state.api.putInference(
        apiKey: key.isEmpty ? null : key,
        model: modelId,
        provider: entry?['provider'] as String?,
        apiKeyEnv: entry?['api_key_env'] as String?,
      );
      if (mounted) {
        setState(() => _status = data);
        _apiKey.clear();
        await state.refreshOnboardingStatus();
        showHermesToast(context, '模型配置已保存');
      }
    } catch (e) {
      if (mounted) showHermesToast(context, '保存失败: $e');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.hermes;

    return Scaffold(
      backgroundColor: p.background,
      appBar: AppBar(
        title: const Text('模型与 API Key'),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios_new, size: 20),
          onPressed: () => Navigator.of(context).pop(),
        ),
      ),
      body: HermesAmbientBackground(
        animate: true,
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : ListView(
                padding: const EdgeInsets.fromLTRB(20, 8, 20, 32),
                children: [
                  if (_status != null) ...[
                    HermesSolidCard(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '当前配置',
                            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                                  color: p.textPrimary,
                                ),
                          ),
                          const SizedBox(height: 12),
                          _InfoRow(
                            label: '模型',
                            value: _status!['model']?.toString() ?? '—',
                          ),
                          _InfoRow(
                            label: '提供商',
                            value: _status!['provider']?.toString() ?? '—',
                          ),
                          _InfoRow(
                            label: 'API Key',
                            value: (_status!['api_key_configured'] == true)
                                ? '已配置 (${_status!['api_key_env'] ?? 'env'})'
                                : '未配置',
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),
                  ],
                  Text(
                    '更换模型',
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                          color: p.textPrimary,
                        ),
                  ),
                  const SizedBox(height: 12),
                  ..._models.map((m) {
                    final id = m['id'] as String? ?? '';
                    final label = m['label'] as String? ?? id;
                    final selected = _selectedModelId == id;
                    return Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Material(
                        color: Colors.transparent,
                        child: InkWell(
                          borderRadius: BorderRadius.circular(14),
                          onTap: () => setState(() => _selectedModelId = id),
                          child: AnimatedContainer(
                            duration: const Duration(milliseconds: 180),
                            padding: const EdgeInsets.all(14),
                            decoration: BoxDecoration(
                              borderRadius: BorderRadius.circular(14),
                              border: Border.all(
                                color: selected
                                    ? HermesColors.gold
                                    : p.cardBorder,
                              ),
                              color: selected
                                  ? HermesColors.gold.withValues(alpha: 0.12)
                                  : p.surfaceElevated,
                            ),
                            child: Row(
                              children: [
                                Icon(
                                  selected
                                      ? Icons.radio_button_checked
                                      : Icons.radio_button_off,
                                  color: selected
                                      ? HermesColors.gold
                                      : p.textMuted,
                                  size: 20,
                                ),
                                const SizedBox(width: 12),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        label,
                                        style: TextStyle(
                                          color: p.textPrimary,
                                          fontWeight: FontWeight.w600,
                                        ),
                                      ),
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
                      ),
                    );
                  }),
                  const SizedBox(height: 16),
                  HermesSolidCard(
                    padding: const EdgeInsets.all(16),
                    child: TextField(
                      controller: _apiKey,
                      obscureText: _obscureKey,
                      style: TextStyle(color: p.textPrimary),
                      decoration: InputDecoration(
                        labelText: '新 API Key（留空则保留原 Key）',
                        hintText: 'sk-...',
                        border: InputBorder.none,
                        enabledBorder: InputBorder.none,
                        focusedBorder: InputBorder.none,
                        suffixIcon: IconButton(
                          icon: Icon(
                            _obscureKey
                                ? Icons.visibility_outlined
                                : Icons.visibility_off_outlined,
                            color: p.textMuted,
                          ),
                          onPressed: () =>
                              setState(() => _obscureKey = !_obscureKey),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 24),
                  HermesGoldButton(
                    label: '保存配置',
                    icon: Icons.save_outlined,
                    loading: _saving,
                    onPressed: _saving ? null : _save,
                  ),
                ],
              ),
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final p = context.hermes;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 72,
            child: Text(
              label,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: p.textSecondary,
                  ),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: p.textPrimary,
                    fontWeight: FontWeight.w500,
                  ),
            ),
          ),
        ],
      ),
    );
  }
}
