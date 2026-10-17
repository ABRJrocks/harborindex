"""Bounded JSON input with duplicate-key and non-finite number rejection."""

import json
import math
from pathlib import Path

from .validation import MAX_BATCH_BYTES, Document, HarborError, require


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "JSON object contains duplicate keys")
        result[key] = value
    return result


def _constant(value):
    raise HarborError("JSON numbers must be finite")


def loads(value):
    try:
        result = json.loads(value, object_pairs_hook=_pairs, parse_constant=_constant)
    except (json.JSONDecodeError, UnicodeError, RecursionError) as error:
        raise HarborError("Invalid JSON input") from error
    pending = [(result, 0)]
    while pending:
        node, depth = pending.pop()
        require(depth <= 32, "JSON nesting exceeds 32 levels")
        if isinstance(node, float):
            require(math.isfinite(node), "JSON numbers must be finite")
        if isinstance(node, (dict, list)):
            children = node.values() if isinstance(node, dict) else node
            pending.extend((child, depth + 1) for child in children)
    return result


def read_json(path):
    with Path(path).open("rb") as source:
        raw = source.read(MAX_BATCH_BYTES + 1)
    require(len(raw) <= MAX_BATCH_BYTES, "JSON input exceeds 16 MiB")
    return loads(raw)


def read_documents(path):
    documents = []
    size = 0
    with Path(path).open("rb") as source:
        while True:
            line = source.readline(256 * 1024 + 1)
            if not line:
                break
            size += len(line)
            require(size <= MAX_BATCH_BYTES, "JSONL input exceeds 16 MiB")
            require(len(line) <= 256 * 1024, "JSONL line exceeds 256 KiB")
            if not line.strip():
                continue
            require(len(documents) < 1000, "JSONL input exceeds 1000 documents")
            row = loads(line)
            require(
                type(row) is dict
                and not set(row) - {"id", "title", "text", "metadata", "vector"},
                "Document has unknown fields or is not an object",
            )
            require("id" in row and "text" in row, "Document requires id and text")
            documents.append(Document(**row))
    require(documents, "JSONL input contains no documents")
    return documents
