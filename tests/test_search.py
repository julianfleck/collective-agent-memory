import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from cam.search import SearchIndex


class TimestampFilterTests(unittest.TestCase):
    def test_filters_yaml_datetime_rows_by_actual_time(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            segment_path = root / "codex@wintermute" / "2026-09-21" / "01-laya.md"
            segment_path.parent.mkdir(parents=True)
            segment_path.write_text(
                """---
session_id: session-123
agent: codex
machine: wintermute
date: 2026-09-21
first_timestamp: 2026-09-22T08:36:18.961000+00:00
last_timestamp: 2026-09-22T08:44:21.148000+00:00
title: Laya experiment
keywords: [laya]
entities: {}
---

The Laya browser experiment is working.
"""
            )
            index = SearchIndex(root / "index.sqlite", root)
            self.assertTrue(index.index_segment(segment_path))
            with sqlite3.connect(root / "index.sqlite") as conn:
                stored_timestamp = conn.execute(
                    "SELECT first_timestamp FROM segments"
                ).fetchone()[0]
            since = datetime(2026, 9, 22, 4, 0, tzinfo=timezone.utc)

            recent = index.list_recent(since)
            search_results = index.search(
                "laya",
                since=since,
                fast=True,
                min_score=0,
                dynamic_cutoff=False,
            )

        self.assertEqual(stored_timestamp, "2026-09-22T08:36:18.961000+00:00")
        self.assertEqual([result.path for result in recent], [str(segment_path.relative_to(root))])
        self.assertEqual(
            [result.path for result in search_results],
            [str(segment_path.relative_to(root))],
        )


if __name__ == "__main__":
    unittest.main()
