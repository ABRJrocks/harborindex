"""Run with: python examples/retrieval_adapter.py. No model or network needed."""

from harborindex import Document, Index

# Replace these illustrative vectors with the output of your own embedding pipeline.
MODEL = "toy-guide-3d-v1"
with Index.create(":memory:", dimensions=3, model=MODEL) as index:
    index.upsert(
        "customer-42",
        [
            Document(
                "guide-1",
                "Restore a verified backup before reopening writes.",
                "Recovery guide",
                {"visibility": "internal"},
                [1, 0, 0],
            ),
            Document(
                "guide-2",
                "Rotate tokens and revoke the previous credential.",
                "Token rotation",
                {"visibility": "internal"},
                [0, 1, 0],
            ),
        ],
        model=MODEL,
    )
    result = index.search(
        "customer-42",
        query="restore backup",
        vector=[1, 0, 0],
        model=MODEL,
        where={"visibility": "internal"},
        k=2,
    )
    # Feed these bounded results into your context builder with stable citation IDs.
    context = "\n\n".join(f"[{hit.id}] {hit.text}" for hit in result.hits)
    print(context)
    print(result.hits[0].components)
