"""Shared pytest fixtures."""

import pytest
from fastapi.testclient import TestClient

from skills_catalog.adapter.client import CatalogClient
from skills_catalog.api.app import create_app
from skills_catalog.core.service import CatalogService


@pytest.fixture
def service(tmp_path):
    return CatalogService(tmp_path / "catalog-data")


@pytest.fixture
def catalog_client(tmp_path):
    """A CatalogClient talking to an in-process API (no network)."""
    app = create_app(tmp_path / "api-data")
    with CatalogClient("http://testserver", http=TestClient(app)) as client:
        yield client
