import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harborindex import Document, HarborError, Index
from harborindex.cli import main
from harborindex.demo import MODEL, QUERIES, run_demo
from harborindex.jsonio import loads, read_documents, read_json
from harborindex.report import compare, render, write_report


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.path = self.root / "docs.db"

    def tearDown(self):
        self.temporary.cleanup()

    def cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main([str(arg) for arg in args])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_cli_full_import_query_report_delete_workflow(self):
        from dataclasses import asdict

        from harborindex.demo import DOCUMENTS

        docs = self.root / "docs.jsonl"
        docs.write_text(
            "\n".join(json.dumps(asdict(d)) for d in DOCUMENTS), encoding="utf-8"
        )
        vector = self.root / "vector.json"
        vector.write_text("[1,0,0]")
        queries = self.root / "queries.json"
        queries.write_text(json.dumps(QUERIES))
        self.assertEqual(
            self.cli("init", self.path, "--dimensions", 3, "--model", MODEL)[0], 0
        )
        args = [self.path, "--namespace", "playbooks"]
        code, output, _ = self.cli("upsert", *args, "--input", docs, "--model", MODEL)
        self.assertEqual((code, json.loads(output)["upserted"]), (0, 9))
        code, output, _ = self.cli(
            "search",
            *args,
            "--mode",
            "hybrid",
            "--model",
            MODEL,
            "--query",
            "credentials",
            "--vector",
            vector,
            "--where",
            '{"team":"platform"}',
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["hits"][0]["id"], "key-rotation")
        report = self.root / "report.html"
        self.assertEqual(
            self.cli(
                "report",
                *args,
                "--model",
                MODEL,
                "--queries",
                queries,
                "--output",
                report,
            )[0],
            0,
        )
        self.assertIn("Recorded retrieval snapshot", report.read_text())
        self.assertEqual(json.loads(self.cli("stats", *args)[1])["documents"], 9)
        self.assertEqual(
            json.loads(self.cli("delete", *args, "key-rotation")[1])["deleted"], 1
        )
        self.assertEqual(json.loads(self.cli("stats", *args)[1])["documents"], 8)

    def test_cli_errors_are_nonzero_and_do_not_echo_private_payloads(self):
        self.cli("init", self.path)
        secret = "private-document-should-never-be-echoed"
        docs = self.root / "bad.jsonl"
        docs.write_text(json.dumps({"id": "x", "text": secret}) + '\n{"bad":true}')
        code, output, error = self.cli(
            "upsert", self.path, "--namespace", "docs", "--input", docs
        )
        self.assertEqual(code, 2)
        self.assertEqual(output, "")
        self.assertNotIn(secret, error)
        with Index.open(self.path) as index:
            self.assertEqual(index.stats("docs")["documents"], 0)
        self.assertEqual(self.cli("init", self.path)[0], 2)
        missing = self.root / "missing.db"
        self.assertEqual(self.cli("stats", missing, "--namespace", "docs")[0], 2)
        self.assertFalse(missing.exists())

    def test_json_rejects_duplicate_keys_nonfinite_and_deep_inputs(self):
        for value in (
            '{"x":1,"x":2}',
            "[NaN]",
            "[Infinity]",
            "[" * 2000 + "0" + "]" * 2000,
            b"\xff",
        ):
            with self.subTest(value=str(value)[:30]), self.assertRaises(HarborError):
                loads(value)
        oversized = self.root / "large.json"
        with oversized.open("wb") as output:
            output.truncate(16 * 1024 * 1024 + 1)
        with self.assertRaises(HarborError):
            read_json(oversized)

    def test_jsonl_bounds_and_unknown_fields(self):
        source = self.root / "input.jsonl"
        for content in (
            "\n",
            '{"id":"a","text":"ok","unknown":1}',
            "x" * (256 * 1024 + 1),
            "\n".join('{"id":"x","text":"ok"}' for _ in range(1001)),
        ):
            source.write_text(content)
            with self.assertRaises(HarborError):
                read_documents(source)

    def test_demo_checks_and_report_escaping(self):
        report = run_demo()
        self.assertTrue(report["toy_vectors"])
        report["cases"][0]["query"] = (
            "</script><script>window.pwned=true</script>&\u2028"
        )
        html = render(report)
        self.assertNotIn("<script>window.pwned", html)
        self.assertIn("\\u003c/script\\u003e", html)
        self.assertNotIn("HARBORINDEX_DATA_PLACEHOLDER", html)
        self.assertIn("connect-src 'none'", html)
        output = self.root / "report.html"
        write_report(output, report)
        with self.assertRaises(FileExistsError):
            write_report(output, run_demo())
        self.assertEqual(output.read_text(), html)

    def test_report_rejects_changes_between_search_snapshots(self):
        with Index.create(":memory:", dimensions=3, model=MODEL) as index:
            index.upsert(
                "playbooks",
                [Document("x", "service credentials", vector=[1, 0, 0])],
                model=MODEL,
            )
            original = index.search
            calls = 0

            def changing_search(*args, **kwargs):
                nonlocal calls
                result = original(*args, **kwargs)
                calls += 1
                if calls == 1:
                    index.upsert("playbooks", [Document("y", "new document")])
                return result

            with (
                patch.object(index, "search", side_effect=changing_search),
                self.assertRaisesRegex(HarborError, "Index changed"),
            ):
                compare(index, "playbooks", QUERIES[:1], model=MODEL)

    def test_revision_persists_and_noop_delete_does_not_change_it(self):
        with Index.create(self.path) as index:
            self.assertEqual(
                index.search("docs", query="word", mode="lexical").revision, 0
            )
            index.upsert("docs", [Document("x", "word")])
            index.delete("docs", ["missing"])
        with Index.open(self.path) as index:
            self.assertEqual(
                index.search("docs", query="word", mode="lexical").revision, 1
            )
            index.delete("docs", ["x"])
            self.assertEqual(
                index.search("docs", query="word", mode="lexical").revision, 2
            )

    def test_clear_optional_vector_and_metadata_on_replacement(self):
        with Index.create(":memory:", dimensions=3, model=MODEL) as index:
            index.upsert(
                "docs",
                [Document("x", "oldword", metadata={"team": "a"}, vector=[1, 0, 0])],
                model=MODEL,
            )
            index.upsert("docs", [Document("x", "newword")])
            self.assertEqual(index.stats("docs")["vectors"], 0)
            self.assertEqual(
                index.search("docs", query="newword", mode="lexical").hits[0].metadata,
                {},
            )
            self.assertEqual(
                index.search("docs", vector=[1, 0, 0], model=MODEL, mode="dense").hits,
                [],
            )

    def test_unsupported_schema_and_wal_are_rejected(self):
        Index.create(self.path).close()
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE harbor_meta SET version=2")
        with self.assertRaisesRegex(HarborError, "schema"):
            Index.open(self.path)
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE harbor_meta SET version=1")
            db.commit()
            self.assertEqual(db.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        with self.assertRaisesRegex(HarborError, "WAL"):
            Index.open(self.path)

    def test_oversized_batch_is_atomic(self):
        with Index.create(":memory:") as index:
            with self.assertRaises(HarborError):
                index.upsert("docs", (Document(str(n), "word") for n in range(1001)))
            self.assertEqual(index.stats("docs")["documents"], 0)
