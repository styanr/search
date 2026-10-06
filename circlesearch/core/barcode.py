import importlib.util
import shutil
import subprocess
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass

from circlesearch.core.registry import Registry


@dataclass(frozen=True)
class Code:
    format: str
    data: str


engines = Registry("barcode engine")


def engine(cls):
    engines.add(cls.name, cls(), getattr(cls, "order", 100))
    return cls


def available():
    return any(e.available() for e in engines)


def scan(path):
    for e in engines:
        if not e.available():
            continue
        try:
            codes = e.scan(path)
        except (OSError, ValueError, subprocess.SubprocessError, ElementTree.ParseError):
            continue
        if codes:
            return list(dict.fromkeys(codes))
    return []


FORMATS = {"QR-Code": "QR", "EAN-13": "EAN-13", "EAN-8": "EAN-8", "UPC-A": "UPC-A", "UPC-E": "UPC-E",
           "ISBN-13": "EAN-13", "ISBN-10": "EAN-13", "CODE-128": "Code 128", "CODE-39": "Code 39",
           "CODE-93": "Code 93", "I2/5": "ITF", "DataBar": "DataBar", "PDF417": "PDF417", "SQ-Code": "SQ"}


@engine
class ZBar:
    name = "zbar"
    order = 10

    def available(self):
        return shutil.which("zbarimg") is not None

    def scan(self, path):
        out = subprocess.run(["zbarimg", "--quiet", "--xml", path], capture_output=True, timeout=5).stdout
        if not out.strip():
            return []
        root = ElementTree.fromstring(out)
        codes = []
        for symbol in root.iter():
            if not symbol.tag.endswith("symbol"):
                continue
            data = next((child.text for child in symbol if child.tag.endswith("data")), None)
            if data:
                kind = symbol.get("type", "")
                codes.append(Code(FORMATS.get(kind, kind), data))
        return codes


@engine
class ZXing:
    name = "zxing"
    order = 20

    def available(self):
        return all(importlib.util.find_spec(name) is not None for name in ("zxingcpp", "PIL"))

    def scan(self, path):
        import zxingcpp
        from PIL import Image
        with Image.open(path) as image:
            results = zxingcpp.read_barcodes(image.convert("RGB"))
        return [Code(str(r.format).rsplit(".", 1)[-1].replace("QRCode", "QR"), r.text) for r in results if r.text]
