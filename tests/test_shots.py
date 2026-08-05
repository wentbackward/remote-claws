"""Test the shot registry: capability names, TTL expiry, eviction, no traversal."""

from remote_claws.shots import MAX_SHOTS, ShotRegistry


def _file(tmp_path, name="a.png", content=b"png"):
    p = tmp_path / name
    p.write_bytes(content)
    return p


def test_register_returns_unique_suffixed_names(tmp_path):
    reg = ShotRegistry(ttl_seconds=600)
    n1 = reg.register(_file(tmp_path, "a.png"))
    n2 = reg.register(_file(tmp_path, "b.png"))
    assert n1 != n2
    assert n1.endswith(".png") and n2.endswith(".png")
    assert "/" not in n1 and "\\" not in n1  # bare name, no path segments


def test_resolve_returns_path_while_fresh(tmp_path):
    reg = ShotRegistry(ttl_seconds=600)
    p = _file(tmp_path)
    assert reg.resolve(reg.register(p)) == p


def test_resolve_unknown_name_returns_none(tmp_path):
    reg = ShotRegistry(ttl_seconds=600)
    assert reg.resolve("no-such-shot.png") is None
    assert reg.resolve("../permissions.json") is None  # never a filesystem join


def test_expired_shot_resolves_none_and_file_deleted(tmp_path):
    reg = ShotRegistry(ttl_seconds=-1)  # already expired on registration
    p = _file(tmp_path)
    name = reg.register(p)
    assert reg.resolve(name) is None
    assert not p.exists()


def test_eviction_beyond_cap_deletes_oldest(tmp_path):
    reg = ShotRegistry(ttl_seconds=600)
    first = _file(tmp_path, "first.png")
    first_name = reg.register(first)
    for i in range(MAX_SHOTS):
        reg.register(_file(tmp_path, f"rest-{i}.png"))
    assert len(reg._shots) == MAX_SHOTS
    assert reg.resolve(first_name) is None
    assert not first.exists()


def test_resolve_missing_file_returns_none(tmp_path):
    reg = ShotRegistry(ttl_seconds=600)
    p = _file(tmp_path)
    name = reg.register(p)
    p.unlink()  # deleted out of band
    assert reg.resolve(name) is None
