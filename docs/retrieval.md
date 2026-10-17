# Retrieval contract

## Candidate selection

Lexical queries accept plain text, up to 1,024 characters and 64 unique Unicode word tokens. Tokens are quoted and joined with OR. FTS operators, field queries and wildcard syntax are not exposed. The FTS5 tokenizer is `unicode61 remove_diacritics 2`. Title matches receive BM25 weight 2 and body matches weight 1. SQLite's lower-is-better raw BM25 is preserved in `components.lexical.raw_score`; lexical result scores negate it.

Dense retrieval normalizes the query, scans matching stored float32 vectors and computes cosine with a norm correction for storage precision. Higher cosine is better, in the range [-1, 1]. Finite nonzero vectors are required. Normalization scales before squaring to avoid overflowing very large finite input values. There is no minimum similarity threshold.

Namespace and metadata restrictions apply before each candidate pool's `LIMIT`. FTS5 corpus statistics remain global. Each branch retains at most `candidate_limit` documents, ordered by score then ID. Hybrid search fuses the two pools with additive weighted reciprocal rank fusion, then returns the first `k` documents. Candidates missing from a branch contribute zero. Ranks begin at 1. Fusion uses ranks rather than adding incomparable raw BM25 and cosine scores.

## Result shape

`SearchResult` includes `hits`, `mode`, `score_kind`, `namespace`, `candidate_limit`, actual lexical/dense pool sizes, `vectors_scanned`, index `revision`, model label, filters and hybrid weights/constant. A `Hit` includes stable ID, title, full text, metadata, final rank, score and components. Convert the dataclasses with `dataclasses.asdict` for JSON.

The revision increments once for each nonempty successful upsert batch and once for a delete batch that removed documents. It is not a content hash, and direct SQL changes bypass it. Only mutate the index through the library. SQLite files are trusted storage and must not be accepted from untrusted uploads.

## Limits in v0.1.0

| Input | Bound |
| --- | --- |
| Dimensions | 1 to 2,048, fixed at creation |
| Matching vectors scanned per search | 10,000 maximum; callers may lower the cap |
| Returned results `k` | 1 to 100 |
| Candidates per branch | `k` to 200 |
| Rank constant | 1 to 1,000,000, default 60 |
| Branch weight | Finite, greater than zero, at most 1,000,000 |
| Documents per atomic upsert / delete IDs | 1,000 |
| Prepared upsert data | 16 MiB per batch |
| Document text | 64 KiB UTF-8, nonblank |
| Document ID / title | 256 characters each |
| Namespace | 1 to 128 ASCII letters, digits, `_`, `.`, `:`, `-`; begins alphanumeric |
| Model label | 128 characters, nonblank |
| Metadata | 32 string pairs, 16 KiB serialized, identifier keys up to 64 characters |
| Metadata value | 1,024 characters |
| JSON / JSONL input | 16 MiB, JSONL line up to 256 KiB, nesting up to 32 levels |
| Report | 1 to 20 named query cases, 16 MiB serialized report data |

The vector scan is O(matching vectors × dimensions). The cap is an operational guard, not a throughput promise. Lexical search is not subject to the vector scan cap. Report generation uses the maximum default scan cap and should target small filtered corpora.

## Storage

Schema version 1 stores metadata, documents, standalone FTS5 rows and normalized little-endian float32 vectors in the same SQLite database. Updates explicitly maintain FTS rows in the same transaction. Only default DELETE journaling is supported. A new database is created exclusively, with mode 0600 where the platform honors POSIX file modes. SQLite files and HTML exports are unencrypted. There is no schema migration tool in this initial release.
