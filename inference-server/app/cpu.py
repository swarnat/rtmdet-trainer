"""CPU instruction set check: OpenVINO's CPU plugin needs SSE4.2 and is only fast with AVX2.

Virtual machines often hide these from the guest (e.g. Proxmox/KVM CPU type "kvm64",
shown as "Common KVM processor"), which makes model loading fail with errors like
``has not found jit_uni_reduce_post_kernel_f32``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

REQUIRED = ("sse4_1", "sse4_2")
RECOMMENDED = ("avx2",)
HINT = (
    "On a virtual machine, set the CPU type to 'host' (Proxmox: VM → Hardware → Processors → Type, "
    "then stop and start the VM) or at least 'x86-64-v3'."
)


@dataclass
class CpuCheck:
    model: Optional[str]
    checked: bool  # False if /proc/cpuinfo could not be read (non-Linux)
    missing_required: list[str] = field(default_factory=list)
    missing_recommended: list[str] = field(default_factory=list)

    @property
    def supported(self) -> Optional[bool]:
        return (not self.missing_required) if self.checked else None

    def warnings(self) -> list[str]:
        if self.missing_required:
            return [f"CPU lacks {', '.join(self.missing_required)} (required by OpenVINO): models cannot be loaded. {HINT}"]
        if self.missing_recommended:
            return [f"CPU lacks {', '.join(self.missing_recommended)}: detection works but is considerably slower. {HINT}"]
        return []


def check_cpu(cpuinfo_path: str = "/proc/cpuinfo") -> CpuCheck:
    try:
        with open(cpuinfo_path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return CpuCheck(model=None, checked=False)
    flags: set[str] = set()
    model = None
    for line in text.splitlines():
        key, _, value = line.partition(":")
        key = key.strip()
        if key == "flags" and not flags:
            flags = set(value.split())
        elif key == "model name" and model is None:
            model = value.strip()
    return CpuCheck(
        model=model,
        checked=True,
        missing_required=[f for f in REQUIRED if f not in flags],
        missing_recommended=[f for f in RECOMMENDED if f not in flags],
    )
