"""Backup/restore logic with in-memory stand-ins for S3 and PostgreSQL (the real tools are covered end-to-end)."""
from __future__ import annotations

import io
import json
import os
import tarfile
from collections import namedtuple

import pytest

from odbackup import core
from odbackup.core import BackupError, BusyError, Config, create_backup, list_backups, restore_backup, verify_backup
from odbackup.s3 import NotFound, ObjectInfo, ObjectStream

Stored = namedtuple("Stored", "data content_type")
DUMP = b"PGDMP fake custom-format dump" * 1000


class FakeS3:
    def __init__(self, objects: dict[str, dict[str, Stored]]):
        self.objects = objects
        self.buckets = {"images": "training-images", "datasets": "datasets", "models": "models"}
        self.vanish: set[str] = set()  # keys that disappear between listing and download

    def iter_logical(self):
        yield from self.buckets

    def list(self, logical):
        return [ObjectInfo(k, len(v.data)) for k, v in sorted(self.objects[logical].items())]

    def open(self, logical, key):
        if key in self.vanish:
            raise NotFound(key)
        obj = self.objects[logical][key]
        return ObjectStream(io.BytesIO(obj.data), len(obj.data), obj.content_type, 1_700_000_000.0)

    def put(self, logical, key, stream, size, content_type):
        data = stream.read()
        assert len(data) == size
        self.objects[logical][key] = Stored(data, content_type)

    def empty(self, logical):
        n = len(self.objects[logical])
        self.objects[logical] = {}
        return n


class FakePostgres:
    def __init__(self, revision="0004", connections=0):
        self.revision, self.connections = revision, connections
        self.restored: bytes | None = None
        self.swapped = False

    def counts(self):
        return {"images": 2, "annotations": 5, "model_versions": 1}

    def size_bytes(self):
        return len(DUMP)

    def alembic_revision(self):
        return self.revision

    def dump(self, path):
        with open(path, "wb") as f:
            f.write(DUMP)

    def other_connections(self):
        return self.connections

    def restore_into_new_database(self, stream):
        self.restored = stream.read()
        return "db_restore"

    def swap_in(self, restored):
        self.swapped = True
        return "db_before_restore"


def sample_objects():
    return {
        "images": {"aa/1.jpg": Stored(b"\xff\xd8jpeg-1", "image/jpeg"), "thumbs/1.jpg": Stored(b"thumb", "image/jpeg")},
        "datasets": {"1/annotations.json": Stored(b'{"images": []}', "application/json")},
        "models": {"model-0001/openvino/model.bin": Stored(bytes(range(256)) * 1200, None)},
    }


@pytest.fixture()
def cfg(tmp_path):
    versions = tmp_path / "versions"
    versions.mkdir()
    for rev in ("0001", "0002", "0003", "0004"):
        (versions / f"{rev}_x.py").write_text(f'revision = "{rev}"\n')
    cache = tmp_path / "cache"
    (cache / "model-0001").mkdir(parents=True)
    (cache / "model-0001" / "model.xml").write_text("cached")
    return Config(backup_dir=str(tmp_path / "backups"), database_url="postgresql+psycopg://u:p@db/x",
                  model_cache_dir=str(cache), alembic_versions_dir=str(versions))


def test_backup_contains_database_and_all_objects(cfg):
    s3 = FakeS3(sample_objects())
    result = create_backup(cfg, s3, FakePostgres(), name="b1")

    assert result["status"] == "completed" and result["warnings"] == []
    assert result["contents"]["images"] == 2 and result["contents"]["models_objects"] == 1
    assert result["progress"]["objects_done"] == result["progress"]["objects_total"] == 4
    path = os.path.join(cfg.backup_dir, "b1.tar")
    with tarfile.open(path) as tar:
        names = tar.getnames()
        assert names[:2] == ["manifest.json", "database.dump"] and names[-1] == "summary.json"
        assert "s3/images/aa/1.jpg" in names and "s3/models/model-0001/openvino/model.bin" in names
        assert tar.getmember("s3/images/aa/1.jpg").pax_headers[core.CONTENT_TYPE_PAX] == "image/jpeg"
        assert tar.extractfile("database.dump").read() == DUMP
    # nothing temporary left behind
    assert sorted(os.listdir(cfg.backup_dir)) == [".lock", "b1.json", "b1.tar"]
    assert verify_backup(path)["summary"]["objects"] == {"images": 2, "datasets": 1, "models": 1}


def test_restore_round_trip(cfg):
    original = sample_objects()
    create_backup(cfg, FakeS3(original), FakePostgres(), name="b1")
    target = FakeS3({"images": {"other.jpg": Stored(b"x", None)}, "datasets": {}, "models": {}})
    pg = FakePostgres()

    result = restore_backup(cfg, target, pg, os.path.join(cfg.backup_dir, "b1.tar"), echo=lambda _m: None)

    assert pg.restored == DUMP and pg.swapped
    assert target.objects == original  # incl. content types; objects not in the backup are gone
    assert result["objects"] == {"images": 2, "datasets": 1, "models": 1}
    assert os.listdir(cfg.model_cache_dir) == []  # stale OpenVINO cache cleared


def test_restore_refuses_while_stack_is_running(cfg):
    create_backup(cfg, FakeS3(sample_objects()), FakePostgres(), name="b1")
    pg = FakePostgres(connections=3)
    with pytest.raises(BackupError, match="stop api and trainer"):
        restore_backup(cfg, FakeS3(sample_objects()), pg, os.path.join(cfg.backup_dir, "b1.tar"), echo=lambda _m: None)
    assert pg.restored is None


def test_restore_refuses_unknown_schema(cfg):
    create_backup(cfg, FakeS3(sample_objects()), FakePostgres(revision="0099"), name="b1")
    pg = FakePostgres()
    with pytest.raises(BackupError, match="newer version"):
        restore_backup(cfg, FakeS3(sample_objects()), pg, os.path.join(cfg.backup_dir, "b1.tar"), echo=lambda _m: None)
    assert pg.restored is None


def test_truncated_backup_is_rejected_before_anything_changes(cfg):
    create_backup(cfg, FakeS3(sample_objects()), FakePostgres(), name="b1")
    path = os.path.join(cfg.backup_dir, "b1.tar")
    with open(path, "r+b") as f:
        f.truncate(os.path.getsize(path) - 200_000)
    target = FakeS3(sample_objects())
    pg = FakePostgres()
    with pytest.raises((BackupError, tarfile.TarError)):
        restore_backup(cfg, target, pg, path, echo=lambda _m: None)
    assert pg.restored is None and target.objects == sample_objects()


def test_object_deleted_during_backup_is_reported(cfg):
    s3 = FakeS3(sample_objects())
    s3.vanish = {"thumbs/1.jpg"}
    result = create_backup(cfg, s3, FakePostgres(), name="b1")
    assert result["status"] == "completed"
    assert result["warnings"] == ["images/thumbs/1.jpg: deleted during the backup, not included"]
    assert verify_backup(os.path.join(cfg.backup_dir, "b1.tar"))["summary"]["objects"]["images"] == 1


def test_failed_backup_leaves_no_partial_file(cfg):
    class Broken(FakeS3):
        def open(self, logical, key):
            if logical == "models":
                raise ConnectionError("S3 unreachable")
            return super().open(logical, key)

    with pytest.raises(ConnectionError):
        create_backup(cfg, Broken(sample_objects()), FakePostgres(), name="b1")
    assert sorted(os.listdir(cfg.backup_dir)) == [".lock", "b1.json"]
    status = json.load(open(os.path.join(cfg.backup_dir, "b1.json")))
    assert status["status"] == "failed" and "S3 unreachable" in status["error"]


def test_not_enough_disk_space(cfg, monkeypatch):
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(core.shutil, "disk_usage", lambda _p: Usage(10**9, 10**9, 1000))
    with pytest.raises(BackupError, match="not enough disk space"):
        create_backup(cfg, FakeS3(sample_objects()), FakePostgres(), name="b1")


def test_only_one_backup_at_a_time(cfg):
    with core.exclusive(cfg.backup_dir):
        assert core.is_busy(cfg.backup_dir)
        with pytest.raises(BusyError):
            create_backup(cfg, FakeS3(sample_objects()), FakePostgres(), name="b2")
    assert not core.is_busy(cfg.backup_dir)


def test_list_and_interrupted_backups(cfg):
    create_backup(cfg, FakeS3(sample_objects()), FakePostgres(), name="b1")
    core.StatusFile(cfg.backup_dir, "b2", {"name": "b2", "status": "running", "created_at": "2099-01-01T00:00:00+00:00"})
    core.StatusFile(cfg.backup_dir, "b3", {"name": "b3", "status": "queued", "created_at": "2099-01-02T00:00:00+00:00"})
    # a tar copied in from elsewhere, without status file
    os.link(os.path.join(cfg.backup_dir, "b1.tar"), os.path.join(cfg.backup_dir, "copied.tar"))

    assert core.mark_interrupted(cfg.backup_dir, pending=frozenset({"b3"})) == 1
    items = {i["name"]: i for i in list_backups(cfg.backup_dir)}
    assert items["b1"]["status"] == "completed" and items["b1"]["size_bytes"] > 0
    assert items["b2"]["status"] == "failed" and "interrupted" in items["b2"]["error"]
    assert items["b3"]["status"] == "queued"  # its job is still in the queue
    assert items["copied"]["source"] == "imported" and items["copied"]["contents"]["images"] == 2


def test_invalid_names(cfg):
    for bad in ("../etc", "a/b", "", "x.tar"):
        with pytest.raises(BackupError):
            core.check_name(bad)


def test_large_objects_are_uploaded_from_a_non_seekable_tar_stream(tmp_path):
    """Regression: boto3 asked the tar stream whether it is seekable, which raised AttributeError."""
    from odbackup.s3 import S3, SequentialReader

    calls = []

    class Client:
        def upload_fileobj(self, fileobj, bucket, key, ExtraArgs=None, Config=None):
            assert fileobj.seekable() is False
            calls.append((bucket, key, len(fileobj.read()), ExtraArgs))

    data = bytes(range(256)) * 40
    path = tmp_path / "t.tar"
    with tarfile.open(path, "w") as tar:
        info = tarfile.TarInfo("s3/models/big.pth")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    s3 = S3(client=Client(), buckets={"models": "models"})
    import odbackup.s3 as s3mod

    with tarfile.open(path, mode="r|") as tar, pytest.MonkeyPatch.context() as mp:
        mp.setattr(s3mod, "SMALL_OBJECT", 100)  # force the multipart path
        member = tar.next()
        s3.put("models", "big.pth", tar.extractfile(member), member.size, None)
    assert calls == [("models", "big.pth", len(data), None)]
    assert SequentialReader(io.BytesIO(b"")).seekable() is False
