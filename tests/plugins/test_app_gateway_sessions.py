"""Session list/history isolation for app gateway."""

from __future__ import annotations


def test_user_hermes_home_stable_inside_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes").mkdir()

    from plugins.app_gateway.user_scope import (
        app_gateway_user_scope,
        ensure_user_home,
        operator_hermes_root,
        user_hermes_home,
    )
    from plugins.app_gateway.auth import UserContext
    from hermes_constants import get_hermes_home

    expected = operator_hermes_root() / "app_gateway" / "users" / "alice"
    assert user_hermes_home("alice") == expected
    ensure_user_home("alice")

    ctx = UserContext(user_id="alice", session_id="s1", device_id=None, raw_claims={})
    with app_gateway_user_scope(ctx):
        assert get_hermes_home() == expected
        assert user_hermes_home("alice") == expected


def test_list_user_sessions_filters_by_prefix(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes").mkdir()

    from hermes_state import get_shared_session_db
    from plugins.app_gateway.auth import UserContext
    from plugins.app_gateway.session_keys import build_hermes_session_id
    from plugins.app_gateway.sessions_service import list_user_sessions

    db = get_shared_session_db()
    alice_ctx = UserContext(user_id="alice", session_id="chat-a", device_id=None, raw_claims={})
    bob_ctx = UserContext(user_id="bob", session_id="chat-b", device_id=None, raw_claims={})
    alice_sid = build_hermes_session_id(alice_ctx)
    bob_sid = build_hermes_session_id(bob_ctx)
    db.create_session(alice_sid, "app_gateway", user_id="alice")
    db.create_session(bob_sid, "app_gateway", user_id="bob")
    db.append_message(alice_sid, "user", "hello alice")
    db.append_message(bob_sid, "user", "hello bob")

    rows = list_user_sessions(alice_ctx, limit=10)
    ids = {r["session_id"] for r in rows}
    assert "chat-a" in ids
    assert "chat-b" not in ids


def test_set_and_suggest_session_title(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes").mkdir()

    from hermes_state import get_shared_session_db
    from plugins.app_gateway.auth import UserContext
    from plugins.app_gateway.session_keys import build_hermes_session_id
    from plugins.app_gateway.sessions_service import (
        set_user_session_title,
        suggest_user_session_title,
    )

    db = get_shared_session_db()
    ctx = UserContext(user_id="alice", session_id="chat-a", device_id=None, raw_claims={})
    sid = build_hermes_session_id(ctx)
    db.create_session(sid, "app_gateway", user_id="alice")
    db.append_message(sid, "user", "武汉天气怎么样")
    db.append_message(sid, "assistant", "今天武汉晴，气温舒适。")

    out = set_user_session_title(ctx, "chat-a", "武汉天气")
    assert out["title"] == "武汉天气"

    ctx2 = UserContext(user_id="alice", session_id="chat-b", device_id=None, raw_claims={})
    sid2 = build_hermes_session_id(ctx2)
    db.create_session(sid2, "app_gateway", user_id="alice")
    db.append_message(sid2, "user", "写一封商务邮件")

    suggested = suggest_user_session_title(ctx2, "chat-b")
    assert suggested["session_id"] == "chat-b"
    assert suggested["title"]
    assert len(suggested["title"]) <= 83


def test_to_app_messages_keeps_tool_only_assistant_turn():
    from plugins.app_gateway.sessions_service import _to_app_messages

    raw = [
        {"role": "user", "content": "查天气"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "content": '{"temp": 20}'},
        {"role": "assistant", "content": "今天 20 度。"},
    ]
    out = _to_app_messages(raw)
    assert [m["role"] for m in out] == ["user", "assistant", "assistant"]
    assert out[1]["content"] == "（调用了工具）"
    assert out[2]["content"] == "今天 20 度。"


def test_to_app_messages_extracts_multimodal_text():
    from plugins.app_gateway.sessions_service import _to_app_messages

    raw = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "  描述图片  "},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        }
    ]
    out = _to_app_messages(raw)
    assert out[0]["content"] == "描述图片\n（图片）"


def test_load_history_prefers_longer_db_over_redis_cache():
    from unittest.mock import MagicMock

    from plugins.app_gateway.auth import UserContext
    from plugins.app_gateway.config import AppGatewayConfig
    from plugins.app_gateway.runtime import AppAgentRuntime

    ctx = UserContext(user_id="alice", session_id="chat-a", device_id=None, raw_claims={})
    db_hist = [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "two"},
        {"role": "user", "content": "three"},
    ]
    cached = [{"role": "user", "content": "one"}]

    runtime = AppAgentRuntime.__new__(AppAgentRuntime)
    runtime._config = AppGatewayConfig(postgres_only=False)
    runtime._cache = MagicMock()
    runtime._cache.get_history.return_value = cached
    runtime._ensure_session_db = MagicMock(
        return_value=MagicMock(get_messages_as_conversation=MagicMock(return_value=db_hist))
    )

    assert runtime.load_history(ctx, "sid") == db_hist


def test_load_history_postgres_only_ignores_redis():
    from unittest.mock import MagicMock

    from plugins.app_gateway.auth import UserContext
    from plugins.app_gateway.config import AppGatewayConfig
    from plugins.app_gateway.runtime import AppAgentRuntime

    ctx = UserContext(user_id="alice", session_id="chat-a", device_id=None, raw_claims={})
    db_hist = [{"role": "user", "content": "from-db"}]
    cached = [
        {"role": "user", "content": "stale-redis-1"},
        {"role": "assistant", "content": "stale-redis-2"},
    ]

    runtime = AppAgentRuntime.__new__(AppAgentRuntime)
    runtime._config = AppGatewayConfig(postgres_only=True)
    runtime._cache = MagicMock()
    runtime._cache.get_history.return_value = cached
    runtime._ensure_session_db = MagicMock(
        return_value=MagicMock(get_messages_as_conversation=MagicMock(return_value=db_hist))
    )

    assert runtime.load_history(ctx, "sid") == db_hist
    runtime._cache.get_history.assert_not_called()


def test_backfill_history_gap_appends_missing_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes").mkdir()

    from hermes_state import SessionDB
    from run_agent import AIAgent

    db = SessionDB()
    sid = "test_session_backfill"
    db.create_session(sid, "app_gateway", user_id="alice")
    db.append_message(sid, "user", "one")
    db.append_message(sid, "assistant", "two")

    agent = AIAgent.__new__(AIAgent)
    agent.session_id = sid
    agent._session_db = db
    agent._session_db_created = True
    agent._last_flushed_db_idx = 0
    agent._persist_user_message_override = None

    history = [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "two"},
        {"role": "user", "content": "three"},
        {"role": "assistant", "content": "four"},
    ]
    messages = history + [{"role": "user", "content": "five"}, {"role": "assistant", "content": "six"}]

    AIAgent._flush_messages_to_session_db(agent, messages, conversation_history=history)

    rows = db.get_messages_as_conversation(sid)
    assert len(rows) == 6
    assert rows[-2]["content"] == "five"
    assert rows[-1]["content"] == "six"


def test_flush_uses_single_batch_insert(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes").mkdir()

    from unittest.mock import MagicMock

    from hermes_state import SessionDB
    from run_agent import AIAgent

    db = SessionDB()
    sid = "test_session_batch"
    db.create_session(sid, "app_gateway", user_id="alice")
    db.append_message(sid, "user", "one")
    db.append_message(sid, "assistant", "two")

    original_append = db.append_message
    append_mock = MagicMock(wraps=original_append)
    db.append_message = append_mock
    batch_mock = MagicMock(wraps=db.append_messages_batch)
    db.append_messages_batch = batch_mock

    agent = AIAgent.__new__(AIAgent)
    agent.session_id = sid
    agent._session_db = db
    agent._session_db_created = True
    agent._last_flushed_db_idx = 0
    agent._session_db_rows = 2
    agent._persist_user_message_override = None

    history = [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "two"},
        {"role": "user", "content": "three"},
        {"role": "assistant", "content": "four"},
    ]
    messages = history + [{"role": "user", "content": "five"}, {"role": "assistant", "content": "six"}]

    AIAgent._flush_messages_to_session_db(agent, messages, conversation_history=history)

    batch_mock.assert_called_once()
    append_mock.assert_not_called()
    written_rows = batch_mock.call_args[0][1]
    assert len(written_rows) == 4
    assert written_rows[0]["content"] == "three"
    assert written_rows[-1]["content"] == "six"
    assert db.message_count(sid) == 6


def test_history_gap_skips_count_when_cache_covers_history(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes").mkdir()

    from unittest.mock import MagicMock

    from run_agent import AIAgent

    db = MagicMock()
    db.message_count = MagicMock(return_value=4)

    agent = AIAgent.__new__(AIAgent)
    agent.session_id = "sid"
    agent._session_db = db
    agent._session_db_rows = 4

    history = [{"role": "user", "content": f"m{i}"} for i in range(4)]
    assert AIAgent._history_gap_messages(agent, history) == []
    db.message_count.assert_not_called()


def test_persist_session_skips_json_snapshot_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes").mkdir()

    from hermes_state import SessionDB
    from run_agent import AIAgent

    db = SessionDB()
    sid = "test_session_no_json"
    db.create_session(sid, "app_gateway", user_id="alice")

    agent = AIAgent.__new__(AIAgent)
    agent.session_id = sid
    agent._session_db = db
    agent._session_db_created = True
    agent._last_flushed_db_idx = 0
    agent.save_session_log = False
    agent._persist_user_message_override = None
    agent.session_log_file = tmp_path / "session.json"

    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi", "finish_reason": "stop"},
    ]
    AIAgent._persist_session(agent, messages, conversation_history=[])

    assert not agent.session_log_file.exists()
    assert db.message_count(sid) == 2
