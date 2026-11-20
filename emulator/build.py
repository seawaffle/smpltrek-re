"""Shared paths and hashing for the emulator scripts."""
import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
WORK = ROOT / "work/emulator"


def digest(data):
    return hashlib.sha256(data).hexdigest()
