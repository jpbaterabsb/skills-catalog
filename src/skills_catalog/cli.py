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
    return parser


def cmd_publish(client: CatalogClient, args: argparse.Namespace) -> None:
    files, _ = load_skill_dir(args.directory)
    result = client.publish(files, config.author())
    if result.created:
        print(f"Published {result.name} v{result.version} ({result.digest})")
    else:
        print(f"Unchanged: {result.name} is already at v{result.version} ({result.digest})")


COMMANDS = {"publish": cmd_publish}


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
