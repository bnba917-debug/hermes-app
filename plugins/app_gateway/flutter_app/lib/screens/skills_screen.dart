import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/app_state.dart';
import '../theme/hermes_palette.dart';
import '../theme/hermes_theme.dart';
import '../widgets/hermes_shell.dart';
import '../widgets/skill_ui_helpers.dart';

class SkillsScreen extends StatefulWidget {
  const SkillsScreen({super.key, this.embedded = false});

  final bool embedded;

  @override
  State<SkillsScreen> createState() => _SkillsScreenState();
}

class _SkillsScreenState extends State<SkillsScreen> {
  String _search = '';
  String? _scopeFilter;
  final _searchController = TextEditingController();
  bool _initialLoadTriggered = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _ensureLoaded());
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _ensureLoaded() async {
    if (!mounted || _initialLoadTriggered) return;
    _initialLoadTriggered = true;
    final state = context.read<AppState>();
    if (state.skills.isEmpty && !state.skillsLoading) {
      await state.refreshSkills();
    }
  }

  Future<void> _load() => context.read<AppState>().refreshSkills();

  Map<String, int> _scopeCounts(List<Map<String, dynamic>> skills) {
    final counts = <String, int>{};
    for (final skill in skills) {
      final scope = skill['scope']?.toString() ?? 'other';
      counts[scope] = (counts[scope] ?? 0) + 1;
    }
    return counts;
  }

  List<SkillSection> _sections(List<Map<String, dynamic>> skills) => groupSkills(
        skills,
        scopeFilter: _scopeFilter,
        searchQuery: _search,
      );

  Widget _buildHeader(HermesPalette palette, List<Map<String, dynamic>> skills) {
    final counts = _scopeCounts(skills);
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TextField(
            controller: _searchController,
            onChanged: (value) => setState(() => _search = value),
            style: TextStyle(color: palette.textPrimary),
            decoration: InputDecoration(
              hintText: '搜索技能名称、描述或分类…',
              hintStyle: TextStyle(color: palette.textMuted),
              prefixIcon: Icon(Icons.search_rounded, color: palette.textMuted),
              suffixIcon: _search.isNotEmpty
                  ? IconButton(
                      icon: Icon(Icons.close_rounded, color: palette.textMuted),
                      onPressed: () {
                        _searchController.clear();
                        setState(() => _search = '');
                      },
                    )
                  : null,
              filled: true,
              fillColor: palette.cardFill,
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(14),
                borderSide: BorderSide(color: palette.cardBorder),
              ),
              enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(14),
                borderSide: BorderSide(color: palette.cardBorder),
              ),
              focusedBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(14),
                borderSide: const BorderSide(color: HermesColors.gold, width: 1.5),
              ),
              contentPadding: const EdgeInsets.symmetric(horizontal: 4, vertical: 12),
            ),
          ),
          const SizedBox(height: 12),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: [
                _ScopeChip(
                  label: '全部 ${skills.length}',
                  selected: _scopeFilter == null,
                  accent: HermesColors.gold,
                  onTap: () => setState(() => _scopeFilter = null),
                ),
                for (final style in SkillScopeStyle.styles)
                  if ((counts[style.id] ?? 0) > 0) ...[
                    const SizedBox(width: 8),
                    _ScopeChip(
                      label: '${style.label} ${counts[style.id]}',
                      selected: _scopeFilter == style.id,
                      accent: style.accent,
                      onTap: () => setState(
                        () => _scopeFilter =
                            _scopeFilter == style.id ? null : style.id,
                      ),
                    ),
                  ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSectionHeader(SkillSection section, HermesPalette palette) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 18, 16, 8),
      child: Row(
        children: [
          Container(
            width: 4,
            height: 22,
            decoration: BoxDecoration(
              color: section.scope.accent,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
          const SizedBox(width: 10),
          Icon(section.scope.icon, size: 18, color: section.scope.accent),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              section.title,
              style: TextStyle(
                color: palette.textPrimary,
                fontWeight: FontWeight.w700,
                fontSize: 15,
              ),
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
            decoration: BoxDecoration(
              color: section.scope.accent.withValues(alpha: 0.15),
              borderRadius: BorderRadius.circular(999),
            ),
            child: Text(
              '${section.skills.length}',
              style: TextStyle(
                color: section.scope.accent,
                fontSize: 12,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSkillTile(
    Map<String, dynamic> skill,
    SkillScopeStyle scopeStyle,
    HermesPalette palette,
  ) {
    final name = skill['name']?.toString() ?? '';
    final desc = skill['description']?.toString() ?? '';
    final disabled = skill['disabled'] == true;
    final category = skill['category']?.toString() ?? categoryFromPath(
          skill['path']?.toString() ?? '',
        );

    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
      child: Container(
        decoration: BoxDecoration(
          color: palette.cardFill,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(
            color: disabled
                ? palette.cardBorder
                : scopeStyle.accent.withValues(alpha: 0.45),
          ),
          boxShadow: disabled
              ? null
              : [
                  BoxShadow(
                    color: scopeStyle.accent.withValues(alpha: 0.08),
                    blurRadius: 12,
                    offset: const Offset(0, 4),
                  ),
                ],
        ),
        child: IntrinsicHeight(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Container(
                width: 5,
                decoration: BoxDecoration(
                  color: disabled
                      ? palette.textMuted.withValues(alpha: 0.35)
                      : scopeStyle.accent,
                  borderRadius: const BorderRadius.horizontal(
                    left: Radius.circular(14),
                  ),
                ),
              ),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Container(
                        width: 42,
                        height: 42,
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(12),
                          color: scopeStyle.accent.withValues(alpha: 0.14),
                          border: Border.all(
                            color: scopeStyle.accent.withValues(alpha: 0.35),
                          ),
                        ),
                        child: Icon(
                          scopeStyle.icon,
                          size: 20,
                          color: scopeStyle.accent,
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                Expanded(
                                  child: Text(
                                    name,
                                    style: TextStyle(
                                      color: disabled
                                          ? palette.textMuted
                                          : palette.textPrimary,
                                      fontWeight: FontWeight.w700,
                                      fontSize: 15,
                                    ),
                                  ),
                                ),
                                if (disabled)
                                  _Badge(
                                    label: '已禁用',
                                    color: palette.textMuted,
                                  ),
                              ],
                            ),
                            if (desc.isNotEmpty) ...[
                              const SizedBox(height: 6),
                              Text(
                                desc,
                                style: TextStyle(
                                  color: palette.textSecondary,
                                  fontSize: 13,
                                  height: 1.35,
                                ),
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis,
                              ),
                            ],
                            const SizedBox(height: 8),
                            Wrap(
                              spacing: 6,
                              runSpacing: 6,
                              children: [
                                _Badge(
                                  label: scopeStyle.label,
                                  color: scopeStyle.accent,
                                ),
                                _Badge(
                                  label: category,
                                  color: palette.textMuted,
                                  outlined: true,
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildBody(
    HermesPalette palette,
    List<Map<String, dynamic>> skills,
    bool loading,
    String? error,
  ) {
    if (loading && skills.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }
    if (error != null && skills.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(
            error,
            style: const TextStyle(color: HermesColors.errorSoft),
            textAlign: TextAlign.center,
          ),
        ),
      );
    }

    final sections = _sections(skills);

    return CustomScrollView(
      slivers: [
        SliverToBoxAdapter(child: _buildHeader(palette, skills)),
        if (sections.isEmpty)
          SliverFillRemaining(
            hasScrollBody: false,
            child: Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      Icons.search_off_rounded,
                      size: 48,
                      color: palette.textMuted,
                    ),
                    const SizedBox(height: 12),
                    Text(
                      _search.isNotEmpty || _scopeFilter != null
                          ? '没有匹配的技能'
                          : '暂无技能',
                      style: TextStyle(color: palette.textSecondary),
                    ),
                    if (_search.isNotEmpty || _scopeFilter != null) ...[
                      const SizedBox(height: 8),
                      TextButton(
                        onPressed: () {
                          _searchController.clear();
                          setState(() {
                            _search = '';
                            _scopeFilter = null;
                          });
                        },
                        child: const Text('清除筛选'),
                      ),
                    ],
                  ],
                ),
              ),
            ),
          )
        else
          for (final section in sections) ...[
            SliverToBoxAdapter(child: _buildSectionHeader(section, palette)),
            SliverList(
              delegate: SliverChildBuilderDelegate(
                (context, index) => _buildSkillTile(
                  section.skills[index],
                  section.scope,
                  palette,
                ),
                childCount: section.skills.length,
              ),
            ),
          ],
        const SliverToBoxAdapter(child: SizedBox(height: 24)),
      ],
    );
  }

  PreferredSizeWidget _appBar(
    List<Map<String, dynamic>> skills,
    bool loading,
    String? error,
  ) {
    final enabledCount =
        skills.where((s) => s['disabled'] != true).length;
    return AppBar(
      title: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('技能库'),
          if (!loading && error == null)
            Text(
              '共 ${skills.length} 个 · 可用 $enabledCount',
              style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: context.hermes.textMuted,
                  ),
            ),
        ],
      ),
      automaticallyImplyLeading: !widget.embedded,
      leading: widget.embedded
          ? null
          : IconButton(
              icon: const Icon(Icons.arrow_back_ios_new, size: 20),
              onPressed: () => Navigator.of(context).pop(),
            ),
      actions: [
        IconButton(
          icon: const Icon(Icons.refresh_rounded),
          onPressed: _load,
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.hermes;
    final app = context.watch<AppState>();
    final skills = app.skills;
    final loading = app.skillsLoading;
    final error = app.skillsError;
    return Scaffold(
      backgroundColor: p.background,
      appBar: _appBar(skills, loading, error),
      body: HermesAmbientBackground(
        animate: true,
        child: _buildBody(p, skills, loading, error),
      ),
    );
  }
}

class _ScopeChip extends StatelessWidget {
  const _ScopeChip({
    required this.label,
    required this.selected,
    required this.accent,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final Color accent;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return FilterChip(
      label: Text(label),
      selected: selected,
      onSelected: (_) => onTap(),
      showCheckmark: false,
      labelStyle: TextStyle(
        color: selected ? accent : context.hermes.textSecondary,
        fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
        fontSize: 12,
      ),
      backgroundColor: context.hermes.cardFill,
      selectedColor: accent.withValues(alpha: 0.18),
      side: BorderSide(
        color: selected ? accent : context.hermes.cardBorder,
      ),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
    );
  }
}

class _Badge extends StatelessWidget {
  const _Badge({
    required this.label,
    required this.color,
    this.outlined = false,
  });

  final String label;
  final Color color;
  final bool outlined;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: outlined ? Colors.transparent : color.withValues(alpha: 0.14),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: color.withValues(alpha: outlined ? 0.35 : 0.25)),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: color,
          fontSize: 10,
          fontWeight: FontWeight.w600,
          letterSpacing: 0.3,
        ),
      ),
    );
  }
}
