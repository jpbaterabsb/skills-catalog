import threading

from skills_catalog.core.service import CatalogService
from tests.helpers import bundle

WRITERS = 8


def test_concurrent_publishes_of_the_same_skill_get_distinct_versions(tmp_path):
    data_dir = tmp_path / "catalog-data"
    CatalogService(data_dir)  # create the schema once, as the API does at startup
    barrier = threading.Barrier(WRITERS)
    results, errors = [], []

    def publish(i: int) -> None:
        # A separate service per thread: separate connections, shared database file.
        service = CatalogService(data_dir)
        barrier.wait()
        try:
            results.append(service.publish(bundle("shared", payload=f"{i}".encode()), f"dev{i}"))
        except Exception as exc:  # collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=publish, args=(i,)) for i in range(WRITERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert all(r.created for r in results)
    assert sorted(r.version for r in results) == list(range(1, WRITERS + 1))

    with CatalogService(data_dir).store.read() as conn:
        rows = conn.execute("SELECT version, digest FROM versions ORDER BY version").fetchall()
    assert [r["version"] for r in rows] == list(range(1, WRITERS + 1))
    assert {r["digest"] for r in rows} == {r.digest for r in results}
