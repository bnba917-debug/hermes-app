import 'package:flutter_test/flutter_test.dart';
import 'package:hermes_app/models/chat_message.dart';

void main() {
  test('ChatMessage serializes text', () {
    final m = ChatMessage(role: ChatRole.user, content: 'hi');
    expect(m.toApiJson(), {'role': 'user', 'content': 'hi'});
  });
}
