"""Opt-in native bridge for Linux CPython / OpenSees 3.8.0, single process only.

No installed engine or tower code is modified. Building explicitly downloads
official, commit-pinned OpenSees headers into an ignored module-local cache.
Each truss gets an independent Python constitutive copy through getCopy().
This is an ABI-specific research adapter, not an official OPS material command.
Call ops.wipe() before interpreter exit. MPI/save/restore/sensitivity unsupported.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import platform
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path
from urllib.request import urlopen

from .material import TianMaQuPrototype

PIN = "6e55293513192aa05c7e1205e66a5a1a1ed088c4"  # v3.8.0
HEADERS = (
    "SRC/material/uniaxial/UniaxialMaterial.h", "SRC/material/Material.h",
    "SRC/domain/component/DomainComponent.h", "SRC/tagged/TaggedObject.h",
    "SRC/actor/actor/MovableObject.h", "SRC/handler/OPS_Stream.h",
    "SRC/matrix/Vector.h", "SRC/OPS_Globals.h", "SRC/classTags.h", "COPYRIGHT",
)
_LIBRARY = None
_ENGINE = None
_METADATA = None


def build_bridge(cache=None):
    import openseespy.opensees as ops
    import openseespylinux.opensees as engine
    if ops.version() != "3.8.0" or sys.implementation.name != "cpython" or platform.system() != "Linux":
        raise RuntimeError("Research bridge is restricted to Linux CPython and OpenSees 3.8.0")
    root = Path(__file__).resolve().parent
    cache = Path(cache) if cache else root / "_native_cache"
    cache.mkdir(parents=True, exist_ok=True)
    source = root / "native_bridge.cpp"
    engine_path = Path(engine.__file__).resolve()
    signature = {"opensees": ops.version(), "headers_commit": PIN,
                 "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                 "engine_sha256": hashlib.sha256(engine_path.read_bytes()).hexdigest(),
                 "python": sys.version, "platform": platform.platform()}
    binary = cache / "tmq_python_bridge.so"
    manifest = cache / "manifest.json"
    saved = json.loads(manifest.read_text()) if manifest.exists() else {}
    if binary.exists() and manifest.exists():
        if saved.get("signature") == signature and saved.get("binary_sha256") == hashlib.sha256(binary.read_bytes()).hexdigest():
            return binary, saved
    header_hashes = {}
    for header in HEADERS:
        url = f"https://raw.githubusercontent.com/OpenSees/OpenSees/{PIN}/{header}"
        local = cache / Path(header).name
        expected_hash = saved.get("header_sha256", {}).get(header)
        reuse = (saved.get("signature", {}).get("headers_commit") == PIN and local.exists()
                 and hashlib.sha256(local.read_bytes()).hexdigest() == expected_hash)
        if reuse:
            contents = local.read_bytes()
        else:
            with urlopen(url, timeout=30) as response:
                contents = response.read()
            local.write_bytes(contents)
        header_hashes[header] = hashlib.sha256(contents).hexdigest()
    compiler = os.environ.get("CXX") or shutil.which("g++-13") or shutil.which("g++")
    if not compiler:
        raise RuntimeError("C++ compiler missing; set CXX or use the pure-Python runner")
    command = [compiler, "-std=c++17", "-O2", "-shared", "-fPIC", str(source),
               "-I" + str(cache), "-I" + sysconfig.get_path("include"), "-o", str(binary)]
    subprocess.run(command, check=True, capture_output=True, text=True)
    metadata = {"signature": signature, "header_sha256": header_hashes,
                "command": command, "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                "limitations": ["ABI-specific", "single-process only", "no MPI/save/restore/sensitivity",
                                "OpenSees energy response unsupported (NaN); Python records external work",
                                "not a production material; not calibrated to current tower"]}
    manifest.write_text(json.dumps(metadata, indent=2) + "\n")
    return binary, metadata


def register_material(tag, parameters):
    return register_model(tag, TianMaQuPrototype(parameters))


def register_model(tag, model):
    """Register a compatible constitutive object, including a section-force adapter.

    Verify/hash the native engine once per process, not once per tower member.
    The loaded binary cannot be hot-replaced; restart after bridge source edits.
    """
    global _LIBRARY, _ENGINE, _METADATA
    import openseespylinux.opensees as engine
    if _LIBRARY is None:
        binary, _METADATA = build_bridge()
        _ENGINE = ctypes.CDLL(engine.__file__, mode=ctypes.RTLD_GLOBAL)
        _LIBRARY = ctypes.PyDLL(str(binary))
        _LIBRARY.tmq_register_python_material.argtypes = [ctypes.c_int, ctypes.py_object]
        _LIBRARY.tmq_register_python_material.restype = ctypes.c_int
    if _LIBRARY.tmq_register_python_material(int(tag), model) != 0:
        raise RuntimeError(f"Could not register TMQ prototype tag {tag}; check duplicate tags")
    return _METADATA
