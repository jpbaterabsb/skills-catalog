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
def api_app(tmp_path):
    return create_app(tmp_path / "api-data")


@pytest.fixture
def make_client(api_app):
    """Factory of CatalogClients talking to the in-process API (no network)."""
    return lambda: CatalogClient("http://testserver", http=TestClient(api_app))


@pytest.fixture
def catalog_client(make_client):
    with make_client() as client:
        yield client
