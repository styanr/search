from array import array

from PyQt6 import sip
from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QImage, QOffscreenSurface, QOpenGLContext
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtOpenGL import (QOpenGLBuffer, QOpenGLFramebufferObject, QOpenGLShader, QOpenGLShaderProgram,
                            QOpenGLTexture, QOpenGLVersionFunctionsFactory, QOpenGLVersionProfile, QOpenGLWindow)

from circlesearch.core import settings
from circlesearch.ui.effects import InkStroke, gaussian
from circlesearch.ui.theme import GOOGLE, SCRIM, SURFACE

TEXTURE_2D, MIN_FILTER, MAG_FILTER, LINEAR = 0x0DE1, 0x2801, 0x2800, 0x2601
BLEND, SCISSOR_TEST, DEPTH_TEST = 0x0BE2, 0x0C11, 0x0B71
ZERO, ONE, ONE_MINUS_SRC_ALPHA, DST_COLOR, ONE_MINUS_DST_COLOR = 0, 1, 0x0303, 0x0306, 0x0307
TRIANGLES, FLOAT, COLOR_BUFFER_BIT, DEPTH_BUFFER_BIT, RENDERER = 0x0004, 0x1406, 0x4000, 0x0100, 0x1F01
LESS, LEQUAL = 0x0201, 0x0203
FUNC_ADD, MAX = 0x8006, 0x8008
TEXTURE0, TEXTURE1 = 0x84C0, 0x84C1
FROST_UNITS = (0x84C2, 0x84C3, 0x84C4)
PANES = 12

OVER, SCREEN, MULTIPLY = (ONE, ONE_MINUS_SRC_ALPHA), (ONE_MINUS_DST_COLOR, ONE), (DST_COLOR, ZERO)
SHIMMER, BORDER, FRAME, TIP = 1, 2, 3, 5
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
uniform float opening;
uniform vec4 source;
uniform float lift;
uniform vec4 glow;
uniform vec4 wave;
uniform vec3 pen;
uniform vec3 activity;
uniform sampler2D halo;
uniform float light;
uniform sampler2D frost_half;
uniform sampler2D frost_quarter;
uniform sampler2D frost;
uniform vec4 panes[12];
uniform vec3 pane_info[12];
uniform int pane_count;
uniform float frosted;
uniform vec3 surface;
uniform vec3 hues[4];
float hash(vec2 q) { return fract(sin(dot(q, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 q) {
    vec2 i = floor(q);
    vec2 f = fract(q);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
}
float fbm(vec2 q) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 3; i++) {
        v += a * noise(q);
        q = q * 2.03 + vec2(17.0, 9.0);
        a *= 0.5;
    }
    return v / 0.875;
}
vec3 hold(float x) {
    x = mod(x, 4.0);
    int i = int(floor(x));
    return mix(hues[i], hues[int(mod(float(i + 1), 4.0))], smoothstep(0.3, 0.7, x - floor(x)));
}
vec3 aurora(vec2 n, float t, float anchor, float seed, float lobe) {
    float x = n.x * view.x / 520.0 + seed;
    float drift = fbm(vec2(x * 0.7, t * 0.12));
    float swell = fbm(vec2(x * 0.9 + 5.2, t * 0.1 + 3.0));
    float d = abs(n.y - anchor) / (0.62 + 0.4 * swell + 0.3 * lobe);
    float a = d < 0.45 ? mix(0.85, 0.35, d / 0.45) : mix(0.35, 0.0, clamp((d - 0.45) / 0.55, 0.0, 1.0));
    vec3 c = hold(n.x * 3.6 + seed + 1.4 * (drift - 0.5) + t * 0.03);
    return c * a * (0.7 + 0.6 * fbm(vec2(x * 1.3 - t * 0.08, 7.0))) * (1.0 + 0.6 * lobe);
}
vec3 screen(vec3 a, vec3 b) { return a + b - a * b; }
void main() {
    vec3 base = texture2D(shot, p / view).rgb;
    float pane = 0.0;
    float inside = 0.0;
    float shadow = 0.0;
    for (int i = 0; i < 12; i++) {
        if (i >= pane_count) break;
        vec4 r = panes[i];
        float k = cover(rbox(p, r, pane_info[i].x));
        inside = max(inside, k);
        pane = max(pane, k * pane_info[i].y * frosted);
        float d = rbox(p - vec2(0.0, 14.0), vec4(r.x + 8.0, r.y, r.z - 16.0, r.w), pane_info[i].x);
        shadow = 1.0 - (1.0 - shadow) * (1.0 - pane_info[i].z * (1.0 - smoothstep(-20.0, 20.0, d)));
    }
    if (pane > 0.0) {
        vec2 fuv = vec2(p.x / view.x, 1.0 - p.y / view.y);
        float lv = pane * 3.0;
        vec3 f1 = texture2D(frost_half, fuv).rgb;
        vec3 f2 = texture2D(frost_quarter, fuv).rgb;
        vec3 f3 = texture2D(frost, fuv).rgb;
        base = lv < 1.0 ? mix(base, f1, lv) : (lv < 2.0 ? mix(f1, f2, lv - 1.0) : mix(f2, f3, lv - 2.0));
    }
    float reveal = clamp((p.y - sweep.x) / sweep.y + 1.0, 0.0, 1.0);
    reveal = reveal * reveal * (3.0 - 2.0 * reveal);
    float a = (mix(shade.x, shade.y, p.y / view.y) + shade.z) * reveal * shade.w;
    vec4 lit = vec4(0.0);
    if (light > 0.0) {
        lit = texture2D(halo, vec2(p.x / view.x, 1.0 - p.y / view.y));
        lit *= min(1.0, 2.5 * lit.a) / max(lit.a, 0.0001);
        a *= 1.0 - 0.5 * light * lit.a;
    }
    vec3 c = mix(base, scrim, a);
    c = c + lit.rgb * 0.65 * light - c * lit.rgb * 0.65 * light;
    if (hole.z > 0.0) {
        vec3 inner = base;
        if (lift > 0.0) {
            float d = rbox(p - vec2(0.0, 6.0), hole, hole_radius);
            c = mix(c, vec3(0.0), lift * 0.38 * shade.w * (1.0 - smoothstep(-18.0, 18.0, d)));
            inner = texture2D(shot, (source.xy + (p - hole.xy) * source.zw / hole.zw) / view).rgb;
        }
        c = mix(c, inner, cover(rbox(p, hole, hole_radius)) * opening);
    }
    if (glow.x > 0.004 && p.y >= glow.z - 0.4 * glow.w) {
        vec2 n = vec2(p.x / view.x, (p.y - glow.z) / glow.w);
        float lobe = pen.y * mix(0.7, 1.6, pen.z) * exp(-pow((p.x - pen.x) / (view.x * mix(0.22, 0.12, pen.z)), 2.0));
        lobe += activity.y * exp(-pow((p.x - activity.z) / (view.x * 0.3), 2.0));
        float run = exp(-pow((fract(n.x * 0.6 - glow.y * 0.22) - 0.5) / 0.14, 2.0));
        c = screen(c, min(aurora(n, glow.y, 1.15, 0.0, lobe) * (1.0 + 0.5 * activity.x * run) * glow.x, 1.0));
    }
    if (wave.x > 0.004 && p.y >= wave.z && p.y <= wave.z + wave.w) {
        vec2 n = vec2(p.x / view.x, (p.y - wave.z) / wave.w);
        float feather = clamp(min(n.y, 1.0 - n.y) / 0.3, 0.0, 1.0);
        c = screen(c, min(aurora(n, wave.y, 0.5, 2.0, 0.0) * wave.x, 1.0) * feather);
    }
    c = mix(c, mix(surface, c, 0.25), pane);
    c *= 1.0 - 0.55 * shadow * (1.0 - inside);
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

INK_VERTEX = """
attribute vec2 pos;
attribute vec2 goal;
attribute vec4 box;
attribute vec4 target;
attribute vec4 info;
uniform vec2 view;
uniform float morph;
varying vec2 p;
varying vec4 seg;
varying vec4 data;
void main() {
    p = mix(pos, goal, morph);
    seg = mix(box, target, morph);
    data = info;
    gl_Position = vec4(p.x / view.x * 2.0 - 1.0, 1.0 - p.y / view.y * 2.0, 0.0, 1.0);
}
"""

INK = COMMON + """
uniform int mode;
uniform float width;
uniform float end_width;
uniform float morph;
uniform float shine;
uniform float flow;
uniform float spin;
uniform float span;
uniform int stage;
uniform vec3 hues[4];
varying vec4 seg;
varying vec4 data;
vec3 band(float x) {
    x = mod(x, 4.0);
    int i = int(floor(x));
    return mix(hues[i], hues[int(mod(float(i + 1), 4.0))], x - floor(x));
}
void main() {
    vec2 ba = seg.zw - seg.xy;
    vec2 pa = p - seg.xy;
    float h = clamp(dot(pa, ba) / max(dot(ba, ba), 0.0001), 0.0, 1.0);
    float s = mix(data.x, data.y, h);
    float m = clamp(morph, 0.0, 1.0);
    float w = mix(end_width, width * min(1.0, 0.45 + 0.55 * s / 60.0), shine);
    float k = cover(length(pa - ba * h) - w * 0.5);
    float x = mod((s - flow) / 220.0, 4.0);
    float y = fract((mix(data.z, data.w, h) - spin) / 360.0) * 4.0;
    float d = mod(y - x + 2.0, 4.0) - 2.0;
    vec3 c = mix(band(x + d * m), band(x + (d - sign(d) * 4.0) * m), 0.5 * smoothstep(1.4, 2.0, abs(d)));
    if (stage == 1 && k < 0.999) discard;
    if (stage == 2 && (k >= 0.999 || k <= 0.0)) discard;
    float depth = 1.0 - 0.99 * clamp(s / span, 0.0, 1.0);
    gl_FragDepth = depth - (stage >= 2 ? 0.99 * 14.0 / span : 0.0);
    if (mode == 1) {
        c = mix(c, vec3(1.0), 0.8);
        k *= shine;
    }
    gl_FragColor = vec4(c * k, k);
}
"""

BLUR = COMMON + """
uniform sampler2D image;
uniform vec2 step;
uniform float weights[10];
varying vec2 st;
void main() {
    vec4 c = texture2D(image, st) * weights[0];
    for (int i = 1; i < 10; i++) {
        c += (texture2D(image, st + step * float(i)) + texture2D(image, st - step * float(i))) * weights[i];
    }
    gl_FragColor = c;
}
"""

SOURCES = {"background": BACKGROUND, "words": WORDS, "shapes": SHAPES, "image": IMAGE, "ink": INK, "blur": BLUR}
VERTICES = {"ink": INK_VERTEX}
ATTRIBUTES = ("pos", "uv", "box", "tint", "goal", "target", "info")
INK_LAYOUT = (("pos", 2), ("goal", 2), ("box", 4), ("target", 4), ("info", 4))

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
        program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex,
                                        "#version 120\n" + VERTICES.get(name, VERTEX))
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
        self.size = image.size()
        self.texture = QOpenGLTexture(QOpenGLTexture.Target.Target2D)
        self.texture.setSize(self.size.width(), self.size.height())
        self.texture.setFormat(QOpenGLTexture.TextureFormat.RGBA8_UNorm)
        self.texture.setMinMagFilters(QOpenGLTexture.Filter.Linear, QOpenGLTexture.Filter.Linear)
        self.texture.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
        self.texture.allocateStorage()
        if image.format() not in (QImage.Format.Format_ARGB32_Premultiplied, QImage.Format.Format_RGB32):
            image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        bits = image.constBits()
        bits.setsize(image.sizeInBytes())
        self.texture.setData(QOpenGLTexture.PixelFormat.BGRA, QOpenGLTexture.PixelType.UInt8, bits)
        self.id = self.texture.textureId()

    def delete(self):
        self.texture.destroy()


class Layer:
    def __init__(self, gl, size, depth=False):
        self.fbo = (QOpenGLFramebufferObject(size, QOpenGLFramebufferObject.Attachment.Depth) if depth
                    else QOpenGLFramebufferObject(size))
        self.size, self.id = QSize(size), self.fbo.texture()
        gl.glBindTexture(TEXTURE_2D, self.id)
        gl.glTexParameteri(TEXTURE_2D, MIN_FILTER, LINEAR)
        gl.glTexParameteri(TEXTURE_2D, MAG_FILTER, LINEAR)


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
        self._layers = None
        self._strokes = {}
        self._light_owner = None
        self._frost = None
        reach, weights = gaussian(InkStroke.GLOW_SIGMA)
        self._weights = weights[reach:reach + 10]
        self._used = set()
        self.view = (1.0, 1.0)
        self.dpr = 1.0

    def begin(self, width, height, dpr):
        self.view, self.dpr = (float(width), float(height)), float(dpr)
        self.device = QSize(round(width * dpr), round(height * dpr))
        rebind()
        gl = self.gl
        gl.glViewport(0, 0, self.device.width(), self.device.height())
        gl.glDisable(SCISSOR_TEST)
        gl.glDisable(DEPTH_TEST)
        gl.glEnable(BLEND)
        self._used = set()

    def end(self):
        for key in [k for k in self._cache if k not in self._used]:
            self._cache.pop(key)[1].delete()
        for key in [k for k in self._strokes if k not in self._used]:
            del self._strokes[key]
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

    def background(self, shade, sweep, hole, glow, wave, lift=None, pen=None, activity=(0.0, 0.0, 0.0), light=None,
                   panes=(), frosted=False):
        frost = self._frost_texture() if panes and frosted else None
        program = self._use("background", (ONE, ZERO))
        self.gl.glBindTexture(TEXTURE_2D, self.shot.id)
        program.setUniformValue("shot", 0)
        program.setUniformValue("scrim", *rgb(SCRIM))
        program.setUniformValue("shade", *map(float, shade))
        program.setUniformValue("sweep", *map(float, sweep))
        rect, radius, opening = hole if hole is not None else (QRectF(), 0.0, 0.0)
        program.setUniformValue("hole", rect.x(), rect.y(), rect.width(), rect.height())
        program.setUniformValue("hole_radius", float(radius))
        program.setUniformValue("opening", float(opening))
        source, amount = lift if lift is not None else (QRectF(), 0.0)
        program.setUniformValue("source", source.x(), source.y(), source.width(), source.height())
        program.setUniformValue("lift", float(amount))
        program.setUniformValue("glow", *map(float, glow))
        program.setUniformValue("wave", *map(float, wave))
        x, energy, near = pen if pen is not None else (0.0, 0.0, 0.0)
        program.setUniformValue("pen", float(x), float(energy), float(near))
        program.setUniformValue("activity", *map(float, activity))
        strength, owner = light if light is not None else (0.0, None)
        if strength > 0.0 and owner is not None and owner is self._light_owner:
            self.gl.glActiveTexture(TEXTURE1)
            self.gl.glBindTexture(TEXTURE_2D, self._layers[3].id)
            self.gl.glActiveTexture(TEXTURE0)
        else:
            strength = 0.0
        program.setUniformValue("halo", 1)
        program.setUniformValue("light", float(strength))
        panes = panes[:PANES]
        for i, (rect, radius, frost_amount, shadow) in enumerate(panes):
            program.setUniformValue(f"panes[{i}]", rect.x(), rect.y(), rect.width(), rect.height())
            program.setUniformValue(f"pane_info[{i}]", float(radius), float(frost_amount), float(shadow))
        program.setUniformValue("pane_count", len(panes))
        program.setUniformValue("frosted", 1.0 if frost is not None else 0.0)
        program.setUniformValue("surface", *rgb(SURFACE))
        for unit, name, layer in zip(FROST_UNITS, ("frost_half", "frost_quarter", "frost"), frost or ()):
            self.gl.glActiveTexture(unit)
            self.gl.glBindTexture(TEXTURE_2D, layer.id)
            program.setUniformValue(name, unit - TEXTURE0)
        self.gl.glActiveTexture(TEXTURE0)
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

    def _ink_layers(self):
        full = self.device
        half = QSize((full.width() + 1) // 2, (full.height() + 1) // 2)
        eighth = QSize((full.width() + 7) // 8, (full.height() + 7) // 8)
        if self._layers is None or self._layers[0].size != full:
            self._layers = [Layer(self.gl, full, depth=True), Layer(self.gl, half), Layer(self.gl, half),
                            Layer(self.gl, eighth), Layer(self.gl, eighth)]
            self._light_owner = None
            for layer in self._layers:
                layer.fbo.bind()
                self.gl.glClearColor(0.0, 0.0, 0.0, 0.0)
                self.gl.glClear(COLOR_BUFFER_BIT | DEPTH_BUFFER_BIT)
        return self._layers

    def _scissor(self, layer, area, scale):
        w, h = layer.size.width(), layer.size.height()
        x0, y0 = max(0, int(area.left() * scale)), max(0, int(area.top() * scale))
        x1, y1 = min(w, int(area.right() * scale) + 2), min(h, int(area.bottom() * scale) + 2)
        self.gl.glScissor(x0, h - y1, max(0, x1 - x0), max(0, y1 - y0))

    def _into(self, layer, area, scale, margin=0.0, depth=False):
        layer.fbo.bind()
        gl = self.gl
        gl.glViewport(0, 0, layer.size.width(), layer.size.height())
        gl.glEnable(SCISSOR_TEST)
        self._scissor(layer, area.adjusted(-margin, -margin, margin, margin), scale)
        gl.glClearColor(0.0, 0.0, 0.0, 0.0)
        gl.glClear(COLOR_BUFFER_BIT | (DEPTH_BUFFER_BIT if depth else 0))
        self._scissor(layer, area, scale)

    def _blur(self, layer, temp, region, scale):
        for source, target, step in ((layer, temp, (1.0 / layer.size.width(), 0.0)),
                                     (temp, layer, (0.0, 1.0 / layer.size.height()))):
            self._into(target, region, self.dpr * scale, 24.0 / scale)
            program = self._use("blur", (ONE, ZERO))
            self.gl.glBindTexture(TEXTURE_2D, source.id)
            program.setUniformValue("image", 0)
            program.setUniformValue("step", *step)
            for i, weight in enumerate(self._weights):
                program.setUniformValue(f"weights[{i}]", float(weight))
            self._draw(program, array("f", self._quad(region, self._flipped(region))), (("pos", 2), ("uv", 2)))

    def frost(self):
        self._frost_texture()

    def _frost_texture(self):
        if self._frost is None:
            full, whole = self.device, self._full()
            levels = []
            source, uv = self.shot.id, None
            for d, passes in ((2, 1), (4, 1), (8, 2)):
                size = QSize((full.width() + d - 1) // d, (full.height() + d - 1) // d)
                layer, temp = Layer(self.gl, size), Layer(self.gl, size)
                self._into(layer, whole, self.dpr / d)
                self._textured(source, whole, 1.0, (ONE, ZERO), uv)
                for _ in range(passes):
                    self._blur(layer, temp, whole, 1 / d)
                levels.append(layer)
                source, uv = layer.id, self._flipped(whole)
            self.gl.glDisable(SCISSOR_TEST)
            rebind()
            self.gl.glViewport(0, 0, self.device.width(), self.device.height())
            self._frost = tuple(levels)
        return self._frost

    def _flipped(self, area):
        w, h = self.view
        return area.left() / w, 1 - area.top() / h, area.right() / w, 1 - area.bottom() / h

    def _ink_data(self, stroke, line, goals):
        key = ("ink", id(stroke))
        entry = self._strokes.get(key)
        if entry is None or entry[0] is not stroke or entry[3] is not goals:
            entry = [stroke, 1, array("f"), goals]
            self._strokes[key] = entry
        self._used.add(key)
        data = entry[2]
        for i in range(entry[1], len(line)):
            self._segment(data, line[i - 1], line[i], goals[i - 1] if goals else None, goals[i] if goals else None)
        entry[1] = max(entry[1], len(line))
        tail = stroke.tail() if goals is None else None
        if tail is None:
            return data
        extra = array("f")
        self._segment(extra, line[-1], tail, None, None)
        return data + extra

    @staticmethod
    def _segment(data, a, b, ga, gb):
        ga, gb = ga or (a[0], a[1], 0.0), gb or (b[0], b[1], 0.0)
        if a[:2] == b[:2] and ga[:2] == gb[:2]:
            return
        pad = InkStroke.GLOW_WIDTH / 2 + 2
        x0, x1 = min(a[0], b[0]) - pad, max(a[0], b[0]) + pad
        y0, y1 = min(a[1], b[1]) - pad, max(a[1], b[1]) + pad
        u0, u1 = min(ga[0], gb[0]) - pad, max(ga[0], gb[0]) + pad
        v0, v1 = min(ga[1], gb[1]) - pad, max(ga[1], gb[1]) + pad
        tail = (a[0], a[1], b[0], b[1], ga[0], ga[1], gb[0], gb[1], a[2], b[2], ga[2], gb[2])
        for x, y, u, v in ((x0, y0, u0, v0), (x1, y0, u1, v0), (x0, y1, u0, v1),
                           (x0, y1, u0, v1), (x1, y0, u1, v0), (x1, y1, u1, v1)):
            data.extend((x, y, u, v, *tail))

    def ink(self, stroke, alpha, flow, spin, tip=True, line=None, goals=None, morph=0.0, shine=1.0, light=False):
        data = self._ink_data(stroke, line or stroke.line, goals)
        area = stroke.bounds
        if goals:
            xs, ys = [g[0] for g in goals], [g[1] for g in goals]
            pad = stroke.PAD
            area = area.united(QRectF(min(xs) - pad, min(ys) - pad, max(xs) - min(xs) + 2 * pad,
                                      max(ys) - min(ys) + 2 * pad))
        area = area.intersected(self._full())
        if alpha <= 0.01 or not data or area.isEmpty():
            return
        gl = self.gl
        raw = data.tobytes()
        core, glow, spare, lit, lit_spare = self._ink_layers()
        tail = stroke.tail() if goals is None else None
        span = max((line or stroke.line)[-1][2], tail[2] if tail else 0.0) + 1.0

        def run(mode, stage, width, end_width, scale):
            program = self._use("ink", (ONE, ONE))
            for name, value in (("dpr", self.dpr * scale), ("width", width), ("end_width", end_width),
                                ("morph", morph), ("shine", shine), ("flow", flow), ("spin", spin), ("span", span)):
                program.setUniformValue(name, float(value))
            program.setUniformValue("mode", mode)
            program.setUniformValue("stage", stage)
            self._hues(program)
            return program

        self._into(core, area, self.dpr, 24.0, depth=True)
        gl.glEnable(DEPTH_TEST)
        for mode, stage, width, end_width, blend, equation, func, write in (
                (0, 1, stroke.CORE_WIDTH, 3.5, (ONE, ZERO), FUNC_ADD, LESS, True),
                (0, 2, stroke.CORE_WIDTH, 3.5, (ONE, ONE), MAX, LESS, False),
                (1, 3, stroke.HIGHLIGHT_WIDTH, 0.0, OVER, FUNC_ADD, LEQUAL, False)):
            program = run(mode, stage, width, end_width, 1.0)
            gl.glBlendFunc(*blend)
            gl.glBlendEquation(equation)
            gl.glDepthFunc(func)
            gl.glDepthMask(write)
            self._draw(program, raw, INK_LAYOUT)
        gl.glBlendEquation(FUNC_ADD)
        gl.glDepthMask(True)
        gl.glDisable(DEPTH_TEST)
        passes = [(glow, 2, stroke.GLOW_WIDTH, 8.0, 0.5, area)]
        blurs = [(glow, spare, 0.5, area), (glow, spare, 0.5, area)]
        if light:
            if self._light_owner is not stroke:
                lit.fbo.bind()
                gl.glDisable(SCISSOR_TEST)
                gl.glClearColor(0.0, 0.0, 0.0, 0.0)
                gl.glClear(COLOR_BUFFER_BIT)
                self._light_owner = stroke
            wide = area.adjusted(-120, -120, 120, 120).intersected(self._full())
            passes.append((lit, 2, stroke.GLOW_WIDTH, 8.0, 0.125, wide))
            blurs += [(lit, lit_spare, 0.125, wide), (lit, lit_spare, 0.125, wide)]
        for layer, mode, width, end_width, scale, region in passes:
            self._into(layer, region, self.dpr * scale, 24.0)
            program = run(mode, 0, width, end_width, scale)
            gl.glBlendEquation(MAX)
            self._draw(program, raw, INK_LAYOUT)
            gl.glBlendEquation(FUNC_ADD)
        uv = self._flipped(area)
        for layer, temp, scale, region in blurs:
            self._blur(layer, temp, region, scale)
        gl.glDisable(SCISSOR_TEST)
        rebind()
        gl.glViewport(0, 0, self.device.width(), self.device.height())
        self._textured(glow.id, area, min(1.0, stroke.GLOW_STRENGTH * alpha * shine), SCREEN, uv)
        self._textured(core.id, area, alpha, OVER, uv)
        if tip:
            self.tip(stroke.cursor, stroke.TIP_RADIUS, stroke.tip_color(flow), alpha * stroke.TIP_STRENGTH)


class Backdrop(QOpenGLWindow):
    def __init__(self, scene):
        super().__init__()
        self.scene = scene
        self.gpu = None
        self.setTitle("Circle to Search")
        self.setFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                      Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowTransparentForInput)

    def initializeGL(self):
        self.gpu = Renderer(self.scene.shot)
        self.scene.backdrop_ready(self.gpu)

    def paintGL(self):
        self.scene.paint_backdrop(self.gpu)


class BackdropWidget(QOpenGLWidget):
    """Same renderer as Backdrop, but embedded in the overlay window (one window instead of two).
    GNOME/mutter stops drawing the separate backdrop window as soon as the fullscreen overlay is clicked."""

    def __init__(self, scene, parent):
        super().__init__(parent)
        self.scene = scene
        self.gpu = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def initializeGL(self):
        self.gpu = Renderer(self.scene.shot)
        self.scene.backdrop_ready(self.gpu)

    def paintGL(self):
        self.scene.paint_backdrop(self.gpu)
