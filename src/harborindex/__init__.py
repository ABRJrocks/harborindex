"""Inspectable hybrid retrieval with caller-supplied embeddings."""

from .search import Hit, Index, SearchResult, fuse
from .validation import Document, HarborError

__version__ = "0.1.0"
__all__ = ["Document", "HarborError", "Hit", "Index", "SearchResult", "fuse"]
