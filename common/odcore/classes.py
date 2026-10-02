"""Target classes of the custom detector and the default COCO mapping."""
from __future__ import annotations

CLASS_NAMES: tuple[str, ...] = ("person", "bicycle", "vehicle")
CLASS_TO_ID: dict[str, int] = {name: i for i, name in enumerate(CLASS_NAMES)}

# The 80 COCO detection classes in the order used by MMDetection checkpoints.
COCO_CLASSES: tuple[str, ...] = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
    "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush",
)

# Default mapping from target class -> COCO source classes. Trains/rail vehicles
# are intentionally NOT mapped to "vehicle". Overridable via the Setting
# "coco_class_mapping".
DEFAULT_COCO_MAPPING: dict[str, list[str]] = {
    "person": ["person"],
    "bicycle": ["bicycle"],
    "vehicle": ["car", "motorcycle", "bus", "truck"],
}


def validate_coco_mapping(mapping: dict[str, list[str]]) -> dict[str, list[int]]:
    """Validate a target->COCO mapping and return it as COCO class indices."""
    result: dict[str, list[int]] = {}
    for target in CLASS_NAMES:
        sources = mapping.get(target)
        if not sources:
            raise ValueError(f"mapping for target class '{target}' is missing or empty")
        ids = []
        for src in sources:
            if src not in COCO_CLASSES:
                raise ValueError(f"unknown COCO class '{src}'")
            ids.append(COCO_CLASSES.index(src))
        result[target] = ids
    unknown = set(mapping) - set(CLASS_NAMES)
    if unknown:
        raise ValueError(f"unknown target classes: {sorted(unknown)}")
    return result
