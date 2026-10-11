"""Camera identity from image metadata (used to group images by camera).

* EXIF with BodySerialNumber (AXIS cameras): "<make> <model> · <serial>" - one physical device
  (which can still deliver several views, e.g. PTZ presets or multi-channel encoders)
* EXIF make/model without serial: "<make> <model>" - a camera type, possibly several devices
* JPEG comment header "CamTim: ..." of some other cameras: "CamTim" - a camera type
* nothing: "" (unknown)
"""
from __future__ import annotations

import struct

HEADER_BYTES = 65536  # metadata is at the start of the file
SERIAL_SEPARATOR = " · "
_TAG_MAKE, _TAG_MODEL, _TAG_EXIF_IFD, _TAG_BODY_SERIAL = 0x010F, 0x0110, 0x8769, 0xA431


def _ifd_strings(tiff: bytes, offset: int, endian: str) -> dict[int, str]:
    """ASCII entries (and the Exif sub-IFD pointer) of one IFD."""
    count = struct.unpack(endian + "H", tiff[offset:offset + 2])[0]
    out: dict[int, str] = {}
    for k in range(count):
        entry = tiff[offset + 2 + 12 * k: offset + 14 + 12 * k]
        tag, typ, n = struct.unpack(endian + "HHI", entry[:8])
        if typ == 2:  # ASCII
            data = entry[8:8 + n] if n <= 4 else tiff[struct.unpack(endian + "I", entry[8:12])[0]:][:n]
            out[tag] = data.split(b"\x00")[0].decode("latin-1").strip()
        elif tag == _TAG_EXIF_IFD:
            out[tag] = str(struct.unpack(endian + "I", entry[8:12])[0])
    return out


def _exif(data: bytes) -> dict[int, str]:
    i = 2
    while i + 4 <= len(data) and data[i] == 0xFF:
        marker = data[i + 1]
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker == 0xE1 and data[i + 4:i + 10] == b"Exif\x00\x00":
            tiff = data[i + 10:i + 2 + length]
            endian = "<" if tiff[:2] == b"II" else ">"
            tags = _ifd_strings(tiff, struct.unpack(endian + "I", tiff[4:8])[0], endian)
            if _TAG_EXIF_IFD in tags:
                tags.update(_ifd_strings(tiff, int(tags.pop(_TAG_EXIF_IFD)), endian))
            return tags
        if marker == 0xDA:  # start of scan: no more metadata
            break
        i += 2 + length
    return {}


def camera_key(data: bytes) -> str:
    head = data[:HEADER_BYTES]
    try:
        tags = _exif(head) if head[:2] == b"\xff\xd8" else {}
    except (struct.error, ValueError, IndexError):
        tags = {}
    device = " ".join(t for t in (tags.get(_TAG_MAKE), tags.get(_TAG_MODEL)) if t)
    serial = tags.get(_TAG_BODY_SERIAL)
    if serial:
        return f"{device or 'camera'}{SERIAL_SEPARATOR}{serial}"[:120]
    if device:
        return device[:120]
    if b"CamTim:" in head[:8192]:
        return "CamTim"
    return ""
