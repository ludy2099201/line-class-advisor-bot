from unittest.mock import MagicMock, patch

from app.handlers.leave_handler import LeaveHandler


def test_leave_handler_reports_private_session_only():
    session = MagicMock()
    session.get_state.return_value = "leave_wait_name"

    with patch("app.handlers.leave_handler.SessionStore", return_value=session):
        handler = LeaveHandler({}, MagicMock(), MagicMock())

    assert handler.is_in_session({"source_type": "user", "user_id": "user-1"}) is True
    assert handler.is_in_session({"source_type": "group", "user_id": "user-1"}) is False
    session.get_state.assert_called_once_with("user-1")


def test_leave_handler_reports_no_private_session_when_state_absent():
    session = MagicMock()
    session.get_state.return_value = None

    with patch("app.handlers.leave_handler.SessionStore", return_value=session):
        handler = LeaveHandler({}, MagicMock(), MagicMock())

    assert handler.is_in_session({"source_type": "user", "user_id": "user-1"}) is False
