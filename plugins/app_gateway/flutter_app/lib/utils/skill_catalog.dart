// Helpers for refreshing the skills library after agent tool calls.

/// True when a tool call may create/edit/delete skills on disk.
bool isSkillCatalogMutatingTool(String? name) {
  final normalized = (name ?? '').trim().toLowerCase();
  return normalized == 'skill_manage';
}
