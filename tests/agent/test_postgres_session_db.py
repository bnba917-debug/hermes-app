"""PostgreSQL session store (skipped unless HERMES_TEST_PG_DSN is set)."""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("HERMES_TEST_PG_DSN", "").strip(),
    reason="Set HERMES_TEST_PG_DSN to run PostgreSQL session integration tests",
)


@pytest.fixture
def pg_db():
    from agent.session_storage.postgres_session_db import PostgresSessionDB

    db = PostgresSessionDB(os.environ["HERMES_TEST_PG_DSN"].strip())
    sid = f"test-pg-{uuid.uuid4().hex[:12]}"
    yield db, sid
    db.delete_session(sid)


def test_create_append_and_conversation(pg_db):
    db, sid = pg_db
    db.create_session(sid, "api_server", user_id="u1")
    db.append_message(sid, "user", content="hello postgres")
    db.append_message(sid, "assistant", content="hi back")
    conv = db.get_messages_as_conversation(sid)
    assert len(conv) == 2
    assert conv[0]["role"] == "user"
    assert conv[1]["content"] == "hi back"


def test_search_messages_keyword(pg_db):
    db, sid = pg_db
    db.create_session(sid, "cli")
    db.append_message(sid, "user", content="unique migration keyword xyzzy")
    hits = db.search_messages("xyzzy", limit=5)
    assert any(h["session_id"] == sid for h in hits)
