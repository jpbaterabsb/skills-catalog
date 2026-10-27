import hashlib

from skills_catalog.core.digest import bundle_digest, digest_files, file_sha256


def test_file_sha256_is_plain_lowercase_hex():
    assert file_sha256(b"abc") == hashlib.sha256(b"abc").hexdigest()


def test_bundle_digest_matches_the_documented_formula():
    files = {"b.md": b"B", "SKILL.md": b"S"}
    lines = "".join(f"{p}\0{hashlib.sha256(files[p]).hexdigest()}\n" for p in sorted(files))
    assert digest_files(files) == "sha256:" + hashlib.sha256(lines.encode()).hexdigest()


def test_digest_is_order_independent():
    a = {"SKILL.md": b"s", "a/x.md": b"x", "b.md": b"b"}
    b = dict(reversed(list(a.items())))
    assert digest_files(a) == digest_files(b)


def test_digest_changes_with_one_byte():
    assert digest_files({"SKILL.md": b"hello"}) != digest_files({"SKILL.md": b"hellp"})


def test_digest_changes_when_a_file_is_renamed():
    assert digest_files({"a.md": b"x"}) != digest_files({"b.md": b"x"})


def test_crlf_is_not_normalized():
    assert digest_files({"SKILL.md": b"a\nb\n"}) != digest_files({"SKILL.md": b"a\r\nb\r\n"})


def test_bundle_digest_accepts_precomputed_hashes():
    files = {"SKILL.md": b"s", "t.md": b"t"}
    entries = [(p, file_sha256(d)) for p, d in files.items()]
    assert bundle_digest(entries) == digest_files(files)
