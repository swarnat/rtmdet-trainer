"""SQLAlchemy ORM models shared by the API (owner of the migrations) and the trainer."""
from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class AnnotationStatus(str, enum.Enum):
    unlabeled = "unlabeled"
    labeled = "labeled"


class DatasetSplit(str, enum.Enum):
    train = "train"
    validation = "validation"


class TrainingStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class ModelStatus(str, enum.Enum):
    candidate = "candidate"
    production = "production"
    archived = "archived"


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    # Stored as plain VARCHAR + CHECK constraint: easy to extend via migrations.
    return Enum(cls, name=name, native_enum=False, length=32, values_callable=lambda e: [m.value for m in e])


class Image(Base):
    __tablename__ = "images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    s3_object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    thumbnail_key: Mapped[Optional[str]] = mapped_column(String(512))
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    original_filename: Mapped[Optional[str]] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    annotation_status: Mapped[AnnotationStatus] = mapped_column(
        _enum(AnnotationStatus, "annotation_status"), nullable=False, default=AnnotationStatus.unlabeled, index=True
    )
    dataset_split: Mapped[Optional[DatasetSplit]] = mapped_column(_enum(DatasetSplit, "dataset_split"))
    labeled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Classes the image was checked for when it was last saved as labeled. An image
    # is only used for training if it was checked for every class of the run, so
    # adding a class never turns unreviewed objects into "background".
    reviewed_classes: Mapped[Optional[list[str]]] = mapped_column(JSONType)
    # Link count (like nlink in a Unix file system): number of dataset snapshots (training runs)
    # that use this image. Snapshots reference the file in the images bucket instead of copying it,
    # so a referenced image is only hidden when deleted (``deleted_at``); its file is removed when
    # the last snapshot referencing it is released. Kept in sync with ``snapshot_images``.
    snapshot_refs: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow, server_default=func.now()
    )

    annotations: Mapped[list["Annotation"]] = relationship(
        back_populates="image", cascade="all, delete-orphan", order_by="Annotation.id"
    )


class SnapshotImage(Base):
    """Link between a training run's dataset snapshot and an image it uses (see ``Image.snapshot_refs``)."""

    __tablename__ = "snapshot_images"

    training_run_id: Mapped[int] = mapped_column(ForeignKey("training_runs.id", ondelete="CASCADE"), primary_key=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id"), primary_key=True, index=True)


class Annotation(Base):
    __tablename__ = "annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"), nullable=False, index=True)
    class_name: Mapped[str] = mapped_column(String(64), nullable=False)
    x1: Mapped[float] = mapped_column(Float, nullable=False)
    y1: Mapped[float] = mapped_column(Float, nullable=False)
    x2: Mapped[float] = mapped_column(Float, nullable=False)
    y2: Mapped[float] = mapped_column(Float, nullable=False)
    # "positive": real object; "hard_negative": region a model wrongly detected as ``class_name``
    # (never trained as an extra class; used for background crops and regression tests)
    type: Mapped[str] = mapped_column(String(16), nullable=False, default="positive", server_default="positive", index=True)
    # "manual" or "prediction" (accepted model prediction, then edited like any other box)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    # for hard negatives: confidence and model version of the false detection
    source_confidence: Mapped[Optional[float]] = mapped_column(Float)
    source_model: Mapped[Optional[str]] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow, server_default=func.now()
    )

    image: Mapped[Image] = relationship(back_populates="annotations")


class TrainingRun(Base):
    __tablename__ = "training_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[TrainingStatus] = mapped_column(
        _enum(TrainingStatus, "training_status"), nullable=False, default=TrainingStatus.queued, index=True
    )
    base_model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Ordered class list of this run (becomes the class list of the resulting model)
    class_names: Mapped[Optional[list[str]]] = mapped_column(JSONType)
    dataset_snapshot: Mapped[Optional[str]] = mapped_column(String(256))
    dataset_stats_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONType)
    input_width: Mapped[int] = mapped_column(Integer, nullable=False)
    input_height: Mapped[int] = mapped_column(Integer, nullable=False)
    epochs: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False)
    learning_rate: Mapped[Optional[float]] = mapped_column(Float)
    params_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONType)
    progress_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONType)
    metrics_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONType)
    log: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    log_key: Mapped[Optional[str]] = mapped_column(String(512))
    error: Mapped[Optional[str]] = mapped_column(Text)
    job_id: Mapped[Optional[str]] = mapped_column(String(64))
    model_version_id: Mapped[Optional[int]] = mapped_column(ForeignKey("model_versions.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    model_version: Mapped[Optional["ModelVersion"]] = relationship(foreign_keys=[model_version_id])


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        # At most one production model at any time.
        Index(
            "uq_model_versions_single_production",
            "status",
            unique=True,
            postgresql_where=text("status = 'production'"),
            sqlite_where=text("status = 'production'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    status: Mapped[ModelStatus] = mapped_column(_enum(ModelStatus, "model_status"), nullable=False, default=ModelStatus.candidate)
    # "trained" (own 3-class model) or "coco-bootstrap" (COCO checkpoint with class mapping)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="trained")
    architecture: Mapped[str] = mapped_column(String(64), nullable=False, default="rtmdet-s")
    checkpoint_key: Mapped[str] = mapped_column(String(512), nullable=False)
    onnx_key: Mapped[str] = mapped_column(String(512), nullable=False)
    openvino_key: Mapped[str] = mapped_column(String(512), nullable=False)
    config_key: Mapped[Optional[str]] = mapped_column(String(512))
    input_width: Mapped[int] = mapped_column(Integer, nullable=False)
    input_height: Mapped[int] = mapped_column(Integer, nullable=False)
    class_names: Mapped[list[str]] = mapped_column(JSONType, nullable=False)
    class_mapping_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONType)
    metrics_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONType)
    dataset_snapshot: Mapped[Optional[str]] = mapped_column(String(256))
    training_run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("training_runs.id", ondelete="SET NULL", use_alter=True, name="fk_model_versions_training_run_id")
    )
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now())
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class BatchStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class PredictionBatch(Base):
    """A "batch test": one model run over many images, producing suggestions."""

    __tablename__ = "prediction_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[BatchStatus] = mapped_column(_enum(BatchStatus, "batch_status"), nullable=False, default=BatchStatus.queued)
    model_ref: Mapped[str] = mapped_column(String(32), nullable=False)          # as requested, e.g. "production"
    model_version: Mapped[Optional[str]] = mapped_column(String(32))           # resolved version
    input_width: Mapped[int] = mapped_column(Integer, nullable=False)
    input_height: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    # "unlabeled" or "unlabeled_and_review" (also labeled images that still need review for new classes)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="unlabeled")
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    detections: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_images: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ImageSuggestion(Base):
    """Latest model suggestions for an image (from a batch test); removed when the image is saved as labeled."""

    __tablename__ = "image_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"), nullable=False, unique=True)
    batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("prediction_batches.id", ondelete="SET NULL"), index=True)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    input_width: Mapped[int] = mapped_column(Integer, nullable=False)
    input_height: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    # [{"class": ..., "confidence": ..., "bbox": {"x1", "y1", "x2", "y2"}}] in original pixels
    detections_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now())


class DetectionClass(Base):
    __tablename__ = "detection_classes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Immutable identifier, referenced by annotations and model versions
    name: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    color: Mapped[str] = mapped_column(String(16), nullable=False)
    # COCO source classes (for the COCO bootstrap model and head initialisation); may be empty
    coco_classes: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow, server_default=func.now()
    )


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONType, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow, server_default=func.now()
    )


def format_version(number: int) -> str:
    return f"model-{number:04d}"


def parse_version_number(version: str) -> int:
    prefix = "model-"
    if not version.startswith(prefix) or not version[len(prefix):].isdigit():
        raise ValueError(f"invalid model version '{version}'")
    return int(version[len(prefix):])
