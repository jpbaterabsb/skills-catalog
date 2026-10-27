"""Command-line interface: ``skills publish | search | get | history``.

Exit codes: 0 on success, 1 on domain errors (validation, not found, catalog unreachable),
2 on usage errors (argparse).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config
from .adapter.client import CatalogClient
from .core.errors import CatalogError, ValidationError
from .core.validation import load_skill_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skills", description="Shared Agent Skills catalog.")
    parser.add_argument("--catalog", help="catalog URL (default: $SKILLS_CATALOG_URL)")
    commands = parser.add_subparsers(dest="command", required=True)

    publish = commands.add_parser("publish", help="publish a skill directory as a new version")
    publish.add_argument("directory", type=Path)

    search = commands.add_parser("search", help="find skills by keywords")
    search.add_argument("query", nargs="+")
    search.add_argument("--limit", type=int, default=5)

    get = commands.add_parser("get", help="show a skill's SKILL.md and file list")
    get.add_argument("name")
    get.add_argument("--version", type=int, default=None)

    history = commands.add_parser("history", help="list every version of a skill")
    history.add_argument("name")
    return parser


def cmd_publish(client: CatalogClient, args: argparse.Namespace) -> None:
    files, _ = load_skill_dir(args.directory)
    result = client.publish(files, config.author())
    if result.created:
        print(f"Published {result.name} v{result.version} ({result.digest})")
    else:
        print(f"Unchanged: {result.name} is already at v{result.version} ({result.digest})")


def cmd_search(client: CatalogClient, args: argparse.Namespace) -> None:
    query = " ".join(args.query)
    results = client.search(query, args.limit)
    if not results:
        print(f'No skills matched "{query}".')
    for r in results:
        print(f"{r.name} (v{r.latest_version}) — {r.description}")


def cmd_get(client: CatalogClient, args: argparse.Namespace) -> None:
    skill = client.get(args.name, args.version)
    print(f"{skill.name} v{skill.version} ({skill.digest})")
    print(f"published by {skill.published_by} at {skill.published_at}")
    print()
    print(skill.skill_md.rstrip("\n"))
    print()
    print("Files:")
    for f in skill.files:
        print(f"  {f.path} ({f.size} bytes)")


def cmd_history(client: CatalogClient, args: argparse.Namespace) -> None:
    for v in client.versions(args.name):
        print(f"v{v.version}  {v.published_at}  {v.published_by}  {v.digest}")


COMMANDS = {"publish": cmd_publish, "search": cmd_search, "get": cmd_get, "history": cmd_history}


def run(argv: list[str] | None = None, client: CatalogClient | None = None) -> int:
    args = build_parser().parse_args(argv)
    own_client = client is None
    client = client or CatalogClient(args.catalog or config.catalog_url())
    try:
        COMMANDS[args.command](client, args)
    except ValidationError as exc:
        print("error: skill is invalid:", file=sys.stderr)
        for error in exc.errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    except CatalogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if own_client:
            client.close()
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
