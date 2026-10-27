"""Shared pytest fixtures."""

import pytest

from skills_catalog.core.service import CatalogService


@pytest.fixture
def service(tmp_path):
    return CatalogService(tmp_path / "catalog-data")
