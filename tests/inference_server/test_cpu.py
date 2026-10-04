"""CPU instruction set check (e.g. Proxmox VMs with CPU type kvm64)."""
from __future__ import annotations

from app.cpu import check_cpu
from app.main import app, get_cpu

from conftest import image_file, upload

# /proc/cpuinfo of a Proxmox VM with CPU type "kvm64": OpenVINO cannot load models there
KVM64 = """processor       : 0
model name      : Common KVM processor
flags           : fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pat pse36 clflush mmx fxsr sse sse2 syscall nx lm constant_tsc nopl xtopology cpuid tsc_known_freq pni cx16 x2apic hypervisor lahf_lm cpuid_fault pti
"""
# x86-64-v2 (SSE4.2, no AVX2): works, but slow
V2 = KVM64.replace("pni cx16", "pni ssse3 cx16 sse4_1 sse4_2 popcnt").replace("Common KVM processor", "QEMU Virtual CPU version 2.5+")
HOST = V2.replace("popcnt", "popcnt avx avx2 fma").replace("QEMU Virtual CPU version 2.5+", "Intel(R) Core(TM) i7-12700")


def cpu_from(tmp_path, text: str):
    path = tmp_path / "cpuinfo"
    path.write_text(text)
    return check_cpu(str(path))


def test_kvm64_is_not_supported(tmp_path):
    cpu = cpu_from(tmp_path, KVM64)
    assert cpu.model == "Common KVM processor"
    assert cpu.supported is False
    assert cpu.missing_required == ["sse4_1", "sse4_2"]
    assert "'host'" in cpu.warnings()[0]


def test_sse42_without_avx2_works_with_warning(tmp_path):
    cpu = cpu_from(tmp_path, V2)
    assert cpu.supported is True
    assert cpu.missing_recommended == ["avx2"]
    assert "slower" in cpu.warnings()[0]


def test_modern_cpu_has_no_warnings(tmp_path):
    cpu = cpu_from(tmp_path, HOST)
    assert cpu.supported is True and cpu.warnings() == []


def test_unreadable_cpuinfo_is_not_reported_as_unsupported(tmp_path):
    cpu = check_cpu(str(tmp_path / "missing"))
    assert cpu.supported is None and cpu.warnings() == []


def test_health_and_upload_report_unsupported_cpu(client, model_files, tmp_path):
    app.dependency_overrides[get_cpu] = lambda: cpu_from(tmp_path, KVM64)
    try:
        health = client.get("/api/v1/health").json()
        assert health["status"] == "degraded"
        assert health["cpu"] == {"model": "Common KVM processor", "supported": False,
                                 "missing_required": ["sse4_1", "sse4_2"], "missing_recommended": ["avx2"]}
        assert "sse4_1, sse4_2" in health["warnings"][0]
        # the test model itself loads (the real CPU is fine), so force an unloadable upload:
        bad = tmp_path / "bad.xml"
        bad.write_text("not a model")
        res = upload(client, (str(bad), str(bad)))
        assert res.status_code == 422
        assert "CPU lacks sse4_1, sse4_2" in res.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_cpu, None)
    assert client.post("/api/v1/detect", files=image_file()).status_code == 503
