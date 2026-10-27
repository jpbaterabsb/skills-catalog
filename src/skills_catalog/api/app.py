"""HTTP API for the shared catalog.

Routes stay thin: they decode transport details and call :class:`CatalogService`. Domain errors
are mapped to HTTP statuses in exactly one place (the exception handlers below).
"""

from __future__ import annotations

import argparse
import base64
import binascii
import logging
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from .. import config
from ..core.errors import NotFoundError, ValidationError
from ..core.search import DEFAULT_LIMIT, MAX_LIMIT
from ..core.service import CatalogService

log = logging.getLogger("skills_catalog.api")
BLOB_CACHE_CONTROL = "public, max-age=31536000, immutable"


class PublishRequest(BaseModel):
    files: dict[str, str]
    author: str = "unknown"


def decode_files(encoded: dict[str, str]) -> dict[str, bytes]:
    files, errors = {}, []
    for path, data in encoded.items():
        try:
            files[path] = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            errors.append(f"{path}: content is not valid base64")
    if errors:
        raise ValidationError(errors)
    return files


def create_app(data_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="Skills Catalog", version="0.1.0")
    service = CatalogService(data_dir if data_dir is not None else config.data_dir())
    app.state.service = service

    @app.exception_handler(ValidationError)
    async def _validation_error(_: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse({"errors": exc.errors}, status_code=422)

    @app.exception_handler(RequestValidationError)
    async def _bad_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
        return JSONResponse({"errors": errors}, status_code=422)

    @app.exception_handler(NotFoundError)
    async def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse({"error": str(exc)}, status_code=404)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/skills")
    def publish(body: PublishRequest) -> JSONResponse:
        result = service.publish(decode_files(body.files), body.author)
        log.info(
            "publish name=%s version=%s digest=%s created=%s",
            result.name,
            result.version,
            result.digest,
            result.created,
        )
        return JSONResponse(
            {
                "name": result.name,
                "version": result.version,
                "digest": result.digest,
                "created": result.created,
            },
            status_code=201 if result.created else 200,
        )

    @app.get("/skills")
    def search(q: str = "", limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)) -> dict:
        return {
            "results": [
                {"name": r.name, "description": r.description, "latest_version": r.latest_version}
                for r in service.search(q, limit)
            ]
        }

    @app.get("/skills/{name}")
    def get_skill(name: str, version: int | None = Query(None, ge=1)) -> dict:
        skill = service.get(name, version)
        return {
            "name": skill.name,
            "version": skill.version,
            "digest": skill.digest,
            "description": skill.description,
            "published_by": skill.published_by,
            "published_at": skill.published_at,
            "skill_md": skill.skill_md,
            "files": [{"path": f.path, "sha256": f.sha256, "size": f.size} for f in skill.files],
        }

    @app.get("/skills/{name}/versions")
    def versions(name: str) -> dict:
        return {
            "name": name,
            "versions": [
                {
                    "version": v.version,
                    "digest": v.digest,
                    "published_by": v.published_by,
                    "published_at": v.published_at,
                }
                for v in service.history(name)
            ],
        }

    @app.get("/blobs/{sha256}")
    def blob(sha256: str) -> Response:
        return Response(
            service.read_blob(sha256),
            media_type="application/octet-stream",
            headers={"Cache-Control": BLOB_CACHE_CONTROL},
        )

    return app


def main(argv: list[str] | None = None) -> None:
    """Run the catalog API. Binds to the host and port of $SKILLS_CATALOG_URL by default."""
    import uvicorn

    default = urlsplit(config.catalog_url())
    parser = argparse.ArgumentParser(prog="skills-catalog-api", description=main.__doc__)
    parser.add_argument("--host", default=default.hostname or "127.0.0.1")
    parser.add_argument("--port", type=int, default=default.port or 8765)
    parser.add_argument("--data", type=Path, default=None, help="data directory")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    uvicorn.run(create_app(args.data), host=args.host, port=args.port)
