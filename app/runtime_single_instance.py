from __future__ import annotations

import atexit
import ctypes
import os


ERROR_ALREADY_EXISTS = 183


class SingleInstanceGuard:
    """Windows named-mutex guard used by the frozen desktop executable."""

    def __init__(self, *, name: str) -> None:
        self._name = name
        self._handle = None

    def acquire(self) -> bool:
        if os.name != "nt":
            return True

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (
            ctypes.c_void_p,
            ctypes.c_bool,
            ctypes.c_wchar_p,
        )
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle.restype = ctypes.c_bool

        handle = kernel32.CreateMutexW(
            None,
            False,
            f"Local\\{self._name}",
        )
        if not handle:
            raise OSError(ctypes.get_last_error(), "CreateMutexW failed")

        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False

        self._handle = (kernel32, handle)
        atexit.register(self.release)
        return True

    def release(self) -> None:
        if self._handle is None:
            return
        kernel32, handle = self._handle
        self._handle = None
        kernel32.CloseHandle(handle)
