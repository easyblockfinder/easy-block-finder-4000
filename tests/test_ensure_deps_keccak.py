from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def test_pycryptodome_missing_triggers_install(monkeypatch):
    import ensure_deps as ed

    # Diger paketler var; yalniz keccak none
    real_import = importlib.import_module

    def fake_import(name, *a, **k):
        if name in ("Crypto.Hash.keccak", "Cryptodome.Hash.keccak"):
            raise ModuleNotFoundError(name)
        if name == "Crypto.Hash":
            raise ModuleNotFoundError(name)
        return real_import(name, *a, **k)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    monkeypatch.setattr(
        ed,
        "_need_install",
        lambda mod: mod in ("Crypto.Hash.keccak", "pycryptodome"),
    )
    pip_calls: list[list[str]] = []

    def fake_pip(args):
        pip_calls.append(list(args))
        return 0

    monkeypatch.setattr(ed, "run_pip", fake_pip)

    # ensure_keccak or ensure_pip_packages fordeki kontrol
    assert hasattr(ed, "ensure_keccak") or "pycryptodome" in str(
        getattr(ed, "ensure_pip_packages", lambda: None).__code__.co_consts
        if hasattr(getattr(ed, "ensure_pip_packages", None), "__code__")
        else ()
    )

    if hasattr(ed, "ensure_keccak"):
        # Kurulum afreandrsei hâlâ nonesa False
        ok = ed.ensure_keccak()
        assert pip_calls, "pycryptodome for pip tetiklenmeli"
        # fake_import hâlâ fail → False
        assert ok is False
