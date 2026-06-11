import 'package:flutter_test/flutter_test.dart';
import 'package:hermes_app/utils/skill_catalog.dart';

void main() {
  test('isSkillCatalogMutatingTool matches skill_manage only', () {
    expect(isSkillCatalogMutatingTool('skill_manage'), isTrue);
    expect(isSkillCatalogMutatingTool('SKILL_MANAGE'), isTrue);
    expect(isSkillCatalogMutatingTool('skill_view'), isFalse);
    expect(isSkillCatalogMutatingTool('terminal'), isFalse);
    expect(isSkillCatalogMutatingTool(null), isFalse);
  });
}
