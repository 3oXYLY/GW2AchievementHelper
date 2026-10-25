from __future__ import annotations

import base64
import sys

_ENTROPY = b"gw2-achievement-helper/v1"


def protect(text: str) -> str:
    raw = text.encode("utf-8")
    if sys.platform == "win32":
        try:
            return "dpapi:" + base64.b64encode(_dpapi(raw, encrypt=True)).decode("ascii")
        except Exception:
            pass
    return "plain:" + base64.b64encode(raw).decode("ascii")


def unprotect(blob: str) -> str:
    scheme, _, payload = blob.partition(":")
    data = base64.b64decode(payload)
    if scheme == "dpapi":
        return _dpapi(data, encrypt=False).decode("utf-8")
    if scheme == "plain":
        return data.decode("utf-8")
    raise ValueError("Unknown key storage format")


def is_encrypted(blob: str | None) -> bool:
    return bool(blob) and blob.startswith("dpapi:")


def _dpapi(data: bytes, encrypt: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def make_blob(b: bytes):
        buf = ctypes.create_string_buffer(b, len(b))
        return DATA_BLOB(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    pblob = ctypes.POINTER(DATA_BLOB)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    blob_in, _keep_in = make_blob(data)
    entropy, _keep_entropy = make_blob(_ENTROPY)
    blob_out = DATA_BLOB()
    ui_forbidden = 0x01

    if encrypt:
        fn = crypt32.CryptProtectData
        fn.argtypes = [pblob, wintypes.LPCWSTR, pblob, ctypes.c_void_p, ctypes.c_void_p,
                       wintypes.DWORD, pblob]
        fn.restype = wintypes.BOOL
        ok = fn(ctypes.byref(blob_in), "GW2 API key", ctypes.byref(entropy), None, None,
                ui_forbidden, ctypes.byref(blob_out))
    else:
        fn = crypt32.CryptUnprotectData
        fn.argtypes = [pblob, ctypes.c_void_p, pblob, ctypes.c_void_p, ctypes.c_void_p,
                       wintypes.DWORD, pblob]
        fn.restype = wintypes.BOOL
        ok = fn(ctypes.byref(blob_in), None, ctypes.byref(entropy), None, None,
                ui_forbidden, ctypes.byref(blob_out))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))
