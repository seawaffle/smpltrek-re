"""Shared conventions of the symbol files in symbols/.

A function entry identifies the code at its address without carrying it: `prefix_sha256` is the SHA-256 of the first
PREFIX_LEN bytes at the address, truncated to 128 bits (32 hex digits). Anyone with the same official update can
recompute it; the repository holds no Sonicware code bytes.
"""
import hashlib

PREFIX_LEN = 16


def prefix_hash(code):
    """prefix_sha256 for the bytes at a function's address (the first PREFIX_LEN of `code` are used)."""
    if len(code) < PREFIX_LEN:
        raise ValueError(f"need {PREFIX_LEN} bytes, got {len(code)}")
    return hashlib.sha256(bytes(code[:PREFIX_LEN])).hexdigest()[:32]
