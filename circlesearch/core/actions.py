import base64
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import urllib.parse

from circlesearch.core.settings import CACHE_DIR

TEXT_SEARCH_URL = "https://www.google.com/search?q={}"
LENS_UPLOAD_URL = "https://lens.google.com/v3/upload?hl=en&re=df&ep=gsbubb"

LENS_PAGE = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>Google Lens</title>
<style>
  :root { color-scheme: dark; }
  body { margin: 0; height: 100vh; display: grid; place-items: center;
         background: #131418; color: #a6a9b4; font: 15px system-ui, sans-serif; }
</style>
<p id="msg">Sending your selection to Google Lens…</p>
<form id="lens" method="post" enctype="multipart/form-data" action="{action}">
  <input type="file" name="encoded_image" hidden>
</form>
<script>
  if (sessionStorage.getItem("sent")) {
    // came back here with the Back button: don't upload again
    document.getElementById("msg").textContent = "Your selection was sent to Google Lens.";
  } else {
    sessionStorage.setItem("sent", "1");
    const bytes = Uint8Array.from(atob("{image}"), c => c.charCodeAt(0));
    const files = new DataTransfer();
    files.items.add(new File([bytes], "selection.png", { type: "image/png" }));
    const form = document.getElementById("lens");
    form.encoded_image.files = files.files;
    form.action += "&st=" + Date.now();
    form.submit();
  }
</script>
</html>
"""


def open_url(url):
    subprocess.Popen(["xdg-open", url], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def search_text(query):
    query = " ".join(query.split())
    open_url(TEXT_SEARCH_URL.format(urllib.parse.quote_plus(query)))


def search_image(png_bytes):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cutoff = time.time() - 600
    for name in os.listdir(CACHE_DIR):
        path = os.path.join(CACHE_DIR, name)
        if name.startswith("lens-") and os.path.getmtime(path) < cutoff:
            os.unlink(path)
    fd, path = tempfile.mkstemp(prefix="lens-", suffix=".html", dir=CACHE_DIR)
    with os.fdopen(fd, "w") as f:
        f.write(LENS_PAGE.replace("{action}", LENS_UPLOAD_URL)
                         .replace("{image}", base64.b64encode(png_bytes).decode()))
    open_url(pathlib.Path(path).as_uri())


def save_file(name, content):
    folder = os.path.join(CACHE_DIR, "files")
    os.makedirs(folder, exist_ok=True)
    safe_name = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in name).strip("-.") or "file"
    path = os.path.join(folder, safe_name)
    with open(path, "w" if isinstance(content, str) else "wb") as f:
        f.write(content)
    return path


def run_command(command, stdin=None):
    if not command or shutil.which(command[0]) is None:
        return False
    try:
        proc = subprocess.Popen(command, start_new_session=True, stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if stdin:
            proc.stdin.write(stdin.encode())
            proc.stdin.close()
    except OSError:
        return False
    return True


def copy_text(text):
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        subprocess.run(["wl-copy"], input=text.encode(), check=False)
        return True
    return False
