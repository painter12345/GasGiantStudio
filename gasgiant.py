import sys, os, io, json, copy, time, shutil, struct, hashlib, tempfile, argparse
import numpy as np
from PIL import Image, ImageFilter, ImageDraw
Image.MAX_IMAGE_PIXELS = None

APP_NAME = 'Gas Giant Studio'
APP_VERSION = '1.1.0'
VERSION = '4'
FROZEN = bool(getattr(sys, 'frozen', False))
TOOL = os.path.dirname(os.path.abspath(sys.executable if FROZEN else __file__))
ROOT = os.path.abspath(os.path.join(TOOL, '..', '..'))
PD = os.path.join(ROOT, 'GameData', 'ActualFirstSystem', 'Textures', 'PluginData')
PRESETS = os.path.join(TOOL, 'presets')
OUTROOT = os.path.join(TOOL, 'out')
SETTINGS_FILE = os.path.join(TOOL, 'studio_settings.json')
COMMANDS = ('make', 'install', 'sample', 'new', 'flow', 'export')


def read_settings():
    try:
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def texture_dir():
    d = read_settings().get('texture_dir')
    if d and os.path.isdir(d):
        return d
    return PD if os.path.isdir(PD) else ''


def mod_root(d):
    d = os.path.abspath(d)
    parts = d.split(os.sep)
    low = [p.lower() for p in parts]
    if 'gamedata' in low:
        i = len(low) - 1 - low[::-1].index('gamedata')
        if i + 1 < len(parts):
            return os.sep.join(parts[:i + 2])
    return ''


def backup_dir(body, stamp):
    legacy = os.path.join(ROOT, '_cloud_preview')
    if os.path.isdir(legacy):
        return os.path.join(legacy, body.lower() + '_texture', 'backup', stamp)
    return os.path.join(TOOL, 'backups', body, stamp)


def nice(p):
    try:
        return os.path.relpath(p, ROOT) if os.path.abspath(p).startswith(ROOT) else p
    except ValueError:
        return p
D = np.float32(np.pi / 180)
N = 64

DEFAULTS = {
    'seed': 1,
    'steps': 100,
    'keyframes': 4,
    'files': {},
    'bands': [[-90, [140, 148, 186]], [0, [200, 180, 175]], [60, [140, 148, 186]]],
    'band_blend': 3.6,
    'emission': [],
    'edges': [],
    'curl_strength': 12.0,
    'curl_spacing': 6.5,
    'curl_window': 7.0,
    'jets': 0.12,
    'turbulence': 0.0007,
    'turbulence_scale': 4.5,
    'edge_wobble': 2.6,
    'polar_calm': [60, 76],
    'polar_smooth': [50, 64],
    'band_wobble': 1.3,
    'stripes': [1.6, 0.7],
    'sub_bands': 0.045,
    'sub_band_waves': [[0.5, 0.83, 0.4], [0.3, 2.1, 2.2], [0.2, 4.7, 1.1]],
    'sub_band_warm': [6, 4, 0],
    'mottle': 0.035,
    'threads': 0.15,
    'thread_width': 0.075,
    'thread_color': [238, 222, 214],
    'storms': {'count': 0, 'lat_range': [-40, 40], 'size': [0.0035, 0.006], 'turns': 2.6, 'core': 0.3, 'core_size': 0.3, 'core_color': [244, 226, 214]},
    'big_storms': [],
    'blur': 0.75,
    'normal_strength': 6.0,
    'flow': {'zonal_std': 40.0, 'meridional_std': 6.0, 'smooth': 2.0},
    'preview': {'tilt': -22, 'view_lat': 12, 'view_lon': 0},
}

BIG_STORM = {'lat': -20.0, 'lon': 180.0, 'size': 0.025, 'aspect': 1.3, 'turns': 1.0, 'spin': 1,
             'core': 0.5, 'core_size': 0.45, 'core_color': [244, 226, 214], 'ragged': 0.2,
             'arms': 0, 'arm_length': 2.5, 'arm_width': 0.2, 'arm_curl': 1.0, 'arm_strength': 0.85, 'arm_color': None}
STORM_MIXR = np.float32(0.9)
STORM_MIX = np.float32(1.0)
STORM_HOLD = np.float32(1.5)
EMISSION = {'band': 0, 'color': None, 'brightness': 0.5}


def big_storm(bs):
    s = copy.deepcopy(BIG_STORM)
    if 'core' not in bs and 'tint' in bs:
        s['core'] = bs['tint']
        s['core_size'] = bs.get('tint_size', 0.8)
        if 'color' in bs:
            s['core_color'] = list(bs['color'])
    s.update({k: copy.deepcopy(v) for k, v in bs.items() if k in BIG_STORM})
    return s


def storm_polar(s, LA, LO, seed, k):
    la0 = np.float32(s['lat'] * D); lo0 = np.float32(s['lon'] * D)
    dn = (LA - la0) / np.float32(2 * np.pi)
    dl = (LO - lo0 + np.pi) % (2 * np.pi) - np.pi
    de = dl * np.cos(la0) / np.float32(2 * np.pi)
    u = de / np.float32(max(float(s['aspect']), 0.2))
    r = np.sqrt(u ** 2 + dn ** 2)
    th = np.arctan2(dn, u)
    if s['ragged']:
        rng = np.random.default_rng(int(seed) * 1000 + 17 * k + 5)
        ph = rng.uniform(0, 2 * np.pi, 4)
        f = sum(np.cos(m * th + ph[m - 2]) / m for m in range(2, 6)) / np.float32(sum(1.0 / m for m in range(2, 6)))
        r = r * (1 + np.float32(min(float(s['ragged']), 0.6)) * f)
    return r, th


def storm_marks(s, r, th, seed, k, jit=None):
    rho = r / np.float32(max(float(s['size']), 1e-4))
    core = np.float32(s['core']) * np.exp(-(rho / np.float32(max(float(s['core_size']), 0.01))) ** 2)
    n = int(s.get('arms', 0))
    if n <= 0 or float(s['arm_strength']) <= 0:
        return core, None
    rng = np.random.default_rng(int(seed) * 1000 + 31 * k + 11)
    th0 = rng.uniform(-0.35, 0.35)
    rho0 = np.float32(0.6 * float(s['core_size']))
    L = np.float32(max(float(s['arm_length']), 0.1))
    curl = np.float32(float(s['spin']) * float(s['arm_curl']))
    t = (rho - rho0) / L
    w = np.float32(max(float(s['arm_width']), 0.02)) * (1 - 0.65 * np.clip(t, 0, 1))
    env = ss(np.float32(-0.3), np.float32(0.05), t) * (1 - ss(np.float32(0.55), np.float32(1.0), t))
    tilt = np.sqrt(1 + (curl * np.maximum(rho, rho0)) ** 2)
    arms = np.zeros_like(rho)
    for a in range(n):
        d = (th - (th0 + 2 * np.pi * a / n + curl * (rho - rho0)) + np.pi) % (2 * np.pi) - np.pi
        dist = np.abs(d * np.maximum(rho, rho0) / tilt + (0 if jit is None else jit * w))
        arms = np.maximum(arms, np.maximum(np.exp(-(dist / w) ** 4), 0.4 * np.exp(-(dist / (2.5 * w)) ** 2)))
    return core, arms * env * np.float32(s['arm_strength'])


def emission_entry(em):
    e = dict(EMISSION)
    e.update({k: v for k, v in em.items() if k in EMISSION})
    return e


def sort_bands(P):
    old = P['bands']
    order = sorted(range(len(old)), key=lambda i: old[i][0])
    P['bands'] = [old[i] for i in order]
    for em in P.get('emission', []):
        b = em.get('band', -1)
        em['band'] = order.index(b) if 0 <= b < len(order) else -1


def normalize(P):
    P['big_storms'] = [big_storm(b) for b in P.get('big_storms', [])]
    P['emission'] = [emission_entry(e) for e in P.get('emission', [])]
    P.pop('glows', None)
    sort_bands(P)
    return P


def glow_list(P):
    out = []
    bands = P['bands']
    for em in P.get('emission', []):
        i = int(em.get('band', -1))
        if not 0 <= i < len(bands):
            continue
        c = em.get('color') or bands[i][1]
        out.append((i, [float(v) * float(em.get('brightness', 1.0)) for v in c]))
    return out


def mk(seed):
    r = np.random.default_rng(seed)
    return [r.random((N, N, N), dtype=np.float32) for _ in range(8)]


def vn(T, x, y, z):
    xi = np.floor(x).astype(np.int32); yi = np.floor(y).astype(np.int32); zi = np.floor(z).astype(np.int32)
    fx = x - xi; fy = y - yi; fz = z - zi
    fx = fx * fx * (3 - 2 * fx); fy = fy * fy * (3 - 2 * fy); fz = fz * fz * (3 - 2 * fz)
    x0 = xi % N; y0 = yi % N; z0 = zi % N; x1 = (x0 + 1) % N; y1 = (y0 + 1) % N; z1 = (z0 + 1) % N
    c00 = T[x0, y0, z0] * (1 - fx) + T[x1, y0, z0] * fx
    c10 = T[x0, y1, z0] * (1 - fx) + T[x1, y1, z0] * fx
    c01 = T[x0, y0, z1] * (1 - fx) + T[x1, y0, z1] * fx
    c11 = T[x0, y1, z1] * (1 - fx) + T[x1, y1, z1] * fx
    return (c00 * (1 - fy) + c10 * fy) * (1 - fz) + (c01 * (1 - fy) + c11 * fy) * fz


def fbm(tabs, x, y, z, t=0, o=4, gain=0.5):
    s = 0; a = 1; n = 0
    for i in range(o):
        s = s + a * vn(tabs[(t + i) % 8], x * 2 ** i + 17.3 * i, y * 2 ** i + 5.1 * i, z * 2 ** i + 9.7 * i); n += a; a *= gain
    return (s / n) * 2 - 1


def ss(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t)


def grid(w, h):
    lat = ((0.5 - (np.arange(h, dtype=np.float32) + 0.5) / h) * np.pi).astype(np.float32)
    lon = ((np.arange(w, dtype=np.float32) + 0.5) / w * 2 * np.pi).astype(np.float32)
    return np.meshgrid(lat, lon, indexing='ij')


def sph(la, lo):
    c = np.cos(la); return c * np.cos(lo), c * np.sin(lo), np.sin(la)


def samp(F, x, y):
    h, w = F.shape
    fx = x * w - 0.5; fy = np.clip(y * h - 0.5, 0, h - 1.001)
    x0 = np.floor(fx).astype(np.int32); y0 = fy.astype(np.int32)
    tx = fx - x0; ty = fy - y0
    x0 %= w; x1 = x0 + 1; x1[x1 == w] = 0
    fl = F.ravel(); r0 = y0 * w; r1 = r0 + w
    a = fl[r0 + x0] * (1 - tx) + fl[r0 + x1] * tx
    b = fl[r1 + x0] * (1 - tx) + fl[r1 + x1] * tx
    return a * (1 - ty) + b * ty


def gblur(a, sigma, wrap=True):
    r = max(1, int(np.ceil(sigma * 3)))
    k = np.exp(-0.5 * (np.arange(-r, r + 1, dtype=np.float32) / sigma) ** 2); k /= k.sum()
    a = sum(w * np.roll(a, i - r, 1) for i, w in enumerate(k))
    ap = np.pad(a, ((r, r), (0, 0)) + ((0, 0),) * (a.ndim - 2), mode='edge')
    return sum(w * ap[i:i + a.shape[0]] for i, w in enumerate(k))


def dxt_bytes(im, fmt):
    b = io.BytesIO(); im.save(b, 'DDS', pixel_format=fmt); return b.getvalue()


def save_mips(im, path, fmt):
    lv = []; cur = im
    while True:
        lv.append(dxt_bytes(cur, fmt))
        if cur.size == (1, 1): break
        cur = cur.resize((max(1, cur.size[0] // 2), max(1, cur.size[1] // 2)), Image.BOX)
    hd = bytearray(lv[0][:128])
    fl = struct.unpack_from('<I', hd, 8)[0] | 0x20000 | 0x80000
    struct.pack_into('<I', hd, 8, fl); struct.pack_into('<I', hd, 20, len(lv[0]) - 128); struct.pack_into('<I', hd, 28, len(lv))
    struct.pack_into('<I', hd, 108, 0x401008)
    with open(path, 'wb') as f:
        f.write(bytes(hd) + b''.join(x[128:] for x in lv))


def merge(base, over):
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            out[k] = merge(base[k], v)
        else:
            out[k] = v
    return out


def preset_path(p):
    if os.path.isfile(p): return p
    q = os.path.join(PRESETS, p if p.endswith('.json') else p + '.json')
    if os.path.isfile(q): return q
    sys.exit('preset not found: ' + p)


def load_preset(p):
    with open(preset_path(p)) as f:
        raw = json.load(f)
    P = normalize(merge(DEFAULTS, raw))
    if 'name' not in P: sys.exit('preset needs a "name"')
    return P, raw


def kf_at(KF, K, tt):
    t = tt * (K - 1); i = min(int(t), K - 2); f = np.float32(t - i)
    return KF[i] * (1 - f) + KF[i + 1] * f


def trace_step(KF, K, STEPS, n, x, y, dt, rk2=False):
    if rk2:
        v1 = samp(kf_at(KF, K, n / STEPS), x, y)
        xm = (x - v1.real * dt * 0.5) % 1.0; ym = np.clip(y - v1.imag * dt * 0.5, 0, 1)
        v = samp(kf_at(KF, K, (n - 0.5) / STEPS), xm, ym)
    else:
        v = samp(kf_at(KF, K, (n - 0.5) / STEPS), x, y)
    return (x - v.real * dt) % 1.0, np.clip(y - v.imag * dt, 0, 1)


class Clock:
    def __init__(self, budget):
        self.t0 = time.time(); self.budget = budget

    def left(self):
        return 1e9 if self.budget is None else self.budget - (time.time() - self.t0)

    def log(self, *a):
        print(round(time.time() - self.t0, 1), *a, flush=True)


class Unfinished(Exception):
    pass


class Field:
    def __init__(self, P, W):
        self.P = P; self.W = W; self.H = W // 2
        self.VW = min(W, 2048); self.VH = self.VW // 2
        s = int(P['seed'])
        self.T = [mk(s * 10 + i) for i in range(1, 6)]
        T1, T2, T3, T4, T5 = self.T
        self.LA, self.LO = grid(self.VW, self.VH)
        self.X, self.Y, self.Z = sph(self.LA, self.LO)
        self.cosv = np.maximum(np.cos(self.LA), 1e-3)
        pc = P['polar_calm']
        self.pfade = 1 - ss(np.float32(pc[0]) * D, np.float32(pc[1]) * D, np.abs(self.LA))
        self.nlat = self.LA / np.float32(2 * np.pi)
        st = P['storms']
        rng = np.random.default_rng(s)
        self.vort = []
        for k in range(int(st['count'])):
            la = np.float32(rng.uniform(*st['lat_range']) * D); lo = np.float32(rng.uniform(0, 2 * np.pi)); sg = np.float32(rng.uniform(*st['size']))
            self.vort.append((la, lo, sg, np.float32(rng.choice([-1, 1]))))
        self.big = [big_storm(b) for b in P['big_storms']]
        self.glow = glow_list(P)
        self.EW =np.float32(P['edge_wobble']) * fbm(T5, self.X * 2, self.Y * 2, self.Z * 2, o=3) * D / np.float32(2 * np.pi)

    def vortpsi(self, la0, lo0, sg, turns):
        px, py, pz = sph(la0, lo0)
        r = np.arccos(np.clip(self.X * px + self.Y * py + self.Z * pz, -1, 1)) / (2 * np.pi)
        return turns * 5.18 * sg * sg * np.exp(-(r / sg) ** 2)

    def big_polar(self, s, LA, LO, k):
        return storm_polar(s, LA, LO, self.P['seed'], k)

    def big_r(self, s, LA, LO, X, Y, Z, k):
        return self.big_polar(s, LA, LO, k)[0]

    def big_rv(self, k):
        if not hasattr(self, '_big_rv'):
            self._big_rv = [self.big_r(b, self.LA, self.LO, self.X, self.Y, self.Z, j) for j, b in enumerate(self.big)]
        return self._big_rv[k]

    def bigpsi(self, s, k):
        sg = np.float32(s['size']); asp = np.float32(max(float(s['aspect']), 0.2))
        r = self.big_rv(k)
        return np.float32(s['spin']) * np.float32(s['turns']) * 5.18 * sg * sg * asp * np.exp(-(r / sg) ** 2)

    def keyframe(self, k):
        P = self.P; T1, T2, T3, T4, T5 = self.T
        X, Y, Z, LA, LO = self.X, self.Y, self.Z, self.LA, self.LO
        o = np.float32(k * 0.41)
        psi = np.zeros_like(LA)
        amul = np.float32(P['curl_strength'])
        for i, ed in enumerate(P['edges']):
            e = ed['lat']; s = ed['spin']; L = ed['width']; r0 = ed['curl']
            en = np.float32(e * np.pi / 180 / (2 * np.pi)) + self.EW
            kk = max(6, int(round(np.cos(e * D) / (P['curl_spacing'] * L))))
            ph = 3.2 * fbm(T3, X * 2.4 + i * 3.1, Y * 2.4, Z * 2.4 + i * 1.7, o=3)
            rho = np.clip(r0 + 0.75 * fbm(T4, X * 3.4 + i * 2.3, Y * 3.4 + o * 0.25, Z * 3.4 + i, o=3), 0.0, 0.85)
            Lf = np.float32(L) * (1 + 0.45 * fbm(T2, X * 2.6 + i * 1.9, Y * 2.6, Z * 2.6 + i * 0.7, o=2))
            xi = (self.nlat - en) / Lf
            th = kk * LO + ph
            win = np.exp(-(xi / np.float32(P['curl_window'])) ** 2)
            psi += s * amul * Lf * Lf * np.log(np.cosh(np.clip(xi, -20, 20)) - rho * np.cos(th)) * win
        s_ = np.float32(P['turbulence_scale'])
        pn = fbm(T1, X * s_ + o, Y * s_ + o * 0.5, Z * s_ * 1.8 + o * 0.8, o=3, gain=0.5)
        pn = pn * np.float32(P['turbulence'])
        d = LA / D; jet = np.zeros_like(LA)
        es = sorted([(ed['lat'], ed['spin']) for ed in P['edges']])
        for (elo, slo), (ehi, _) in zip(es[:-1], es[1:]):
            inz = (d >= elo) & (d < ehi)
            jet[inz] = (-slo * np.sin(np.pi * (d[inz] - elo) / (ehi - elo)) * (1 + 0.25 * np.sin(d[inz] * 0.7)))
        jet = jet * np.float32(P['jets']) * self.pfade
        dn = np.float32(0.5 / self.VH)
        if self.big:
            jr = jet[:, 0]
            pj = np.concatenate([[0.0], np.cumsum(0.5 * (jr[1:] + jr[:-1]) * dn)]).astype(np.float32)
            bg = (psi + pn) * self.pfade + pj[:, None]
            for j, bs in enumerate(self.big):
                sg = np.float32(bs['size'])
                M = np.exp(-(self.big_rv(j) / (STORM_HOLD * sg)) ** 4)
                c = np.float32((bg * M).sum() / max(float(M.sum()), 1e-9))
                bg = c + (bg - c) * (1 - M)
            own = np.zeros_like(LA)
            for la0, lo0, sg, sgn in self.vort:
                own += sgn * self.vortpsi(la0, lo0, sg, P['storms']['turns'])
            for j, bs in enumerate(self.big):
                own += self.bigpsi(bs, j)
            psi = bg + own * self.pfade
            jet = 0
        else:
            for la0, lo0, sg, sgn in self.vort:
                pn += sgn * self.vortpsi(la0, lo0, sg, P['storms']['turns'])
            psi = (psi + pn) * self.pfade
        dpdn = np.zeros_like(psi); dpdn[1:-1] = (psi[:-2] - psi[2:]) / (2 * dn)
        de = self.cosv / self.VW
        dpde = (np.roll(psi, -1, 1) - np.roll(psi, 1, 1)) / (2 * de)
        ue = -dpdn; vn_ = dpde
        dx = (ue + jet) / self.cosv; dy = -2 * vn_
        return (dx + 1j * dy).astype(np.complex64)

    def color(self, x, y, r0=0, r1=None):
        P = self.P; T1, T2, T3, T4, T5 = self.T; W, H = self.W, self.H
        r1 = H if r1 is None else r1
        lat_all = ((0.5 - (np.arange(H, dtype=np.float32) + 0.5) / H) * np.pi).astype(np.float32)
        lon_all = ((np.arange(W, dtype=np.float32) + 0.5) / W * 2 * np.pi).astype(np.float32)
        LAf, LOf = np.meshgrid(lat_all[r0:r1], lon_all, indexing='ij')
        XF, YF, ZF = sph(LAf, LOf)
        mix = np.zeros(LAf.shape, np.float32)
        pol = []
        for j, bs in enumerate(self.big):
            sg = np.float32(bs['size'])
            r, th = self.big_polar(bs, LAf, LOf, j)
            mix = np.maximum(mix, np.exp(-(r / (STORM_MIXR * sg)) ** 2))
            pol.append((r, th))
        la0 = ((0.5 - y) * np.pi).astype(np.float32); lo0 = (x * 2 * np.pi).astype(np.float32)
        X0, Y0, Z0 = sph(la0, lo0)
        jit = tex = None
        if any(int(bs.get('arms', 0)) > 0 for bs in self.big):
            jit = 0.9 * fbm(T4, X0 * 9 + 2.7, Y0 * 9, Z0 * 9, o=3)
            tex = np.clip(0.75 + 1.6 * fbm(T3, X0 * 11 + 5.1, Y0 * 11, Z0 * 11, o=3), 0, 1)
        marks = []
        for j, (bs, (r, th)) in enumerate(zip(self.big, pol)):
            c, a = storm_marks(bs, r, th, P['seed'], j, jit)
            marks.append((c, None if a is None else a * tex))
        del pol, jit, tex
        ps = P['polar_smooth']
        fp = 1 - ss(np.float32(ps[0] * D), np.float32(ps[1] * D), np.abs(la0))
        b = la0 / D + np.float32(P['band_wobble']) * fbm(T2, X0 * 2.2, Y0 * 2.2, Z0 * 2.2, o=3)
        s1, s2 = P['stripes']
        b += fp * (s1 * fbm(T3, X0 * 1.6, Y0 * 1.6, Z0 * 40, o=3) + s2 * fbm(T4, X0 * 3.5, Y0 * 3.5, Z0 * 100, o=2))
        thr = fbm(T5, X0 * 1.2, Y0 * 1.2, Z0 * 170, o=2)
        thw = 0.5 + 0.5 * fbm(T1, X0 * 2.5, Y0 * 2.5, Z0 * 12, o=2)
        ZC = P['bands']
        bl = np.float32(P['band_blend']) * (1 + STORM_MIX * mix) if self.big else np.float32(P['band_blend'])
        col = np.empty(b.shape + (3,), np.float32)
        for c in range(3):
            v = np.full(b.shape, ZC[0][1][c], np.float32)
            prev = ZC[0][1][c]
            for e, cc in ZC[1:]:
                v += (cc[c] - prev) * ss(np.float32(e) - bl, np.float32(e) + bl, b); prev = cc[c]
            col[..., c] = v
        em = None
        if self.glow:
            em = np.zeros(b.shape + (3,), np.float32)
            nb = len(ZC)
            for i, gc in self.glow:
                lo_w = 1 if i == 0 else ss(np.float32(ZC[i][0]) - bl, np.float32(ZC[i][0]) + bl, b)
                hi_w = 0 if i == nb - 1 else ss(np.float32(ZC[i + 1][0]) - bl, np.float32(ZC[i + 1][0]) + bl, b)
                em += np.clip(lo_w - hi_w, 0, 1)[..., None] * np.array(gc, np.float32)
        g = sum(a * np.sin(b * f + p) for a, f, p in P['sub_band_waves'])
        g = g * fp
        col = col * (1 + np.float32(P['sub_bands']) * g[..., None]) + np.maximum(g, 0)[..., None] * np.array(P['sub_band_warm'], np.float32)
        del b, g, bl
        m = 1 + np.float32(P['mottle']) * fbm(T1, X0 * 5, Y0 * 5, Z0 * 9, o=3)
        col *= m[..., None]
        tl = np.exp(-(thr / np.float32(P['thread_width'])) ** 2) * np.clip(thw, 0, 1) * np.float32(P['threads']) * fp
        col = col * (1 - tl[..., None]) + np.array(P['thread_color'], np.float32) * tl[..., None]
        if em is not None:
            em *= (m * (1 - tl))[..., None]
        del thr, thw, tl, fp, m, mix
        del X0, Y0, Z0, la0, lo0
        st = P['storms']
        cream = np.array(st['core_color'], np.float32)
        for la, lo, sg, sgn in self.vort:
            px, py, pz = sph(la, lo)
            r = np.arccos(np.clip(XF * px + YF * py + ZF * pz, -1, 1)) / (2 * np.pi)
            w = np.float32(st['core']) * np.exp(-(r / (sg * np.float32(st['core_size']))) ** 2)
            col = col * (1 - w[..., None]) + cream * w[..., None]
            if em is not None:
                em *= (1 - w)[..., None]
        for bs, (w, aw) in zip(self.big, marks):
            if aw is not None:
                ac = bs.get('arm_color') or bs['core_color']
                col = col * (1 - aw[..., None]) + np.array(ac, np.float32) * aw[..., None]
                if em is not None:
                    em *= (1 - aw)[..., None]
            col = col * (1 - w[..., None]) + np.array(bs['core_color'], np.float32) * w[..., None]
            if em is not None:
                em *= (1 - w)[..., None]
        col = np.clip(col + 0.5, 0, 255).astype(np.uint8)
        if em is not None:
            em = np.clip(em + 0.5, 0, 255).astype(np.uint8)
        return col, em


def finish_blur(img, P, W):
    p = 16
    im = Image.fromarray(np.concatenate([img[:, -p:], img, img[:, :p]], 1), 'RGB').filter(ImageFilter.GaussianBlur(P['blur'] * W / 4096))
    return np.asarray(im)[:, p:-p]


BLOCK_PX = 4194304


def block_rows(W, H):
    return max(8, min(H, BLOCK_PX // W))


def out_dir(P, res):
    d = os.path.join(OUTROOT, P['name'] if res == 4096 else '%s_%d' % (P['name'], res))
    os.makedirs(d, exist_ok=True)
    return d


def work_dir(P, raw, res):
    h = hashlib.sha1((VERSION + json.dumps(raw, sort_keys=True) + str(res)).encode()).hexdigest()[:12]
    d = os.path.join(tempfile.gettempdir(), 'gasgiant_work', '%s_%d_%s' % (P['name'], res, h))
    os.makedirs(d, exist_ok=True)
    return d


def est(res, unit, px=None):
    f = (res / 4096.0) ** 2; fv = (min(res, 2048) / 2048.0) ** 2
    b = (px or 0) / 8388608.0
    return {'kf': 26 * fv + 2, 'step': 0.95 * b + 0.02, 'color': 40 * b + 1, 'finish': 6 * f + 2,
            'files': 6 * f + 3, 'preview': 4 + 6 * min(f, 1.0)}[unit]


def need(clock, res, unit, px=None):
    if clock.left() < est(res, unit, px) * 1.25:
        raise Unfinished()


def normal_channels(c, strength):
    H, W, _ = c.shape
    f = c[::-1].astype(np.float32).mean(-1)
    f = gblur(f, 1.2)
    gy = np.zeros_like(f); gy[1:-1] = (f[2:] - f[:-2]) * 0.5
    lat = (np.arange(H, dtype=np.float32) + 0.5) / H * np.pi - np.pi / 2
    gx = (np.roll(f, -1, 1) - np.roll(f, 1, 1)) * 0.5 / np.maximum(np.cos(lat), 0.15)[:, None]
    G = np.clip(128 - strength * gy, 1, 255); A = np.clip(128 - strength * gx, 1, 255)
    return (G + 0.5).astype(np.uint8), (A + 0.5).astype(np.uint8)


def write_normal(c, path, strength, flip=True):
    g8, a8 = normal_channels(c, strength)
    rgba = np.stack([g8, g8, g8, a8], -1)
    if not flip:
        rgba = np.ascontiguousarray(rgba[::-1])
    save_mips(Image.fromarray(rgba, 'RGBA'), path, 'DXT5')


EXPORT_FORMATS = {
    'color': ['DDS (DXT1, KSP)', 'PNG', 'JPG', 'TGA', 'BMP'],
    'normal': ['DDS (DXT5nm, KSP)', 'PNG'],
    'flow': ['truecolor (EVE)', 'PNG'],
    'emissive': ['DDS (DXT1, KSP)', 'PNG'],
    'preview': ['PNG', 'JPG'],
}
FMT_EXT = {'DDS (DXT1, KSP)': '.dds', 'DDS (DXT5nm, KSP)': '.dds', 'PNG': '.png', 'JPG': '.jpg', 'TGA': '.tga',
           'BMP': '.bmp', 'truecolor (EVE)': '.truecolor'}
PIL_FMT = {'PNG': 'PNG', 'JPG': 'JPEG', 'TGA': 'TGA', 'BMP': 'BMP'}


def export_target(folder, base, fmt):
    return os.path.join(folder, base + FMT_EXT[fmt])


def export_maps(src_dir, name, P, jobs, folder, size=None, flip=True, log=print):
    os.makedirs(folder, exist_ok=True)
    c = np.asarray(Image.open(os.path.join(src_dir, name + '_color.png')).convert('RGB'))
    if size and size != c.shape[1]:
        c = np.asarray(Image.fromarray(c).resize((size, size // 2), Image.LANCZOS))
    written = []
    for kind, base, fmt in jobs:
        path = export_target(folder, base, fmt)
        if kind == 'color':
            if fmt.startswith('DDS'):
                save_mips(Image.fromarray(np.ascontiguousarray(c[::-1] if flip else c), 'RGB'), path, 'DXT1')
            elif fmt == 'JPG':
                Image.fromarray(c).save(path, 'JPEG', quality=95)
            else:
                Image.fromarray(c).save(path, PIL_FMT[fmt])
        elif kind == 'normal':
            if fmt.startswith('DDS'):
                write_normal(c, path, float(P['normal_strength']), flip)
            else:
                g8, a8 = normal_channels(c, float(P['normal_strength']))
                g8 = g8[::-1].astype(np.float32); a8 = a8[::-1].astype(np.float32)
                x = (a8 - 128) / 127.0; y = (g8 - 128) / 127.0
                z = np.sqrt(np.clip(1 - x * x - y * y, 0, 1))
                rgb = np.stack([a8, g8, 128 + 127 * z], -1).clip(0, 255).astype(np.uint8)
                Image.fromarray(rgb).save(path, 'PNG')
        elif kind == 'flow':
            fp = os.path.join(src_dir, name + '_flow.truecolor')
            if not os.path.isfile(fp):
                log('no flow map in this build - skipped')
                continue
            fl = np.asarray(Image.open(fp).convert('RGB'))
            if size and size < fl.shape[1]:
                fl = np.asarray(Image.fromarray(fl).resize((size, size // 2), Image.BILINEAR))
            if fmt.startswith('truecolor'):
                save_truecolor(fl, path)
            else:
                Image.fromarray(fl).save(path, 'PNG')
        elif kind == 'emissive':
            ep = os.path.join(src_dir, name + '_emissive.png')
            if not os.path.isfile(ep):
                log('no emissive map in this build - skipped')
                continue
            e = np.asarray(Image.open(ep).convert('RGB'))
            if size and size != e.shape[1]:
                e = np.asarray(Image.fromarray(e).resize((size, size // 2), Image.LANCZOS))
            if fmt.startswith('DDS'):
                save_mips(Image.fromarray(np.ascontiguousarray(e[::-1] if flip else e), 'RGB'), path, 'DXT1')
            else:
                Image.fromarray(e).save(path, 'PNG')
        elif kind == 'preview':
            pp = os.path.join(src_dir, name + '_preview.png')
            if not os.path.isfile(pp):
                log('no preview in this build - skipped')
                continue
            im = Image.open(pp).convert('RGB')
            if fmt == 'JPG':
                im.save(path, 'JPEG', quality=92)
            else:
                im.save(path, 'PNG')
        written.append(path)
        log('exported ' + path)
    return written


def write_flow(KF, P, path):
    F = KF.mean(0)
    u = F.real.astype(np.float32); v = (-F.imag).astype(np.float32)
    if u.shape != (1024, 2048):
        u = np.asarray(Image.fromarray(u, 'F').resize((2048, 1024), Image.BILINEAR))
        v = np.asarray(Image.fromarray(v, 'F').resize((2048, 1024), Image.BILINEAR))
    fl = P['flow']
    u = gblur(u, fl['smooth']); v = gblur(v, fl['smooth'])
    R = np.clip(128 + u / max(u.std(), 1e-9) * fl['zonal_std'], 4, 251)
    G = np.clip(128 + v / max(v.std(), 1e-9) * fl['meridional_std'], 4, 251)
    B = np.full_like(R, 128)
    img = np.stack([R, G, B], -1).astype(np.uint8)
    b = io.BytesIO(); Image.fromarray(img, 'RGB').save(b, 'PNG')
    with open(path, 'wb') as f:
        f.write(b.getvalue())


def render_sphere(tex, S, tilt, vlat, vlon, emis=None):
    H, W, _ = tex.shape
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
    u = (xx + 0.5) / S * 2 - 1; v = 1 - (yy + 0.5) / S * 2
    r2 = u * u + v * v; m = r2 < 1
    z = np.sqrt(np.clip(1 - r2, 0, 1))
    t = np.radians(tilt); cu, su = np.cos(t), np.sin(t)
    u2 = u * cu - v * su; v2 = u * su + v * cu
    a = np.radians(vlat); cl, sl = np.cos(a), np.sin(a)
    y3 = v2 * cl + z * sl; z3 = -v2 * sl + z * cl
    lat = np.arcsin(np.clip(y3, -1, 1)); lon = np.arctan2(u2, z3) + np.radians(vlon)
    px = ((lon / (2 * np.pi)) % 1 * W).astype(np.int32) % W; py = np.clip(((0.5 - lat / np.pi) * H).astype(np.int32), 0, H - 1)
    c = tex[py, px]
    L = np.array([0.55, 0.25, 0.8]); L /= np.linalg.norm(L)
    nd = np.clip(u * L[0] + v * L[1] + z * L[2], 0, 1)
    c = c * (0.18 + 0.95 * nd ** 0.8)[..., None]
    rim = np.exp(-z * 6)[..., None] * np.array([0.35, 0.6, 0.95]) * 0.6
    c = c * (1 - 0.35 * np.exp(-z * 5))[..., None] + rim
    if emis is not None:
        c = c + emis[py, px] * (1 - 0.8 * nd)[..., None]
    o = np.zeros((S, S, 3), np.float32); o[m] = c[m]
    return Image.fromarray((np.clip(o, 0, 1) * 255).astype(np.uint8))


def write_preview(cimg, P, path, eimg=None):
    if cimg.shape[1] > 4096:
        cimg = np.asarray(Image.fromarray(cimg).resize((4096, 2048), Image.LANCZOS))
    tex = cimg.astype(np.float32) / 255
    em = None
    if eimg is not None:
        if eimg.shape[:2] != cimg.shape[:2]:
            eimg = np.asarray(Image.fromarray(eimg).resize((cimg.shape[1], cimg.shape[0]), Image.LANCZOS))
        em = eimg.astype(np.float32) / 255
    pv = P['preview']
    sheet = Image.new('RGB', (2400, 1200))
    sheet.paste(render_sphere(tex, 800, pv['tilt'], pv['view_lat'], pv['view_lon'], em), (0, 0))
    sheet.paste(Image.fromarray(cimg).resize((1600, 800), Image.LANCZOS), (800, 0))
    sheet.paste(render_sphere(tex, 400, 0, 75, 0, em), (0, 800))
    sheet.paste(render_sphere(tex, 400, 0, -75, 0, em), (400, 800))
    H, W, _ = cimg.shape
    s = W / 4096.0
    crop = Image.fromarray(cimg).crop((int(1300 * s), int(700 * s), int(2900 * s), int(1100 * s))).resize((1600, 400), Image.LANCZOS)
    sheet.paste(crop, (800, 800))
    sheet.save(path)


FLOWS = os.path.join(PRESETS, 'flows')
FLOWOUT = os.path.join(OUTROOT, 'flows')
FLOW_DEFAULTS = {
    'texture': '',
    'out': '',
    'seed': 1,
    'auto_edges': True,
    'edges': [],
    'sensitivity': 0.3,
    'min_gap': 4.0,
    'equator': 1,
    'jets': 1.0,
    'jet_variation': 0.25,
    'wobble': 0.08,
    'wobble_scale': 3.0,
    'smooth': 2.0,
    'calm': [65, 82],
    'strength': 100.0,
    'storms': [],
    'preview_motion': 8.0,
}


def body_of(path):
    b = os.path.basename(path)
    for suf in ('_flow.truecolor', '_color.dds', '_color.png', '.truecolor', '.dds', '.png'):
        if b.lower().endswith(suf.lower()):
            return b[:-len(suf)]
    return os.path.splitext(b)[0]


def texture_path(t):
    if not t: return ''
    return t if os.path.isabs(t) else os.path.join(texture_dir(), t)


def load_texture(path):
    a = np.asarray(Image.open(path).convert('RGB'))
    if path.lower().endswith('.dds'):
        a = a[::-1]
    return np.ascontiguousarray(a)


def list_textures():
    out = []
    td = texture_dir()
    if td and os.path.isdir(td):
        for f in sorted(os.listdir(td)):
            fl = f.lower()
            if ('_color' in fl) and (fl.endswith('.dds') or fl.endswith('.png')):
                out.append(f)
    return out


def detect_edges(rgb, sensitivity=0.3, min_gap=4.0, limit=80.0):
    small = np.asarray(Image.fromarray(rgb).resize((512, 256), Image.BOX)).astype(np.float32)
    prof = small.mean(1)
    k = np.exp(-0.5 * (np.arange(-4, 5) / 1.5) ** 2); k /= k.sum()
    pp = np.pad(prof, ((4, 4), (0, 0)), mode='edge')
    prof = sum(w * pp[i:i + 256] for i, w in enumerate(k))
    g = np.zeros(256)
    g[1:-1] = np.sqrt(((prof[2:] - prof[:-2]) ** 2).sum(-1))
    lat = 90 - (np.arange(256) + 0.5) / 256 * 180
    if g.max() <= 0: return []
    thr = sensitivity * g.max()
    cand = [i for i in range(1, 255) if g[i] >= g[i - 1] and g[i] >= g[i + 1] and g[i] > thr and abs(lat[i]) < limit]
    cand.sort(key=lambda i: -g[i])
    keep = []
    for i in cand:
        if all(abs(lat[i] - lat[j]) >= min_gap for j in keep):
            keep.append(i)
    return sorted([round(float(lat[i]), 1) for i in keep], reverse=True)


def flow_field(F, W=2048, H=1024, rgb=None):
    LA, LO = grid(W, H)
    d = LA / D
    if F['auto_edges'] and rgb is not None:
        edges = detect_edges(rgb, F['sensitivity'], F['min_gap'], F['calm'][1])
    else:
        edges = [e['lat'] if isinstance(e, dict) else e for e in F['edges']]
    bounds = sorted(set([-90.0] + [float(e) for e in edges if -90 < e < 90] + [90.0]))
    keq = max(i for i in range(len(bounds) - 1) if bounds[i] <= 0)
    u = np.zeros_like(LA)
    for k, (lo, hi) in enumerate(zip(bounds[:-1], bounds[1:])):
        sign = F['equator'] * (-1) ** abs(k - keq)
        inz = (d >= lo) & (d < hi)
        u[inz] = sign * np.sin(np.pi * (d[inz] - lo) / (hi - lo))
    u *= np.float32(F['jets'])
    s = int(F['seed'])
    T1, T2, T3 = mk(s * 10 + 7), mk(s * 10 + 8), mk(s * 10 + 9)
    X, Y, Z = sph(LA, LO)
    u *= 1 + np.float32(F['jet_variation']) * fbm(T1, X * 2.5, Y * 2.5, Z * 2.5, o=3)
    ws = np.float32(F['wobble_scale'])
    v = np.float32(F['wobble']) * fbm(T2, X * ws, Y * ws, Z * ws * 1.5, o=3)
    u += np.float32(F['wobble']) * 0.5 * fbm(T3, X * ws, Y * ws, Z * ws * 1.5, o=3)
    for st in F['storms']:
        la0 = np.radians(st['lat'])
        dn = d - st['lat']
        dl = ((LO / D - st['lon'] + 180) % 360 - 180) * np.cos(la0)
        asp = max(st.get('aspect', 1.0), 0.2)
        de = dl / asp
        R = max(st.get('radius', 5.0), 0.2)
        r = np.sqrt(de ** 2 + dn ** 2) / R
        prof = r * np.exp(0.5 * (1 - r ** 2))
        nrm = np.sqrt(de ** 2 + dn ** 2) + 1e-6
        k = np.float32(st.get('strength', 1.0) * st.get('spin', 1))
        u += k * prof * (-dn / nrm) * asp
        v += k * prof * (de / nrm)
    c0, c1 = F['calm']
    fade = 1 - ss(np.float32(c0), np.float32(c1), np.abs(d))
    u *= fade; v *= fade
    sm = float(F['smooth']) * W / 2048.0
    if sm > 0.05:
        u = gblur(u, sm); v = gblur(v, sm)
    return u.astype(np.float32), v.astype(np.float32), edges


def encode_flow(u, v, strength):
    R = np.clip(128 + strength * u, 2, 253)
    G = np.clip(128 + strength * v, 2, 253)
    return np.stack([R, G, np.full_like(R, 128)], -1).astype(np.uint8)


def save_truecolor(img, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    b = io.BytesIO(); Image.fromarray(img, 'RGB').save(b, 'PNG')
    with open(path, 'wb') as f:
        f.write(b.getvalue())


def samp_rgb(tex, x, y):
    h, w, _ = tex.shape
    x0 = np.floor(x).astype(np.int32); y0 = np.clip(np.floor(y).astype(np.int32), 0, h - 2)
    tx = (x - np.floor(x))[..., None]; ty = np.clip(y - y0, 0, 1)[..., None]
    x0 %= w; x1 = (x0 + 1) % w; y1 = y0 + 1
    a = tex[y0, x0] * (1 - tx) + tex[y0, x1] * tx
    b = tex[y1, x0] * (1 - tx) + tex[y1, x1] * tx
    return a * (1 - ty) + b * ty


def flow_frames(rgb, flowimg, motion_deg=8.0, n=24, width=1024):
    h = width // 2
    tex = np.asarray(Image.fromarray(rgb).resize((width, h), Image.BOX)).astype(np.float32)
    fl = np.asarray(Image.fromarray(flowimg).resize((width, h), Image.BILINEAR)).astype(np.float32)
    fu = (fl[..., 0] - 128) / 127.0; fv = (fl[..., 1] - 128) / 127.0
    k = motion_deg / 360.0 * width
    yy, xx = np.mgrid[0:h, 0:width].astype(np.float32)
    frames = []
    for i in range(n):
        p0 = i / n; p1 = (p0 + 0.5) % 1.0
        c0 = samp_rgb(tex, xx - fu * k * p0, yy + fv * k * p0)
        c1 = samp_rgb(tex, xx - fu * k * p1, yy + fv * k * p1)
        wgt = abs(0.5 - p0) / 0.5
        frames.append(Image.fromarray(np.clip(c0 * (1 - wgt) + c1 * wgt, 0, 255).astype(np.uint8)))
    return frames


def flow_arrows(rgb, flowimg, width=1024, step=32):
    h = width // 2
    im = Image.fromarray(rgb).resize((width, h), Image.BOX).convert('RGB')
    fl = np.asarray(Image.fromarray(flowimg).resize((width, h), Image.BILINEAR)).astype(np.float32)
    dr = ImageDraw.Draw(im)
    for y in range(step // 2, h, step):
        for x in range(step // 2, width, step):
            fu = (fl[y, x, 0] - 128) / 127.0; fv = (fl[y, x, 1] - 128) / 127.0
            m = np.hypot(fu, fv)
            if m < 0.03: continue
            L = step * 0.9 * min(1.0, m)
            ex, ey = x + fu / m * L, y - fv / m * L
            col = (255, 255, 255) if fu >= 0 else (255, 200, 120)
            dr.line([(x, y), (ex, ey)], fill=col, width=2)
            a = np.arctan2(ey - y, ex - x)
            for da in (2.6, -2.6):
                dr.line([(ex, ey), (ex + 6 * np.cos(a + da), ey + 6 * np.sin(a + da))], fill=col, width=2)
    return im


def load_flow_settings(p):
    if not os.path.isfile(p):
        q = os.path.join(FLOWS, p if p.endswith('.json') else p + '.json')
        if not os.path.isfile(q): sys.exit('flow settings not found: ' + p)
        p = q
    with open(p) as f:
        raw = json.load(f)
    return merge(FLOW_DEFAULTS, raw)


def build_flow(F, W=2048):
    tp = texture_path(F['texture'])
    rgb = load_texture(tp) if tp and os.path.isfile(tp) else None
    u, v, edges = flow_field(F, W, W // 2, rgb)
    return rgb, encode_flow(u, v, float(F['strength'])), edges


def install_file(src, rel, body):
    dst = os.path.join(texture_dir(), rel)
    stamp = time.strftime('%Y%m%d_%H%M%S')
    bdir = backup_dir(body, stamp)
    if os.path.isfile(dst):
        os.makedirs(bdir, exist_ok=True)
        shutil.copy2(dst, os.path.join(bdir, os.path.basename(dst)))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)
    return dst, (bdir if os.path.isdir(bdir) else None)


def eve_flow_info(rel):
    key = rel.replace('\\', '/')
    if key.lower().endswith('.truecolor'): key = key[:-10]
    td = texture_dir()
    cfgdir = mod_root(td) if td else ''
    hits = []
    if not cfgdir or not os.path.isdir(cfgdir):
        return hits
    for dp, dn, fn in os.walk(cfgdir):
        for f in fn:
            if not f.lower().endswith('.cfg'): continue
            p = os.path.join(dp, f)
            try:
                txt = open(p, errors='ignore').read()
            except Exception:
                continue
            i = txt.find(key)
            if i < 0: continue
            j = txt.rfind('_FlowMap', 0, i)
            blk = txt[j:i] if j >= 0 else ''
            sp = re_find(r'speed\s*=\s*([-0-9.eE]+)', blk)
            dp_ = re_find(r'displacement\s*=\s*([-0-9.eE]+)', blk)
            hits.append((nice(p), sp, dp_))
    return hits


def re_find(pat, s):
    import re
    m = re.search(pat, s)
    return m.group(1) if m else None


def cmd_flow(a):
    F = load_flow_settings(a.settings)
    if not F['out']:
        F['out'] = 'GiantFlow/%s_flow.truecolor' % body_of(F['texture'])
    body = body_of(F['out'])
    rgb, img, edges = build_flow(F)
    os.makedirs(FLOWOUT, exist_ok=True)
    outp = os.path.join(FLOWOUT, body + '_flow.truecolor')
    save_truecolor(img, outp)
    print('edges', edges)
    print('saved', os.path.relpath(outp, TOOL))
    if rgb is not None:
        flow_arrows(rgb, img).save(os.path.join(FLOWOUT, body + '_flow_arrows.png'))
        fr = [f.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG) for f in flow_frames(rgb, img, float(F['preview_motion']), 24, 768)]
        fr[0].save(os.path.join(FLOWOUT, body + '_flow_preview.gif'), save_all=True, append_images=fr[1:], duration=80, loop=0)
        print('preview', os.path.relpath(os.path.join(FLOWOUT, body + '_flow_preview.gif'), TOOL))
    for p, sp, dp_ in eve_flow_info(F['out']):
        print('used by', p, 'speed', sp, 'displacement', dp_)
    if a.install:
        dst, b = install_file(outp, F['out'], body)
        print('installed ->', nice(dst))
        if b: print('backup ->', nice(b))


def cmd_make(a):
    P, raw = load_preset(a.preset)
    res = a.res
    clock = Clock(a.budget)
    wd = work_dir(P, raw, res)
    od = out_dir(P, res)
    name = P['name']
    st_path = os.path.join(wd, 'state.json')
    st = json.load(open(st_path)) if os.path.isfile(st_path) and not a.fresh else {'stage': 'kf'}
    if a.fresh:
        for f in os.listdir(wd): os.remove(os.path.join(wd, f))

    def save_state():
        json.dump(st, open(st_path, 'w'))

    K = int(P['keyframes']); STEPS = int(round(int(P['steps']) * max(1.0, min(3.0, res / 4096.0))))
    W = res; H = W // 2
    try:
        clock.log(name, res, 'stage', st['stage'], 'work', wd)
        fld = None
        if st['stage'] == 'trace' and 'b' not in st:
            st = {'stage': 'kf'}
        BR = block_rows(W, H)
        NB = (H + BR - 1) // BR
        xp = os.path.join(wd, 'x.npy'); yp = os.path.join(wd, 'y.npy'); ip = os.path.join(wd, 'img.npy'); ep = os.path.join(wd, 'emis.npy')
        glows = bool(glow_list(P))
        emis_png = os.path.join(od, name + '_emissive.png'); emis_dds = os.path.join(od, name + '_emissive.dds')
        if st['stage'] == 'kf':
            for k in range(K):
                kp = os.path.join(wd, 'kf%d.npy' % k)
                if os.path.isfile(kp): continue
                need(clock, res, 'kf')
                if fld is None: fld = Field(P, W)
                np.save(kp, fld.keyframe(k)); clock.log('keyframe', k + 1, 'of', K)
            xm = np.lib.format.open_memmap(xp, mode='w+', dtype=np.float32, shape=(H, W))
            ym = np.lib.format.open_memmap(yp, mode='w+', dtype=np.float32, shape=(H, W))
            lat_all = ((0.5 - (np.arange(H, dtype=np.float32) + 0.5) / H) * np.pi).astype(np.float32)
            lon_all = ((np.arange(W, dtype=np.float32) + 0.5) / W * 2 * np.pi).astype(np.float32)
            for bi in range(NB):
                r0, r1 = bi * BR, min(H, (bi + 1) * BR)
                LAf, LOf = np.meshgrid(lat_all[r0:r1], lon_all, indexing='ij')
                xm[r0:r1] = (LOf / (2 * np.pi)).astype(np.float32)
                ym[r0:r1] = (0.5 - LAf / np.pi).astype(np.float32)
            xm.flush(); ym.flush(); del xm, ym
            st = {'stage': 'trace', 'b': 0, 'n': STEPS}; save_state()
        if st['stage'] == 'trace':
            KF = np.stack([np.load(os.path.join(wd, 'kf%d.npy' % k)) for k in range(K)])
            xm = np.load(xp, mmap_mode='r+'); ym = np.load(yp, mmap_mode='r+')
            dt = np.float32(1.0 / STEPS)
            rk2 = bool(P['big_storms'])
            bi, n = st.get('b', 0), st['n']
            last = -1
            while bi < NB:
                r0, r1 = bi * BR, min(H, (bi + 1) * BR)
                x = np.array(xm[r0:r1]); y = np.array(ym[r0:r1])
                try:
                    while n > 0:
                        need(clock, res, 'step', (r1 - r0) * W * (2 if rk2 else 1))
                        x, y = trace_step(KF, K, STEPS, n, x, y, dt, rk2)
                        n -= 1
                        pct = int(100 * (bi * STEPS + STEPS - n) / (NB * STEPS))
                        if pct != last and pct % 2 == 0:
                            clock.log('trace %d%%' % pct); last = pct
                finally:
                    xm[r0:r1] = x; ym[r0:r1] = y
                    xm.flush(); ym.flush()
                    st = {'stage': 'trace', 'b': bi, 'n': n}; save_state()
                bi += 1; n = STEPS
                st = {'stage': 'trace', 'b': bi, 'n': n} if bi < NB else {'stage': 'color', 'b': 0}
                save_state()
            del KF, xm, ym
        if st['stage'] == 'color':
            xm = np.load(xp, mmap_mode='r'); ym = np.load(yp, mmap_mode='r')
            fresh = st.get('b', 0) == 0 or not os.path.isfile(ip) or (glows and not os.path.isfile(ep))
            if fresh:
                st = {'stage': 'color', 'b': 0}
                im_m = np.lib.format.open_memmap(ip, mode='w+', dtype=np.uint8, shape=(H, W, 3))
                em_m = np.lib.format.open_memmap(ep, mode='w+', dtype=np.uint8, shape=(H, W, 3)) if glows else None
            else:
                im_m = np.load(ip, mmap_mode='r+')
                em_m = np.load(ep, mmap_mode='r+') if glows else None
            bi = st.get('b', 0)
            while bi < NB:
                r0, r1 = bi * BR, min(H, (bi + 1) * BR)
                need(clock, res, 'color', (r1 - r0) * W)
                if fld is None: fld = Field(P, W)
                cb, eb = fld.color(np.array(xm[r0:r1]), np.array(ym[r0:r1]), r0, r1)
                im_m[r0:r1] = cb
                im_m.flush()
                if em_m is not None:
                    em_m[r0:r1] = eb
                    em_m.flush()
                del cb, eb
                bi += 1
                st = {'stage': 'color', 'b': bi}; save_state()
                clock.log('color %d%%' % int(100 * bi / NB))
            del im_m, em_m, xm, ym
            st = {'stage': 'finish'}; save_state()
        if st['stage'] == 'finish':
            need(clock, res, 'finish')
            img = finish_blur(np.load(ip), P, W)
            Image.fromarray(img, 'RGB').save(os.path.join(od, name + '_color.png'))
            del img
            if glows:
                img = finish_blur(np.load(ep), P, W)
                Image.fromarray(img, 'RGB').save(emis_png)
                del img
            st = {'stage': 'files'}; save_state(); clock.log('color map done')
        if st['stage'] == 'files':
            need(clock, res, 'files')
            c = np.asarray(Image.open(os.path.join(od, name + '_color.png')).convert('RGB'))
            save_mips(Image.fromarray(np.ascontiguousarray(c[::-1]), 'RGB'), os.path.join(od, name + '_color.dds'), 'DXT1')
            write_normal(c, os.path.join(od, name + '_normal.dds'), float(P['normal_strength']))
            fl_path = os.path.join(od, name + '_flow.truecolor')
            if P['files'].get('flow'):
                KF = np.stack([np.load(os.path.join(wd, 'kf%d.npy' % k)) for k in range(K)])
                write_flow(KF, P, fl_path); del KF
            elif os.path.isfile(fl_path):
                os.remove(fl_path)
            if glows:
                e = np.asarray(Image.open(emis_png).convert('RGB'))
                save_mips(Image.fromarray(np.ascontiguousarray(e[::-1]), 'RGB'), emis_dds, 'DXT1')
                del e
            else:
                for f in (emis_png, emis_dds):
                    if os.path.isfile(f):
                        os.remove(f)
            st = {'stage': 'preview'}; save_state(); clock.log('dds files done')
        if st['stage'] == 'preview':
            need(clock, res, 'preview')
            c = np.asarray(Image.open(os.path.join(od, name + '_color.png')).convert('RGB'))
            e = np.asarray(Image.open(emis_png).convert('RGB')) if glows and os.path.isfile(emis_png) else None
            write_preview(c, P, os.path.join(od, name + '_preview.png'), e)
            st = {'stage': 'done'}; save_state()
        if st['stage'] == 'done':
            with open(os.path.join(od, name + '_preset.json'), 'w') as f:
                json.dump(raw, f, indent=1)
            shutil.rmtree(wd, ignore_errors=True)
            clock.log('DONE', od)
            for f in sorted(os.listdir(od)): print('  ', f)
            return 0
    except Unfinished:
        clock.log('UNFINISHED at stage', st['stage'], '- run the same command again to continue')
        return 3


def cmd_export(a):
    P, raw = load_preset(a.preset)
    name = P['name']
    src = os.path.join(OUTROOT, name if a.res == 4096 else '%s_%d' % (name, a.res))
    if not os.path.isfile(os.path.join(src, name + '_color.png')):
        sys.exit('nothing built at %d yet - run make first' % a.res)
    pick = {'color': {'dds': 'DDS (DXT1, KSP)', 'png': 'PNG', 'jpg': 'JPG', 'tga': 'TGA', 'bmp': 'BMP'},
            'normal': {'dds': 'DDS (DXT5nm, KSP)', 'png': 'PNG'},
            'flow': {'truecolor': 'truecolor (EVE)', 'png': 'PNG'},
            'emissive': {'dds': 'DDS (DXT1, KSP)', 'png': 'PNG'},
            'preview': {'png': 'PNG', 'jpg': 'JPG'}}
    jobs = []
    for kind in ('color', 'normal', 'flow', 'emissive', 'preview'):
        f = getattr(a, kind)
        if f and f != 'none':
            jobs.append((kind, '%s_%s' % (name, kind), pick[kind][f]))
    export_maps(src, name, P, jobs, a.to, a.size or None, not a.no_flip)


def cmd_install(a):
    P, raw = load_preset(a.preset)
    od = out_dir(P, a.res)
    name = P['name']
    src = {'color': name + '_color.dds', 'normal': name + '_normal.dds', 'flow': name + '_flow.truecolor', 'emissive': name + '_emissive.dds'}
    what = [w for w in (a.only.split(',') if a.only else ['color', 'normal', 'flow', 'emissive']) if P['files'].get(w)]
    if 'emissive' in what and not glow_list(P):
        what.remove('emissive')
    stamp = time.strftime('%Y%m%d_%H%M%S')
    bdir = backup_dir(name, stamp)
    if not texture_dir():
        sys.exit('no game texture folder set - use export instead')
    for w in what:
        s = os.path.join(od, src[w])
        if not os.path.isfile(s): sys.exit('missing %s - run make first' % s)
    for w in what:
        dst = os.path.join(texture_dir(), P['files'][w])
        if os.path.isfile(dst):
            os.makedirs(bdir, exist_ok=True)
            shutil.copy2(dst, os.path.join(bdir, os.path.basename(dst)))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(os.path.join(od, src[w]), dst)
        print('installed', w, '->', nice(dst))
    if os.path.isdir(bdir): print('backup ->', nice(bdir))


def sample_bands(im, x1, y1, x2, y2, n=17, lat0=70.0, lat1=-70.0, gain=1.12, box=4):
    H, W, _ = im.shape
    pts = []
    for i in range(n):
        t = i / (n - 1)
        x = int(round(x1 + (x2 - x1) * t)); y = int(round(y1 + (y2 - y1) * t))
        blk = im[max(0, y - box):min(H, y + box + 1), max(0, x - box):min(W, x + box + 1)].reshape(-1, 3)
        c = np.clip(blk.mean(0) * gain, 0, 255)
        pts.append((lat0 + (lat1 - lat0) * t, [int(round(v)) for v in c]))
    pts.sort(key=lambda p: p[0])
    bands = [[-90, pts[0][1]]]
    for (l0, _), (l1, c1) in zip(pts[:-1], pts[1:]):
        bands.append([round((l0 + l1) / 2, 1), c1])
    return bands


def auto_edges(bands, limit=60.0, threshold=20.0, width=0.0045, curl=0.4):
    bs = sorted(bands, key=lambda b: b[0])
    out = []
    for (l0, c0), (l1, c1) in zip(bs[:-1], bs[1:]):
        if abs(l1) >= limit: continue
        if np.sqrt(sum((a - b) ** 2 for a, b in zip(c0, c1))) < threshold: continue
        out.append(l1)
    edges = []
    for i, l in enumerate(sorted(out, reverse=True)):
        edges.append({'lat': l, 'spin': 1 if i % 2 == 0 else -1, 'width': width, 'curl': curl})
    return edges


def cmd_sample(a):
    im = np.asarray(Image.open(a.image).convert('RGB')).astype(np.float32)
    print(json.dumps(sample_bands(im, a.x1, a.y1, a.x2, a.y2, a.n, a.lat[0], a.lat[1], a.gain, a.box)))


def cmd_new(a):
    tpl = a.template
    if not os.path.isfile(os.path.join(PRESETS, tpl + '.json')):
        avail = sorted(f[:-5] for f in os.listdir(PRESETS) if f.endswith('.json')) if os.path.isdir(PRESETS) else []
        if not avail: sys.exit('no presets to copy from')
        tpl = avail[0]
    src = preset_path(tpl)
    raw = json.load(open(src))
    raw['name'] = a.name
    raw['seed'] = int(hashlib.sha1(a.name.encode()).hexdigest()[:6], 16) % 100000
    raw['files'] = {'color': a.name + '_color.dds', 'normal': a.name + '_normal.dds', 'flow': 'GiantFlow/' + a.name + '_flow.truecolor'}
    if raw.get('emission'):
        raw['files']['emissive'] = a.name + '_emissive.dds'
    dst = os.path.join(PRESETS, a.name + '.json')
    if os.path.exists(dst) and not a.force: sys.exit('exists: ' + dst)
    json.dump(raw, open(dst, 'w'), indent=1)
    print('created', os.path.relpath(dst, TOOL))


def main():
    ap = argparse.ArgumentParser(prog='gasgiant', description='%s %s' % (APP_NAME, APP_VERSION))
    sp = ap.add_subparsers(dest='cmd', required=True)
    m = sp.add_parser('make'); m.add_argument('preset'); m.add_argument('--res', type=int, default=4096); m.add_argument('--budget', type=float, default=None); m.add_argument('--fresh', action='store_true')
    i = sp.add_parser('install'); i.add_argument('preset'); i.add_argument('--res', type=int, default=4096); i.add_argument('--only', default=None)
    s = sp.add_parser('sample'); s.add_argument('image'); s.add_argument('x1', type=float); s.add_argument('y1', type=float); s.add_argument('x2', type=float); s.add_argument('y2', type=float)
    s.add_argument('--n', type=int, default=17); s.add_argument('--lat', type=float, nargs=2, default=[70, -70]); s.add_argument('--gain', type=float, default=1.12); s.add_argument('--box', type=int, default=4)
    n = sp.add_parser('new'); n.add_argument('name'); n.add_argument('--template', default='Pilgrim46'); n.add_argument('--force', action='store_true')
    f = sp.add_parser('flow'); f.add_argument('settings'); f.add_argument('--install', action='store_true')
    e = sp.add_parser('export'); e.add_argument('preset'); e.add_argument('--to', required=True); e.add_argument('--res', type=int, default=4096)
    e.add_argument('--color', default='dds', choices=['dds', 'png', 'jpg', 'tga', 'bmp', 'none'])
    e.add_argument('--normal', default='dds', choices=['dds', 'png', 'none'])
    e.add_argument('--flow', default='truecolor', choices=['truecolor', 'png', 'none'])
    e.add_argument('--emissive', default='dds', choices=['dds', 'png', 'none'])
    e.add_argument('--preview', default='none', choices=['png', 'jpg', 'none'])
    e.add_argument('--size', type=int, default=0); e.add_argument('--no-flip', action='store_true')
    a = ap.parse_args()
    r = {'make': cmd_make, 'install': cmd_install, 'sample': cmd_sample, 'new': cmd_new, 'flow': cmd_flow, 'export': cmd_export}[a.cmd](a)
    sys.exit(r or 0)


if __name__ == '__main__':
    main()
