import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trustworthy_assistant.runtime.sessions import SessionManager


class SessionPersistenceTests(unittest.TestCase):
    def test_session_persists_and_reload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_dir = Path(tmp_dir)
            state_file = root_dir / ".trustworthy_state" / "sessions.json"

            manager = SessionManager(state_file=state_file)
            session = manager.get_or_create(agent_id="main", channel="terminal", user_id="local")
            manager.append(session.session_key, "user", "hello")
            manager.append(session.session_key, "assistant", "world")

            reloaded = SessionManager(state_file=state_file)
            rows = reloaded.list_sessions()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["session_key"], session.session_key)

            # Ensure messages are present after reload.
            state = reloaded.get_or_create(agent_id="main", channel="terminal", user_id="local")
            self.assertEqual(len(state.messages), 2)
            self.assertEqual(state.messages[0]["role"], "user")
            self.assertEqual(state.messages[0]["content"], "hello")

    def test_session_trims_by_message_count_and_char_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_dir = Path(tmp_dir)
            state_file = root_dir / ".trustworthy_state" / "sessions.json"
            manager = SessionManager(
                state_file=state_file,
                max_messages_per_session=3,
                max_chars_per_session=20,
            )
            session = manager.get_or_create(agent_id="main", channel="terminal", user_id="local")

            manager.append(session.session_key, "user", "1234567890")
            manager.append(session.session_key, "assistant", "abcdefghij")
            manager.append(session.session_key, "user", "KLMNOPQRST")

            # Over max_messages_per_session => oldest dropped.
            manager.append(session.session_key, "assistant", "tail")
            state = manager.get_or_create(agent_id="main", channel="terminal", user_id="local")
            self.assertLessEqual(len(state.messages), 3)

            # Over max_chars_per_session => further dropping should keep at least one message.
            manager.append(session.session_key, "user", "01234567890123456789")
            state2 = manager.get_or_create(agent_id="main", channel="terminal", user_id="local")
            self.assertGreaterEqual(len(state2.messages), 1)


if __name__ == "__main__":
    unittest.main()

