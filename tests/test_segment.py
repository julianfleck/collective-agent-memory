import json
import tempfile
import unittest
from pathlib import Path

from cam.segment import load_session_messages


class LoadSessionMessagesTests(unittest.TestCase):
    def test_loads_codex_response_messages_without_event_duplicates(self):
        records = [
            {
                "timestamp": "2026-09-21T22:26:05.603Z",
                "type": "session_meta",
                "payload": {
                    "id": "session-123",
                    "timestamp": "2026-09-21T22:25:15.990Z",
                    "cwd": "/tmp/project",
                },
            },
            {
                "timestamp": "2026-09-21T22:26:06.170Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": "internal instructions"}],
                },
            },
            {
                "timestamp": "2026-09-21T22:26:07.000Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Investigate"},
                        {"type": "input_text", "text": "Laya indexing"},
                    ],
                },
            },
            {
                "timestamp": "2026-09-21T22:26:07.001Z",
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "Investigate Laya indexing"},
            },
            {
                "timestamp": "2026-09-21T22:26:08.000Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "I found the problem."}],
                },
            },
            {
                "timestamp": "2026-09-21T22:26:09.000Z",
                "type": "response_item",
                "payload": {"type": "function_call", "name": "exec_command"},
            },
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / ".codex" / "sessions" / "rollout.jsonl"
            session_path.parent.mkdir(parents=True)
            session_path.write_text("\n".join(json.dumps(record) for record in records))

            metadata, messages = load_session_messages(session_path)

        self.assertEqual(metadata["agent"], "codex")
        self.assertEqual(metadata.get("session_id"), "session-123")
        self.assertEqual(metadata.get("started"), "2026-09-21T22:25:15.990Z")
        self.assertEqual(metadata.get("cwd"), "/tmp/project")
        self.assertEqual([message["role"] for message in messages], ["user", "assistant"])
        self.assertEqual(messages[0]["text"], "Investigate Laya indexing")
        self.assertEqual(messages[1]["text"], "I found the problem.")


if __name__ == "__main__":
    unittest.main()
