"""Shared types for session storage backends."""


class SessionStoreBase:
    """Marker base for :class:`hermes_state.SessionDB` and :class:`postgres_session_db.PostgresSessionDB`."""

    MAX_TITLE_LENGTH = 100
