# Contributing

Open an issue with the concrete retrieval behavior, a minimal public dataset and expected document IDs. Remove private document content, credentials and embeddings derived from sensitive sources.

For changes, install the package in a Python 3.10+ environment, run the unittest suite and Ruff, and add a focused regression check for changed behavior. Report viewer changes should also run the browser checks in the README. Keep runtime dependencies at zero unless a demonstrated requirement justifies reconsidering that boundary. Document any score, ordering, filtering or storage compatibility change.

Small pull requests with a clear before/after example are easiest to review. Do not present toy-vector results as semantic-quality benchmarks.
