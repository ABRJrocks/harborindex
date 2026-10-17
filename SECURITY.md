# Security

This initial release is intended for trusted local indexes. The embedding model and input documents are supplied by the host application. Namespace and metadata filters do not implement authentication or authorization.

Do not expose arbitrary SQLite files, file paths or report output paths through a public endpoint. Stored documents, vectors, queries and HTML reports may contain sensitive information. SQLite files and exports are unencrypted, and deletion is not secure erasure.

For a suspected vulnerability, use the repository's private vulnerability reporting feature when available: https://github.com/ABRJrocks/harborindex/security/advisories/new. Do not post secrets or private document samples in public issues. Only the current 0.1.x release line is maintained at launch.
