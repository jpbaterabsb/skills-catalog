from skills_catalog.core.errors import (
    CatalogError,
    NotFoundError,
    SkillNotFoundError,
    ValidationError,
    VersionNotFoundError,
)


def test_validation_error_keeps_every_message():
    err = ValidationError(["missing name", "empty body"])
    assert err.errors == ["missing name", "empty body"]
    assert "missing name" in str(err) and "empty body" in str(err)
    assert isinstance(err, CatalogError)


def test_not_found_errors_share_a_base_class():
    assert isinstance(SkillNotFoundError("x"), NotFoundError)
    assert isinstance(VersionNotFoundError("x", 3), NotFoundError)
    assert "version 3" in str(VersionNotFoundError("x", 3))
