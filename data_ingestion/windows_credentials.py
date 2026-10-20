"""Read the existing Windows SecureString CLIXML using native DPAPI only."""
import ctypes
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from ctypes import wintypes


def encrypted_blob(path):
    root = ET.fromstring(Path(path).read_bytes())
    values = list(root.iter('{http://schemas.microsoft.com/powershell/2004/04}SS'))
    if len(values) != 1 or not values[0].text:
        raise ValueError('Expected one encrypted SecureString')
    blob = bytes.fromhex(values[0].text)
    if not blob:
        raise ValueError('Empty encrypted credential')
    return blob


def load_key(path):
    if os.name != 'nt':
        raise OSError('Windows DPAPI required')
    encrypted = encrypted_blob(path)

    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    crypt.CryptUnprotectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    crypt.CryptUnprotectData.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    storage = (ctypes.c_ubyte * len(encrypted)).from_buffer_copy(encrypted)
    source, output = Blob(len(encrypted), storage), Blob()
    # CRYPTPROTECT_UI_FORBIDDEN: never request interactive credential prompts.
    if not crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise OSError('DPAPI decryption failed for current Windows identity')
    try:
        key = ctypes.string_at(output.data, output.size).decode('utf-16-le')
        if not key or key != key.strip() or not key.isascii() or any(c.isspace() for c in key):
            raise ValueError('Invalid credential format')
        return key
    finally:
        ctypes.memset(output.data, 0, output.size)
        kernel.LocalFree(output.data)
