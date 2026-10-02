from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from odcore.classes import active_class_names

from app.api.routes.images import get_image_or_404, to_detail
from app.core.database import get_db
from app.schemas.annotation import AnnotationOut, AnnotationsSave, ImageDetail
from app.services.annotation import AnnotationValidationError, replace_annotations

router = APIRouter(prefix="/images/{image_id}/annotations", tags=["annotations"])


@router.get("", response_model=list[AnnotationOut], summary="Annotations of an image (original pixel coordinates)")
def get_annotations(image_id: int, session: Session = Depends(get_db)) -> list[AnnotationOut]:
    image = get_image_or_404(session, image_id)
    return [AnnotationOut.model_validate(a) for a in image.annotations]


@router.put(
    "",
    response_model=ImageDetail,
    summary="Replace all annotations of an image",
    description=(
        "Saves the complete set of bounding boxes (original pixel coordinates). With `mark_labeled=true` "
        "(default) the image becomes `labeled`; an empty list then marks a valid negative example."
    ),
)
def save_annotations(image_id: int, body: AnnotationsSave, session: Session = Depends(get_db)) -> ImageDetail:
    image = get_image_or_404(session, image_id)
    try:
        image = replace_annotations(session, image, body.annotations, body.mark_labeled)
    except AnnotationValidationError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return to_detail(image, active_class_names(session))
