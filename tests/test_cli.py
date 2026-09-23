import tempfile
import unittest
from pathlib import Path

from cam import cli


class IndexedSessionStateTests(unittest.TestCase):
    def test_reads_paths_from_timestamped_and_legacy_state_entries(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = Path(tmp_dir) / ".indexed_sessions"
            state_file.write_text(
                "/tmp/current.jsonl:1790029577.1688385\n"
                "/tmp/legacy.jsonl\n"
            )

            self.assertTrue(hasattr(cli, "read_indexed_session_paths"))
            paths = cli.read_indexed_session_paths(state_file)
            state = cli.read_indexed_session_state(state_file)

        self.assertEqual(paths, {"/tmp/current.jsonl", "/tmp/legacy.jsonl"})
        self.assertEqual(
            state,
            {"/tmp/current.jsonl": 1790029577.1688385, "/tmp/legacy.jsonl": 0.0},
        )


if __name__ == "__main__":
    unittest.main()
