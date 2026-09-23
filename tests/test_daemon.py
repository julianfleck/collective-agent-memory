import os
import subprocess
import sys
import tempfile
import time
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from cam import daemon, segment


class IndexWorkerTests(unittest.TestCase):
    def test_does_not_mark_unparseable_session_as_indexed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / "session.jsonl"
            session_path.write_text('{"type":"unknown"}\n')
            worker = daemon.IndexWorker(Path(tmp_dir) / "segments", "test-machine")

            with (
                patch.object(segment, "load_session_messages", return_value=({}, [])),
                patch.object(daemon, "mark_session_indexed") as mark_indexed,
            ):
                result = worker.index_session(str(session_path))

        self.assertFalse(result)
        mark_indexed.assert_not_called()

    def test_does_not_mark_failed_session_as_indexed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / "session.jsonl"
            session_path.write_text('{"type":"message"}\n')
            worker = daemon.IndexWorker(Path(tmp_dir) / "segments", "test-machine")

            with (
                patch.object(segment, "load_session_messages", side_effect=ValueError("bad format")),
                patch.object(daemon, "mark_session_indexed") as mark_indexed,
            ):
                result = worker.index_session(str(session_path))

        self.assertFalse(result)
        mark_indexed.assert_not_called()


class SessionWatcherTests(unittest.TestCase):
    def test_queues_modified_session_after_incremental_debounce(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_path = Path(tmp_dir) / "session.jsonl"
            session_path.write_text("{}\n")
            current_mtime = time.time() - daemon.INCREMENTAL_DEBOUNCE - 1
            os.utime(session_path, (current_mtime, current_mtime))
            indexed = {str(session_path): current_mtime - 30}

            with patch.object(daemon, "get_indexed_sessions", return_value=indexed):
                watcher = daemon.SessionWatcher()
                watcher.pending_paths.add(str(session_path))
                watcher.last_change[str(session_path)] = datetime.now() - timedelta(
                    seconds=daemon.INCREMENTAL_DEBOUNCE + 1
                )

                with patch.object(daemon, "queue_add", return_value=True) as queue_add:
                    watcher.check_and_queue()

        queue_add.assert_called_once_with(str(session_path), priority=False)
        self.assertNotIn(str(session_path), watcher.pending_paths)


class QueueSessionsTests(unittest.TestCase):
    def test_force_queue_forgets_existing_index_state(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = Path(tmp_dir) / ".indexed_sessions"
            forced_path = str(Path(tmp_dir) / "forced.jsonl")
            preserved_path = str(Path(tmp_dir) / "preserved.jsonl")
            state_file.write_text(
                f"{forced_path}:1790029577.0\n"
                f"{preserved_path}:1790029588.0\n"
            )

            with (
                patch.object(daemon, "STATE_FILE", state_file),
                patch.object(daemon, "_indexed_sessions_cache", {}),
                patch.object(daemon, "_indexed_sessions_mtime", 0.0),
                patch.object(daemon, "queue_add", return_value=True) as queue_add,
            ):
                queued = daemon.queue_sessions_for_indexing(
                    [Path(forced_path)],
                    priority=True,
                    force=True,
                )

            state = state_file.read_text().splitlines()

        self.assertEqual(queued, 1)
        queue_add.assert_called_once_with(forced_path, priority=True)
        self.assertNotIn(f"{forced_path}:1790029577.0", state)
        self.assertIn(f"{preserved_path}:1790029588.0", state)


class LaunchdStatusTests(unittest.TestCase):
    def test_checks_the_user_launchd_domain(self):
        completed = subprocess.CompletedProcess([], 0)
        with (
            patch("platform.system", return_value="Darwin"),
            patch.object(daemon.os, "getuid", return_value=501),
            patch.object(daemon.subprocess, "run", return_value=completed) as run,
        ):
            self.assertTrue(daemon.is_daemon_running())

        run.assert_called_once_with(
            ["launchctl", "print", "gui/501/net.julianfleck.cam"],
            capture_output=True,
        )


class ProcessTitleTests(unittest.TestCase):
    def test_sets_daemon_process_and_thread_titles(self):
        set_process_title = Mock()
        set_thread_title = Mock()
        fake_module = types.SimpleNamespace(
            setproctitle=set_process_title,
            setthreadtitle=set_thread_title,
        )

        self.assertTrue(hasattr(daemon, "set_daemon_process_title"))
        with patch.dict(sys.modules, {"setproctitle": fake_module}):
            daemon.set_daemon_process_title("cam-daemon")

        set_process_title.assert_called_once_with("cam-daemon")
        set_thread_title.assert_called_once_with("cam-daemon")


if __name__ == "__main__":
    unittest.main()
