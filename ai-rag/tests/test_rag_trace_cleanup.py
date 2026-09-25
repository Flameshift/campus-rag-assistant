"""RAG Trace 清理策略测试。"""

import tempfile
import time
import unittest
import os
from pathlib import Path
from unittest.mock import patch

from app.rag_trace import RagTrace


class RagTraceCleanupTests(unittest.TestCase):
    def test_cleanup_keeps_current_file_and_enforces_max_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace_dir = Path(tmp)
            old = trace_dir / "old.json"
            old.write_text("{}", encoding="utf-8")
            old_time = time.time() - 10 * 24 * 60 * 60
            old.touch()
            os.utime(old, (old_time, old_time))
            current = trace_dir / "current.json"
            current.write_text("{}", encoding="utf-8")

            with (
                patch("app.rag_trace.config.RAG_TRACE_RETENTION_DAYS", 7),
                patch("app.rag_trace.config.RAG_TRACE_MAX_FILES", 1),
                patch("app.rag_trace.config.RAG_TRACE_MAX_TOTAL_BYTES", 1000),
            ):
                RagTrace._cleanup_traces(trace_dir, current)

            self.assertFalse(old.exists())
            self.assertTrue(current.exists())


if __name__ == "__main__":
    unittest.main()
