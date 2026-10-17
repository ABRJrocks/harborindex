import math
import sqlite3
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from harborindex import Document, HarborError, Index, fuse
from harborindex.validation import cosine, pack, unit_vector, words


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "index.db"
        self.index = Index.create(self.path, dimensions=3, model="test-v1")

    def tearDown(self):
        self.index.close()
        self.temporary.cleanup()

    def seed(self):
        self.index.upsert(
            "docs",
            [
                Document(
                    "a",
                    "rotate credentials safely",
                    "Credential rotation",
                    {"team": "platform"},
                    [1, 0, 0],
                ),
                Document(
                    "b",
                    "restore database backup",
                    "Recovery plan",
                    {"team": "data"},
                    [0, 1, 0],
                ),
                Document(
                    "c",
                    "route traffic to canary",
                    "Routing change",
                    {"team": "platform"},
                    [0, 0, 1],
                ),
                Document(
                    "d",
                    "credentials used for database jobs",
                    "Job credentials",
                    {"team": "data"},
                    [0.7, 0.7, 0],
                ),
            ],
            model="test-v1",
        )

    def test_ingest_model_must_be_explicit_and_match(self):
        for model in (None, "wrong-model"):
            with self.subTest(model=model), self.assertRaises(HarborError):
                self.index.upsert(
                    "docs", [Document("a", "text", vector=[1, 0, 0])], model=model
                )
        self.assertEqual(self.index.stats("docs")["documents"], 0)

    def test_exact_dense_and_lexical_search(self):
        self.seed()
        result = self.index.search(
            "docs", mode="dense", vector=[1, 0, 0], model="test-v1", k=2
        )
        self.assertEqual([h.id for h in result.hits], ["a", "d"])
        self.assertAlmostEqual(result.hits[0].score, 1)
        lexical = self.index.search("docs", mode="lexical", query="backup")
        self.assertEqual([h.id for h in lexical.hits], ["b"])
        self.assertLess(lexical.hits[0].components["lexical"]["raw_score"], 0)
        self.assertGreater(lexical.hits[0].score, 0)

    def test_rrf_components_add_to_final_score(self):
        self.seed()
        result = self.index.search(
            "docs", query="credentials", vector=[1, 0, 0], model="test-v1"
        )
        for hit in result.hits:
            self.assertAlmostEqual(
                hit.score, sum(c["rrf_contribution"] for c in hit.components.values())
            )
        self.assertEqual(result.hits[0].id, "a")
        self.assertEqual(result.score_kind, "weighted_rrf")
        self.assertEqual(result.vectors_scanned, 4)
        self.assertIn("text", asdict(result)["hits"][0])

    def test_namespace_and_filters_apply_before_candidate_limit(self):
        self.seed()
        self.index.upsert(
            "other",
            [Document("a", "credentials credentials credentials", vector=[1, 0, 0])],
            model="test-v1",
        )
        for mode in ("lexical", "dense", "hybrid"):
            kwargs = {"query": "credentials"} if mode != "dense" else {}
            if mode != "lexical":
                kwargs.update(vector=[1, 0, 0], model="test-v1")
            result = self.index.search(
                "docs",
                mode=mode,
                where={"team": "data"},
                k=1,
                candidate_limit=1,
                **kwargs,
            )
            self.assertEqual([h.id for h in result.hits], ["d"])
            self.assertTrue(all(h.namespace == "docs" for h in result.hits))
        result = self.index.search(
            "missing", query="credentials", vector=[1, 0, 0], model="test-v1"
        )
        self.assertEqual(result.hits, [])

    def test_upsert_replaces_text_vector_and_metadata_together(self):
        self.seed()
        self.index.upsert(
            "docs",
            [
                Document(
                    "a",
                    "new uniquephrase",
                    metadata={"team": "changed"},
                    vector=[0, 0, 1],
                )
            ],
            model="test-v1",
        )
        self.assertEqual(
            self.index.search("docs", mode="lexical", query="rotate").hits, []
        )
        hit = self.index.search("docs", mode="lexical", query="uniquephrase").hits[0]
        self.assertEqual(hit.metadata, {"team": "changed"})
        result = self.index.search(
            "docs", mode="dense", vector=[1, 0, 0], model="test-v1"
        )
        self.assertNotEqual(result.hits[0].id, "a")

    def test_delete_is_scoped_and_removes_fts_content(self):
        self.seed()
        self.index.upsert("other", [Document("a", "rotate credentials")])
        self.assertEqual(self.index.delete("docs", ["a", "a", "missing"]), 1)
        self.assertEqual(
            self.index.search("docs", mode="lexical", query="rotate").hits, []
        )
        self.assertEqual(
            len(self.index.search("other", mode="lexical", query="rotate").hits), 1
        )

    def test_sql_failure_rolls_back_a_whole_batch(self):
        self.seed()
        self.index._db.execute(
            "CREATE TRIGGER reject_bad BEFORE INSERT ON harbor_documents WHEN new.id='bad' BEGIN SELECT RAISE(ABORT,'test failure'); END"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.index.upsert(
                "docs", [Document("a", "changed"), Document("bad", "rejected")]
            )
        self.assertEqual(
            self.index.search("docs", mode="lexical", query="changed").hits, []
        )
        self.assertEqual(
            self.index.search("docs", mode="lexical", query="rotate").hits[0].id, "a"
        )

    def test_invalid_batch_writes_nothing(self):
        for docs in (
            [Document("a", "valid"), Document("b", "bad", vector=[0, 0, 0])],
            [Document("a", "one"), Document("a", "two")],
        ):
            with self.assertRaises(HarborError):
                self.index.upsert("docs", docs)
            self.assertEqual(self.index.stats("docs")["documents"], 0)

    def test_missing_open_never_creates_and_create_never_overwrites(self):
        with self.assertRaises(sqlite3.OperationalError):
            Index.open(self.path.parent / "missing.db")
        with self.assertRaises(FileExistsError):
            Index.create(self.path)
        self.assertEqual(self.index.stats("docs")["documents"], 0)

    def test_read_only_index_can_search_but_cannot_mutate(self):
        self.seed()
        with Index.open(self.path, read_only=True) as reader:
            self.assertEqual(
                reader.search("docs", mode="lexical", query="backup").hits[0].id, "b"
            )
            with self.assertRaises(HarborError):
                reader.delete("docs", ["b"])
            with self.assertRaises(HarborError):
                reader.upsert("docs", [Document("new", "text")])

    def test_scan_limit_fails_instead_of_returning_partial_results(self):
        self.seed()
        with self.assertRaisesRegex(HarborError, "scan limit"):
            self.index.search(
                "docs", mode="dense", vector=[1, 0, 0], model="test-v1", max_scan=2
            )
        result = self.index.search(
            "docs",
            mode="dense",
            vector=[1, 0, 0],
            model="test-v1",
            where={"team": "platform"},
            max_scan=2,
        )
        self.assertEqual(result.vectors_scanned, 2)

    def test_invalid_query_contracts(self):
        self.seed()
        for kwargs in (
            {"model": "different"},
            {"vector": [1, 0]},
            {"vector": [0, 0, 0]},
            {"k": True},
            {"candidate_limit": 0},
            {"rank_constant": 0},
            {"lexical_weight": 0},
            {"dense_weight": math.inf},
            {"where": {"team": True}},
        ):
            params = dict(query="credentials", vector=[1, 0, 0], model="test-v1")
            params.update(kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(HarborError):
                self.index.search("docs", **params)

    def test_plain_query_cannot_inject_fts_syntax(self):
        self.seed()
        for query in ('" OR *', "title:credentials", "credentials NEAR(backup)"):
            result = self.index.search("docs", mode="lexical", query=query)
            self.assertTrue(all(h.namespace == "docs" for h in result.hits))
        with self.assertRaises(HarborError):
            self.index.search("docs", mode="lexical", query="***")

    def test_lexical_only_index(self):
        with Index.create(":memory:") as index:
            index.upsert("docs", [Document("a", "Hello café world")])
            self.assertEqual(
                index.search("docs", query="cafe", mode="lexical").hits[0].id, "a"
            )
            with self.assertRaises(HarborError):
                index.upsert("docs", [Document("b", "test", vector=[1])])

    def test_same_score_ties_are_deterministic(self):
        self.index.upsert(
            "docs",
            [Document(name, "same", vector=[1, 0, 0]) for name in ("z", "a", "m")],
            model="test-v1",
        )
        for mode in ("lexical", "dense", "hybrid"):
            kwargs = {"query": "same"} if mode != "dense" else {}
            if mode != "lexical":
                kwargs.update(vector=[1, 0, 0], model="test-v1")
            self.assertEqual(
                [h.id for h in self.index.search("docs", mode=mode, **kwargs).hits],
                ["a", "m", "z"],
            )


class ArithmeticTests(unittest.TestCase):
    def test_one_based_weighted_rrf(self):
        ordered, scores, parts = fuse(
            [("a", -2), ("b", -1)],
            [("b", 1), ("c", 0.5)],
            rank_constant=60,
            lexical_weight=2,
        )
        self.assertEqual(ordered[0], "b")
        self.assertAlmostEqual(scores["b"], 2 / 62 + 1 / 61)
        self.assertEqual(parts["a"]["lexical"]["rank"], 1)
        with self.assertRaises(HarborError):
            fuse([("a", 0), ("a", 0)], [])
        with self.assertRaisesRegex(HarborError, "too small"):
            fuse([("a", 0)], [], lexical_weight=5e-324)

    def test_large_and_tiny_finite_vectors_do_not_overflow(self):
        for vector in ([1e308, 1e308, 0], [1e-300, 1e-300, 0]):
            unit = unit_vector(vector, 3)
            self.assertAlmostEqual(sum(v * v for v in unit), 1)
            self.assertAlmostEqual(cosine(unit, pack(vector, 3), 3), 1)

    def test_malformed_vectors_and_metadata_are_rejected(self):
        with Index.create(":memory:", dimensions=3, model="test") as index:
            for vector in (
                [True, 0, 1],
                [float("nan"), 0, 1],
                [float("inf"), 0, 1],
                [0, 0, 0],
            ):
                with self.subTest(vector=vector), self.assertRaises(HarborError):
                    index.upsert(
                        "docs", [Document("a", "text", vector=vector)], model="test"
                    )
            for meta in ({"x": 0}, {"x": {}}, {"bad.key": "v"}, {"x": "\ud800"}):
                with self.subTest(meta=meta), self.assertRaises(HarborError):
                    index.upsert("docs", [Document("a", "text", metadata=meta)])

    def test_corrupt_vector_is_detected(self):
        with self.assertRaises(HarborError):
            cosine((1, 0, 0), b"bad", 3)
        with self.assertRaises(HarborError):
            cosine((1, 0, 0), b"\0" * 12, 3)

    def test_query_size_bounds(self):
        for query in ("", "x" * 1025, " ".join("word" + str(i) for i in range(65))):
            with self.assertRaises(HarborError):
                words(query)
