# Integrating HarborIndex

## An embedding pipeline plus one retrieval call

1. Split source documents into independently useful chunks in your application. Preserve a stable source/chunk ID and enough metadata to cite the source later.
2. Encode the chunks using your chosen embedding model. Convert arrays with `.tolist()` before passing them to HarborIndex. Keep the same model revision, pooling and preprocessing for queries and documents.
3. Create a database with that dimension count and a descriptive model label. The label is a compatibility check supplied by your application, not verified provenance.
4. Batch `Document` objects into `upsert(namespace, documents, model=...)`. Each batch is atomic. Reusing an ID replaces text, title, metadata and vector together. Omit a vector to remove a previously stored vector.
5. At query time, derive the namespace and allowed filters from your authenticated application context. Encode the user's query with the same pipeline and call `search`.
6. Build a context window from returned `hit.text` values and cite `hit.id`. Apply your own relevance or abstention policy before returning an answer.

[`examples/retrieval_adapter.py`](../examples/retrieval_adapter.py) is a runnable, provider-independent context-building example with toy vectors. No model SDK is required by the package.

```python
# embed() is your existing encoder. It is not supplied by HarborIndex.
query_vector = embed(user_query).tolist()
with Index.open("guides.db", read_only=True) as index:
    result = index.search(
        trusted_namespace,
        query=user_query,
        vector=query_vector,
        model=MODEL_REVISION,
        where=trusted_filters,
        k=8,
        candidate_limit=80,
    )
```

Do not map an arbitrary request parameter directly to the namespace. This library has no user accounts, authentication or row-level authorization. Use separate database files when you need independent BM25 statistics or stronger operational isolation.

## Failure handling

Catch `harborindex.HarborError` for invalid documents, incompatible vectors, unsupported configuration or excessive scan sizes. SQLite locking, corruption and I/O exceptions remain standard `sqlite3.Error` or `OSError` exceptions in the Python API. Set your application's retry and error-redaction policy around them. The CLI returns code 2 and prints a controlled diagnostic.

The library uses a five-second SQLite connection timeout. A connection belongs to its creating thread. Open one connection per thread or use a synchronous worker. A search holds a read transaction over both candidate branches and document fetching. Writes use `BEGIN IMMEDIATE` and roll back as one batch if any SQL operation fails.

Deleting a document removes its text and vector from active tables and search results. It is not secure erasure of filesystem pages or backups. Do not copy a live database without a consistent SQLite backup procedure or closing all connections first.

## Evaluation and reports

Prepare a JSON array with 1 to 20 cases. Each case contains `name`, `query`, `vector` and optional `where`. Names must be unique. A comparison runs lexical, dense and hybrid search for each case, preserving the exact filters and candidate settings. If a write changes the database revision between searches, generation fails and asks for a retry.

```python
from harborindex.report import compare, write_report

with Index.open("guides.db", read_only=True) as index:
    report = compare(index, trusted_namespace, cases, model=MODEL_REVISION)
write_report("review-01.html", report)
```

The report is self-contained and renders document strings as text rather than HTML. It makes no external requests. It includes full retrieved content and queries, so treat it with the same access rules as the source documents. Only the bundled toy report is intended for public hosting.

A score breakdown explains the ranking math. It does not show whether a result is relevant. Build a held-out set of queries with source IDs judged relevant by people who know your domain. Compare retrieval recall and ranking quality as you vary candidate depth and weights. Dense top-k always returns available candidates even when cosine is weak or negative, so an application may need its own relevance gate.

## JSONL document shape

```json
{"id":"guide-42#chunk-1","title":"Restore a backup","text":"Verify the recovery target before restoring.","metadata":{"team":"data","kind":"runbook"},"vector":[1,0,0]}
```

`id` and `text` are required. `title`, `metadata` and `vector` are optional. Unknown fields, duplicate object keys and non-finite numbers are rejected by the JSON adapters. Query vector files contain a JSON array. Metadata and filters contain only flat string pairs and compare exactly, including case. There is no automatic chunking, embedding, reranker, language model or HTTP server.
