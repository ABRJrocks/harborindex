# Research and scope

HarborIndex provides a local retrieval component for applications that already produce embeddings and want lexical matching, vector candidates and explainable fusion in one Python API.

## Primary references

- [SQLite FTS5](https://www.sqlite.org/fts5.html) supplies full-text indexing, Unicode tokenization and BM25 ranking. SQLite's BM25 function uses lower scores for better matches; the API preserves that raw score separately from the result score.
- [Elasticsearch reciprocal rank fusion](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion) documents one-based rank fusion and a rank constant of 60 by default. HarborIndex uses `sum(weight / (constant + rank))` with the contributions included in each hit.
- [Qdrant hybrid queries](https://qdrant.tech/documentation/search/hybrid-queries/) explains why raw dense and sparse scores have incompatible scales and documents its own fusion defaults. HarborIndex's additive weighted formula and defaults are explicit; it does not claim bit-for-bit compatibility with Qdrant's weighted formula.
- [SQLite JSON functions](https://www.sqlite.org/json1.html) support parameterized exact metadata filters. This release limits metadata to flat string pairs to avoid ambiguous type coercion.
- [SQLite URI filenames](https://www.sqlite.org/uri.html) allow read-only access and opening an existing database without silently creating one after a typo.

## Alternatives and boundary

Use a dedicated vector service such as Qdrant or an established search platform such as Elasticsearch when distributed operation, approximate nearest-neighbor indexing or large-corpus throughput is required. HarborIndex is an embedded option for local applications and small scoped corpora, not a replacement for those platforms.

Dense retrieval scans all matching stored vectors exactly, bounded to 10,000 vectors per request. The application supplies embeddings. No model, inference service, credential or external network call is bundled. Matching dimensions and a model label guard accidental mixing; a label cannot establish that embeddings really came from the claimed model.

Namespace and metadata restrictions are applied before each candidate pool is truncated. They are query scoping tools, not authentication or authorization. The host application must derive trusted scope from its authenticated identity.

The demo uses hand-authored three-dimensional toy vectors to illustrate the algorithms. It is not a semantic-quality benchmark. Fusion scores are ranking signals, not confidence probabilities. Candidate depth and weights must be evaluated on held-out relevance judgments for a real deployment.
