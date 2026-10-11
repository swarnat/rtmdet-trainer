"""Camera identity from image metadata."""
from __future__ import annotations

import struct

import cv2
import numpy as np

from app.services.camera_meta import camera_key


def jpeg() -> bytes:
    return cv2.imencode(".jpg", np.full((36, 64, 3), 100, np.uint8))[1].tobytes()


def with_exif(make: str | None, model: str | None, serial: str | None) -> bytes:
    """JPEG with an APP1 Exif block (little endian): IFD0 Make/Model + Exif IFD BodySerialNumber."""
    ifd0 = [(t, v) for t, v in ((0x010F, make), (0x0110, model)) if v]
    exif = [(0xA431, serial)] if serial else []
    ifd0_size = 2 + 12 * (len(ifd0) + 1) + 4
    exif_off = 8 + ifd0_size
    exif_size = 2 + 12 * len(exif) + 4
    data_off = exif_off + exif_size
    blob = b""

    def entries(items, base):
        nonlocal blob
        out = struct.pack("<H", len(items))
        for tag, text in items:
            raw = text.encode() + b"\x00"
            if len(raw) <= 4:
                out += struct.pack("<HHI", tag, 2, len(raw)) + raw.ljust(4, b"\x00")
            else:
                out += struct.pack("<HHII", tag, 2, len(raw), base + len(blob))
                blob += raw
        return out

    head0 = entries(ifd0, data_off)
    head0 = struct.pack("<H", len(ifd0) + 1) + head0[2:] + struct.pack("<HHII", 0x8769, 4, 1, exif_off) + b"\x00" * 4
    headx = entries(exif, data_off) + b"\x00" * 4
    tiff = b"II" + struct.pack("<HI", 42, 8) + head0 + headx + blob
    app1 = b"Exif\x00\x00" + tiff
    return b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + jpeg()[2:]


def test_serial_number_identifies_the_device():
    assert camera_key(with_exif("AXIS", "Q3536-LVE", "B8A44F55F126")) == "AXIS Q3536-LVE · B8A44F55F126"


def test_camera_type_without_serial_and_unknown():
    assert camera_key(with_exif("AXIS", "Q3615", None)) == "AXIS Q3615"
    assert camera_key(b"\xff\xd8\xff\xfe\x00\x20DataLen: 1\r\nCamTim: 2026-09-18" + jpeg()[2:]) == "CamTim"
    assert camera_key(jpeg()) == ""
    assert camera_key(b"\xff\xd8\xff\xe1\x00\x10Exif\x00\x00II*\x00\xff\xff") == ""  # broken Exif block
