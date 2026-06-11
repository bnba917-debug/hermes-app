import 'package:flutter/material.dart';

/// Visual + grouping helpers for the skills library screen.
class SkillScopeStyle {
  const SkillScopeStyle({
    required this.id,
    required this.label,
    required this.accent,
    required this.icon,
  });

  final String id;
  final String label;
  final Color accent;
  final IconData icon;

  static const styles = <SkillScopeStyle>[
    SkillScopeStyle(
      id: 'bundled_readonly',
      label: '内置',
      accent: Color(0xFF94A3B8),
      icon: Icons.inventory_2_outlined,
    ),
    SkillScopeStyle(
      id: 'public',
      label: '公共',
      accent: Color(0xFF38BDF8),
      icon: Icons.public_outlined,
    ),
    SkillScopeStyle(
      id: 'user',
      label: '我的',
      accent: Color(0xFFEAB308),
      icon: Icons.person_outline,
    ),
    SkillScopeStyle(
      id: 'shared',
      label: '共享',
      accent: Color(0xFFA78BFA),
      icon: Icons.folder_shared_outlined,
    ),
  ];

  static SkillScopeStyle forScope(String scope) {
    final key = scope.trim().toLowerCase();
    for (final style in styles) {
      if (style.id == key) return style;
    }
    return const SkillScopeStyle(
      id: 'other',
      label: '其他',
      accent: Color(0xFF78716C),
      icon: Icons.extension_outlined,
    );
  }
}

class SkillSection {
  SkillSection({
    required this.scope,
    required this.category,
    required this.skills,
  });

  final SkillScopeStyle scope;
  final String category;
  final List<Map<String, dynamic>> skills;

  String get title => '${scope.label} · $category';
}

List<SkillSection> groupSkills(
  List<Map<String, dynamic>> skills, {
  String? scopeFilter,
  String searchQuery = '',
}) {
  final query = searchQuery.trim().toLowerCase();
  final filtered = skills.where((skill) {
    final scope = skill['scope']?.toString() ?? '';
    if (scopeFilter != null && scopeFilter.isNotEmpty && scope != scopeFilter) {
      return false;
    }
    if (query.isEmpty) return true;
    final name = skill['name']?.toString().toLowerCase() ?? '';
    final desc = skill['description']?.toString().toLowerCase() ?? '';
    final category = skill['category']?.toString().toLowerCase() ?? '';
    return name.contains(query) ||
        desc.contains(query) ||
        category.contains(query);
  }).toList();

  final buckets = <String, List<Map<String, dynamic>>>{};
  for (final skill in filtered) {
    final scope = SkillScopeStyle.forScope(skill['scope']?.toString() ?? '');
    final category = _categoryLabel(skill);
    final key = '${scope.id}::$category';
    buckets.putIfAbsent(key, () => []).add(skill);
  }

  final sections = buckets.entries.map((entry) {
    final parts = entry.key.split('::');
    final scope = SkillScopeStyle.forScope(parts.first);
    final category = parts.length > 1 ? parts[1] : '其他';
    final items = List<Map<String, dynamic>>.from(entry.value)
      ..sort(
        (a, b) => (a['name']?.toString() ?? '')
            .compareTo(b['name']?.toString() ?? ''),
      );
    return SkillSection(scope: scope, category: category, skills: items);
  }).toList();

  sections.sort((a, b) {
    final scopeOrder = _scopeOrder(a.scope.id).compareTo(_scopeOrder(b.scope.id));
    if (scopeOrder != 0) return scopeOrder;
    return a.category.compareTo(b.category);
  });
  return sections;
}

int _scopeOrder(String scopeId) {
  switch (scopeId) {
    case 'bundled_readonly':
      return 0;
    case 'public':
      return 1;
    case 'user':
      return 2;
    case 'shared':
      return 3;
    default:
      return 4;
  }
}

String _categoryLabel(Map<String, dynamic> skill) {
  final raw = skill['category']?.toString().trim();
  if (raw != null && raw.isNotEmpty && raw != '_bundled') return raw;
  final path = skill['path']?.toString() ?? '';
  final parts = path
      .split('/')
      .where((p) => p.isNotEmpty && p != 'SKILL.md' && p != '_bundled')
      .toList();
  if (parts.length >= 2) return parts.first;
  return '其他';
}

String categoryFromPath(String path) => _categoryLabel({'path': path});
