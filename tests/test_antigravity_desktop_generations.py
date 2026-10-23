from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from scripts import antigravity_desktop_generations as generations
from scripts import antigravity_desktop_tokens as numeric
from tests.test_antigravity_desktop_tokens import integer, message, varint


PRIVATE_ID = b"PRIVATE_NATIVE_RESPONSE_ID_7F35"
PRIVATE_CONTENT = b"PRIVATE_PROMPT_TOOL_SOURCE_ARGUMENTS_OUTPUT_SENTINEL"
SELECTOR = "12345678-1234-1234-1234-123456789abc"


def metadata(response_id=PRIVATE_ID, indices=(3, 4), *, packed=True, created=None):
    usage = integer(2, 10) + integer(3, 8) + integer(9, 3) + integer(10, 5)
    if response_id is not None:
        usage += message(11, response_id)
    chat = message(4, usage) + message(1, PRIVATE_CONTENT) + message(2, PRIVATE_CONTENT)
    if created is not None:
        chat += message(9, message(4, integer(1, created)))
    if packed:
        steps = message(2, b"".join(varint(index) for index in indices))
    else:
        steps = b"".join(integer(2, index) for index in indices)
    return message(1, chat) + steps + message(9, PRIVATE_CONTENT)


def step_metadata(created, *, completed=None, finished=None):
    data = message(4, PRIVATE_CONTENT) + message(29, PRIVATE_CONTENT) + message(30, PRIVATE_CONTENT)
    for number, value in ((1, created), (8, completed), (7, finished)):
        if value is not None:
            data += message(number, integer(1, value) + integer(2, 123000000))
    return data


def database(root, *, name=SELECTOR, rows=None, steps=None):
    path = root / (name + ".db")
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE gen_metadata(idx INTEGER, data BLOB)")
        connection.execute("CREATE TABLE steps(idx INTEGER, metadata BLOB, body BLOB, tool_args BLOB)")
        connection.executemany("INSERT INTO gen_metadata VALUES (?,?)", rows or [(0, metadata())])
        connection.executemany("INSERT INTO steps VALUES (?,?,?,?)", [
            (index, data, PRIVATE_CONTENT, PRIVATE_CONTENT) for index, data in (steps or [
                (3, step_metadata(1770000000, completed=1770000003, finished=1770000001)),
                (4, step_metadata(1770000002, completed=1770000006, finished=1770000004)),
            ])])
        connection.commit()
    finally:
        connection.close()
    return path


class DesktopGenerationTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(generations.local, "get_desktop_version", return_value="2.25.0")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_referenced_step_created_time_and_completion_remain_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database(root, steps=[(3, step_metadata(1770000000, completed=1770000003, finished=1770000001)),
                                  (4, step_metadata(1770000002, completed=1770000006, finished=1770000004)),
                                  (9, step_metadata(1880000000))])
            result = generations.collect_desktop_generations(source_root=root)
            record, = result.records
            self.assertEqual(record.response_id, PRIVATE_ID)
            self.assertEqual(record.step_indices, (3, 4))
            self.assertEqual(record.source_time_kind, "first-referenced-step-created-at")
            self.assertAlmostEqual(record.source_timestamp_seconds, 1770000000.123)
            self.assertAlmostEqual(record.latest_referenced_step_completed_timestamp_seconds, 1770000006.123)
            self.assertAlmostEqual(record.latest_referenced_step_finished_generating_timestamp_seconds, 1770000004.123)
            self.assertEqual(record.tokens["total_output_tokens"], 8)
            self.assertEqual(result.safe_summary()["coverage"]["linked_step_metadata_read"], 2)

    def test_explicit_chat_start_time_has_a_separate_source_kind(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database(root, rows=[(0, metadata(created=1760000000))])
            record, = generations.collect_desktop_generations(source_root=root).records
            self.assertEqual(record.source_time_kind, "chat-start-created-at")
            self.assertEqual(record.source_timestamp_seconds, 1760000000)

    def test_missing_first_step_time_is_unknown_not_the_newer_step_time(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database(root, steps=[(4, step_metadata(1770000002))])
            result = generations.collect_desktop_generations(source_root=root)
            record, = result.records
            self.assertIsNone(record.source_timestamp_seconds)
            self.assertEqual(record.source_time_kind, "unknown")
            self.assertEqual(result.safe_summary()["generation_source_times_missing"], 1)
            self.assertEqual(result.safe_summary()["status"], "partial")

    def test_absent_and_invalid_native_id_remain_untrusted(self):
        for response_id in (None, b"", b"private id with spaces", b"x" * 513, b"invalid\nidentity"):
            with self.subTest(kind=type(response_id).__name__):
                parsed, identity, _ = generations._generation_parts(metadata(response_id))
                self.assertIsNone(identity)
                self.assertEqual(parsed["tokens"]["total_output_tokens"], 8)

    def test_packed_and_unpacked_references_have_the_same_numeric_meaning(self):
        for packed in (True, False):
            _, _, indices = generations._generation_parts(metadata(indices=(0, 3, 400, 3), packed=packed))
            self.assertEqual(indices, (0, 3, 400))
        with self.assertRaises(numeric.DesktopTokenError):
            generations._generation_parts(metadata(indices=(1 << 32,)))

    def test_native_identity_survives_reread_copy_and_row_index_reorder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "original"
            copied = root / "copied"
            original.mkdir()
            copied.mkdir()
            rows = [(0, metadata(PRIVATE_ID)), (1, metadata(b"another-native-response-id"))]
            database(original, rows=rows)
            first = generations.collect_desktop_generations(source_root=original)
            reread = generations.collect_desktop_generations(source_root=original)
            # Simulates a copied/forked source retaining native provider IDs,
            # but with different conversation and database index ordering.
            database(copied, name="different-private-selector", rows=[(81, rows[1][1]), (99, rows[0][1])])
            fork = generations.collect_desktop_generations(source_root=copied)
            accepted = {record.response_id: record.tokens for record in first.records}
            self.assertEqual({record.response_id for record in reread.records} - accepted.keys(), set())
            self.assertEqual({record.response_id: record.tokens for record in fork.records}, accepted)
            self.assertNotEqual(first.records[0].selector, fork.records[0].selector)
            self.assertNotEqual(first.records[0].row_index, fork.records[0].row_index)

    def test_safe_summary_and_default_repr_never_expose_private_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database(root)
            result = generations.collect_desktop_generations(source_root=root)
            rendered = json.dumps(result.safe_summary()) + repr(result) + repr(result.records[0])
            for private in (PRIVATE_ID.decode(), PRIVATE_CONTENT.decode(), SELECTOR, directory):
                self.assertNotIn(private, rendered)
            summary = result.safe_summary()
            summary["coverage"]["diagnostics"]["test"] = 1
            self.assertNotIn("test", result.safe_summary()["coverage"]["diagnostics"])

    def test_private_selector_is_fixed_root_only_and_not_exposed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database(root)
            database(root, name="another-private-source", rows=[(0, metadata(b"other-id"))])
            result = generations.collect_desktop_generations(source_root=root, selector=SELECTOR)
            self.assertEqual(len(result.records), 1)
            self.assertEqual(result.records[0].selector, SELECTOR)
            self.assertNotIn(SELECTOR, json.dumps(result.safe_summary()))
        for selector in ("../private", "C:/private", "not-a-uuid"):
            result = generations.collect_desktop_generations(selector=selector)
            self.assertEqual(result.safe_summary()["reason"], "invalid_private_selector")

    def test_unsupported_version_prevents_source_access(self):
        root = mock.Mock(spec=Path)
        generations.local.get_desktop_version.return_value = "2.26.0"
        result = generations.collect_desktop_generations(source_root=root)
        self.assertEqual(result.safe_summary()["reason"], "desktop_version_review_required")
        self.assertEqual(result.records, ())
        root.iterdir.assert_not_called()

    def test_only_metadata_columns_of_referenced_steps_are_queried_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = database(root)
            queries = []
            real_connect = sqlite3.connect
            def connect(database_uri, *args, **kwargs):
                self.assertIn("mode=ro", database_uri)
                self.assertNotIn("immutable", database_uri)
                connection = real_connect(database_uri, *args, **kwargs)
                connection.set_trace_callback(queries.append)
                return connection
            before = path.read_bytes()
            with mock.patch.object(generations.sqlite3, "connect", side_effect=connect):
                result = generations.collect_desktop_generations(source_root=root)
            self.assertEqual(len(result.records), 1)
            self.assertEqual(path.read_bytes(), before)
            selected = [query for query in queries if query.startswith("SELECT")]
            self.assertFalse(any("body" in query or "tool_args" in query for query in selected))
            self.assertTrue(any("FROM steps WHERE idx IN" in query for query in selected))

    def test_wal_metadata_is_visible_and_timestamp_strings_are_not_guessed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = database(root)
            writer = sqlite3.connect(path)
            try:
                writer.execute("PRAGMA journal_mode=WAL")
                writer.execute("INSERT INTO gen_metadata VALUES (1,?)", (metadata(b"new-native-id"),))
                writer.commit()
                result = generations.collect_desktop_generations(source_root=root)
                self.assertEqual(len(result.records), 2)
            finally:
                writer.close()
        parsed = generations.parse_step_numeric_timestamps(message(1, b"2026-10-23T00:00:00Z"))
        self.assertEqual(parsed, {})


if __name__ == "__main__":
    unittest.main()
