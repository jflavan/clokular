"""Minimal VNC (RFB 3.3/3.8) client for driving a hidden test Okular started
with QT_QPA_PLATFORM=vnc. See "Testing the real menu" in the README.

    c = VNC("127.0.0.1", 5977)
    c.snapshot("shot.png"); c.move(x, y); c.click(x, y, button=3); c.key(0xff1b)
"""

from __future__ import annotations

import socket
import struct
import time


class VNC:
    def __init__(self, host: str, port: int, timeout: float = 10):
        self.s = socket.create_connection((host, port), timeout=timeout)
        ver = self._recv(12)
        if not ver.startswith(b"RFB "):
            raise RuntimeError(f"not a VNC server: {ver!r}")
        if ver.startswith(b"RFB 003.003"):
            # Qt's VNC server speaks 3.3: the server picks the security type.
            self.s.sendall(b"RFB 003.003\n")
            if struct.unpack(">I", self._recv(4))[0] != 1:
                raise RuntimeError("server wants authentication")
        else:
            self.s.sendall(b"RFB 003.008\n")
            n = self._recv(1)[0]
            if n == 0:
                raise RuntimeError("server refused connection")
            types = self._recv(n)
            if 1 not in types:
                raise RuntimeError(f"no 'None' security type offered: {list(types)}")
            self.s.sendall(b"\x01")
            if struct.unpack(">I", self._recv(4))[0] != 0:
                raise RuntimeError("security handshake failed")
        self.s.sendall(b"\x01")  # shared
        self.w, self.h = struct.unpack(">HH", self._recv(4))
        self._recv(16)  # server pixel format
        name_len = struct.unpack(">I", self._recv(4))[0]
        self._recv(name_len)
        # 32bpp, depth 24, little-endian, true colour, BGRX
        pf = struct.pack(">BBBBHHHBBB3x", 32, 24, 0, 1, 255, 255, 255, 16, 8, 0)
        self.s.sendall(struct.pack(">B3x", 0) + pf)
        self.s.sendall(struct.pack(">BxHi", 2, 1, 0))  # raw encoding only
        self.fb = bytearray(self.w * self.h * 4)
        self.buttons = 0
        self.x = self.y = 0

    def _recv(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self.s.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("VNC server closed the connection")
            buf += chunk
        return bytes(buf)

    def refresh(self) -> None:
        self.s.sendall(struct.pack(">BBHHHH", 3, 0, 0, 0, self.w, self.h))
        while True:
            t = self._recv(1)[0]
            if t == 0:
                break
            if t == 2:  # bell
                continue
            if t == 1:  # colour map
                _, _, n = struct.unpack(">xHH", self._recv(5))
                self._recv(n * 6)
                continue
            if t == 3:
                n = struct.unpack(">I", self._recv(7)[3:])[0]
                self._recv(n)
                continue
            raise RuntimeError(f"unexpected server message {t}")
        nrects = struct.unpack(">xH", self._recv(3))[0]
        for _ in range(nrects):
            x, y, w, h, enc = struct.unpack(">HHHHi", self._recv(12))
            if enc != 0:
                raise RuntimeError(f"unexpected encoding {enc}")
            data = self._recv(w * h * 4)
            for row in range(h):
                o = ((y + row) * self.w + x) * 4
                self.fb[o : o + w * 4] = data[row * w * 4 : (row + 1) * w * 4]

    def snapshot(self, path: str) -> None:
        self.refresh()
        from PySide6.QtGui import QImage

        QImage(bytes(self.fb), self.w, self.h, self.w * 4, QImage.Format.Format_RGB32).save(path)

    def _pointer(self) -> None:
        self.s.sendall(struct.pack(">BBHH", 5, self.buttons, self.x, self.y))

    def move(self, x: int, y: int, steps: int = 1) -> None:
        x0, y0 = self.x, self.y
        for i in range(1, steps + 1):
            self.x = int(x0 + (x - x0) * i / steps)
            self.y = int(y0 + (y - y0) * i / steps)
            self._pointer()
            time.sleep(0.02)

    def press(self, button: int = 1) -> None:
        self.buttons |= 1 << (button - 1)
        self._pointer()

    def release(self, button: int = 1) -> None:
        self.buttons &= ~(1 << (button - 1))
        self._pointer()

    def click(self, x: int, y: int, button: int = 1) -> None:
        self.move(x, y)
        time.sleep(0.1)
        self.press(button)
        time.sleep(0.08)
        self.release(button)

    def drag(self, x0: int, y0: int, x1: int, y1: int) -> None:
        self.move(x0, y0)
        time.sleep(0.15)
        self.press(1)
        time.sleep(0.15)
        self.move(x1, y1, steps=25)
        time.sleep(0.15)
        self.release(1)

    def key(self, keysym: int) -> None:
        self.s.sendall(struct.pack(">BBxxI", 4, 1, keysym))
        time.sleep(0.03)
        self.s.sendall(struct.pack(">BBxxI", 4, 0, keysym))
