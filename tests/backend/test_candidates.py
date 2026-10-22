"""Candidate search: starting, listing with the effect of accepting, accepting/rejecting."""
from __future__ import annotations

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from odcore.db import Annotation, AnnotationStatus, BatchStatus, Candidate, CandidateSearch, Image, utcnow

from app.api.routes import candidates as candidates_route
from app.core.database import get_db
from app.core.s3 import get_storage
from app.main import app
from app.services.annotation_crops import decoded_cache

from conftest import FakeStorage

API = "/api/v1/candidates"


@pytest.fixture()
def env(session_factory, monkeypatch):
    ok, buf = cv2.imencode(".jpg", np.full((1080, 1920, 3), 128, np.uint8))
    storage = FakeStorage(buf.tobytes())
    queued: list[int] = []
    monkeypatch.setattr(candidates_route, "enqueue_candidate_search", lambda search_id: queued.append(search_id) or "job")

    def db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_storage] = lambda: storage
    decoded_cache._items.clear()
    yield TestClient(app), session_factory, queued
    app.dependency_overrides.clear()


def seed(session_factory, status=BatchStatus.completed):
    """One labeled image with a person box and a vehicle box, searched for "vehicle"; returns the candidate ids."""
    with session_factory() as s:
        image = Image(s3_object_key="a.jpg", sha256="a" * 64, content_type="image/jpeg", size_bytes=1, width=1920, height=1080,
                      annotation_status=AnnotationStatus.labeled, reviewed_classes=["person", "bicycle"])
        gone = Image(s3_object_key="b.jpg", sha256="b" * 64, content_type="image/jpeg", size_bytes=1, width=1920, height=1080,
                     deleted_at=utcnow())
        search = CandidateSearch(class_name="vehicle", prompts=["car"], scope="all", status=status)
        s.add_all([image, gone, search])
        s.flush()
        s.add_all([
            Annotation(image_id=image.id, class_name="person", x1=100, y1=100, x2=300, y2=400),
            Annotation(image_id=image.id, class_name="vehicle", x1=1000, y1=500, x2=1400, y2=800),
        ])
        c = lambda **kw: Candidate(search_id=search.id, image_id=image.id, prompt="car", **kw)  # noqa: E731
        cands = [
            c(x1=105, y1=100, x2=300, y2=395, score=0.9),      # on the person box: accepting reclassifies it
            c(x1=600, y1=600, x2=800, y2=700, score=0.8),      # empty area: new box
            c(x1=1010, y1=500, x2=1400, y2=800, score=0.7),    # on a vehicle box: exists
            c(x1=1500, y1=100, x2=1600, y2=200, score=0.15),
            Candidate(search_id=search.id, image_id=gone.id, prompt="car", x1=0, y1=0, x2=50, y2=50, score=0.95),  # deleted image
        ]
        s.add_all(cands)
        s.commit()
        return search.id, [x.id for x in cands]


def test_start_search_queues_one_job_at_a_time(env):
    client, _, queued = env
    body = {"class": "vehicle", "prompts": [" excavator ", "excavator", "digger"], "scope": "labeled", "min_score": 0.2}
    res = client.post(f"{API}/searches", json=body)
    assert res.status_code == 202
    out = res.json()
    assert out["class"] == "vehicle" and out["prompts"] == ["excavator", "digger"] and out["status"] == "queued"
    assert queued == [out["id"]]
    assert client.post(f"{API}/searches", json=body).status_code == 409  # one at a time
    assert client.post(f"{API}/searches/{out['id']}/cancel").json()["status"] == "cancelled"
    assert client.post(f"{API}/searches", json=body).status_code == 202


def test_start_search_with_examples_copies_the_boxes(env):
    client, session_factory, queued = env
    search_id, _ = seed(session_factory)  # image 1 has a person box and a vehicle box
    client.delete(f"{API}/searches/{search_id}")
    with session_factory() as s:
        ids = [a.id for a in s.query(Annotation).order_by(Annotation.id)]
    res = client.post(f"{API}/searches", json={"class": "vehicle", "mode": "examples", "exemplar_ids": ids + [ids[0]]})
    assert res.status_code == 202
    out = res.json()
    assert out["mode"] == "examples" and out["examples"] == 2 and out["prompts"] == [] and queued == [out["id"]]
    with session_factory() as s:
        stored = s.get(CandidateSearch, out["id"]).exemplars
    assert [(e["class"], e["x1"], e["x2"]) for e in stored] == [("person", 100, 300), ("vehicle", 1000, 1400)]
    # the copies survive the annotation being replaced (ids change whenever an image is saved)
    assert stored[0]["image_id"] == 1


def test_examples_must_be_real_objects_of_existing_images(env):
    client, session_factory, _ = env
    assert client.post(f"{API}/searches", json={"class": "vehicle", "mode": "examples"}).status_code == 422
    assert client.post(f"{API}/searches", json={"class": "vehicle", "mode": "examples", "exemplar_ids": [999]}).status_code == 422
    with session_factory() as s:
        image = Image(s3_object_key="c.jpg", sha256="c" * 64, content_type="image/jpeg", size_bytes=1, width=100, height=100)
        s.add(image)
        s.flush()
        s.add_all([Annotation(image_id=image.id, class_name="person", x1=1, y1=1, x2=50, y2=50, type="hard_negative"),
                   Annotation(image_id=image.id, class_name="person", x1=1, y1=1, x2=60, y2=60, type="ignore")])
        s.commit()
        ids = [a.id for a in s.query(Annotation)]
    res = client.post(f"{API}/searches", json={"class": "vehicle", "mode": "examples", "exemplar_ids": ids})
    assert res.status_code == 422 and "not found" in res.json()["detail"]  # only real objects are examples


def test_start_search_validates_class_and_prompts(env):
    client, _, _ = env
    assert client.post(f"{API}/searches", json={"class": "dog", "prompts": ["dog"]}).status_code == 422
    assert client.post(f"{API}/searches", json={"class": "vehicle", "prompts": []}).status_code == 422
    assert client.post(f"{API}/searches", json={"class": "vehicle", "prompts": ["  "]}).status_code == 422


def test_candidates_show_what_accepting_does(env):
    client, session_factory, _ = env
    search_id, _ = seed(session_factory)
    res = client.get(f"{API}/searches/{search_id}/items").json()
    assert res["total"] == 4 and res["margin"] == 20  # the deleted image is skipped
    assert [(i["score"], i["action"], i["current_class"]) for i in res["items"]] == [
        (0.9, "reclassify", "person"), (0.8, "new", None), (0.7, "exists", "vehicle"), (0.15, "new", None)]
    assert client.get(f"{API}/searches/{search_id}/items", params={"min_score": 0.5}).json()["total"] == 3
    assert [i["id"] for i in client.get(f"{API}/searches/{search_id}/items", params={"sort": "image"}).json()["items"]][0] > 0
    counts = client.get(f"{API}/searches/{search_id}").json()
    assert (counts["pending"], counts["accepted"], counts["rejected"]) == (4, 0, 0)


def test_accept_reclassifies_or_adds_and_keeps_the_image_status(env):
    client, session_factory, _ = env
    search_id, ids = seed(session_factory)
    res = client.post(f"{API}/decide", json={"accept": ids[:3], "reject": [ids[3]]}).json()
    assert res == {"added": 1, "reclassified": 1, "already_present": 1, "rejected": 1}
    with session_factory() as s:
        image = s.query(Image).filter_by(sha256="a" * 64).one()
        boxes = sorted((a.class_name, round(a.x1), a.source, a.source_model) for a in image.annotations)
        assert boxes == [("vehicle", 100, "manual", None), ("vehicle", 600, "prediction", "owlv2"), ("vehicle", 1000, "manual", None)]
        # reviewed for the old classes only: the image still needs a review for "vehicle" before it is trained with it
        assert image.annotation_status == AnnotationStatus.labeled and image.reviewed_classes == ["person", "bicycle"]
    states = {state: client.get(f"{API}/searches/{search_id}/items", params={"status": state}).json()["total"]
              for state in ("pending", "accepted", "rejected")}
    assert states == {"pending": 0, "accepted": 3, "rejected": 1}
    again = client.post(f"{API}/decide", json={"accept": [ids[1]]}).json()
    assert again["added"] == 0 and again["already_present"] == 1  # accepting twice does not duplicate the box


def test_reject_wins_nothing_over_accept_and_unknown_ids_are_ignored(env):
    client, session_factory, _ = env
    _, ids = seed(session_factory)
    res = client.post(f"{API}/decide", json={"accept": [ids[1], 99999], "reject": [ids[1], 88888]}).json()
    assert res["added"] == 1 and res["rejected"] == 0  # an id in both lists is accepted


def test_delete_search_removes_candidates_unless_running(env):
    client, session_factory, _ = env
    search_id, _ = seed(session_factory, status=BatchStatus.running)
    assert client.delete(f"{API}/searches/{search_id}").status_code == 409
    client.post(f"{API}/searches/{search_id}/cancel")
    assert client.delete(f"{API}/searches/{search_id}").status_code == 204
    assert client.get(f"{API}/searches/{search_id}").status_code == 404
    with session_factory() as s:
        assert s.query(Candidate).count() == 0


def test_crop_endpoint(env):
    client, session_factory, _ = env
    _, ids = seed(session_factory)
    res = client.get(f"{API}/{ids[1]}/crop")
    assert res.status_code == 200 and res.headers["content-type"] == "image/jpeg"
    assert cv2.imdecode(np.frombuffer(res.content, np.uint8), cv2.IMREAD_COLOR).shape[:2] == (140, 240)  # 200x100 box + 2x20
    assert client.get(f"{API}/{ids[4]}/crop").status_code == 404  # deleted image
    assert client.get(f"{API}/99999/crop").status_code == 404
