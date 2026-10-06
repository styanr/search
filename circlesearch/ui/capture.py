import os
import shutil
import subprocess
import tempfile
import time
import urllib.parse

from PyQt6.QtCore import QEventLoop, QObject, QTimer, pyqtSlot
from PyQt6.QtDBus import QDBus, QDBusConnection, QDBusMessage
from PyQt6.QtGui import QImage

from circlesearch.core.registry import Registry

APP_ID = "io.github.styanr.search"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
KWIN_GRAB = os.path.join(ROOT, "kwin-grab")

backends = Registry("capture backend")


def backend(name, order=100, enabled=lambda: True):
    def register(cls):
        instance = cls()
        instance.enabled = enabled
        backends.add(name, instance, order)
        return cls
    return register


def on_kde():
    return "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()


class Backend:
    def begin(self):
        return None

    def grab(self, started):
        raise NotImplementedError


class Capture:
    def __init__(self):
        self.started = {}
        for b in backends:
            if b.enabled():
                handle = b.begin()
                if handle is not None:
                    self.started[b] = handle

    def finish(self):
        for b in backends:
            if not b.enabled():
                continue
            image = b.grab(self.started.get(b))
            if image is not None and not image.isNull():
                return image
        return None


@backend("kwin", order=10)
class KWinGrab(Backend):
    def begin(self):
        if not os.access(KWIN_GRAB, os.X_OK):
            return None
        try:
            return subprocess.Popen([KWIN_GRAB], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            return None

    def grab(self, proc):
        if proc is None:
            return None
        try:
            out, _ = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            return None
        if proc.returncode != 0:
            return None
        header, _, pixels = out.partition(b"\n")
        width, height, stride, fmt, _scale = header.split()
        image = QImage(pixels, int(width), int(height), int(stride), QImage.Format(int(fmt)))
        return image.copy()


class PortalResponse(QObject):
    def __init__(self, loop):
        super().__init__()
        self.loop, self.code, self.results = loop, None, {}

    @pyqtSlot(QDBusMessage)
    def response(self, message):
        args = message.arguments()
        self.code = args[0] if args else 2
        self.results = args[1] if len(args) > 1 else {}
        self.loop.quit()


def in_own_scope():
    try:
        with open("/proc/self/cgroup") as f:
            return f"app-{APP_ID}-" in f.read()
    except OSError:
        return None


def own_scope():
    if in_own_scope() is not False or shutil.which("busctl") is None:
        return
    pid = str(os.getpid())
    try:
        subprocess.run(["busctl", "--user", "call", "org.freedesktop.systemd1", "/org/freedesktop/systemd1",
                        "org.freedesktop.systemd1.Manager", "StartTransientUnit", "ssa(sv)a(sa(sv))",
                        f"app-{APP_ID}-{pid}.scope", "fail", "1", "PIDs", "au", "1", pid, "0"],
                       capture_output=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return
    deadline = time.monotonic() + 0.5
    while not in_own_scope() and time.monotonic() < deadline:
        time.sleep(0.01)


@backend("portal", order=20, enabled=lambda: not on_kde())
@backend("portal-fallback", order=60, enabled=on_kde)
class Portal(Backend):
    def grab(self, _started, timeout_ms=60000):
        own_scope()
        bus = QDBusConnection.connectToBus(QDBusConnection.BusType.SessionBus, "circle-search-portal")
        if not bus.isConnected():
            return None
        register = QDBusMessage.createMethodCall("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                                                 "org.freedesktop.host.portal.Registry", "Register")
        register.setArguments([APP_ID, {}])
        bus.call(register, QDBus.CallMode.Block, 3000)
        token = f"circlesearch{os.getpid()}{int(time.monotonic() * 1000)}"
        sender = bus.baseService().lstrip(":").replace(".", "_")
        request = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        loop = QEventLoop()
        receiver = PortalResponse(loop)
        if not bus.connect("org.freedesktop.portal.Desktop", request, "org.freedesktop.portal.Request", "Response",
                           receiver.response):
            return None
        call = QDBusMessage.createMethodCall("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                                             "org.freedesktop.portal.Screenshot", "Screenshot")
        call.setArguments(["", {"handle_token": token, "interactive": False}])
        reply = bus.call(call, QDBus.CallMode.Block, timeout_ms)
        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            return None
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec()
        uri = str(receiver.results.get("uri", "")) if receiver.code == 0 else ""
        if not uri.startswith("file://"):
            return None
        path = urllib.parse.unquote(urllib.parse.urlsplit(uri).path)
        image = QImage(path)
        try:
            if time.time() - os.path.getmtime(path) < 60:
                os.unlink(path)
        except OSError:
            pass
        return None if image.isNull() else image


def tool(name, order, *command):
    class Tool(Backend):
        def grab(self, _started):
            if shutil.which(command[0]) is None:
                return None
            fd, path = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            try:
                subprocess.run([*command, path], check=True, timeout=10,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                image = QImage(path)
                return None if image.isNull() else image
            except (subprocess.SubprocessError, OSError):
                return None
            finally:
                os.unlink(path)

    backend(name, order)(Tool)


tool("spectacle", 30, "spectacle", "-b", "-n", "-f", "-o")
tool("grim", 40, "grim")
tool("gnome-screenshot", 50, "gnome-screenshot", "-f")
