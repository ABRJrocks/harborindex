"""Command line adapters for local files and JSON output."""

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict

from . import __version__
from .demo import run_demo
from .jsonio import loads, read_documents, read_json
from .report import compare, write_report
from .search import Index
from .validation import HarborError


def parser():
    root = argparse.ArgumentParser(
        description="Inspectable local hybrid retrieval. Vectors are supplied by you."
    )
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="command", required=True)
    init = commands.add_parser(
        "init", help="Create a new index without overwriting files"
    )
    init.add_argument("path")
    init.add_argument("--dimensions", type=int)
    init.add_argument("--model")
    for name in ("upsert", "search", "delete", "stats", "report"):
        command = commands.add_parser(name)
        command.add_argument("path")
        command.add_argument("--namespace", required=True)
        if name == "upsert":
            command.add_argument(
                "--input", required=True, help="JSONL documents, one atomic batch"
            )
            command.add_argument("--model")
        elif name == "delete":
            command.add_argument("ids", nargs="+")
        elif name in ("search", "report"):
            command.add_argument("--model")
            command.add_argument("--k", type=int, default=5 if name == "report" else 10)
            command.add_argument("--candidates", type=int, default=50)
            command.add_argument("--rank-constant", type=int, default=60)
            command.add_argument("--lexical-weight", type=float, default=1)
            command.add_argument("--dense-weight", type=float, default=1)
            if name == "search":
                command.add_argument(
                    "--mode", choices=("lexical", "dense", "hybrid"), default="lexical"
                )
                command.add_argument("--query")
                command.add_argument(
                    "--vector", help="JSON file containing the query vector array"
                )
                command.add_argument(
                    "--where", default="{}", help="Flat JSON object of string filters"
                )
                command.add_argument("--max-scan", type=int, default=10000)
            else:
                command.add_argument(
                    "--queries", required=True, help="JSON array of named query cases"
                )
                command.add_argument(
                    "--output",
                    required=True,
                    help="New HTML file; includes retrieved document content",
                )
    demo = commands.add_parser(
        "demo",
        help="Verify illustrative toy vectors and optionally write an HTML report",
    )
    demo.add_argument("--output")
    return root


def execute(args):
    if args.command == "demo":
        report = run_demo()
        if args.output:
            write_report(args.output, report)
        return {
            "verified": True,
            "toy_vectors": True,
            "cases": len(report["cases"]),
            "output": args.output,
        }
    if args.command == "init":
        with Index.create(
            args.path, dimensions=args.dimensions, model=args.model
        ) as index:
            return {
                "created": True,
                "model": index.model,
                "dimensions": index.dimensions,
            }
    with Index.open(
        args.path, read_only=args.command in ("search", "stats", "report")
    ) as index:
        if args.command == "upsert":
            return {
                "upserted": index.upsert(
                    args.namespace, read_documents(args.input), model=args.model
                )
            }
        if args.command == "delete":
            return {"deleted": index.delete(args.namespace, args.ids)}
        if args.command == "stats":
            return index.stats(args.namespace)
        options = dict(
            k=args.k,
            candidate_limit=args.candidates,
            rank_constant=args.rank_constant,
            lexical_weight=args.lexical_weight,
            dense_weight=args.dense_weight,
        )
        if args.command == "search":
            return asdict(
                index.search(
                    args.namespace,
                    mode=args.mode,
                    query=args.query,
                    vector=read_json(args.vector) if args.vector else None,
                    model=args.model,
                    where=loads(args.where),
                    max_scan=args.max_scan,
                    **options,
                )
            )
        report = compare(
            index, args.namespace, read_json(args.queries), model=args.model, **options
        )
        write_report(args.output, report)
        return {
            "written": args.output,
            "cases": len(report["cases"]),
            "revision": report["revision"],
        }


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = execute(args)
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return 0
    except HarborError as error:
        print(f"harborindex: {error}", file=sys.stderr)
    except FileExistsError:
        print("harborindex: Output already exists; choose a new path", file=sys.stderr)
    except (OSError, sqlite3.Error):
        print(
            "harborindex: Unable to access the index or file; check paths, permissions, SQLite FTS5/JSON1 support and database integrity",
            file=sys.stderr,
        )
    return 2
