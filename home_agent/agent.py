"""PultOS uy agenti.

Uy kompyuterida (masalan Pop!_OS) doim ishlab turadi: relay-serverga
ulanadi, loyiha papkasini kuzatadi va fleshkadagi PultOS'dan kelgan
buyruqlarni bajaradi.

Ishga tushirish: python3 agent.py
(avval config.json faylini shu papkaga qo'yish kerak -- pultos/setup.py
generatsiya qilgan home_agent_config.json shu fayl bo'ladi)
"""

import asyncio
import base64
import glob
import json
import logging
import os
import platform
import shlex
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
from urllib.parse import urlparse

import websockets
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("pultos.agent")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
LOG_DIR = os.path.expanduser("~/.pultos-agent")
COMMANDS_LOG_PATH = os.path.join(LOG_DIR, "commands.log")
APP_USAGE_LOG_PATH = os.path.join(LOG_DIR, "app_usage.log")

IGNORED_DIR_NAMES = {".git", "__pycache__", "node_modules", ".venv", "venv"}
FILE_EVENT_THROTTLE_SECONDS = 1.0
APP_USAGE_POLL_SECONDS = 5


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        raise RuntimeError(
            f"{CONFIG_PATH} topilmadi. pultos/setup.py chiqargan "
            "home_agent_config.json faylini shu nom bilan (config.json) shu papkaga qo'ying."
        )
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def log_command(action: str, payload: dict, result: dict) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    entry = {
        "ts": time.time(),
        "action": action,
        "payload": payload,
        "result_summary": {k: v for k, v in result.items() if k not in ("image_base64", "images")},
    }
    with open(COMMANDS_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def run_shell(payload: dict) -> dict:
    cmd = payload.get("cmd", "")
    if not cmd:
        return {"error": "Buyruq bo'sh."}
    try:
        proc = subprocess.run(
            ["/bin/bash", "-c", cmd],
            capture_output=True,
            text=True,
            timeout=payload.get("timeout", 30),
        )
        return {"stdout": proc.stdout[-8000:], "stderr": proc.stderr[-4000:], "exit_code": proc.returncode}
    except subprocess.TimeoutExpired:
        return {"error": "Buyruq vaqti tugadi."}
    except Exception as exc:
        return {"error": str(exc)}


def _run_cosmic_screenshot(tmp_dir: str) -> str | None:
    """cosmic-screenshot saves under an auto-generated name inside --save-dir
    (xdg-desktop-portal-cosmic), so we point it at an empty tmp dir and pick
    up whatever file lands there."""
    subprocess.run(
        ["cosmic-screenshot", "--interactive=false", "--modal=false", "--notify=false", f"--save-dir={tmp_dir}"],
        capture_output=True,
        timeout=20,
        check=True,
    )
    shots = [f for f in os.listdir(tmp_dir) if f.lower().endswith(".png")]
    if not shots:
        return None
    return os.path.join(tmp_dir, shots[0])


def run_screenshot(_payload: dict) -> dict:
    tmp_path = os.path.join(tempfile.gettempdir(), f"pultos-shot-{int(time.time())}.png")
    tools = [
        ["gnome-screenshot", "-f", tmp_path],
        ["grim", tmp_path],
        ["scrot", tmp_path],
    ]
    for tool_cmd in tools:
        try:
            subprocess.run(tool_cmd, capture_output=True, timeout=10, check=True)
            if os.path.exists(tmp_path):
                with open(tmp_path, "rb") as f:
                    data = base64.b64encode(f.read()).decode("utf-8")
                os.remove(tmp_path)
                return {"image_base64": data}
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            continue

    with tempfile.TemporaryDirectory(prefix="pultos-shot-") as tmp_dir:
        try:
            shot_path = _run_cosmic_screenshot(tmp_dir)
            if shot_path:
                with open(shot_path, "rb") as f:
                    data = base64.b64encode(f.read()).decode("utf-8")
                return {"image_base64": data}
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            pass

    return {"error": "Skrinshot vositasi topilmadi (gnome-screenshot/grim/scrot/cosmic-screenshot)."}


def run_lock(_payload: dict) -> dict:
    for cmd in (["loginctl", "lock-session"], ["gnome-screensaver-command", "--lock"]):
        try:
            subprocess.run(cmd, capture_output=True, timeout=10, check=True)
            return {"ok": True}
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return {"error": "Qulflash vositasi topilmadi."}


def run_power(action: str) -> dict:
    cmd = ["systemctl", "reboot"] if action == "restart" else ["systemctl", "poweroff"]
    try:
        subprocess.run(cmd, capture_output=True, timeout=10, check=True)
        return {"ok": True}
    except Exception as exc:
        return {"error": f"{exc} (agent foydalanuvchisi uchun passwordless sudo/polkit qoidasi kerak boʻlishi mumkin)"}


def run_open_app(payload: dict) -> dict:
    app = payload.get("app", "")
    if not app:
        return {"error": "Dastur nomi berilmagan."}
    try:
        subprocess.Popen(shlex.split(app))
        return {"ok": True}
    except Exception as exc:
        return {"error": str(exc)}


def run_close_app(payload: dict) -> dict:
    app = payload.get("app", "")
    if not app:
        return {"error": "Dastur nomi berilmagan."}
    binary = shlex.split(app)[0] if shlex.split(app) else app
    try:
        proc = subprocess.run(["pkill", "-i", binary], capture_output=True, timeout=10)
        if proc.returncode == 0:
            return {"ok": True}
        return {"error": f"'{binary}' nomli ishlayotgan dastur topilmadi."}
    except Exception as exc:
        return {"error": str(exc)}


def _local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "noma'lum"


def _uptime_str() -> str:
    try:
        with open("/proc/uptime") as f:
            seconds = float(f.read().split()[0])
    except Exception:
        return "noma'lum"
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days} kun")
    if hours:
        parts.append(f"{hours} soat")
    parts.append(f"{minutes} daqiqa")
    return " ".join(parts)


def _mem_str() -> str:
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                key, _, rest = line.partition(":")
                info[key.strip()] = int(rest.strip().split()[0])
        total_gb = info.get("MemTotal", 0) / 1024 / 1024
        avail_gb = info.get("MemAvailable", 0) / 1024 / 1024
        used_gb = total_gb - avail_gb
        return f"{used_gb:.1f} GB / {total_gb:.1f} GB ishlatilmoqda"
    except Exception:
        return "noma'lum"


def run_report(_payload: dict) -> dict:
    try:
        du = shutil.disk_usage("/")
        disk_used_gb = du.used / 1024**3
        disk_total_gb = du.total / 1024**3
        try:
            load1, load5, load15 = os.getloadavg()
            load_str = f"{load1:.2f}, {load5:.2f}, {load15:.2f}"
        except (OSError, AttributeError):
            load_str = "noma'lum"

        lines = [
            f"Kompyuter nomi: {socket.gethostname()}",
            f"Tizim: {platform.system()} {platform.release()}",
            f"Ishlash vaqti: {_uptime_str()}",
            f"Yuklama (1/5/15 daq): {load_str}",
            f"Xotira: {_mem_str()}",
            f"Disk (/): {disk_used_gb:.1f} GB / {disk_total_gb:.1f} GB ishlatilmoqda",
            f"Lokal IP: {_local_ip()}",
        ]
        return {"report": "\n".join(lines)}
    except Exception as exc:
        return {"error": str(exc)}


IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
MAX_TRANSFER_IMAGES = 12


def run_transfer_images(payload: dict) -> dict:
    folder = payload.get("folder", "")
    if not folder:
        return {"error": "Papka manzili berilmagan."}
    expanded = os.path.expanduser(os.path.expandvars(folder))
    if not os.path.isdir(expanded):
        return {"error": f"Papka topilmadi: {expanded}"}

    try:
        all_images = sorted(
            f for f in os.listdir(expanded)
            if f.lower().endswith(IMAGE_EXTENSIONS) and os.path.isfile(os.path.join(expanded, f))
        )
    except Exception as exc:
        return {"error": str(exc)}

    if not all_images:
        return {"error": f"'{expanded}' papkasida rasm topilmadi."}

    selected = all_images[:MAX_TRANSFER_IMAGES]
    images = []
    for name in selected:
        try:
            with open(os.path.join(expanded, name), "rb") as f:
                images.append({"name": name, "data": base64.b64encode(f.read()).decode("utf-8")})
        except Exception:
            continue

    return {
        "images": images,
        "folder": expanded,
        "total_found": len(all_images),
        "transferred": len(images),
    }


# ---------- Brauzer tarixi ----------


def _read_firefox_history(cutoff_ts: float) -> list:
    visits = []
    for profile_dir in glob.glob(os.path.expanduser("~/.mozilla/firefox/*.default*")):
        places = os.path.join(profile_dir, "places.sqlite")
        if not os.path.exists(places):
            continue
        tmp_copy = os.path.join(tempfile.gettempdir(), f"places-{uuid.uuid4().hex}.sqlite")
        try:
            shutil.copy2(places, tmp_copy)  # Firefox locks the live file, so read a copy
            conn = sqlite3.connect(tmp_copy)
            cur = conn.cursor()
            cur.execute(
                "SELECT p.url, h.visit_date FROM moz_historyvisits h "
                "JOIN moz_places p ON p.id = h.place_id WHERE h.visit_date > ?",
                (int(cutoff_ts * 1_000_000),),
            )
            visits.extend((url, visit_date / 1_000_000) for url, visit_date in cur.fetchall())
            conn.close()
        except Exception:
            pass
        finally:
            try:
                os.remove(tmp_copy)
            except OSError:
                pass
    return visits


def _read_chrome_history(cutoff_ts: float) -> list:
    visits = []
    epoch_diff = 11644473600  # seconds between the Windows/Chrome epoch (1601) and Unix epoch (1970)
    chrome_cutoff = int((cutoff_ts + epoch_diff) * 1_000_000)
    for base in (
        os.path.expanduser("~/.config/google-chrome/Default"),
        os.path.expanduser("~/.config/chromium/Default"),
    ):
        hist = os.path.join(base, "History")
        if not os.path.exists(hist):
            continue
        tmp_copy = os.path.join(tempfile.gettempdir(), f"chist-{uuid.uuid4().hex}.sqlite")
        try:
            shutil.copy2(hist, tmp_copy)
            conn = sqlite3.connect(tmp_copy)
            cur = conn.cursor()
            cur.execute(
                "SELECT u.url, v.visit_time FROM visits v "
                "JOIN urls u ON u.id = v.url WHERE v.visit_time > ?",
                (chrome_cutoff,),
            )
            visits.extend((url, visit_time / 1_000_000 - epoch_diff) for url, visit_time in cur.fetchall())
            conn.close()
        except Exception:
            pass
        finally:
            try:
                os.remove(tmp_copy)
            except OSError:
                pass
    return visits


def run_browser_history(payload: dict) -> dict:
    hours = payload.get("hours") or 24
    cutoff_ts = time.time() - hours * 3600

    visits = _read_firefox_history(cutoff_ts) + _read_chrome_history(cutoff_ts)
    if not visits:
        return {"report": f"Oxirgi {hours} soatda brauzer tarixi topilmadi (Firefox/Chrome o'rnatilmagan yoki tarix bo'sh)."}

    visits.sort(key=lambda v: v[1])

    per_site = {}
    IDLE_CAP = 30 * 60  # bitta tashrif uchun eng ko'p 30 daqiqa hisoblanadi
    NOISE_PREFIXES = ("127.0.0.1", "localhost", "[::1]")
    for i, (url, ts) in enumerate(visits):
        scheme = urlparse(url).scheme
        if scheme in ("chrome-extension", "moz-extension", "about", "chrome", "file"):
            continue
        try:
            host = urlparse(url).netloc or url
        except Exception:
            host = url
        if host.startswith(NOISE_PREFIXES):
            continue
        bucket = per_site.setdefault(host, {"time": 0.0, "count": 0, "last": 0.0})
        bucket["count"] += 1
        bucket["last"] = max(bucket["last"], ts)
        if i + 1 < len(visits):
            bucket["time"] += min(visits[i + 1][1] - ts, IDLE_CAP)

    ranked = sorted(per_site.items(), key=lambda kv: kv[1]["time"], reverse=True)
    lines = [f"Oxirgi {hours} soatlik sayt tarixi (vaqt taxminiy hisoblangan):"]
    for host, stats in ranked[:15]:
        mins = int(stats["time"] // 60)
        h, m = divmod(mins, 60)
        dur_str = f"{h} soat {m} daqiqa" if h else f"{m} daqiqa"
        last_str = time.strftime("%d-%m %H:%M", time.localtime(stats["last"]))
        lines.append(f"- {host}: taxminan {dur_str}, {stats['count']} marta, oxirgi: {last_str}")
    return {"report": "\n".join(lines)}


# ---------- Dasturlardan foydalanishni kuzatish (fon jarayoni) ----------


def _build_app_allowlist() -> dict:
    """.desktop launcherlardan haqiqiy ilovalar ro'yxatini yasaydi, shunda
    tasodifiy CLI/shell jarayonlari emas, faqat GUI dasturlar kuzatiladi."""
    apps = {}
    desktop_dirs = [
        "/usr/share/applications",
        "/var/lib/snapd/desktop/applications",
        os.path.expanduser("~/.local/share/applications"),
        "/var/lib/flatpak/exports/share/applications",
    ]
    for d in desktop_dirs:
        for path in glob.glob(os.path.join(d, "*.desktop")):
            try:
                name = None
                exec_bin = None
                nodisplay = False
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("[") and line != "[Desktop Entry]":
                            break
                        if line.startswith("Name=") and name is None:
                            name = line[len("Name="):]
                        elif line.startswith("Exec=") and exec_bin is None:
                            tokens = line[len("Exec="):].split()
                            exec_bin = os.path.basename(tokens[0]) if tokens else None
                        elif line == "NoDisplay=true":
                            nodisplay = True
                if exec_bin and name and not nodisplay:
                    apps[exec_bin] = name
            except Exception:
                continue
    return apps


def _proc_comm(pid: str) -> str | None:
    try:
        with open(f"/proc/{pid}/comm") as f:
            return f.read().strip()
    except Exception:
        return None


def _proc_ppid(pid: str) -> str | None:
    try:
        with open(f"/proc/{pid}/stat") as f:
            data = f.read()
        fields = data[data.rfind(")") + 2:].split()
        return fields[1]
    except Exception:
        return None


def _log_app_event(event: str, app_name: str, binary: str, extra: dict) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    entry = {"ts": time.time(), "event": event, "app": app_name, "binary": binary, **extra}
    with open(APP_USAGE_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def app_usage_tracker(stop_event: threading.Event) -> None:
    allowlist = _build_app_allowlist()
    if not allowlist:
        logger.warning("Ilovalar roʻyxati topilmadi, foydalanish kuzatuvi oʻchirilgan.")
        return
    active = {}  # pid -> (binary, start_ts)
    while not stop_event.is_set():
        try:
            current_pids = {p for p in os.listdir("/proc") if p.isdigit()}
            seen = set()
            for pid in current_pids:
                comm = _proc_comm(pid)
                if not comm or comm not in allowlist:
                    continue
                ppid = _proc_ppid(pid)
                if ppid and _proc_comm(ppid) == comm:
                    continue  # bir xil ilovaning ichki (renderer/worker) jarayoni, tashlab yuboriladi
                seen.add(pid)
                if pid not in active:
                    active[pid] = (comm, time.time())
                    _log_app_event("open", allowlist[comm], comm, {})

            for pid in list(active.keys()):
                if pid not in seen:
                    comm, start_ts = active.pop(pid)
                    _log_app_event("close", allowlist.get(comm, comm), comm, {"duration": time.time() - start_ts})
        except Exception:
            logger.exception("Foydalanish kuzatuvida xatolik")
        stop_event.wait(APP_USAGE_POLL_SECONDS)


def run_app_usage_report(payload: dict) -> dict:
    hours = payload.get("hours") or 24
    cutoff = time.time() - hours * 3600

    if not os.path.exists(APP_USAGE_LOG_PATH):
        return {"report": "Hozircha dasturlardan foydalanish maʼlumotlari yoʻq."}

    per_app = {}
    pending_opens = {}
    try:
        with open(APP_USAGE_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry["ts"] < cutoff:
                    continue
                app = entry["app"]
                bucket = per_app.setdefault(app, {"total": 0.0, "opens": 0, "last": 0.0})
                if entry["event"] == "open":
                    bucket["opens"] += 1
                    bucket["last"] = max(bucket["last"], entry["ts"])
                    pending_opens.setdefault(app, []).append(entry["ts"])
                elif entry["event"] == "close":
                    bucket["total"] += entry.get("duration", 0)
                    bucket["last"] = max(bucket["last"], entry["ts"])
                    lst = pending_opens.get(app)
                    if lst:
                        lst.pop(0)
    except Exception as exc:
        return {"error": str(exc)}

    now = time.time()
    for app, starts in pending_opens.items():
        for st in starts:
            per_app[app]["total"] += now - st

    if not per_app:
        return {"report": f"Oxirgi {hours} soatda dastur ishlatilmagan."}

    ranked = sorted(per_app.items(), key=lambda kv: kv[1]["total"], reverse=True)
    lines = [f"Oxirgi {hours} soatlik dasturlardan foydalanish hisoboti:"]
    for app, stats in ranked[:15]:
        mins = int(stats["total"] // 60)
        h, m = divmod(mins, 60)
        dur_str = f"{h} soat {m} daqiqa" if h else f"{m} daqiqa"
        last_str = time.strftime("%d-%m %H:%M", time.localtime(stats["last"]))
        lines.append(f"- {app}: {dur_str} ({stats['opens']} marta ochilgan, oxirgi: {last_str})")
    return {"report": "\n".join(lines)}


ACTIONS = {
    "shell": run_shell,
    "screenshot": run_screenshot,
    "lock": run_lock,
    "restart": lambda payload: run_power("restart"),
    "shutdown": lambda payload: run_power("shutdown"),
    "open_app": run_open_app,
    "close_app": run_close_app,
    "report": run_report,
    "transfer_images": run_transfer_images,
    "browser_history": run_browser_history,
    "app_usage_report": run_app_usage_report,
}


class _WatchHandler(FileSystemEventHandler):
    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
        self._loop = loop
        self._queue = queue
        self._last_sent = {}

    def _should_emit(self, path: str) -> bool:
        if any(part in IGNORED_DIR_NAMES for part in path.split(os.sep)):
            return False
        now = time.time()
        last = self._last_sent.get(path, 0)
        if now - last < FILE_EVENT_THROTTLE_SECONDS:
            return False
        self._last_sent[path] = now
        return True

    def _emit(self, event_type: str, path: str) -> None:
        if not self._should_emit(path):
            return
        self._loop.call_soon_threadsafe(
            self._queue.put_nowait, {"path": path, "event": event_type, "ts": time.time()}
        )

    def on_created(self, event):
        self._emit("created", event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._emit("modified", event.src_path)

    def on_deleted(self, event):
        self._emit("deleted", event.src_path)

    def on_moved(self, event):
        self._emit("moved", f"{event.src_path} -> {event.dest_path}")


async def _file_event_sender(ws_holder: dict, queue: asyncio.Queue) -> None:
    while True:
        event = await queue.get()
        ws = ws_holder.get("ws")
        if ws is not None:
            try:
                await ws.send(json.dumps({"type": "file_event", **event}))
            except Exception:
                pass


def _start_watchdog(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue, watch_paths: list) -> Observer:
    observer = Observer()
    handler = _WatchHandler(loop, queue)
    for path in watch_paths:
        expanded = os.path.expanduser(path)
        if os.path.isdir(expanded):
            observer.schedule(handler, expanded, recursive=True)
            logger.info("Kuzatilmoqda: %s", expanded)
        else:
            logger.warning("Papka topilmadi, o'tkazib yuborildi: %s", expanded)
    observer.start()
    return observer


async def _handle_command(ws, config: dict, msg: dict) -> None:
    request_id = msg.get("request_id")
    if msg.get("agent_secret") != config["agent_secret"]:
        result = {"error": "Ruxsat yo'q (agent_secret mos emas)."}
    else:
        action = msg.get("action")
        payload = msg.get("payload") or {}
        handler = ACTIONS.get(action)
        if handler is None:
            result = {"error": "Notanish amal."}
        else:
            result = await asyncio.to_thread(handler, payload)
            log_command(action, payload, result)

    await ws.send(json.dumps({"type": "command_result", "request_id": request_id, **result}))


async def _connection_loop(config: dict, queue: asyncio.Queue, ws_holder: dict) -> None:
    backoff = 2
    while True:
        try:
            async with websockets.connect(config["relay_url"], open_timeout=10) as ws:
                ws_holder["ws"] = ws
                await ws.send(json.dumps({"type": "hello", "role": "agent", "token": config["relay_token"]}))
                logger.info("Relayga ulandi.")
                backoff = 2
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("type") == "command":
                        asyncio.create_task(_handle_command(ws, config, msg))
        except Exception:
            logger.exception("Relay ulanishida xatolik, qayta urinilmoqda...")
        finally:
            ws_holder["ws"] = None
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 30)


async def main() -> None:
    config = load_config()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    ws_holder: dict = {"ws": None}

    observer = _start_watchdog(loop, queue, config.get("watch_paths") or [])

    app_usage_stop = threading.Event()
    app_usage_thread = threading.Thread(target=app_usage_tracker, args=(app_usage_stop,), daemon=True)
    app_usage_thread.start()

    try:
        await asyncio.gather(
            _connection_loop(config, queue, ws_holder),
            _file_event_sender(ws_holder, queue),
        )
    finally:
        observer.stop()
        observer.join()
        app_usage_stop.set()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
