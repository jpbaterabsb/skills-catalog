"""HTTP client for the catalog API. Translates HTTP failures back into domain errors."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from urllib.parse import quote

import httpx

from ..core.errors import CatalogError, NotFoundError, ValidationError
from ..core.models import FileEntry, PublishResult, SearchResult, SkillVersion, VersionSummary


class CatalogUnreachableError(CatalogError):
    def __init__(self, url: str, reason: str = "") -> None:
        self.url = url
        super().__init__(f"catalog unreachable at {url}" + (f" ({reason})" if reason else ""))


class CatalogClient:
    def __init__(self, base_url: str, *, http: httpx.Client | None = None, timeout: float = 30):
        self.base_url = base_url.rstrip("/")
        self._http = http or httpx.Client(base_url=self.base_url, timeout=timeout)

    def __enter__(self) -> CatalogClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            raise CatalogUnreachableError(self.base_url, type(exc).__name__) from exc
        if response.status_code == 404:
            raise NotFoundError(_json(response).get("error") or f"{path} not found")
        if response.status_code == 422:
            raise ValidationError(_json(response).get("errors") or ["invalid request"])
        if response.is_error:
            raise CatalogError(f"catalog returned HTTP {response.status_code} for {path}")
        return response

    def publish(self, files: Mapping[str, bytes], author: str) -> PublishResult:
        encoded = {path: base64.b64encode(data).decode("ascii") for path, data in files.items()}
        body = self._request("POST", "/skills", json={"files": encoded, "author": author}).json()
        return PublishResult(body["name"], body["version"], body["digest"], body["created"])

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        body = self._request("GET", "/skills", params={"q": query, "limit": limit}).json()
        return [
            SearchResult(r["name"], r["description"], r["latest_version"]) for r in body["results"]
        ]

    def get(self, name: str, version: int | None = None) -> SkillVersion:
        params = {"version": version} if version is not None else {}
        b = self._request("GET", f"/skills/{_seg(name)}", params=params).json()
        return SkillVersion(
            name=b["name"],
            version=b["version"],
            digest=b["digest"],
            description=b["description"],
            published_by=b["published_by"],
            published_at=b["published_at"],
            skill_md=b["skill_md"],
            files=tuple(FileEntry(f["path"], f["sha256"], f["size"]) for f in b["files"]),
        )

    def versions(self, name: str) -> list[VersionSummary]:
        body = self._request("GET", f"/skills/{_seg(name)}/versions").json()
        return [
            VersionSummary(v["version"], v["digest"], v["published_by"], v["published_at"])
            for v in body["versions"]
        ]

    def blob(self, sha256: str) -> bytes:
        return self._request("GET", f"/blobs/{_seg(sha256)}").content


def _json(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _seg(value: str) -> str:
    """Quote a value as a single path segment, so names like ``../x`` stay one segment."""
    return quote(value, safe="")
