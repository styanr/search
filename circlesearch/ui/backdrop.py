from array import array

from PyQt6 import sip
from PyQt6.QtCore import QRectF, QSize
from PyQt6.QtGui import QImage, QOffscreenSurface, QOpenGLContext
from PyQt6.QtOpenGL import (QOpenGLBuffer, QOpenGLFramebufferObject, QOpenGLShader, QOpenGLShaderProgram,
                            QOpenGLVersionFunctionsFactory, QOpenGLVersionProfile)

from circlesearch.core import settings
from circlesearch.ui.theme import GOOGLE, SCRIM

TEXTURE_2D, RGBA8, BGRA, UNSIGNED_BYTE = 0x0DE1, 0x8058, 0x80E1, 0x1401
MIN_FILTER, MAG_FILTER, WRAP_S, WRAP_T = 0x2801, 0x2800, 0x2802, 0x2803
LINEAR, CLAMP_TO_EDGE = 0x2601, 0x812F
BLEND, SCISSOR_TEST, DEPTH_TEST = 0x0BE2, 0x0C11, 0x0B71
ZERO, ONE, ONE_MINUS_SRC_ALPHA, DST_COLOR, ONE_MINUS_DST_COLOR = 0, 1, 0x0303, 0x0306, 0x0307
TRIANGLES, FLOAT, COLOR_BUFFER_BIT, RENDERER = 0x0004, 0x1406, 0x4000, 0x1F01

OVER, SCREEN, MULTIPLY = (ONE, ONE_MINUS_SRC_ALPHA), (ONE_MINUS_DST_COLOR, ONE), (DST_COLOR, ZERO)
SHIMMER, BORDER, FRAME, SHADOW, TIP = 1, 2, 3, 4, 5
SOFTWARE = ("llvmpipe", "softpipe", "swrast", "swiftshader")

VERTEX = """
attribute vec2 pos;
attribute vec2 uv;
attribute vec4 box;
attribute vec3 tint;
uniform vec2 view;
varying vec2 p;
varying vec2 st;
varying vec4 word;
varying vec3 brush;
void main() {
    p = pos;
    st = uv;
    word = box;
    brush = tint;
    gl_Position = vec4(pos.x / view.x * 2.0 - 1.0, 1.0 - pos.y / view.y * 2.0, 0.0, 1.0);
}
"""

COMMON = """
uniform vec2 view;
uniform float dpr;
varying vec2 p;
float rbox(vec2 q, vec4 r, float radius) {
    vec2 b = r.zw * 0.5;
    radius = min(radius, min(b.x, b.y));
    vec2 d = abs(q - r.xy - b) - b + radius;
    return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0) - radius;
}
float cover(float d) { return clamp(0.5 - d * dpr, 0.0, 1.0); }
float stroke(float d, float width) { return clamp(0.5 + (width * 0.5 - abs(d)) * dpr, 0.0, 1.0); }
"""

BACKGROUND = COMMON + """
uniform sampler2D shot;
uniform vec3 scrim;
uniform vec4 shade;
uniform vec2 sweep;
uniform vec4 hole;
uniform float hole_radius;
uniform vec4 glow;
uniform vec4 wave;
uniform vec3 hues[4];
vec3 aurora(vec2 n, float t, float anchor, float seed) {
    vec3 sum = vec3(0.0);
    for (int i = 0; i < 4; i++) {
        float k = float(i) * 1.7 + seed;
        vec2 c = vec2((float(i) + 0.5) / 4.0 + 0.07 * sin(t * 0.31 + k), anchor + 0.08 * sin(t * 0.47 + k * 1.3));
        vec2 r = vec2(0.32 + 0.06 * sin(t * 0.39 + k * 0.7), 0.80 + 0.12 * sin(t * 0.57 + k * 2.1));
        float d = length((n - c) / r);
        float a = d < 0.45 ? mix(0.85, 0.35, d / 0.45) : mix(0.35, 0.0, clamp((d - 0.45) / 0.55, 0.0, 1.0));
        sum += hues[i] * a;
    }
    return sum;
}
vec3 screen(vec3 a, vec3 b) { return a + b - a * b; }
void main() {
    vec3 c = texture2D(shot, p / view).rgb;
    float reveal = clamp((p.y - sweep.x) / sweep.y + 1.0, 0.0, 1.0);
    reveal = reveal * reveal * (3.0 - 2.0 * reveal);
    float a = (mix(shade.x, shade.y, p.y / view.y) + shade.z) * reveal * shade.w;
    if (hole.z > 0.0) a *= 1.0 - cover(rbox(p, hole, hole_radius));
    c = mix(c, scrim, a);
    if (glow.x > 0.004 && p.y >= glow.z) {
        vec2 n = vec2(p.x / view.x, (p.y - glow.z) / glow.w);
        c = screen(c, min(aurora(n, glow.y, 1.15, 0.0) * glow.x, 1.0));
    }
    if (wave.x > 0.004 && p.y >= wave.z && p.y <= wave.z + wave.w) {
        vec2 n = vec2(p.x / view.x, (p.y - wave.z) / wave.w);
        float feather = clamp(min(n.y, 1.0 - n.y) / 0.3, 0.0, 1.0);
        c = screen(c, min(aurora(n, wave.y, 0.5, 2.0) * wave.x, 1.0) * feather);
    }
    gl_FragColor = vec4(c, 1.0);
}
"""

WORDS = COMMON + """
uniform vec4 clip;
uniform float clip_radius;
uniform float light;
varying vec4 word;
varying vec3 brush;
void main() {
    float k = cover(rbox(p, word, 6.0)) * cover(rbox(p, clip, clip_radius));
    gl_FragColor = light > 0.5 ? vec4(1.0 - k * (1.0 - brush), 1.0) : vec4(brush * k, 1.0);
}
"""

SHAPES = COMMON + """
uniform int mode;
uniform vec4 rect;
uniform float radius;
uniform vec4 color;
uniform vec4 a0;
uniform vec4 a1;
uniform vec3 hues[4];
vec4 conic(vec2 q, vec2 center, float angle, float alpha) {
    float t = fract((degrees(atan(center.y - q.y, q.x - center.x)) - angle) / 360.0) * 4.0;
    int i = int(floor(t));
    vec3 c = mix(hues[i], hues[int(mod(float(i + 1), 4.0))], t - floor(t));
    return vec4(c * alpha, alpha);
}
vec4 over(vec4 top, vec4 under) { return top + under * (1.0 - top.a); }
float square(vec2 corner, float side) { return cover(rbox(p, vec4(corner, side, side), 0.0)); }
void main() {
    float d = rbox(p, rect, radius);
    if (mode == 1) {
        vec2 g = a0.zw - a0.xy;
        float t = clamp(dot(p - a0.xy, g) / dot(g, g), 0.0, 1.0);
        float k = color.a * (1.0 - abs(2.0 * t - 1.0)) * cover(d);
        gl_FragColor = a1.x > 0.5 ? vec4(1.0 - k * (1.0 - color.rgb), 1.0) : vec4(color.rgb * k, k);
    } else if (mode == 2) {
        gl_FragColor = conic(p, a1.xy, a1.z, a0.y) * stroke(d, a0.x);
    } else if (mode == 3) {
        float s = a0.x;
        float inside = max(max(square(rect.xy - 8.0, s + 8.0), square(vec2(rect.x + rect.z - s, rect.y - 8.0), s + 8.0)),
                           max(square(vec2(rect.x - 8.0, rect.y + rect.w - s), s + 8.0), square(rect.xy + rect.zw - s, s + 8.0)));
        vec4 c = vec4(0.0);
        if (a0.w < 1.0) c = conic(p, a1.yz, a1.w, (1.0 - a0.w) * a1.x) * stroke(d, a0.y);
        float w = a0.w * a1.x;
        if (w > 0.01) {
            c = over(vec4(0.0, 0.0, 0.0, 0.30 * w) * stroke(d, a0.z + 4.0), c);
            c = over(vec4(w) * stroke(d, a0.z), c);
        }
        gl_FragColor = c * inside;
    } else if (mode == 4) {
        float k = color.a * (1.0 - smoothstep(-a0.x, a0.x, d));
        gl_FragColor = vec4(0.0, 0.0, 0.0, k);
    } else {
        float r = length(p - a0.xy) / a0.z;
        vec4 inner = vec4(mix(color.rgb, vec3(1.0), 0.35), 1.0) * 0.5 * color.a;
        vec4 mid = vec4(color.rgb, 1.0) * 0.22 * color.a;
        vec4 c = r < 0.4 ? mix(inner, mid, r / 0.4) : mix(mid, vec4(0.0), clamp((r - 0.4) / 0.6, 0.0, 1.0));
        gl_FragColor = c;
    }
}
"""

IMAGE = COMMON + """
uniform sampler2D image;
uniform float opacity;
varying vec2 st;
void main() { gl_FragColor = texture2D(image, st) * opacity; }
"""

SOURCES = {"background": BACKGROUND, "words": WORDS, "shapes": SHAPES, "image": IMAGE}
ATTRIBUTES = ("pos", "uv", "box", "tint")

_programs = {}
LITE = settings.GPU == "lite"


def functions(context):
    profile = QOpenGLVersionProfile()
    profile.setVersion(2, 1)
    gl = QOpenGLVersionFunctionsFactory.get(profile, context)
    if gl is None or not gl.initializeOpenGLFunctions():
        return None
    return gl


def programs():
    group = QOpenGLContext.currentContext().shareGroup()
    if group in _programs:
        return _programs[group]
    compiled = {}
    for name, source in SOURCES.items():
        program = QOpenGLShaderProgram()
        program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, "#version 120\n" + VERTEX)
        program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, "#version 120\n" + source)
        for i, attribute in enumerate(ATTRIBUTES):
            program.bindAttributeLocation(attribute, i)
        if not program.link():
            raise RuntimeError(f"{name} shader: {program.log().strip()}")
        compiled[name] = program
    _programs[group] = compiled
    return compiled


def prepare():
    global LITE
    context = QOpenGLContext.globalShareContext()
    surface = QOffscreenSurface()
    surface.setFormat(context.format() if context is not None else surface.requestedFormat())
    surface.create()
    if context is None or not context.makeCurrent(surface):
        return "Could not start OpenGL."
    try:
        gl = functions(context)
        if gl is None:
            return "OpenGL 2.1 is not available."
        renderer = (gl.glGetString(RENDERER) or "").lower()
        LITE = LITE or any(name in renderer for name in SOFTWARE)
        programs()
    except RuntimeError as e:
        return str(e)
    finally:
        context.doneCurrent()
    return None


def rebind():
    QOpenGLFramebufferObject.bindDefault()


def rgb(color):
    return color.redF(), color.greenF(), color.blueF()


class Texture:
    def __init__(self, gl, image):
        self.gl = gl
        self.size = image.size()
        self.id = gl.glGenTextures(1)
        gl.glBindTexture(TEXTURE_2D, self.id)
        for name, value in ((MIN_FILTER, LINEAR), (MAG_FILTER, LINEAR), (WRAP_S, CLAMP_TO_EDGE),
                            (WRAP_T, CLAMP_TO_EDGE)):
            gl.glTexParameteri(TEXTURE_2D, name, value)
        gl.glTexImage2D(TEXTURE_2D, 0, RGBA8, self.size.width(), self.size.height(), 0, BGRA, UNSIGNED_BYTE,
                        pixels(image))

    def write(self, x, y, image):
        self.gl.glBindTexture(TEXTURE_2D, self.id)
        self.gl.glTexSubImage2D(TEXTURE_2D, 0, x, y, image.width(), image.height(), BGRA, UNSIGNED_BYTE,
                                pixels(image))

    def delete(self):
        self.gl.glDeleteTextures(1, [self.id])


class Layer:
    def __init__(self, gl, size):
        self.fbo = QOpenGLFramebufferObject(size)
        self.fbo.bind()
        gl.glClearColor(0.0, 0.0, 0.0, 0.0)
        gl.glClear(COLOR_BUFFER_BIT)
        self.fbo.release()
        self.gl, self.size, self.id = gl, QSize(size), self.fbo.texture()
        gl.glBindTexture(TEXTURE_2D, self.id)
        gl.glTexParameteri(TEXTURE_2D, MIN_FILTER, LINEAR)
        gl.glTexParameteri(TEXTURE_2D, MAG_FILTER, LINEAR)

    write = Texture.write

    def delete(self):
        self.fbo = None


def pixels(image):
    if image.format() not in (QImage.Format.Format_ARGB32_Premultiplied, QImage.Format.Format_RGB32):
        image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    bits = image.constBits()
    bits.setsize(image.sizeInBytes())
    return bits


class Renderer:
    def __init__(self, shot):
        self.gl = functions(QOpenGLContext.currentContext())
        if self.gl is None:
            raise RuntimeError("OpenGL 2.1 is not available.")
        self.programs = programs()
        self.buffer = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self.buffer.setUsagePattern(QOpenGLBuffer.UsagePattern.StreamDraw)
        self.buffer.create()
        self.shot = Texture(self.gl, shot)
        self.lite = LITE
        self._cache = {}
        self._used = set()
        self.view = (1.0, 1.0)
        self.dpr = 1.0

    def begin(self, width, height, dpr):
        self.view, self.dpr = (float(width), float(height)), float(dpr)
        rebind()
        gl = self.gl
        gl.glViewport(0, 0, round(width * dpr), round(height * dpr))
        gl.glDisable(SCISSOR_TEST)
        gl.glDisable(DEPTH_TEST)
        gl.glEnable(BLEND)
        self._used = set()

    def end(self):
        for key in [k for k in self._cache if k not in self._used]:
            for item in self._cache.pop(key)[1:]:
                item.delete()
        self.gl.glBindTexture(TEXTURE_2D, 0)

    def _use(self, name, blend=OVER):
        program = self.programs[name]
        program.bind()
        program.setUniformValue("view", *self.view)
        program.setUniformValue("dpr", self.dpr)
        self.gl.glBlendFunc(*blend)
        return program

    def _draw(self, program, data, layout):
        stride = sum(size for _, size in layout)
        raw = data if isinstance(data, bytes) else data.tobytes()
        self.buffer.bind()
        self.buffer.allocate(sip.voidptr(raw), len(raw))
        offset = 0
        for name, size in layout:
            location = ATTRIBUTES.index(name)
            program.enableAttributeArray(location)
            program.setAttributeBuffer(location, FLOAT, offset * 4, size, stride * 4)
            offset += size
        self.gl.glDrawArrays(TRIANGLES, 0, len(raw) // (4 * stride))
        for name, _ in layout:
            program.disableAttributeArray(ATTRIBUTES.index(name))
        self.buffer.release()

    @staticmethod
    def _quad(rect, uv=None, extra=()):
        x0, y0, x1, y1 = rect.left(), rect.top(), rect.right(), rect.bottom()
        u0, v0, u1, v1 = uv or (0.0, 0.0, 1.0, 1.0)
        out = []
        for x, y, u, v in ((x0, y0, u0, v0), (x1, y0, u1, v0), (x0, y1, u0, v1),
                           (x0, y1, u0, v1), (x1, y0, u1, v0), (x1, y1, u1, v1)):
            out += [x, y, u, v, *extra]
        return out

    def _full(self):
        return QRectF(0, 0, *self.view)

    def background(self, shade, sweep, hole, glow, wave):
        program = self._use("background", (ONE, ZERO))
        self.gl.glBindTexture(TEXTURE_2D, self.shot.id)
        program.setUniformValue("shot", 0)
        program.setUniformValue("scrim", *rgb(SCRIM))
        program.setUniformValue("shade", *map(float, shade))
        program.setUniformValue("sweep", *map(float, sweep))
        rect, radius = hole if hole is not None else (QRectF(), 0.0)
        program.setUniformValue("hole", rect.x(), rect.y(), rect.width(), rect.height())
        program.setUniformValue("hole_radius", float(radius))
        program.setUniformValue("glow", *map(float, glow))
        program.setUniformValue("wave", *map(float, wave))
        self._hues(program)
        self._draw(program, array("f", self._quad(self._full())), (("pos", 2), ("uv", 2)))

    def _hues(self, program):
        for i, hue in enumerate(GOOGLE):
            program.setUniformValue(f"hues[{i}]", *rgb(hue))

    def word_batch(self, light, dark):
        batch = []
        for words, flag, blend in ((light, 1.0, MULTIPLY), (dark, 0.0, SCREEN)):
            data = array("f")
            for rect, color in words:
                box = rect.adjusted(-1, -1, 1, 1)
                data.extend(self._quad(box, extra=(rect.x(), rect.y(), rect.width(), rect.height(), *rgb(color))))
            if data:
                batch.append((flag, blend, data.tobytes()))
        return batch

    def words(self, batch, clip, clip_radius):
        for flag, blend, data in batch:
            program = self._use("words", blend)
            program.setUniformValue("clip", clip.x(), clip.y(), clip.width(), clip.height())
            program.setUniformValue("clip_radius", float(clip_radius))
            program.setUniformValue("light", flag)
            self._draw(program, data, (("pos", 2), ("uv", 2), ("box", 4), ("tint", 3)))

    def _shape(self, mode, bounds, blend=OVER, rect=None, radius=0.0, color=(0, 0, 0, 0), a0=(0, 0, 0, 0),
               a1=(0, 0, 0, 0)):
        program = self._use("shapes", blend)
        program.setUniformValue("mode", mode)
        rect = rect if rect is not None else bounds
        program.setUniformValue("rect", rect.x(), rect.y(), rect.width(), rect.height())
        program.setUniformValue("radius", float(radius))
        program.setUniformValue("color", *map(float, color))
        program.setUniformValue("a0", *map(float, a0))
        program.setUniformValue("a1", *map(float, a1))
        self._hues(program)
        area = bounds.intersected(self._full())
        if not area.isEmpty():
            self._draw(program, array("f", self._quad(area)), (("pos", 2), ("uv", 2)))

    def shimmer(self, rect, radius, start, end, color, alpha, light):
        self._shape(SHIMMER, rect.adjusted(-1, -1, 1, 1), MULTIPLY if light else OVER, rect, radius,
                    (*rgb(color), alpha), (start.x(), start.y(), end.x(), end.y()), (1.0 if light else 0.0, 0, 0, 0))

    def border(self, rect, radius, width, angle, alpha):
        pad = width + 2
        center = rect.center()
        self._shape(BORDER, rect.adjusted(-pad, -pad, pad, pad), OVER, rect, radius, a0=(width, alpha, 0, 0),
                    a1=(center.x(), center.y(), angle, 0))

    def frame(self, rect, radius, side, gradient_width, pen, white, fade, angle, center):
        pad = max(gradient_width, pen + 4) + 10
        self._shape(FRAME, rect.adjusted(-pad, -pad, pad, pad), OVER, rect, radius,
                    a0=(side, gradient_width, pen, white), a1=(fade, center.x(), center.y(), angle))

    def shadow(self, geometry, opacity, radius, blur=12.0):
        rect = QRectF(geometry.x() + 8, geometry.y() + 14, geometry.width() - 16, geometry.height())
        self._shape(SHADOW, geometry.adjusted(-48, -48, 48, 48), OVER, rect, radius,
                    (0, 0, 0, opacity * 170 / 255), (blur, 0, 0, 0))

    def tip(self, center, radius, color, alpha):
        bounds = QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius)
        self._shape(TIP, bounds, SCREEN, color=(*rgb(color), alpha), a0=(center.x(), center.y(), radius, 0))

    def image(self, key, image, rect, opacity, blend=OVER, reload=False):
        entry = self._cache.get(key)
        if entry is None or reload or entry[1].size != image.size():
            if entry is not None:
                entry[1].delete()
            entry = (None, Texture(self.gl, image))
            self._cache[key] = entry
        self._used.add(key)
        self._textured(entry[1].id, rect, opacity, blend)

    def _textured(self, texture, rect, opacity, blend, uv=None):
        program = self._use("image", blend)
        self.gl.glBindTexture(TEXTURE_2D, texture)
        program.setUniformValue("image", 0)
        program.setUniformValue("opacity", float(opacity))
        self._draw(program, array("f", self._quad(rect, uv)), (("pos", 2), ("uv", 2)))

    def ink(self, stroke, alpha=1.0, tip=True):
        key = ("ink", id(stroke))
        entry = self._cache.get(key)
        if entry is None or entry[0] is not stroke:
            halo = Layer(self.gl, stroke.halo.size())
            core = Layer(self.gl, stroke.core.size())
            rebind()
            entry = (stroke, halo, core)
            self._cache[key] = entry
        self._used.add(key)
        _, halo, core = entry
        for layer, x, y, image in stroke.uploads():
            (halo if layer == "halo" else core).write(x, y, image)
        area = stroke.bounds.intersected(self._full())
        if alpha <= 0.01 or area.isEmpty():
            return
        scale = stroke.GLOW_SCALE
        hw, hh = halo.size.width() * scale, halo.size.height() * scale
        self._textured(halo.id, area, min(1.0, stroke.GLOW_STRENGTH * alpha), SCREEN,
                       (area.left() / hw, area.top() / hh, area.right() / hw, area.bottom() / hh))
        w, h = self.view
        self._textured(core.id, area, alpha, OVER, (area.left() / w, area.top() / h, area.right() / w, area.bottom() / h))
        if tip:
            self.tip(stroke.cursor, stroke.TIP_RADIUS, stroke.tip_color(), alpha)
