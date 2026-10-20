import sys, os, io, json, copy, time, shutil, struct, hashlib, tempfile, argparse
import numpy as np
from PIL import Image, ImageFilter, ImageDraw
Image.MAX_IMAGE_PIXELS = None

APP_NAME = 'Gas Giant Studio'
APP_VERSION = '1.1.12'
VERSION = '5'
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
    'band_shapes': [],
    'poles': {'north': {'type': 'none'}, 'south': {'type': 'none'}},
    'heat_glow': {'strength': 0.0},
    'storm_chains': [],
    'rings': {'enabled': False},
    'atmosphere': {'enabled': False},
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
ARM_COVER = np.float32(1.3)
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


def arm_cover(a):
    return np.clip(a * ARM_COVER, 0, 1)


POLE = {'type': 'none', 'lat': 76.0, 'sides': 6, 'roundness': 0.3, 'rotation': 0.0, 'jet': 1.0, 'wobble': 0.15,
        'band': 0.6, 'band_width': 4.0, 'band_color': None, 'turns': 0.8, 'spin': 1,
        'ring_lat': 80.0, 'count': 8, 'size': 0.011, 'centre': 1, 'cap_lat': 66.0,
        'cap_color': None, 'texture': 0.8, 'texture_color': None, 'eye': 0.45, 'eye_color': None, 'eye_size': 0.45}


def pole_entry(p, south=False):
    e = copy.deepcopy(POLE)
    if south:
        e['count'] = 5
    e.update({k: copy.deepcopy(v) for k, v in (p if isinstance(p, dict) else {}).items() if k in POLE})
    e['type'] = str(e['type']).lower()
    if e['type'] not in ('none', 'hexagon', 'cyclones'):
        e['type'] = 'none'
    return e


def pole_colours(P, key, e):
    bands = P['bands']
    base = np.array((bands[-1] if key == 'north' else bands[0])[1], np.float32)
    cap = np.array(e['cap_color'], np.float32) if e.get('cap_color') else base
    tex = np.array(e['texture_color'], np.float32) if e.get('texture_color') else np.clip(cap * 1.15 + 28, 0, 255)
    band = np.array(e['band_color'], np.float32) if e.get('band_color') else np.clip(cap * 1.15 + 24, 0, 255)
    eye = np.array(e['eye_color'], np.float32) if e.get('eye_color') else cap * 0.55
    return cap, tex, band, eye


def hex_q(e, c, az):
    n = max(3, int(e['sides']))
    a = np.float32(max(90.0 - float(e['lat']), 1.0) * D)
    seg = np.float32(2 * np.pi / n)
    d = ((az - np.float32(float(e['rotation']) * D)) % seg) - seg / 2
    rp = a / np.cos(d) ** np.float32(1 - min(max(float(e['roundness']), 0.0), 1.0))
    return c / rp


def pole_cyclones(sgn, e):
    out = []
    sg = np.float32(max(float(e['size']), 0.002))
    if int(e['centre']):
        out.append((np.array([0, 0, sgn], np.float32), sg * np.float32(1.2)))
    n = int(e['count'])
    for k in range(n):
        lat = sgn * float(e['ring_lat']) * D
        lon = float(e['rotation']) * D + 2 * np.pi * k / max(n, 1)
        out.append((np.array(sph(np.float32(lat), np.float32(lon)), np.float32), sg))
    return out


def pole_preview(P, LA, LO, col):
    for sgn, key in ((1, 'north'), (-1, 'south')):
        e = pole_entry(P.get('poles', {}).get(key), south=(sgn < 0))
        if e['type'] == 'none':
            continue
        cap, tex, band, eye = pole_colours(P, key, e)
        capcol = cap + (tex - cap) * np.float32(e['texture']) * np.float32(0.5)
        c = np.float32(np.pi / 2) - sgn * LA
        es = np.float32(max(float(e['eye_size']), 0.02))
        if e['type'] == 'hexagon':
            a = np.float32(max(90.0 - float(e['lat']), 1.0) * D)
            q = hex_q(e, c, LO)
            bw = np.float32(max(float(e['band_width']), 0.3) * D) / a
            sq = np.float32(0.35) * bw
            inner = ss(1 - bw - sq, 1 - bw + sq, q)
            wi = 1 - inner
            wb = np.float32(e['band']) * (inner - ss(1 - sq, 1 + sq, q))
            col = col * (1 - wi - wb)[..., None] + capcol * wi[..., None] + band * wb[..., None]
            eyes = [np.exp(-(c / (es * np.float32(0.55) * a)) ** 2)]
        else:
            capc = np.float32(max(90.0 - float(e['cap_lat']), 2.0) * D)
            sd = np.float32(3.0 * D)
            wi = 1 - ss(capc - sd, capc + sd, c)
            col = col * (1 - wi)[..., None] + capcol * wi[..., None]
            X, Y, Z = sph(LA, LO)
            eyes = []
            for v, sg in pole_cyclones(sgn, e):
                r = np.arccos(np.clip(X * v[0] + Y * v[1] + Z * v[2], -1, 1)) / np.float32(2 * np.pi)
                ring = np.float32(0.5 * min(float(e['texture']), 1.0)) * np.exp(-((r - sg * np.float32(0.8)) / (sg * np.float32(0.3))) ** 2)
                col = col * (1 - ring)[..., None] + tex * ring[..., None]
                eyes.append(np.exp(-(r / (es * sg)) ** 2))
        for w in eyes:
            w = np.float32(e['eye']) * w
            col = col * (1 - w)[..., None] + eye * w[..., None]
    return col


HEAT = {'strength': 0.0, 'dim_color': [130, 14, 4], 'bright_color': [255, 120, 28], 'dark': 0.7, 'poles': 0.4, 'patches': 0.3}
NIGHT_LIGHT = (0.7, 0.2, 0.3)


def heat_entry(h):
    e = copy.deepcopy(HEAT)
    e.update({k: copy.deepcopy(v) for k, v in (h if isinstance(h, dict) else {}).items() if k in HEAT})
    for k in ('dim_color', 'bright_color'):
        if not e[k]:
            e[k] = list(HEAT[k])
    return e


def has_heat(P):
    try:
        return float((P.get('heat_glow') or {}).get('strength', 0) or 0) > 0
    except (TypeError, ValueError):
        return False


def heat_emission(P, col, LA, patch=None):
    h = heat_entry(P.get('heat_glow'))
    s = float(h['strength'])
    if s <= 0:
        return None
    w = np.array([0.299, 0.587, 0.114], np.float32)
    Ls = [float(np.dot(w, np.array(b[1], np.float32))) for b in P['bands']]
    lo, hi = min(Ls), max(Ls)
    if hi - lo < 8:
        t = np.full(col.shape[:2], 0.5, np.float32)
    else:
        t = np.clip((np.float32(hi) - col @ w) / np.float32(hi - lo), 0, 1)
    d = np.float32(min(max(float(h['dark']), 0.0), 1.0))
    k = (1 - d) + d * t
    k = k * (1 - np.float32(min(max(float(h['poles']), 0.0), 1.0)) * np.sin(LA) ** 2)
    if patch is not None:
        k = k * patch
    k = np.clip(k, 0, 1).astype(np.float32)
    dim = np.array(h['dim_color'], np.float32); bri = np.array(h['bright_color'], np.float32)
    k2 = k * k
    return (dim + (bri - dim) * k2[..., None]) * (k2 * np.float32(s))[..., None]


CHAIN = {'lat': -40.0, 'lat_end': None, 'lon': 0.0, 'length': 360.0, 'count': 10, 'size': 0.012, 'aspect': 1.3,
         'turns': 1.0, 'spin': 1, 'ragged': 0.15, 'core': 0.55, 'core_size': 0.45, 'core_color': [244, 236, 226], 'jitter': 0.4}


def chain_entry(c):
    e = copy.deepcopy(CHAIN)
    e.update({k: copy.deepcopy(v) for k, v in (c if isinstance(c, dict) else {}).items() if k in CHAIN})
    if e['lat_end'] is None:
        e['lat_end'] = e['lat']
    e['count'] = max(1, int(e['count']))
    e['length'] = min(max(float(e['length']), 0.0), 360.0)
    return e


def chain_points(c):
    c = chain_entry(c)
    n = c['count']
    full = c['length'] >= 359.99
    out = []
    for i in range(n):
        t = i / float(n) if full else (i / float(n - 1) if n > 1 else 0.0)
        lon = c['lon'] + (360.0 if full else c['length']) * t
        lat = c['lat'] + (c['lat_end'] - c['lat']) * (0.0 if full else t)
        out.append((lat, lon % 360.0))
    return out


def expand_chains(P):
    out = []
    seed = int(P.get('seed', 1))
    for ci, c in enumerate(P.get('storm_chains', [])):
        c = chain_entry(c)
        rng = np.random.default_rng(seed * 31 + 1000 * ci + 7)
        pts = chain_points(c)
        n = len(pts)
        sp = (360.0 / n) if c['length'] >= 359.99 else (c['length'] / max(n - 1, 1))
        j = float(c['jitter'])
        for lat, lon in pts:
            dlon, dlat, ds = rng.uniform(-1, 1, 3)
            b = {k: copy.deepcopy(c[k]) for k in ('aspect', 'turns', 'spin', 'ragged', 'core', 'core_size', 'core_color')}
            b.update({'lat': max(-85.0, min(85.0, lat + 1.5 * j * dlat)), 'lon': (lon + 0.3 * j * sp * dlon) % 360.0,
                      'size': float(c['size']) * (1 + 0.3 * j * ds), 'arms': 0})
            out.append(big_storm(b))
    return out


def all_big(P):
    return [big_storm(b) for b in P.get('big_storms', [])] + expand_chains(P)


RING = {'enabled': False, 'inner': 1.35, 'outer': 2.3, 'angle': 0.0, 'opacity': 0.85, 'zones': 4, 'ringlets': 0.6,
        'detail': 1.0, 'edge': 0.3, 'variation': 0.4, 'gaps': [[0.62, 0.035, 1.0], [0.88, 0.008, 0.9]],
        'inner_color': None, 'middle_color': None, 'outer_color': None, 'size': 2048, 'pattern': 0, 'view': 18.0}


def ring_entry(r):
    e = copy.deepcopy(RING)
    e.update({k: copy.deepcopy(v) for k, v in (r if isinstance(r, dict) else {}).items() if k in RING})
    gaps = []
    for g in e['gaps'] or []:
        try:
            gaps.append([min(max(float(g[0]), 0.0), 1.0), min(max(float(g[1]), 0.0005), 0.5), min(max(float(g[2]), 0.0), 1.0)])
        except (TypeError, ValueError, IndexError):
            pass
    e['gaps'] = gaps
    e['inner'] = max(1.0, float(e['inner']))
    e['outer'] = max(e['inner'] + 0.05, float(e['outer']))
    e['size'] = int(e['size']) if int(e['size']) in (1024, 2048, 4096) else 2048
    return e


def has_rings(P):
    return bool((P.get('rings') or {}).get('enabled'))


def ring_colours(P, e):
    cols = np.array([b[1] for b in P['bands']], np.float32).reshape(-1, 3)
    m = cols.mean(0)
    grey = float(np.dot(m, [0.299, 0.587, 0.114]))
    d = m * 0.55 + grey * 0.45
    auto = (np.clip(d * 0.78, 0, 255), np.clip(d * 1.05 + 12, 0, 255), np.clip(d * 0.95 + 6, 0, 255))
    out = []
    for k, a in zip(('inner_color', 'middle_color', 'outer_color'), auto):
        out.append(np.array(e[k], np.float32) if e.get(k) else a)
    return out


def noise1d(x, freq, rng):
    n = int(np.ceil(freq)) + 2
    v = rng.random(n + 1).astype(np.float32)
    t = x * np.float32(freq)
    i = np.floor(t).astype(np.int32)
    f = t - i
    f = f * f * (3 - 2 * f)
    return v[i] * (1 - f) + v[i + 1] * f


def fbm1d(x, freq, rng, o=5):
    s = 0; a = 1.0; n = 0
    for k in range(o):
        s = s + a * noise1d(x, freq * 2 ** k, rng); n += a; a *= 0.5
    return s / n


def ring_profile(P, n=2048):
    e = ring_entry(P.get('rings'))
    rng = np.random.default_rng(int(P.get('seed', 1)) * 7 + 991 + int(e['pattern']) * 104729)
    x = ((np.arange(n) + 0.5) / n).astype(np.float32)
    k = max(1, int(e['zones']))
    bounds = np.sort(rng.uniform(0.08, 0.92, k - 1))
    levels = rng.uniform(0.25, 1.0, k)
    levels = levels / levels.max()
    dens = np.full(n, levels[0], np.float32)
    for b, l0, l1 in zip(bounds, levels[:-1], levels[1:]):
        w = rng.uniform(0.004, 0.03)
        dens += np.float32(l1 - l0) * ss(np.float32(b - w), np.float32(b + w), x)
    det = max(float(e['detail']), 0.1)
    rl = float(e['ringlets'])
    n1 = fbm1d(x, 60 * det, rng)
    dens *= np.clip(1 + rl * (2 * n1 - 1) * 1.4, 0, None)
    for pos, wid, dep in e['gaps']:
        g = np.exp(-(np.abs(x - pos) / (wid / 2)) ** 6)
        dens *= 1 - np.float32(dep) * g
    soft = np.float32(0.002 + float(e['edge']) * 0.04)
    dens *= ss(np.float32(0), soft, x) * (1 - ss(1 - soft, np.float32(1), x))
    alpha = np.clip(dens * np.float32(e['opacity']), 0, 1)
    ci, cm, co = ring_colours(P, e)
    t = x[:, None]
    col = np.where(t < 0.5, ci + (cm - ci) * (t / 0.5), cm + (co - cm) * ((t - 0.5) / 0.5))
    n2 = fbm1d(x, 25 * det, rng)
    col = col * (1 + float(e['variation']) * 0.35 * (2 * n2 - 1))[:, None]
    col = col * (0.85 + 0.15 * np.clip(dens, 0, 1))[:, None]
    return np.clip(col, 0, 255).astype(np.float32), alpha.astype(np.float32)


def ring_image(P, n=None, h=16):
    e = ring_entry(P.get('rings'))
    col, a = ring_profile(P, n or e['size'])
    rgba = np.concatenate([col, (a * 255)[:, None]], 1)[::-1]
    return np.repeat((rgba + 0.5).clip(0, 255).astype(np.uint8)[None], h, 0)


def ring_scene(tex, col, alpha, e, w=560, h=300, light=(0.75, -0.45, 0.5), ss_=2):
    W, Hh = w * ss_, h * ss_
    el = np.radians(max(2.0, min(89.0, float(e.get('view', 18.0)))))
    ang = np.radians(float(e.get('angle', 0.0)))
    ro = float(e['outer']); ri = float(e['inner'])
    half_w = ro * 1.06
    half_h = max(1.06, ro * np.sin(el) * 1.06 + 0.1)
    sc = min(W / (2 * half_w), Hh / (2 * half_h))
    xs = (np.arange(W) + 0.5 - W / 2) / sc
    ys = (Hh / 2 - np.arange(Hh) - 0.5) / sc
    X, Yv = np.meshgrid(xs.astype(np.float32), ys.astype(np.float32))
    c = np.array([0, -np.cos(el), np.sin(el)], np.float32)
    up = np.array([0, np.sin(el), np.cos(el)], np.float32)
    O = X[..., None] * np.array([1, 0, 0], np.float32) + Yv[..., None] * up + 10 * c
    d = -c
    L = np.array(light, np.float32); L /= np.linalg.norm(L)
    nr = np.array([0, -np.sin(ang), np.cos(ang)], np.float32)
    b = O @ d
    cc = (O * O).sum(-1) - 1
    disc = b * b - cc
    hit_s = disc >= 0
    ts = -b - np.sqrt(np.maximum(disc, 0))
    tr = -(O @ nr) / float(d @ nr)
    Q = O + tr[..., None] * d
    rq = np.sqrt((Q * Q).sum(-1))
    n = len(alpha)

    def ring_at(r):
        u = (r - ri) / (ro - ri)
        inside = (u >= 0) & (u <= 1)
        i = np.clip((u * n).astype(np.int32), 0, n - 1)
        return inside, i
    in_r, ir = ring_at(rq)
    a_r = np.where(in_r, alpha[ir], 0)
    bg = np.array([13, 15, 20], np.float32)
    out = np.broadcast_to(bg, X.shape + (3,)).copy()
    S = O + ts[..., None] * d
    Hs, Ws = tex.shape[:2]
    lat = np.arcsin(np.clip(S[..., 2], -1, 1))
    lon = np.arctan2(S[..., 1], S[..., 0])
    py = np.clip(((0.5 - lat / np.pi) * Hs).astype(np.int32), 0, Hs - 1)
    px = ((lon / (2 * np.pi)) % 1 * Ws).astype(np.int32) % Ws
    shade = np.clip(S @ L, 0, 1) * 0.95 + 0.04
    tl = -(S @ nr) / max(abs(float(L @ nr)), 1e-4) * np.sign(float(L @ nr))
    Qs = S + tl[..., None] * L
    in_s, isd = ring_at(np.sqrt((Qs * Qs).sum(-1)))
    shade = shade * np.where((tl > 0) & in_s, 1 - 0.85 * alpha[isd], 1)
    planet = tex[py, px].astype(np.float32) * shade[..., None]
    out[hit_s] = planet[hit_s]
    bq = Q @ L
    cq = (Q * Q).sum(-1) - 1
    dq = bq * bq - cq
    shadowed = (dq > 0) & (-bq - np.sqrt(np.maximum(dq, 0)) > 0)
    rl = (0.25 + 0.75 * abs(float(L @ nr))) * np.where(shadowed, 0.12, 1.0)
    rc = col[ir] * rl[..., None]
    front = in_r & (~hit_s | (tr < ts))
    out = np.where(front[..., None], rc * a_r[..., None] + out * (1 - a_r[..., None]), out)
    img = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    return img.resize((w, h), Image.LANCZOS) if ss_ > 1 else img


def ring_snippet(P, path):
    e = ring_entry(P.get('rings'))
    return ('Rings\n{\n\tRing\n\t{\n\t\tinnerRadius = %d\n\t\touterRadius = %d\n\t\tangle = %s\n'
            '\t\ttexture = %s\n\t\tcolor = 1,1,1,1\n\t\tlockRotation = false\n\t\tuseNewShader = true\n\t}\n}\n') % (
        round(e['inner'] * 1000), round(e['outer'] * 1000), ('%g' % float(e['angle'])), path)


ATMO_POINT = {'altitude': 0.0, 'skyExposure': 0.2, 'skyAlpha': 1.0, 'skyExtinctionTint': 1.0, 'scatteringExposure': 0.2,
              'extinctionThickness': 1.0, 'postProcessAlpha': 1.0, 'postProcessDepth': 0.0, 'extinctionTint': 1.0}
ATMO_POINT_KEYS = ('altitude', 'skyExposure', 'skyAlpha', 'skyExtinctionTint', 'scatteringExposure', 'extinctionThickness',
                   'postProcessAlpha', 'postProcessDepth', 'extinctionTint')
ATMO_VALUES = ('atmosphereStartRadiusScale', 'HR', 'HM', 'm_betaR', 'BETA_MSca', 'm_mieG', 'ozoneAbsorption', 'ozoneHeight',
               'ozoneFalloff', 'useOzone', 'averageGroundReflectance', 'multipleScattering', 'godrayStrength')
ATMO_EXTRA = [['flattenScaledSpaceMesh', '0'], ['rimBlend', '20'], ['rimpower', '600'], ['specR', '1'], ['specG', '1'],
              ['specB', '1'], ['shininess', '10'], ['noonSunlightExtinctionStrength', '1'], ['cloudColorMultiplier', '1'],
              ['cloudScatteringMultiplier', '0.2'], ['cloudSkyIrradianceMultiplier', '0'], ['volumetricsColorMultiplier', '1'],
              ['EVEIntegration_preserveCloudColors', 'True'], ['adjustScaledTexture', 'False'], ['scaledLandBrightnessAdjust', '1'],
              ['scaledLandContrastAdjust', '1'], ['scaledLandSaturationAdjust', '1'], ['scaledOceanBrightnessAdjust', '1'],
              ['scaledOceanContrastAdjust', '1'], ['scaledOceanSaturationAdjust', '1']]
ATMO = {'enabled': False, 'radius': 6000.0, 'atmosphereStartRadiusScale': 1.0, 'HR': 46.4, 'HM': 5.57,
        'm_betaR': [0.002844, 0.008425, 0.002313], 'BETA_MSca': [0.005782, 0.005782, 0.005782], 'm_mieG': 0.85,
        'useOzone': False, 'ozoneAbsorption': [0.0003426, 0.0008298, 0.000036], 'ozoneHeight': 25.0, 'ozoneFalloff': 15.0,
        'averageGroundReflectance': 0.1, 'multipleScattering': True, 'godrayStrength': 0.8,
        'configPoints': [dict(ATMO_POINT)], 'sun': 'Sun', 'sun_color': [255, 255, 255], 'cloud_integration': True,
        'flat_model': True, 'eclipse_casters': '', 'sun_angle': 55.0, 'view': 'planet', 'extra': None}
ATMO_PRESETS = {
    'Jool (stock)': {'atmosphereStartRadiusScale': 0.997, 'HR': 46.40625, 'HM': 5.56875, 'm_betaR': [0.002844, 0.008425, 0.002313],
                     'BETA_MSca': [0.005782, 0.005782, 0.005782], 'm_mieG': 0.85, 'useOzone': False,
                     'configPoints': [dict(ATMO_POINT, skyExposure=0.2, scatteringExposure=0.2)]},
    'Kerbin (stock)': {'atmosphereStartRadiusScale': 1.0, 'HR': 3.84, 'HM': 1.0, 'm_betaR': [0.01534078, 0.0357075, 0.0875489],
                       'BETA_MSca': [0.01214062, 0.01214062, 0.01214062], 'm_mieG': 0.85, 'useOzone': True,
                       'ozoneAbsorption': [0.000493594, 0.00142889, 0.0000645469], 'ozoneHeight': 20.0, 'ozoneFalloff': 12.0,
                       'configPoints': [dict(ATMO_POINT)]},
    'Earth-like': {'atmosphereStartRadiusScale': 1.0, 'HR': 8.0, 'HM': 1.2, 'm_betaR': [0.0058, 0.0135, 0.0331],
                   'BETA_MSca': [0.004, 0.004, 0.004], 'm_mieG': 0.8, 'useOzone': True,
                   'ozoneAbsorption': [0.0003426, 0.0008298, 0.000036], 'ozoneHeight': 25.0, 'ozoneFalloff': 15.0,
                   'configPoints': [dict(ATMO_POINT)]},
}


def vec3(v, d):
    try:
        if isinstance(v, str):
            v = [float(x) for x in v.replace(' ', '').split(',') if x != '']
        v = [float(x) for x in v]
        if len(v) == 1:
            v = v * 3
        return [v[0], v[1], v[2]]
    except (TypeError, ValueError, IndexError):
        return list(d)


def atmo_entry(a):
    e = copy.deepcopy(ATMO)
    a = a if isinstance(a, dict) else {}
    for k, v in a.items():
        if k in ATMO:
            e[k] = copy.deepcopy(v)
    for k in ('m_betaR', 'BETA_MSca', 'ozoneAbsorption'):
        e[k] = [max(0.0, x) for x in vec3(e[k], ATMO[k])]
    for k in ('radius', 'atmosphereStartRadiusScale', 'HR', 'HM', 'm_mieG', 'ozoneHeight', 'ozoneFalloff',
              'averageGroundReflectance', 'godrayStrength', 'sun_angle'):
        try:
            e[k] = float(e[k])
        except (TypeError, ValueError):
            e[k] = ATMO[k]
    e['radius'] = max(1.0, e['radius'])
    e['HR'] = max(0.01, e['HR']); e['HM'] = max(0.01, e['HM'])
    e['ozoneFalloff'] = max(0.01, e['ozoneFalloff'])
    e['m_mieG'] = min(max(e['m_mieG'], -0.99), 0.99)
    for k in ('useOzone', 'multipleScattering', 'enabled', 'cloud_integration', 'flat_model'):
        e[k] = bool(e[k])
    pts = []
    for p in e.get('configPoints') or []:
        q = dict(ATMO_POINT)
        if isinstance(p, dict):
            for k in ATMO_POINT_KEYS:
                try:
                    q[k] = float(p.get(k, q[k]))
                except (TypeError, ValueError):
                    pass
        pts.append(q)
    e['configPoints'] = sorted(pts, key=lambda q: q['altitude']) or [dict(ATMO_POINT)]
    e['sun_color'] = [int(min(255, max(0, round(float(c))))) for c in vec3(e['sun_color'], ATMO['sun_color'])]
    if e['view'] not in ('planet', 'limb', 'sunset'):
        e['view'] = 'planet'
    if not isinstance(e['extra'], list):
        e['extra'] = copy.deepcopy(ATMO_EXTRA)
    e['extra'] = atmo_fix_extra([[str(k), str(v)] for k, v in e['extra'] if str(k) not in ATMO_VALUES and str(k) not in ('name', 'configPoints')])
    return e


def atmo_fix_extra(extra):
    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0
    d = dict(ATMO_EXTRA)
    have = {k for k, v in extra}
    out = [list(x) for x in extra] + [list(x) for x in ATMO_EXTRA if x[0] not in have]
    cur = dict(out)
    bad = set()
    if num(cur.get('shininess')) <= 0:
        bad.add('shininess')
    if all(num(cur.get(k)) <= 0 for k in ('specR', 'specG', 'specB')):
        bad.update(('specR', 'specG', 'specB'))
    return [[k, d[k] if k in bad else v] for k, v in out]


def has_atmo(P):
    return bool((P.get('atmosphere') or {}).get('enabled'))


def atmo_top(e):
    tr = 1000.0 * e['HR'] * np.log(max(np.linalg.norm(e['m_betaR']), 2e-7) / 1e-7)
    tm = 1000.0 * e['HM'] * np.log(max(np.linalg.norm(e['BETA_MSca']), 2e-7) / 1e-7)
    t = max(tr, tm)
    if e['useOzone']:
        t = max(t, 1000.0 * (e['ozoneHeight'] + e['ozoneFalloff']))
    return t / 1000.0


class AtmoModel:
    def __init__(self, e):
        R = e['radius']
        self.Rg = float(e['atmosphereStartRadiusScale'])
        self.Rt = self.Rg + atmo_top(e) / R
        self.HR = e['HR'] / R; self.HM = e['HM'] / R
        self.bR = np.array(e['m_betaR'], np.float32) * np.float32(R)
        self.bM = np.array(e['BETA_MSca'], np.float32) * np.float32(R)
        self.bMe = self.bM / np.float32(0.9)
        self.oz = bool(e['useOzone'])
        self.bO = np.array(e['ozoneAbsorption'], np.float32) * np.float32(R)
        self.oH = e['ozoneHeight'] / R; self.oF = e['ozoneFalloff'] / R
        self.g = float(e['m_mieG'])
        self.albedo = float(e['averageGroundReflectance'])
        self.H = np.sqrt(self.Rt ** 2 - self.Rg ** 2)
        self.trans_lut()
        self.ms = self.ms_lut() if e['multipleScattering'] else None

    def dens(self, r):
        h = np.maximum(r - np.float32(self.Rg), 0)
        dR = np.exp(-h / np.float32(self.HR))
        dM = np.exp(-h / np.float32(self.HM))
        dO = np.maximum(0, 1 - np.abs(h - np.float32(self.oH)) / np.float32(self.oF)) if self.oz else None
        return dR, dM, dO

    def ext(self, dR, dM, dO):
        s = dR[..., None] * self.bR + dM[..., None] * self.bMe
        if dO is not None:
            s = s + dO[..., None] * self.bO
        return s

    def trans_lut(self, nr=64, nm=256, steps=96):
        Rg, Rt, H = self.Rg, self.Rt, self.H
        xr = np.linspace(0, 1, nr, dtype=np.float64)
        xm = np.linspace(0, 1, nm, dtype=np.float64)
        rho = H * xr
        r = np.sqrt(rho ** 2 + Rg ** 2)[:, None]
        dmin = (Rt - r); dmax = rho[:, None] + H
        d = dmin + xm[None, :] * (dmax - dmin)
        mu = np.where(d > 0, (H * H - rho[:, None] ** 2 - d * d) / np.maximum(2 * r * d, 1e-12), 1.0)
        mu = np.clip(mu, -1, 1)
        tau = np.zeros((nr, nm, 3), np.float32)
        for i in range(steps):
            t = (i + 0.5) / steps * d
            ri = np.sqrt(np.maximum(t * t + 2 * r * mu * t + r * r, 0)).astype(np.float32)
            tau += self.ext(*self.dens(ri)) * (d / steps).astype(np.float32)[..., None]
        self.tau = tau
        self.nr, self.nm = nr, nm

    def sun_t(self, r, mu):
        Rg, Rt, H = self.Rg, self.Rt, self.H
        r = np.clip(r, Rg, Rt).astype(np.float32)
        rho = np.sqrt(np.maximum(r * r - np.float32(Rg * Rg), 0))
        disc = r * r * (mu * mu - 1) + np.float32(Rt * Rt)
        d = np.maximum(-r * mu + np.sqrt(np.maximum(disc, 0)), 0)
        dmin = np.float32(Rt) - r; dmax = rho + np.float32(H)
        xm = np.clip((d - dmin) / np.maximum(dmax - dmin, 1e-9), 0, 1) * (self.nm - 1)
        xr = np.clip(rho / np.float32(H), 0, 1) * (self.nr - 1)
        i0 = np.minimum(xr.astype(np.int32), self.nr - 2); fr = (xr - i0)[..., None]
        j0 = np.minimum(xm.astype(np.int32), self.nm - 2); fm = (xm - j0)[..., None]
        T = self.tau
        tau = (T[i0, j0] * (1 - fm) + T[i0, j0 + 1] * fm) * (1 - fr) + (T[i0 + 1, j0] * (1 - fm) + T[i0 + 1, j0 + 1] * fm) * fr
        hor = -np.sqrt(np.maximum(1 - (np.float32(Rg) / r) ** 2, 0))
        lit = np.clip((mu - hor) / np.float32(0.004) + 0.5, 0, 1)
        lit = lit * lit * (3 - 2 * lit)
        return np.exp(-tau) * lit[..., None]

    def ms_lut(self, nr=16, nm=24, nd=48, steps=16):
        Rg, Rt = self.Rg, self.Rt
        xr = np.linspace(0, 1, nr)
        rr = Rg + (Rt - Rg) * xr ** 2
        ms = np.linspace(-1, 1, nm)
        k = np.arange(nd) + 0.5
        cz = 1 - 2 * k / nd
        phi = np.pi * (1 + 5 ** 0.5) * k
        sz = np.sqrt(1 - cz * cz)
        D = np.stack([sz * np.cos(phi), sz * np.sin(phi), cz], -1)
        R_, M_, K_ = np.meshgrid(rr, ms, np.arange(nd), indexing='ij')
        d = D[K_]
        r0 = R_
        mu = d[..., 2]
        disc_g = r0 * r0 * (mu * mu - 1) + Rg * Rg
        tg = -r0 * mu - np.sqrt(np.maximum(disc_g, 0))
        hit = (disc_g >= 0) & (tg > 0)
        tt = -r0 * mu + np.sqrt(np.maximum(r0 * r0 * (mu * mu - 1) + Rt * Rt, 0))
        tmax = np.where(hit, tg, tt)
        sun = np.stack([np.sqrt(1 - M_ * M_), np.zeros_like(M_), M_], -1)
        L2 = np.zeros(R_.shape + (3,), np.float32)
        Lf = np.zeros(R_.shape + (3,), np.float32)
        Tv = np.ones(R_.shape + (3,), np.float32)
        pu = np.float32(1 / (4 * np.pi))
        for i in range(steps):
            t = (i + 0.5) / steps * tmax
            ds = (tmax / steps).astype(np.float32)[..., None]
            px = d[..., 0] * t; py = d[..., 1] * t; pz = r0 + d[..., 2] * t
            r = np.sqrt(px * px + py * py + pz * pz).astype(np.float32)
            mus = ((px * sun[..., 0] + pz * sun[..., 2]) / r).astype(np.float32)
            dR, dM, dO = self.dens(r)
            se = self.ext(dR, dM, dO)
            ss = dR[..., None] * self.bR + dM[..., None] * self.bM
            st = np.exp(-se * ds)
            w = np.where(se > 1e-9, (1 - st) / np.maximum(se, 1e-9), ds)
            Ts = self.sun_t(r, mus)
            L2 += Tv * ss * Ts * pu * w
            Lf += Tv * ss * w
            Tv *= st
        gx = d[..., 0] * tmax; gy = d[..., 1] * tmax; gz = r0 + d[..., 2] * tmax
        gr = np.sqrt(gx * gx + gy * gy + gz * gz)
        gmu = (gx * sun[..., 0] + gz * sun[..., 2]) / np.maximum(gr, 1e-9)
        Tg = self.sun_t(gr.astype(np.float32), gmu.astype(np.float32))
        L2 += np.where(hit[..., None], Tv * Tg * np.maximum(gmu, 0)[..., None] * np.float32(self.albedo / np.pi), 0)
        L2n = L2.mean(2); fms = np.clip(Lf.mean(2), 0, 0.98)
        self.ms_nr, self.ms_nm = nr, nm
        return (L2n / (1 - fms)).astype(np.float32)

    def ms_at(self, r, mus):
        xr = np.sqrt(np.clip((r - np.float32(self.Rg)) / np.float32(self.Rt - self.Rg), 0, 1)) * (self.ms_nr - 1)
        xm = np.clip((mus + 1) * 0.5, 0, 1) * (self.ms_nm - 1)
        i0 = np.minimum(xr.astype(np.int32), self.ms_nr - 2); fr = (xr - i0)[..., None]
        j0 = np.minimum(xm.astype(np.int32), self.ms_nm - 2); fm = (xm - j0)[..., None]
        T = self.ms
        return (T[i0, j0] * (1 - fm) + T[i0, j0 + 1] * fm) * (1 - fr) + (T[i0 + 1, j0] * (1 - fm) + T[i0 + 1, j0 + 1] * fm) * fr

    def phases(self, nu):
        pr = 3.0 / (16 * np.pi) * (1 + nu * nu)
        g = self.g
        pm = 1.5 / (4 * np.pi) * (1 - g * g) * (1 + g * g - 2 * g * nu) ** -1.5 * (1 + nu * nu) / (2 + g * g)
        return np.float32(pr), np.float32(pm)

    def jlut(self, nu, nr=192, nm=384):
        Rg, Rt = self.Rg, self.Rt
        xr = np.linspace(0, 1, nr, dtype=np.float32)
        r = (np.float32(Rg) + np.float32(Rt - Rg) * xr * xr)[:, None] * np.ones((1, nm), np.float32)
        mus = np.linspace(-1, 1, nm, dtype=np.float32)[None, :] * np.ones((nr, 1), np.float32)
        pr, pm = self.phases(nu)
        dR, dM, dO = self.dens(r)
        sR = dR[..., None] * self.bR; sM = dM[..., None] * self.bM
        J = self.sun_t(r, mus) * (sR * pr + sM * pm)
        if self.ms is not None:
            J = J + (sR + sM) * self.ms_at(r, mus)
        self.Jc = np.ascontiguousarray(J.reshape(-1, 3).T.astype(np.float32))
        self.j_nr, self.j_nm = nr, nm
        self.cR = self.bR[:, None]; self.cMe = self.bMe[:, None]; self.cO = self.bO[:, None]

    def j_at(self, r, mus):
        nr, nm = self.j_nr, self.j_nm
        xr = np.sqrt(np.maximum(r - np.float32(self.Rg), 0) * np.float32((nr - 1) ** 2 / (self.Rt - self.Rg)))
        xm = mus * np.float32(0.5 * (nm - 1)) + np.float32(0.5 * (nm - 1))
        i0 = np.minimum(xr.astype(np.int32), nr - 2)
        j0 = np.minimum(xm.astype(np.int32), nm - 2)
        fr = xr - i0; fm = xm - j0
        k = i0 * nm + j0
        J = self.Jc
        a = np.take(J, k, axis=1); b = np.take(J, k + 1, axis=1)
        c = np.take(J, k + nm, axis=1); d = np.take(J, k + nm + 1, axis=1)
        x0 = a + (c - a) * fr
        return x0 + (b + (d - b) * fr - x0) * fm

    def march(self, u, v, s0, s1, L, n, dense_end, cancel=None):
        b2 = (u * u + v * v).astype(np.float32)
        Lin = np.zeros((3,) + u.shape, np.float32)
        Tv = np.ones((3,) + u.shape, np.float32)
        ln = (s1 - s0).astype(np.float32)
        lx, ly, lz = np.float32(L[0]), np.float32(L[1]), np.float32(L[2])
        uv = u * lx + v * ly
        for i in range(n):
            if cancel and i % 4 == 0:
                cancel()
            a = (i + 0.5) / n; a1 = (i + 1.0) / n; a0 = i / float(n)
            if dense_end:
                f = 1 - (1 - a) ** 2; ds = ln * np.float32((1 - a0) ** 2 - (1 - a1) ** 2)
            else:
                f = a * a; ds = ln * np.float32(a1 * a1 - a0 * a0)
            s = s0 + ln * np.float32(f)
            r = np.sqrt(b2 + s * s)
            mus = (uv - s * lz) / r
            dR, dM, dO = self.dens(r)
            x = self.cR * (dR * ds) + self.cMe * (dM * ds)
            if dO is not None:
                x += self.cO * (dO * ds)
            np.maximum(x, np.float32(1e-20), out=x)
            em = np.expm1(-x)
            Lin += Tv * self.j_at(r, mus) * (-em / x * ds)
            Tv *= 1 + em
        return Lin.T, Tv.T


def scatterer_hdr(L, exposure):
    L = L * np.float32(exposure)
    return np.where(L < 1.413, np.power(np.maximum(L * 0.38317, 0), 1 / 2.2), 1 - np.exp(-L)).astype(np.float32)


def sphere_sample(tex, x, y, z, tilt, vlat, vlon):
    H, W = tex.shape[:2]
    t = np.radians(tilt); cu, su = np.cos(t), np.sin(t)
    u2 = x * cu - y * su; v2 = x * su + y * cu
    a = np.radians(vlat); cl, sl = np.cos(a), np.sin(a)
    y3 = v2 * cl + z * sl; z3 = -v2 * sl + z * cl
    lat = np.arcsin(np.clip(y3, -1, 1)); lon = np.arctan2(u2, z3) + np.radians(vlon)
    fx = (lon / (2 * np.pi)) % 1 * W - 0.5
    fy = np.clip((0.5 - lat / np.pi) * H - 0.5, 0, H - 1.001)
    x0 = np.floor(fx).astype(np.int32); y0 = fy.astype(np.int32)
    ax = (fx - x0).astype(np.float32)[:, None]; ay = (fy - y0).astype(np.float32)[:, None]
    x0 %= W; x1 = (x0 + 1) % W; y1 = np.minimum(y0 + 1, H - 1)
    top = tex[y0, x0] * (1 - ax) + tex[y0, x1] * ax
    bot = tex[y1, x0] * (1 - ax) + tex[y1, x1] * ax
    return top * (1 - ay) + bot * ay


ATMO_CACHE = {}


def atmo_model(e):
    key = json.dumps([e[k] for k in ATMO_VALUES] + [e['radius']], default=str)
    m = ATMO_CACHE.get(key)
    if m is None:
        m = AtmoModel(e)
        ATMO_CACHE[key] = m
        while len(ATMO_CACHE) > 4:
            ATMO_CACHE.pop(next(iter(ATMO_CACHE)))
    return m


def atmo_light(e, ang=None):
    ph = np.radians(float(e['sun_angle'] if ang is None else ang)); ps = np.radians(18.0)
    return np.array([np.sin(ph) * np.cos(ps), np.sin(ph) * np.sin(ps), np.cos(ph)], np.float32)


def atmo_frame(e, view, w, h, m):
    L = atmo_light(e)
    if view == 'planet':
        half = 1.0 + max(0.07, min(7 * max(m.HR, m.HM), m.Rt - 1.0 + 0.02))
        sc = min(w, h) / (2 * half)
        X = (np.arange(w, dtype=np.float32) + 0.5 - w / 2) / np.float32(sc)
        Y = (h / 2 - np.arange(h, dtype=np.float32) - 0.5) / np.float32(sc)
        u, v = np.meshgrid(X, Y)
        return u, v, 1.0 / sc
    if view == 'limb':
        n = np.array([L[0], L[1]], np.float64)
    else:
        n = np.array([-L[1], L[0]], np.float64)
    nn = np.linalg.norm(n)
    n = n / nn if nn > 1e-6 else np.array([1.0, 0.0])
    t = np.array([-n[1], n[0]])
    span = float(np.clip(30 * max(m.HR, m.HM), 0.05, 0.6))
    sc = w / span
    X = (np.arange(w, dtype=np.float32) + 0.5 - w / 2) / np.float32(sc)
    Y = (h * 0.62 - np.arange(h, dtype=np.float32) - 0.5) / np.float32(sc)
    Xg, Yg = np.meshgrid(X, Y)
    r0 = 1.0
    u = (n[0] * r0 + Xg * t[0] + Yg * n[0]).astype(np.float32)
    v = (n[1] * r0 + Xg * t[1] + Yg * n[1]).astype(np.float32)
    return u, v, 1.0 / sc


def ingame_glow(P, W=1024, cancel=None):
    if not has_aurora(P):
        return None
    e = aurora_entry(P.get('aurora'))
    low, top = aurora_maps(P, W, cancel=cancel)
    nl = max(1, e['layers'] - e['top_layers']); nt = e['top_layers']
    ol = 1 - (1 - min(1.0, e['opacity'] / 255.0)) ** min(nl, 3)
    ot = (1 - (1 - min(1.0, e['opacity'] * (0.5 + 0.5 * e['fade']) / 255.0)) ** min(nt, 3)) * 0.6 if nt else 0.0
    return (low[..., :3] * low[..., 3:4] * np.float32(ol) + top[..., :3] * top[..., 3:4] * np.float32(ot)).astype(np.float32)


def render_ingame(P, tex, emis=None, view=None, w=560, h=360, rot=(0.0, 0.0), steps=16, cancel=None, glow=None, bg=(13, 15, 20)):
    if has_atmo(P):
        return render_atmo(P, tex, emis, view, w, h, rot, steps, cancel=cancel, glow=glow)
    e = atmo_entry(P.get('atmosphere'))
    pv = P.get('preview', {'tilt': 0, 'view_lat': 0, 'view_lon': 0})
    vlat = max(-90.0, min(90.0, float(pv.get('view_lat', 0)) + rot[1])); vlon = float(pv.get('view_lon', 0)) + rot[0]
    em = emis
    if glow is not None:
        G = glow
        if G.shape[:2] != tex.shape[:2]:
            G = np.asarray(Image.fromarray((np.clip(G, 0, 1) * 255).astype(np.uint8)).resize((tex.shape[1], tex.shape[0]), Image.BILINEAR), np.float32) / 255
        em = G if em is None else em + G
    S = max(40, min(w, h) - 8)
    g = render_sphere(tex, S, float(pv.get('tilt', 0)), vlat, vlon, em, [float(v) for v in atmo_light(e)])
    out = Image.new('RGB', (w, h), tuple(bg))
    yy, xx = np.mgrid[0:S, 0:S]
    rr = np.sqrt(((xx + 0.5) / S * 2 - 1) ** 2 + ((yy + 0.5) / S * 2 - 1) ** 2)
    mask = Image.fromarray((np.clip((1 - rr) * S / 2 + 0.5, 0, 1) * 255).astype(np.uint8), 'L')
    out.paste(g, ((w - S) // 2, (h - S) // 2), mask)
    return out


def render_atmo(P, tex, emis=None, view=None, w=560, h=360, rot=(0.0, 0.0), steps=16, chunk=60000, cancel=None, glow=None):
    e = atmo_entry(P.get('atmosphere'))
    m = atmo_model(e)
    view = view or e['view']
    pt = e['configPoints'][-1]
    L = atmo_light(e)
    sun = np.array(e['sun_color'], np.float32) / 255 * np.float32(100.0)
    u, v, px = atmo_frame(e, view, w, h, m)
    m.jlut(-float(L[2]))
    b = np.sqrt(u * u + v * v)
    out = np.zeros((h, w, 3), np.float32)
    cov = np.clip((1 - b) / np.float32(px) + 0.5, 0, 1)
    pv = P.get('preview', {'tilt': 0, 'view_lat': 0, 'view_lon': 0})
    tilt = float(pv.get('tilt', 0)); vlat = max(-90.0, min(90.0, float(pv.get('view_lat', 0)) + rot[1])); vlon = float(pv.get('view_lon', 0)) + rot[0]
    gi = np.nonzero((cov > 0).ravel())[0]
    si = np.nonzero(((cov < 1) & (b < m.Rt)).ravel())[0]
    uf, vf, bf = u.ravel(), v.ravel(), b.ravel()
    flat = out.reshape(-1, 3)
    covf = cov.ravel()
    for c0 in range(0, len(gi), chunk):
        idx = gi[c0:c0 + chunk]
        bb = np.minimum(bf[idx], np.float32(1 - 1e-5))
        sc_ = bb / np.maximum(bf[idx], 1e-9)
        uu = uf[idx] * sc_; vv = vf[idx] * sc_
        zg = np.sqrt(np.maximum(1 - bb * bb, 0)).astype(np.float32)
        s0 = -np.sqrt(np.maximum(np.float32(m.Rt ** 2) - bb * bb, 0)).astype(np.float32)
        s1 = -zg
        Lin, Tv = m.march(uu, vv, s0, s1, L, steps, True, cancel)
        nd = np.clip(uu * L[0] + vv * L[1] + zg * L[2], 0, 1)
        C = sphere_sample(tex, uu, vv, zg, tilt, vlat, vlon) * nd[:, None]
        if emis is not None:
            C = C + sphere_sample(emis, uu, vv, zg, tilt, vlat, vlon) * (1 - 0.8 * nd)[:, None]
        C = np.clip(C, 0, 1)
        E = Tv
        avg = E.mean(1, keepdims=True)
        E = np.float32(pt['extinctionTint']) * E + np.float32(1 - pt['extinctionTint']) * avg
        E = np.maximum(0, np.float32(1 - pt['extinctionThickness']) + np.float32(pt['extinctionThickness']) * E)
        S = scatterer_hdr(Lin * sun, pt['scatteringExposure'])
        CE = C * E
        px_ = CE + S * (1 - CE)
        if glow is not None:
            nd_ = np.clip(uu * L[0] + vv * L[1] + zg * L[2], 0, 1)
            px_ = px_ + sphere_sample(glow, uu, vv, zg, tilt, vlat, vlon) * (1 - np.float32(0.75) * nd_)[:, None]
        flat[idx] += px_ * covf[idx][:, None]
    for c0 in range(0, len(si), chunk):
        idx = si[c0:c0 + chunk]
        bb = np.maximum(bf[idx], np.float32(max(1.0, m.Rg) + 1e-6))
        sc_ = bb / np.maximum(bf[idx], 1e-9)
        uu = uf[idx] * sc_; vv = vf[idx] * sc_
        sm = np.sqrt(np.maximum(np.float32(m.Rt ** 2) - bb * bb, 0)).astype(np.float32)
        z0 = np.zeros_like(sm)
        La, Ta = m.march(uu, vv, -sm, z0, L, steps, True, cancel)
        Lb, Tb = m.march(uu, vv, z0, sm, L, steps, False, cancel)
        Lin = La + Ta * Lb
        S = scatterer_hdr(Lin * sun, pt['skyExposure']) * np.float32(pt['skyAlpha'])
        flat[idx] += S * (1 - covf[idx])[:, None]
    img = np.clip(out * 255 + 0.5, 0, 255).astype(np.uint8)
    return Image.fromarray(img)


def cfg_num(v):
    v = float('%.7g' % float(v))
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return np.format_float_positional(np.float64(v), trim='-')


def cfg_vec(v):
    return ','.join(cfg_num(x) for x in v)


def cfg_val(v):
    if isinstance(v, bool):
        return 'True' if v else 'False'
    if isinstance(v, (list, tuple)):
        return cfg_vec(v)
    return cfg_num(v)


def atmo_cfg(P, name=None):
    e = atmo_entry(P.get('atmosphere'))
    name = name or P['name']
    out = ['Scatterer_atmosphere', '{', '\tAtmo', '\t{', '\t\tname = %s' % name]
    for k in ATMO_VALUES:
        out.append('\t\t%s = %s' % (k, cfg_val(e[k])))
    for k, v in e['extra']:
        out.append('\t\t%s = %s' % (k, v))
    out += ['\t\tconfigPoints', '\t\t{']
    for p in e['configPoints']:
        out += ['\t\t\tItem', '\t\t\t{'] + ['\t\t\t\t%s = %s' % (k, cfg_num(p[k])) for k in ATMO_POINT_KEYS] + ['\t\t\t}']
    out += ['\t\t}', '\t}', '}']
    return '\n'.join(out) + '\n'


def atmo_casters(e):
    return [c.strip() for c in str(e.get('eclipse_casters') or '').replace(';', ',').split(',') if c.strip()]


def atmo_planets(P, name=None):
    e = atmo_entry(P.get('atmosphere'))
    name = name or P['name']
    t = '\t\t\t'
    out = ['@Scatterer_planetsList:AFTER[Kopernicus]', '{', '\t@scattererCelestialBodies', '\t{', '\t\tItem', '\t\t{',
           t + 'celestialBodyName = ' + name, t + 'transformName = ' + name,
           t + 'loadDistance = 1000000000', t + 'unloadDistance = 2000000000', t + 'hasOcean = False',
           t + 'flatScaledSpaceModel = ' + cfg_val(bool(e['flat_model'])),
           t + 'usesCloudIntegration = ' + cfg_val(bool(e['cloud_integration'])),
           t + 'cloudIntegrationUsesScattererSunColors = False',
           t + 'mainSunCelestialBody = ' + (str(e['sun']).strip() or 'Sun')]
    if list(e['sun_color']) != [255, 255, 255]:
        out.append(t + 'sunColor = %s,1' % cfg_vec([round(c / 255.0, 3) for c in e['sun_color']]))
    out.append(t + 'sunsUseIntensityCurves = False')
    cs = atmo_casters(e)
    if cs:
        out += [t + 'eclipseCasters', t + '{'] + [t + '\tItem = ' + c for c in cs] + [t + '}']
    out += ['\t\t}', '\t}', '}']
    return '\n'.join(out) + '\n'


def parse_cfg(text):
    root = {'name': '', 'values': [], 'nodes': []}
    stack = [root]
    pending = ''
    for raw in text.replace('﻿', '').splitlines():
        line = raw.split('//', 1)[0].strip()
        while line:
            if line[0] == '{':
                node = {'name': pending, 'values': [], 'nodes': []}
                stack[-1]['nodes'].append(node)
                stack.append(node)
                pending = ''
                line = line[1:].strip()
                continue
            if line[0] == '}':
                if len(stack) > 1:
                    stack.pop()
                pending = ''
                line = line[1:].strip()
                continue
            cut = [i for i in (line.find('{'), line.find('}')) if i >= 0]
            seg, line = (line[:min(cut)], line[min(cut):]) if cut else (line, '')
            seg = seg.strip()
            if '=' in seg:
                k, v = seg.split('=', 1)
                stack[-1]['values'].append((k.strip(), v.strip()))
                pending = ''
            elif seg:
                pending = seg
    return root


def cfg_base(name):
    n = name.lstrip('@!%+-').split(':')[0]
    return n.split('[')[0].strip()


def cfg_get(node, key, default=None):
    for k, v in node['values']:
        if k == key:
            return v
    return default


def cfg_walk(node, name):
    for n in node['nodes']:
        if cfg_base(n['name']) == name:
            yield n
        for x in cfg_walk(n, name):
            yield x


def cfg_bool(v, default):
    if v is None:
        return default
    return str(v).strip().lower() in ('true', '1', 'yes')


def atmo_from_cfg(text, body=None):
    root = parse_cfg(text)
    atmos = list(cfg_walk(root, 'Atmo'))
    if not atmos:
        return None, None
    pick = next((a for a in atmos if body and cfg_get(a, 'name') == body), atmos[0])
    e = copy.deepcopy(ATMO)
    extra = []
    for k, v in pick['values']:
        if k == 'name':
            continue
        if k in ('m_betaR', 'BETA_MSca', 'ozoneAbsorption'):
            e[k] = vec3(v, ATMO[k])
        elif k in ('useOzone', 'multipleScattering'):
            e[k] = cfg_bool(v, ATMO[k])
        elif k in ATMO_VALUES:
            try:
                e[k] = float(v)
            except ValueError:
                pass
        else:
            extra.append([k, v])
    e['extra'] = extra
    pts = []
    for cp in cfg_walk(pick, 'configPoints'):
        for it in cfg_walk(cp, 'Item'):
            q = dict(ATMO_POINT)
            for k, v in it['values']:
                if k in q:
                    try:
                        q[k] = float(v)
                    except ValueError:
                        pass
            pts.append(q)
        break
    if pts:
        e['configPoints'] = pts
    return e, cfg_get(pick, 'name')


def planets_item(text, body):
    root = parse_cfg(text)
    for it in cfg_walk(root, 'Item'):
        if cfg_get(it, 'celestialBodyName') == body:
            d = {'sun': cfg_get(it, 'mainSunCelestialBody', 'Sun'),
                 'cloud_integration': cfg_bool(cfg_get(it, 'usesCloudIntegration'), True),
                 'flat_model': cfg_bool(cfg_get(it, 'flatScaledSpaceModel'), True)}
            sc = cfg_get(it, 'sunColor')
            if sc:
                c = vec3(sc, [1, 1, 1])
                d['sun_color'] = [int(round(min(1.0, max(0.0, x)) * 255)) for x in c]
            ec = [v for n in cfg_walk(it, 'eclipseCasters') for k, v in n['values'] if k == 'Item']
            d['eclipse_casters'] = ', '.join(ec)
            return d
    return None


def cfg_files(folder, needle=None, limit=4000):
    out = []
    for dp, dn, fn in os.walk(folder):
        dn[:] = [d for d in dn if d.lower() not in ('plugindata', 'cache', 'textures', 'models')]
        for f in fn:
            if f.lower().endswith('.cfg'):
                p = os.path.join(dp, f)
                try:
                    with open(p, encoding='utf-8', errors='replace') as fh:
                        t = fh.read()
                except OSError:
                    continue
                if needle is None or needle in t:
                    out.append((p, t))
                if len(out) >= limit:
                    return out
    return out


def game_mod_dir():
    d = texture_dir()
    return mod_root(d) if d else ''


def scatterer_dir(mod):
    if not mod:
        return ''
    for n in os.listdir(mod) if os.path.isdir(mod) else []:
        if n.lower() == 'scatterer' and os.path.isdir(os.path.join(mod, n)):
            return os.path.join(mod, n)
    return ''


def find_atmo_cfg(body, mod=None):
    mod = mod if mod is not None else game_mod_dir()
    sd = scatterer_dir(mod)
    if not sd:
        return ''
    p = os.path.join(sd, 'Planets', body, 'atmo.cfg')
    if os.path.isfile(p):
        return p
    for path, t in cfg_files(sd, body):
        if 'Scatterer_atmosphere' in t:
            e, nm = atmo_from_cfg(t, body)
            if e is not None and nm == body:
                return path
    return ''


def find_planets_item(body, folder):
    for path, t in cfg_files(folder, body):
        if 'scattererCelestialBodies' in t:
            d = planets_item(t, body)
            if d:
                return d, path
    return None, ''


def find_body_radius(body, mod=None):
    mod = mod if mod is not None else game_mod_dir()
    if not mod or not os.path.isdir(mod):
        return None, ''
    for path, t in cfg_files(mod, body):
        if 'Body' not in t:
            continue
        for b in cfg_walk(parse_cfg(t), 'Body'):
            nm = cfg_get(b, 'name')
            if nm is None and '[' in b['name']:
                nm = b['name'].split('[', 1)[1].split(']', 1)[0]
            if nm != body:
                continue
            for pr in cfg_walk(b, 'Properties'):
                r = cfg_get(pr, 'radius')
                if r:
                    try:
                        return float(r) / 1000.0, path
                    except ValueError:
                        pass
    return None, ''


def colour_from_beta(b):
    b = np.maximum(np.array(b, np.float64), 0)
    if b.max() <= 0:
        return [255, 255, 255]
    c = (b / b.max()) ** (1 / 2.2)
    return [int(round(x * 255)) for x in c]


def beta_from_colour(rgb, old):
    c = np.maximum(np.array(rgb, np.float64) / 255.0, 0.004) ** 2.2
    mag = max(float(np.linalg.norm(old)), 1e-5)
    b = c / np.linalg.norm(c) * mag
    return [float('%.6g' % x) for x in b]


def planet_tint(P):
    bands = sorted(P['bands'], key=lambda b: b[0])
    lats = [b[0] for b in bands] + [90]
    acc = np.zeros(3); wsum = 0.0
    for i, b in enumerate(bands):
        lo, hi = max(-90.0, float(lats[i])), min(90.0, float(lats[i + 1]))
        if hi <= lo:
            continue
        w = np.sin(np.radians(hi)) - np.sin(np.radians(lo))
        acc += w * np.array(b[1], np.float64); wsum += w
    m = acc / max(wsum, 1e-9)
    grey = m.mean()
    m = grey + (m - grey) * 1.6
    return [int(round(min(255, max(0, x)))) for x in m]


def emission_entry(em):
    e = dict(EMISSION)
    e.update({k: v for k, v in em.items() if k in EMISSION})
    return e


def sort_bands(P):
    old = P['bands']
    order = sorted(range(len(old)), key=lambda i: old[i][0])
    P['bands'] = [old[i] for i in order]
    for em in P.get('emission', []) + P.get('band_shapes', []):
        b = em.get('band', -1)
        em['band'] = order.index(b) if 0 <= b < len(order) else -1


def shape_entry(sh):
    pts = []
    for p in sh.get('points', []):
        try:
            pts.append([round(float(p[0]) % 360.0, 2), round(min(max(float(p[1]), 0.0), 3.0), 3)])
        except (TypeError, ValueError, IndexError):
            pass
    return {'band': int(sh.get('band', -1)), 'points': sorted(pts)}


def shape_factor(points, lon):
    lon = np.asarray(lon, np.float32) % np.float32(360)
    pts = sorted((float(p[0]) % 360.0, float(p[1])) for p in points)
    if not pts:
        return np.ones_like(lon)
    if len(pts) == 1:
        return np.full_like(lon, pts[0][1])
    L = np.array([p[0] for p in pts], np.float32); F = np.array([p[1] for p in pts], np.float32)
    n = len(pts)
    i0 = (np.searchsorted(L, lon, side='right') - 1) % n
    i1 = (i0 + 1) % n
    span = (L[i1] - L[i0]) % np.float32(360)
    span = np.where(span <= 0, np.float32(360), span)
    t = np.clip(((lon - L[i0]) % np.float32(360)) / span, 0, 1)
    t = t * t * (3 - 2 * t)
    return F[i0] + (F[i1] - F[i0]) * t


def band_edges(P, lon):
    bands = P['bands']
    n = len(bands)
    base = [np.float32(b[0]) for b in bands[1:]]
    shapes = [sh for sh in P.get('band_shapes', []) if 0 <= int(sh.get('band', -1)) < n and sh.get('points')]
    if not shapes or n < 2:
        return base
    E = [np.full(np.shape(lon), e, np.float32) for e in base]
    for sh in sorted(shapes, key=lambda q: int(q['band'])):
        k = int(sh['band'])
        f = np.clip(shape_factor(sh['points'], lon), 0, 3)
        if k == 0:
            E[0] = -90 + f * (E[0] + 90)
        elif k == n - 1:
            E[n - 2] = 90 - f * (90 - E[n - 2])
        else:
            c = (E[k - 1] + E[k]) / 2; h = (E[k] - E[k - 1]) / 2
            E[k - 1] = c - f * h; E[k] = c + f * h
    for k in range(1, len(E)):
        E[k] = np.maximum(E[k], E[k - 1])
    return [np.clip(e, -90, 90).astype(np.float32) for e in E]


def normalize(P):
    P['big_storms'] = [big_storm(b) for b in P.get('big_storms', [])]
    P['emission'] = [emission_entry(e) for e in P.get('emission', [])]
    P['band_shapes'] = [shape_entry(sh) for sh in P.get('band_shapes', [])]
    po = P.get('poles') or {}
    P['poles'] = {'north': pole_entry(po.get('north')), 'south': pole_entry(po.get('south'), south=True)}
    P['heat_glow'] = heat_entry(P.get('heat_glow'))
    P['storm_chains'] = [chain_entry(c) for c in P.get('storm_chains', [])]
    P['rings'] = ring_entry(P.get('rings'))
    P['atmosphere'] = atmo_entry(P.get('atmosphere'))
    P['aurora'] = aurora_entry(P.get('aurora'))
    P.pop('glows', None)
    sort_bands(P)
    return P


def has_emission(P):
    return bool(glow_list(P)) or has_heat(P)


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
    F = T.reshape(-1)
    a0 = x0 * (N * N); a1 = x1 * (N * N); b0 = y0 * N; b1 = y1 * N
    c00 = F[a0 + b0 + z0] * (1 - fx) + F[a1 + b0 + z0] * fx
    c10 = F[a0 + b1 + z0] * (1 - fx) + F[a1 + b1 + z0] * fx
    c01 = F[a0 + b0 + z1] * (1 - fx) + F[a1 + b0 + z1] * fx
    c11 = F[a0 + b1 + z1] * (1 - fx) + F[a1 + b1 + z1] * fx
    return (c00 * (1 - fy) + c10 * fy) * (1 - fz) + (c01 * (1 - fy) + c11 * fy) * fz


def fbm(tabs, x, y, z, t=0, o=4, gain=0.5):
    s = 0; a = 1; n = 0
    for i in range(o):
        s = s + a * vn(tabs[(t + i) % 8], x * 2 ** i + 17.3 * i, y * 2 ** i + 5.1 * i, z * 2 ** i + 9.7 * i); n += a; a *= gain
    return (s / n) * 2 - 1


def fbm_lod(tabs, x, y, z, g, t=0, o=4, gain=0.5):
    s = 0; a = 1; n = 0
    for i in range(o):
        att = np.exp(-(g * np.float32(2 ** i * 1.4)) ** 2)
        s = s + a * (0.5 + (vn(tabs[(t + i) % 8], x * 2 ** i + 17.3 * i, y * 2 ** i + 5.1 * i, z * 2 ** i + 9.7 * i) - 0.5) * att); n += a; a *= gain
    return (s / n) * 2 - 1


def footprint(X, Y, Z, nb=None):
    fw = np.sqrt((np.roll(X, -1, 1) - X) ** 2 + (np.roll(Y, -1, 1) - Y) ** 2 + (np.roll(Z, -1, 1) - Z) ** 2)
    g = np.maximum(fw, np.roll(fw, 1, 1))
    up = [X[:1], Y[:1], Z[:1]]; dn = [X[-1:], Y[-1:], Z[-1:]]
    if nb is not None:
        if nb[0] is not None:
            up = list(sph((0.5 - nb[0][1]) * np.float32(np.pi), nb[0][0] * np.float32(2 * np.pi)))
            up = [u[None, :] for u in up]
        if nb[1] is not None:
            dn = list(sph((0.5 - nb[1][1]) * np.float32(np.pi), nb[1][0] * np.float32(2 * np.pi)))
            dn = [d[None, :] for d in dn]
    vd = 0
    for A, u, d in zip((X, Y, Z), up, dn):
        E = np.concatenate([u, A, d], 0)
        vd = vd + (E[1:] - E[:-1]) ** 2
    vd = np.sqrt(vd)
    return np.maximum(g, np.maximum(vd[1:], vd[:-1]))


def box3(a):
    p = np.concatenate([a[:1], a, a[-1:]], 0)
    v = (p[:-2] + p[1:-1] + p[2:]) / np.float32(3)
    return (np.roll(v, 1, 1) + v + np.roll(v, -1, 1)) / np.float32(3)


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


def bc_blocks(a):
    if a.ndim == 2:
        a = a[..., None]
    H, W, C = a.shape
    ph, pw = (-H) % 4, (-W) % 4
    if ph or pw:
        a = np.pad(a, ((0, ph), (0, pw), (0, 0)), mode='edge')
        H, W = a.shape[:2]
    return a.reshape(H // 4, 4, W // 4, 4, C).transpose(0, 2, 1, 3, 4).reshape(-1, 16, C)


def bc4_encode(ch):
    v = bc_blocks(ch)[..., 0].astype(np.int32)
    hi = v.max(1); lo = v.min(1)
    rng = np.maximum(hi - lo, 1)
    k = np.clip(np.rint((hi[:, None] - v) * 7.0 / rng[:, None]), 0, 7).astype(np.uint64)
    code = np.where(k == 0, 0, np.where(k == 7, 1, k + 1)).astype(np.uint64)
    code[hi == lo] = 0
    bits = np.zeros(len(v), np.uint64)
    for i in range(16):
        bits |= code[:, i] << np.uint64(3 * i)
    out = np.zeros((len(v), 8), np.uint8)
    out[:, 0] = hi; out[:, 1] = lo
    for j in range(6):
        out[:, 2 + j] = ((bits >> np.uint64(8 * j)) & np.uint64(255)).astype(np.uint8)
    return out


def bc5_encode(r, g):
    return np.concatenate([bc4_encode(r), bc4_encode(g)], 1).tobytes()


BC7_W = np.array([0, 4, 9, 13, 17, 21, 26, 30, 34, 38, 43, 47, 51, 55, 60, 64], np.float32)


def bc7_chunk(px):
    n = len(px)
    mean = px.mean(1)
    d = px - mean[:, None]
    ax = d.max(1) - d.min(1) + 1e-3
    for _ in range(4):
        ax = np.einsum('nki,nk->ni', d, np.einsum('nkj,nj->nk', d, ax))
        ax /= np.maximum(np.linalg.norm(ax, axis=1, keepdims=True), 1e-6)
    t = np.einsum('nki,ni->nk', d, ax)
    e0 = np.clip(mean + t.min(1)[:, None] * ax, 0, 255)
    e1 = np.clip(mean + t.max(1)[:, None] * ax, 0, 255)

    def quant(e):
        res = None
        for p in (0, 1):
            q = np.clip(np.rint((e - p) / 2.0), 0, 127)
            err = ((q * 2 + p - e) ** 2).sum(1)
            if res is None:
                res = [q, np.full(len(e), p), err]
            else:
                m = err < res[2]
                res = [np.where(m[:, None], q, res[0]), np.where(m, p, res[1]), np.where(m, err, res[2])]
        return res[0].astype(np.int64), res[1].astype(np.int64)
    q0, p0 = quant(e0)
    q1, p1 = quant(e1)
    E0 = (q0 * 2 + p0[:, None]).astype(np.float32)
    E1 = (q1 * 2 + p1[:, None]).astype(np.float32)
    best = None; idx = None
    for k in range(16):
        col = np.floor(((64 - BC7_W[k]) * E0 + BC7_W[k] * E1 + 32) / 64)
        err = ((px - col[:, None, :]) ** 2).sum(2)
        if best is None:
            best, idx = err, np.zeros(err.shape, np.int64)
        else:
            m = err < best
            best = np.where(m, err, best); idx = np.where(m, k, idx)
    sw = idx[:, 0] >= 8
    q0s = np.where(sw[:, None], q1, q0); q1s = np.where(sw[:, None], q0, q1)
    p0s = np.where(sw, p1, p0); p1s = np.where(sw, p0, p1)
    idx = np.where(sw[:, None], 15 - idx, idx)
    U = np.uint64
    lo = np.full(n, 0x40, np.uint64)
    sh = 7
    for c in range(4):
        lo |= q0s[:, c].astype(U) << U(sh); sh += 7
        lo |= q1s[:, c].astype(U) << U(sh); sh += 7
    lo |= p0s.astype(U) << U(63)
    hi = p1s.astype(U) | (idx[:, 0].astype(U) << U(1))
    for i in range(1, 16):
        hi |= idx[:, i].astype(U) << U(4 + 4 * (i - 1))
    return np.stack([lo, hi], 1).astype('<u8').tobytes()


def bc7_encode(rgba, chunk=131072):
    px = bc_blocks(rgba)
    return b''.join(bc7_chunk(px[i:i + chunk].astype(np.float32)) for i in range(0, len(px), chunk))


def dds_header(w, h, mips, top_size, fourcc=b'DX10', dxgi=None):
    hd = bytearray(128)
    hd[0:4] = b'DDS '
    struct.pack_into('<7I', hd, 4, 124, 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | 0x80000, h, w, top_size, 0, mips)
    struct.pack_into('<2I', hd, 76, 32, 0x4)
    hd[84:88] = fourcc
    struct.pack_into('<I', hd, 108, 0x401008)
    if fourcc == b'DX10':
        hd += struct.pack('<5I', dxgi, 3, 0, 1, 0)
    return bytes(hd)


def save_bc(arr, path, kind):
    levels = []
    cur = Image.fromarray(arr)
    while True:
        a = np.asarray(cur)
        if kind == 'BC7':
            if a.shape[-1] == 3:
                a = np.concatenate([a, np.full(a.shape[:2] + (1,), 255, np.uint8)], 2)
            levels.append(bc7_encode(a))
        else:
            levels.append(bc5_encode(a[..., 0], a[..., 1]))
        if cur.size == (1, 1):
            break
        cur = cur.resize((max(1, cur.size[0] // 2), max(1, cur.size[1] // 2)), Image.BOX)
    w, h = arr.shape[1], arr.shape[0]
    with open(path, 'wb') as f:
        f.write(dds_header(w, h, len(levels), len(levels[0]), b'DX10', 98 if kind == 'BC7' else 83) + b''.join(levels))


def save_colour_dds(c, path, fmt, flip=True):
    a = np.ascontiguousarray(c[::-1] if flip else c)
    if fmt == 'BC7':
        save_bc(a, path, 'BC7')
    elif fmt == 'DXT5':
        rgba = np.concatenate([a, np.full(a.shape[:2] + (1,), 255, np.uint8)], 2)
        save_mips(Image.fromarray(rgba, 'RGBA'), path, 'DXT5')
    else:
        save_mips(Image.fromarray(a, 'RGB'), path, 'DXT1')


def write_normal_bc5(c, path, strength, flip=True):
    g8, a8 = normal_channels(c, strength)
    rg = np.stack([a8, g8, np.zeros_like(g8)], -1)
    if not flip:
        rg = np.ascontiguousarray(rg[::-1])
    save_bc(rg, path, 'BC5')


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


def has_poles(P):
    return any(p.get('type', 'none') != 'none' for p in P.get('poles', {}).values())


def pole_zone(P):
    z = 0.0
    for key in ('north', 'south'):
        e = pole_entry(P.get('poles', {}).get(key), south=(key == 'south'))
        if e['type'] == 'hexagon':
            z = max(z, 90.0 - float(e['lat']) + 2 * float(e['band_width']) + 6)
        elif e['type'] == 'cyclones':
            z = max(z, 90.0 - float(e['cap_lat']) + 6)
            if int(e['count']) > 0:
                z = max(z, 90.0 - float(e['ring_lat']) + float(e['size']) * 1080 + 6)
            if int(e['centre']):
                z = max(z, float(e['size']) * 1300 + 6)
    return min(z, 90.0)


def needs_rk2(P):
    return bool(P['big_storms']) or bool(P.get('storm_chains')) or any(p.get('type', 'none') != 'none' for p in P.get('poles', {}).values())


def over_pole(x, y):
    lo = y < 0; hi = y > 1
    if lo.any() or hi.any():
        flip = lo | hi
        y = np.where(lo, -y, np.where(hi, 2 - y, y))
        x = np.where(flip, (x + 0.5) % 1.0, x)
    return x, y


def vel_at(KF, K, tt, x, y):
    t = tt * (K - 1); i = min(int(t), K - 2); f = np.float32(t - i)
    a = samp(KF[i], x, y)
    return a + (samp(KF[i + 1], x, y) - a) * f


def trace_step(KF, K, STEPS, n, x, y, dt, rk2=False, adapt=0, W=0, zone=90.0):
    if adapt:
        shp = x.shape
        x = x.ravel(); y = y.ravel()
        v1 = vel_at(KF, K, n / STEPS, x, y)
        la = (np.float32(0.5) - y) * np.float32(np.pi)
        dpx = np.sqrt((v1.real * np.cos(la)) ** 2 + (v1.imag * np.float32(0.5)) ** 2) * dt * np.float32(W)
        m = np.ceil(np.maximum(dpx / np.float32(adapt), np.abs(v1.real) * dt * np.float32(2 * np.pi / 0.1)))
        m = np.clip(m, 1, 16).astype(np.int32)
        m[np.abs(la) < np.float32((90.0 - zone) * D)] = 1
        del la, dpx
        for k in np.unique(m):
            idx = np.nonzero(m == k)[0]
            xs = x[idx]; ys = y[idx]
            h = dt / np.float32(k)
            for j in range(int(k)):
                t0 = (n - j / float(k)) / STEPS
                tm = (n - (j + 0.5) / float(k)) / STEPS
                va = v1[idx] if j == 0 else vel_at(KF, K, t0, xs, ys)
                xm, ym = over_pole((xs - va.real * h * 0.5) % 1.0, ys - va.imag * h * 0.5)
                vb = vel_at(KF, K, tm, xm, ym)
                xs, ys = over_pole((xs - vb.real * h) % 1.0, ys - vb.imag * h)
            x[idx] = xs; y[idx] = ys
        return x.reshape(shp), y.reshape(shp)
    if rk2:
        v1 = samp(kf_at(KF, K, n / STEPS), x, y)
        xm, ym = over_pole((x - v1.real * dt * 0.5) % 1.0, y - v1.imag * dt * 0.5)
        v = samp(kf_at(KF, K, (n - 0.5) / STEPS), xm, ym)
    else:
        v = samp(kf_at(KF, K, (n - 0.5) / STEPS), x, y)
    return over_pole((x - v.real * dt) % 1.0, y - v.imag * dt)


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
        self.big = all_big(P)
        self.glow = glow_list(P)
        self.heat = heat_entry(P.get('heat_glow')) if has_heat(P) else None
        self.poles = []
        for sgn, key in ((1, 'north'), (-1, 'south')):
            e = pole_entry(P.get('poles', {}).get(key), south=(sgn < 0))
            if e['type'] != 'none':
                self.poles.append((sgn, key, e, pole_cyclones(sgn, e) if e['type'] == 'cyclones' else []))
        self.edge_static = {}
        self.polar_cache = None
        self.edge_shift = [None] * len(P['edges'])
        if P.get('band_shapes'):
            cols = (np.arange(self.VW, dtype=np.float32) + 0.5) / self.VW * 360
            E = band_edges(P, cols)
            base = [float(b[0]) for b in P['bands'][1:]]
            for i, ed in enumerate(P['edges']):
                near = [k for k, b in enumerate(base) if abs(b - float(ed['lat'])) < 0.75]
                if near and not np.isscalar(E[near[0]]):
                    sh = (E[near[0]] - base[near[0]]) / np.float32(360)
                    if np.abs(sh).max() > 1e-6:
                        self.edge_shift[i] = sh[None, :].astype(np.float32)
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

    def polar_psi(self, k):
        T1, T2, T3, T4, T5 = self.T
        X, Y, Z, LA, LO = self.X, self.Y, self.Z, self.LA, self.LO
        out = np.zeros_like(LA)
        for sgn, key, e, cyc in self.poles:
            c = np.float32(np.pi / 2) - sgn * LA
            spin = np.float32(1 if float(e['spin']) >= 0 else -1)
            if e['type'] == 'hexagon':
                a = np.float32(max(90.0 - float(e['lat']), 1.0) * D)
                q = hex_q(e, c, LO)
                wq = np.float32(max(float(e['band_width']), 0.3) * D * 1.3) / a
                amp = np.float32(0.25 * float(e['jet'])) * a / np.float32(2 * np.pi) * wq
                out -= spin * amp * np.tanh((q - 1) / wq)
                if float(e['wobble']):
                    out += np.float32(float(e['wobble']) * 0.8) * amp * fbm(T1, X * 7 + 4.1, Y * 7, Z * 7 + 2.3, o=3) * np.exp(-((q - 1) / (2.5 * wq)) ** 2)
                sv = np.float32(0.55) * a / np.float32(2 * np.pi)
                out += spin * np.float32(float(e['turns']) * 5.18) * sv * sv * np.exp(-((c / np.float32(2 * np.pi)) / sv) ** 2)
            else:
                for v, sg in cyc:
                    r = np.arccos(np.clip(X * v[0] + Y * v[1] + Z * v[2], -1, 1)) / np.float32(2 * np.pi)
                    out += spin * np.float32(float(e['turns']) * 5.18) * sg * sg * np.exp(-(r / sg) ** 2)
                if float(e['wobble']):
                    capc = np.float32(max(90.0 - float(e['cap_lat']), 2.0) * D)
                    capm = 1 - ss(capc * np.float32(0.85), capc * np.float32(1.1), c)
                    out += np.float32(float(e['wobble']) * 0.0012) * capm * fbm(T1, X * 6 + 4.1, Y * 6 + 1.7, Z * 6, o=3)
        return out

    def keyframe(self, k):
        P = self.P; T1, T2, T3, T4, T5 = self.T
        X, Y, Z, LA, LO = self.X, self.Y, self.Z, self.LA, self.LO
        o = np.float32(k * 0.41)
        psi = np.zeros_like(LA)
        amul = np.float32(P['curl_strength'])
        for i, ed in enumerate(P['edges']):
            e = ed['lat']; s = ed['spin']; L = ed['width']; r0 = ed['curl']
            en = np.float32(e * np.pi / 180 / (2 * np.pi)) + self.EW
            if self.edge_shift[i] is not None:
                en = en + self.edge_shift[i]
            kk = max(6, int(round(np.cos(e * D) / (P['curl_spacing'] * L))))
            if i not in self.edge_static:
                self.edge_static[i] = (3.2 * fbm(T3, X * 2.4 + i * 3.1, Y * 2.4, Z * 2.4 + i * 1.7, o=3),
                                       np.float32(L) * (1 + 0.45 * fbm(T2, X * 2.6 + i * 1.9, Y * 2.6, Z * 2.6 + i * 0.7, o=2)))
            ph, Lf = self.edge_static[i]
            rho = np.clip(r0 + 0.75 * fbm(T4, X * 3.4 + i * 2.3, Y * 3.4 + o * 0.25, Z * 3.4 + i, o=3), 0.0, 0.85)
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
        if self.poles:
            if self.polar_cache is None:
                self.polar_cache = self.polar_psi(k)
            psi = psi + self.polar_cache
        dpdn = np.zeros_like(psi); dpdn[1:-1] = (psi[:-2] - psi[2:]) / (2 * dn)
        de = self.cosv / self.VW
        dpde = (np.roll(psi, -1, 1) - np.roll(psi, 1, 1)) / (2 * de)
        ue = -dpdn; vn_ = dpde
        dx = (ue + jet) / self.cosv; dy = -2 * vn_
        return (dx + 1j * dy).astype(np.complex64)

    def color(self, x, y, r0=0, r1=None, nb=None):
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
            jit = 0.9 * fbm(T4, XF * 9 + 2.7, YF * 9, ZF * 9, o=3)
            tex = np.clip(0.75 + 1.6 * fbm(T3, XF * 11 + 5.1, YF * 11, ZF * 11, o=3), 0, 1)
        marks = []
        for j, (bs, (r, th)) in enumerate(zip(self.big, pol)):
            c, a = storm_marks(bs, r, th, P['seed'], j, jit)
            marks.append((c, None if a is None else (arm_cover(a), np.float32(0.86) + np.float32(0.28) * tex)))
        del pol, jit, tex
        ps = P['polar_smooth']
        fp = 1 - ss(np.float32(ps[0] * D), np.float32(ps[1] * D), np.abs(la0))
        b = la0 / D + np.float32(P['band_wobble']) * fbm(T2, X0 * 2.2, Y0 * 2.2, Z0 * 2.2, o=3)
        s1, s2 = P['stripes']
        b += fp * (s1 * fbm(T3, X0 * 1.6, Y0 * 1.6, Z0 * 40, o=3) + s2 * fbm(T4, X0 * 3.5, Y0 * 3.5, Z0 * 100, o=2))
        thr = fbm(T5, X0 * 1.2, Y0 * 1.2, Z0 * 170, o=2)
        thw = 0.5 + 0.5 * fbm(T1, X0 * 2.5, Y0 * 2.5, Z0 * 12, o=2)
        ZC = P['bands']
        EG = band_edges(P, x * np.float32(360)) if P.get('band_shapes') else [np.float32(e) for e, _ in ZC[1:]]
        bl = np.float32(P['band_blend']) * (1 + STORM_MIX * mix) if self.big else np.float32(P['band_blend'])
        col = np.empty(b.shape + (3,), np.float32)
        for c in range(3):
            v = np.full(b.shape, ZC[0][1][c], np.float32)
            prev = ZC[0][1][c]
            for e, (_, cc) in zip(EG, ZC[1:]):
                v += (cc[c] - prev) * ss(e - bl, e + bl, b); prev = cc[c]
            col[..., c] = v
        em = None
        if self.glow:
            em = np.zeros(b.shape + (3,), np.float32)
            nb = len(ZC)
            for i, gc in self.glow:
                lo_w = 1 if i == 0 else ss(EG[i - 1] - bl, EG[i - 1] + bl, b)
                hi_w = 0 if i == nb - 1 else ss(EG[i] - bl, EG[i] + bl, b)
                em += np.clip(lo_w - hi_w, 0, 1)[..., None] * np.array(gc, np.float32)
        del EG
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
        if self.poles:
            tts = {}
            gfp = footprint(X0, Y0, Z0, nb)
            for sgn, key, e, cyc in self.poles:
                cap, tex, band, eye = pole_colours(P, key, e)
                c0 = np.float32(np.pi / 2) - sgn * la0
                fq = 9.0 if e['type'] == 'hexagon' else 15.0
                if fq not in tts:
                    tts[fq] = np.clip(0.5 + 1.2 * fbm_lod(T2, X0 * fq + 1.3, Y0 * fq, Z0 * fq, gfp * np.float32(fq), o=4), 0, 1)
                capcol = cap + (tex - cap) * (np.float32(e['texture']) * tts[fq])[..., None]
                if e['type'] == 'hexagon':
                    a = np.float32(max(90.0 - float(e['lat']), 1.0) * D)
                    q = hex_q(e, c0, lo0)
                    bw = np.float32(max(float(e['band_width']), 0.3) * D) / a
                    sq = np.float32(0.35) * bw
                    inner = ss(1 - bw - sq, 1 - bw + sq, q)
                    wi = 1 - inner
                    wb = np.float32(e['band']) * (inner - ss(1 - sq, 1 + sq, q))
                else:
                    capc = np.float32(max(90.0 - float(e['cap_lat']), 2.0) * D)
                    cw = c0 * (1 + np.float32(0.18) * fbm(T4, X0 * 5 + 2.2, Y0 * 5, Z0 * 5, o=3))
                    sd = np.float32(3.0 * D)
                    wi = 1 - ss(capc - sd, capc + sd, cw)
                    wb = np.zeros_like(wi)
                col = col * (1 - wi - wb)[..., None] + capcol * wi[..., None] + band * wb[..., None]
                if em is not None:
                    em *= (1 - wi - wb)[..., None]
            zc = np.float32((90.0 - pole_zone(P)) * D)
            wst = np.clip((gfp / np.float32(2 * np.pi / W) - 4) / 8, 0, 1) * (np.abs(LAf) > zc)
            if wst.any():
                col = col + (box3(box3(col)) - col) * wst[..., None]
            del tts, gfp, wst
        del thr, thw, tl, fp, m, mix
        hp = None
        if self.heat and float(self.heat['patches']):
            hp = np.clip(1 + np.float32(float(self.heat['patches']) * 1.5) * fbm(T3, X0 * 3.3 + 7.7, Y0 * 3.3 + 1.1, Z0 * 3.3, o=3), 0, 2)
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
                aw, at = aw
                ac = np.array(bs.get('arm_color') or bs['core_color'], np.float32)
                col = col * (1 - aw[..., None]) + np.clip(ac * at[..., None], 0, 255) * aw[..., None]
                if em is not None:
                    em *= (1 - aw)[..., None]
            col = col * (1 - w[..., None]) + np.array(bs['core_color'], np.float32) * w[..., None]
            if em is not None:
                em *= (1 - w)[..., None]
        for sgn, key, e, cyc in self.poles:
            if not float(e['eye']):
                continue
            cap, tex, band, eye = pole_colours(P, key, e)
            if e['type'] == 'hexagon':
                a = np.float32(max(90.0 - float(e['lat']), 1.0) * D)
                cf = np.float32(np.pi / 2) - sgn * LAf
                ws = [np.exp(-(cf / (np.float32(max(float(e['eye_size']), 0.02)) * np.float32(0.55) * a)) ** 2)]
            else:
                ws = []
                for v, sg in cyc:
                    r = np.arccos(np.clip(XF * v[0] + YF * v[1] + ZF * v[2], -1, 1))
                    ws.append(np.exp(-(r / (np.float32(max(float(e['eye_size']), 0.02)) * sg * np.float32(2 * np.pi))) ** 2))
            for w in ws:
                w = np.float32(e['eye']) * w
                col = col * (1 - w[..., None]) + eye * w[..., None]
                if em is not None:
                    em *= (1 - w)[..., None]
        if self.heat:
            eh = heat_emission(P, col, LAf, hp)
            em = eh if em is None else em + eh
            del eh, hp
        col = np.clip(col + 0.5, 0, 255).astype(np.uint8)
        if em is not None:
            em = np.clip(em + 0.5, 0, 255).astype(np.uint8)
        return col, em


FLOW_KEYS = ('seed', 'steps', 'keyframes', 'edges', 'curl_strength', 'curl_spacing', 'curl_window', 'jets', 'turbulence',
             'turbulence_scale', 'edge_wobble', 'polar_calm', 'band_shapes')
POLE_FLOW = ('type', 'lat', 'sides', 'roundness', 'rotation', 'jet', 'wobble', 'band_width', 'turns', 'spin', 'ring_lat',
             'count', 'size', 'centre', 'cap_lat')


def flow_key(P):
    d = {k: P.get(k) for k in FLOW_KEYS}
    d['band_lats'] = sorted(float(b[0]) for b in P['bands'])
    st = P.get('storms', {})
    d['storms'] = [st.get(k) for k in ('count', 'lat_range', 'size', 'turns')]
    d['big'] = [[b.get(k) for k in ('lat', 'lon', 'size', 'aspect', 'turns', 'spin', 'ragged')] for b in all_big(P)]
    d['poles'] = {}
    for key in ('north', 'south'):
        e = pole_entry(P.get('poles', {}).get(key), south=(key == 'south'))
        d['poles'][key] = [e[k] for k in POLE_FLOW] if e['type'] != 'none' else 'none'
    return json.dumps(d, sort_keys=True, default=str)


class Cancelled(Exception):
    pass


def live_map(P, W, cache=None, cancel=None):
    H = W // 2
    fld = Field(P, W)
    key = (flow_key(P), W)
    xy = cache.get(key) if cache is not None else None
    if xy is None:
        K = int(P['keyframes'])
        KF = []
        for k in range(K):
            if cancel:
                cancel()
            KF.append(fld.keyframe(k))
        KF = np.stack(KF)
        STEPS = int(P['steps'])
        LA, LO = grid(W, H)
        x = (LO / (2 * np.pi)).astype(np.float32); y = (0.5 - LA / np.pi).astype(np.float32)
        dt = np.float32(1.0 / STEPS)
        rk2 = needs_rk2(P); adapt = 1.0 if has_poles(P) else 0; zone = pole_zone(P)
        for n in range(STEPS, 0, -1):
            if cancel and n % 5 == 0:
                cancel()
            x, y = trace_step(KF, K, STEPS, n, x, y, dt, rk2, adapt, W, zone)
        del KF
        xy = (x, y)
        if cache is not None:
            cache[key] = xy
            while len(cache) > 6:
                cache.pop(next(iter(cache)))
    if cancel:
        cancel()
    c, e = fld.color(xy[0], xy[1])
    c = finish_blur(c, P, W)
    if e is not None:
        e = finish_blur(e, P, W)
    return c, e


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
    h = hashlib.sha1((VERSION + json.dumps({k: v for k, v in raw.items() if k != 'aurora'}, sort_keys=True) + str(res)).encode()).hexdigest()[:12]
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


DDS_BC1 = 'DDS BC1 / DXT1 (KSP default)'
DDS_BC3 = 'DDS BC3 / DXT5 (with alpha)'
DDS_BC7 = 'DDS BC7 (best quality)'
DDS_NM = 'DDS DXT5nm (KSP default)'
DDS_BC5 = 'DDS BC5 (two-channel)'
DDS_CODEC = {DDS_BC1: 'DXT1', DDS_BC3: 'DXT5', DDS_BC7: 'BC7'}
EXPORT_FORMATS = {
    'color': [DDS_BC1, DDS_BC3, DDS_BC7, 'PNG', 'JPG', 'TGA', 'BMP'],
    'normal': [DDS_NM, DDS_BC5, 'PNG'],
    'flow': ['truecolor (EVE)', 'PNG'],
    'emissive': [DDS_BC1, DDS_BC3, DDS_BC7, 'PNG'],
    'preview': ['PNG', 'JPG'],
    'ring': [DDS_BC3, DDS_BC7, 'PNG'],
    'atmo': ['Scatterer cfg'],
    'aurora': [DDS_BC3, 'PNG'],
}
FMT_EXT = {DDS_BC1: '.dds', DDS_BC3: '.dds', DDS_BC7: '.dds', DDS_NM: '.dds', DDS_BC5: '.dds', 'PNG': '.png',
           'JPG': '.jpg', 'TGA': '.tga', 'BMP': '.bmp', 'truecolor (EVE)': '.truecolor', 'Scatterer cfg': '.cfg'}
PIL_FMT = {'PNG': 'PNG', 'JPG': 'JPEG', 'TGA': 'TGA', 'BMP': 'BMP'}


AURORA = {'enabled': False, 'seed': 1, 'north': True, 'south': True,
          'north_tilt': 8.0, 'north_lon': 40.0, 'south_tilt': 10.0, 'south_lon': 215.0,
          'oval': 17.0, 'wobble': 7.0, 'polar_gap': 0.0,
          'curtains': 4, 'spread': 1.0, 'width': 1.5, 'patchy': 0.5, 'rays': 0.65, 'glow': 0.16, 'brightness': 0.9,
          'color': [41, 255, 107], 'edge_color': [242, 97, 217], 'core_color': [140, 255, 204],
          'top_color': [230, 56, 128], 'top_edge_color': [128, 71, 255], 'top_core_color': [255, 128, 191],
          'layers': 7, 'top_layers': 3, 'altitude': 17000.0, 'spacing': 2500.0, 'opacity': 130, 'fade': 0.42,
          'speed': 12.0, 'size': 4096}
AURORA_COLOURS = ('color', 'edge_color', 'core_color', 'top_color', 'top_edge_color', 'top_core_color')
AURORA_SIZES = (1024, 2048, 4096, 8192)
AURORA_CURTAINS = ((0.0, 0.37, 0.68, 1.0), (4.8, 0.42, 0.76, 0.8), (-3.4, 0.46, 0.8, 0.6), (8.5, 0.5, 0.84, 0.5),
                   (-6.8, 0.52, 0.86, 0.42), (12.0, 0.55, 0.88, 0.36))
AURORA_COVERAGE = 'StockVolumetricClouds/Clouds/Textures/PluginData/Kerbin/base/coverage'
AURORA_UVNOISE = 'StockVolumetricClouds/Clouds/Textures/PluginData/uvnoise1'


def aurora_entry(a):
    e = copy.deepcopy(AURORA)
    a = a if isinstance(a, dict) else {}
    for k, v in a.items():
        if k in AURORA:
            e[k] = copy.deepcopy(v)
    for k in ('enabled', 'north', 'south'):
        e[k] = bool(e[k])
    for k in ('north_tilt', 'north_lon', 'south_tilt', 'south_lon', 'oval', 'wobble', 'polar_gap', 'spread', 'width',
              'patchy', 'rays', 'glow', 'brightness', 'altitude', 'spacing', 'fade', 'speed'):
        try:
            e[k] = float(e[k])
        except (TypeError, ValueError):
            e[k] = float(AURORA[k])
    for k in ('seed', 'curtains', 'layers', 'top_layers', 'opacity', 'size'):
        try:
            e[k] = int(round(float(e[k])))
        except (TypeError, ValueError):
            e[k] = int(AURORA[k])
    for k in AURORA_COLOURS:
        try:
            e[k] = [int(max(0, min(255, round(float(c))))) for c in e[k]][:3]
            if len(e[k]) != 3:
                raise ValueError
        except (TypeError, ValueError):
            e[k] = list(AURORA[k])
    e['curtains'] = max(1, min(len(AURORA_CURTAINS), e['curtains']))
    e['layers'] = max(1, min(16, e['layers']))
    e['top_layers'] = max(0, min(e['layers'], e['top_layers']))
    e['opacity'] = max(0, min(255, e['opacity']))
    e['fade'] = max(0.0, min(1.0, e['fade']))
    e['oval'] = max(1.0, min(60.0, e['oval']))
    e['wobble'] = max(0.0, e['wobble'])
    e['polar_gap'] = max(0.0, e['polar_gap'])
    e['spread'] = max(0.1, e['spread'])
    e['width'] = max(0.1, e['width'])
    for k in ('patchy', 'rays'):
        e[k] = max(0.0, min(1.0, e[k]))
    e['glow'] = max(0.0, e['glow'])
    e['brightness'] = max(0.0, min(1.0, e['brightness']))
    e['spacing'] = max(0.0, e['spacing'])
    e['seed'] = max(1, e['seed'])
    if e['size'] not in AURORA_SIZES:
        e['size'] = min(AURORA_SIZES, key=lambda s: abs(s - e['size']))
    return e


def has_aurora(P):
    e = (P.get('aurora') or {})
    return bool(e.get('enabled')) and bool(e.get('north', True) or e.get('south', True))


class AuroraNoise:
    N = 64

    def __init__(self, seed):
        rng = np.random.default_rng(4116 + int(seed))
        self.tabs = [rng.random((self.N, self.N, self.N), dtype=np.float32) for _ in range(8)]

    def vn(self, x, y, z, t):
        T = self.tabs[t]; N = self.N
        xi = np.floor(x).astype(np.int32); yi = np.floor(y).astype(np.int32); zi = np.floor(z).astype(np.int32)
        fx = (x - xi).astype(np.float32); fy = (y - yi).astype(np.float32); fz = (z - zi).astype(np.float32)
        fx = fx * fx * (3 - 2 * fx); fy = fy * fy * (3 - 2 * fy); fz = fz * fz * (3 - 2 * fz)
        x0 = xi % N; y0 = yi % N; z0 = zi % N; x1 = (x0 + 1) % N; y1 = (y0 + 1) % N; z1 = (z0 + 1) % N
        c00 = T[x0, y0, z0] * (1 - fx) + T[x1, y0, z0] * fx
        c10 = T[x0, y1, z0] * (1 - fx) + T[x1, y1, z0] * fx
        c01 = T[x0, y0, z1] * (1 - fx) + T[x1, y0, z1] * fx
        c11 = T[x0, y1, z1] * (1 - fx) + T[x1, y1, z1] * fx
        return (c00 * (1 - fy) + c10 * fy) * (1 - fz) + (c01 * (1 - fy) + c11 * fy) * fz

    def fbm(self, x, y, z, t, o=4):
        s = 0; a = 1.0; n = 0.0
        for i in range(o):
            s = s + a * self.vn(x * 2 ** i + 17.3 * i, y * 2 ** i + 5.1 * i, z * 2 ** i + 9.7 * i, (t + i) % 8)
            n += a; a *= 0.5
        return (s / n) * 2 - 1


def aurora_ss(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def aurora_axis(e, sgn):
    key = 'north' if sgn > 0 else 'south'
    t = np.radians(e[key + '_tilt']); l = np.radians(e[key + '_lon'])
    return np.array([np.sin(t) * np.cos(l), np.sin(t) * np.sin(l), np.cos(t)]) * sgn


def aurora_reach(e):
    offs = [c[0] for c in AURORA_CURTAINS[:e['curtains']]]
    th = e['oval'] + e['wobble'] + 3.0 + 3.6 + 1.1 + max(offs) * e['spread'] + 4 * e['width'] * 1.6 + 8.0
    return th + max(e['north_tilt'], e['south_tilt'])


def aurora_hemi(e, nz, px, py, pz, sgn):
    m = aurora_axis(e, sgn)
    e1 = np.cross(m, [0.3, 0.9, 0.1]); e1 /= np.linalg.norm(e1); e2 = np.cross(m, e1)
    cm = px * m[0] + py * m[1] + pz * m[2]
    th = np.degrees(np.arccos(np.clip(cm, -1, 1))).astype(np.float32)
    cx = px * e1[0] + py * e1[1] + pz * e1[2]; cy = px * e2[0] + py * e2[1] + pz * e2[2]
    r = np.sqrt(cx * cx + cy * cy) + 1e-6; cx = (cx / r).astype(np.float32); cy = (cy / r).astype(np.float32)
    s = float((3 if sgn > 0 else 71) + 13 * (e['seed'] - 1))
    fb = nz.fbm
    th0 = e['oval'] + e['wobble'] * fb(cx * 1.3 + s, cy * 1.3, s * 0.7, 0, 3) + 3.0 * cx
    thw = th + 3.6 * fb(px * 5 + s, py * 5, pz * 5, 1, 4) + 1.1 * fb(px * 13, py * 13 + s, pz * 13, 2, 3)
    rays = 0.5 + 0.5 * fb(cx * 16 + s, cy * 16, th * 0.05, 3, 2)
    rays = (1 - e['rays']) + e['rays'] * aurora_ss(0.25, 0.8, rays)
    rays = rays * (0.75 + 0.25 * (0.5 + 0.5 * fb(cx * 38, cy * 38 + s, th * 0.08, 4, 2)))
    I = np.zeros_like(th); Cv = np.zeros_like(th)
    gd = (e['patchy'] - 0.5) * 0.5
    for k, (off, g0, g1, amp) in enumerate(AURORA_CURTAINS[:e['curtains']]):
        thk = th0 + off * e['spread'] + 2.4 * fb(cx * 2.6 + k * 7.1 + s, cy * 2.6, k * 3.3, 5, 3)
        w = e['width'] * (1 + 0.6 * fb(cx * 3.1 + s, cy * 3.1 + k * 2.2, 1.7, 6, 2))
        gate = aurora_ss(g0 + gd, g1 + gd, 0.5 + 0.5 * fb(cx * 1.9 + k * 11.3, cy * 1.9 + s, k * 1.9, 7, 3))
        d = thw - thk
        prof = np.where(d > 0, np.exp(-(d / w) ** 2), np.exp(-(np.abs(d) / (1.7 * w)) ** 1.6))
        a = amp * gate * prof
        I += a; Cv += a * np.clip(-d / (2.6 * w), 0, 1)
    patch = 0.5 + 0.5 * fb(px * 3 + s, py * 3, pz * 3, 2, 3)
    I = I * rays + e['glow'] * np.exp(-((thw - th0 - 1) / 8) ** 2) * aurora_ss(0.3, 0.7, patch)
    if e['polar_gap'] > 0:
        I = I * aurora_ss(e['polar_gap'] / 3.0, e['polar_gap'], th)
    v = Cv / np.maximum(I, 1e-4)
    return I.astype(np.float32), np.clip(v, 0, 1).astype(np.float32)


def aurora_maps(P, W=None, cancel=None):
    e = aurora_entry(P.get('aurora'))
    W = int(W or e['size']); H = W // 2
    nz = AuroraNoise(e['seed'])
    low = np.zeros((H, W, 4), np.float32); top = np.zeros((H, W, 4), np.float32)
    cl = [np.array(e[k], np.float32) / 255 for k in AURORA_COLOURS]
    low[..., :3] = cl[0]; top[..., :3] = cl[3]
    reach = min(90.0, aurora_reach(e))
    lon = ((np.arange(W) + 0.5) / W * 2 * np.pi).astype(np.float32)
    CH = max(8, min(256, (1 << 21) // W))
    for sgn, on in ((1, e['north']), (-1, e['south'])):
        if not on:
            continue
        rows = np.arange(0, H // 2) if sgn > 0 else np.arange(H // 2, H)
        lat_all = (np.pi / 2 - (rows + 0.5) / H * np.pi).astype(np.float32)
        keep = rows[np.abs(np.degrees(lat_all)) >= 90.0 - reach]
        for c0 in range(0, len(keep), CH):
            if cancel:
                cancel()
            rr = keep[c0:c0 + CH]
            lat = (np.pi / 2 - (rr + 0.5) / H * np.pi).astype(np.float32)
            la, lo = np.meshgrid(lat, lon, indexing='ij')
            px = np.cos(la) * np.cos(lo); py = np.cos(la) * np.sin(lo); pz = np.sin(la)
            I, v = aurora_hemi(e, nz, px, py, pz, sgn)
            a0 = (np.clip(I, 0, 1.25) / 1.25) ** 0.85 * (1 - 0.2 * aurora_ss(0.2, 1.0, v))
            core = aurora_ss(0.55, 1.0, 0.9 * a0)[..., None] * 0.45
            vv = aurora_ss(0.05, 1.0, v)[..., None] * 0.85
            a = np.clip(e['brightness'] * a0, 0, 1)
            for out, (g, pu, cy) in ((low, cl[0:3]), (top, cl[3:6])):
                col = g * (1 - vv) + pu * vv
                out[rr, :, :3] = col * (1 - core) + cy * core
                out[rr, :, 3] = a
    return low, top


def aurora_u8(m):
    return (np.clip(m, 0, 1) * 255 + 0.5).astype(np.uint8)


def aurora_layers(e):
    n = e['layers']
    out = []
    for i in range(n):
        f = i / float(n - 1) if n > 1 else 0.0
        alt = e['altitude'] + e['spacing'] * i
        a = int(round(e['opacity'] * (1 - (1 - e['fade']) * f)))
        out.append((i, alt, a, i >= n - e['top_layers']))
    return out


def aurora_cfg(P, name, tex_low, tex_top):
    e = aurora_entry(P.get('aurora'))
    t = '\t'
    def g(v):
        return ('%.6g' % v)
    L = ['EVE_CLOUDS', '{']
    for i, alt, a, is_top in aurora_layers(e):
        lo = alt - 500; hi = alt + 500
        L += [t + 'OBJECT', t + '{',
              t * 2 + 'name = %s-aurora-%d' % (name, i),
              t * 2 + 'body = ' + name,
              t * 2 + 'altitude = ' + g(alt),
              t * 2 + 'detailSpeed = 0,25,0',
              t * 2 + 'speed = 0,%s,0' % g(e['speed']),
              t * 2 + 'speedMode = LinearSurface',
              t * 2 + 'settings', t * 2 + '{',
              t * 3 + '_UVNoiseTex = ' + AURORA_UVNOISE,
              t * 3 + '_UVNoiseStrength = 0.0012',
              t * 3 + '_Color = 255,255,255,%d' % a,
              t * 3 + '_MainTex', t * 3 + '{',
              t * 4 + 'value = ' + (tex_top if is_top else tex_low),
              t * 4 + 'isClamped = True',
              t * 3 + '}', t * 2 + '}',
              t * 2 + 'layer2D', t * 2 + '{',
              t * 3 + 'macroCloudMaterial', t * 3 + '{',
              t * 4 + '_DetailDist = 2E-06',
              t * 4 + '_MinLight = 1',
              t * 3 + '}', t * 2 + '}',
              t * 2 + 'layerRaymarchedVolumeV5', t * 2 + '{',
              t * 3 + 'scaledFadeStartAltitude = -2000',
              t * 3 + 'scaledFadeEndAltitude = -1000',
              t * 3 + 'coverageMap', t * 3 + '{',
              t * 4 + 'value = ' + AURORA_COVERAGE,
              t * 4 + 'type = AlphaMap',
              t * 4 + 'alphaMask = ALPHAMAP_R',
              t * 3 + '}',
              t * 3 + 'raymarchingSettings', t * 3 + '{',
              t * 4 + 'adaptiveStepSizeFactor = 0',
              t * 4 + 'baseStepSize = 90000000',
              t * 4 + 'maxStepSize = 90000000',
              t * 4 + 'lightMarchDistance = 0',
              t * 4 + 'lightMarchSteps = 0',
              t * 4 + 'fxOnlyLayer = True',
              t * 3 + '}',
              t * 3 + 'cloudTypes', t * 3 + '{',
              t * 4 + 'Item', t * 4 + '{',
              t * 5 + 'typeName = AuroraEmpty',
              t * 5 + 'minAltitude = ' + g(lo),
              t * 5 + 'maxAltitude = ' + g(hi),
              t * 5 + 'interpolateCloudHeights = false',
              t * 5 + 'baseNoiseTiling = 0',
              t * 5 + 'density = 0.0',
              t * 5 + 'lightningFrequency = 0.0',
              t * 5 + 'coverageCurve', t * 5 + '{', t * 6 + 'key = 0 0', t * 5 + '}',
              t * 5 + 'densityCurve', t * 5 + '{', t * 5 + '}',
              t * 4 + '}', t * 3 + '}',
              t * 3 + 'noise', t * 3 + '{', t * 3 + '}',
              t * 3 + 'lightVolumeSettings', t * 3 + '{', t * 4 + 'useLightVolume = False', t * 3 + '}',
              t * 3 + 'phaseFunctions', t * 3 + '{', t * 3 + '}',
              t * 2 + '}', t + '}']
    L.append('}')
    return '\n'.join(L) + '\n'


def aurora_composite(e, low, top, bg):
    o = bg.astype(np.float32)
    al = low[..., 3:4]; at = top[..., 3:4]
    nl = max(1, e['layers'] - e['top_layers']); nt = e['top_layers']
    ol = 1 - (1 - min(1.0, e['opacity'] / 255.0)) ** min(nl, 3)
    ot = (1 - (1 - min(1.0, e['opacity'] * (0.5 + 0.5 * e['fade']) / 255.0)) ** min(nt, 3)) * 0.6 if nt else 0.0
    o = o * (1 - al * ol) + low[..., :3] * al * ol
    o = o * (1 - at * ot) + top[..., :3] * at * ot
    return o


def aurora_preview(P, low, top, bg=None, S=420):
    e = aurora_entry(P.get('aurora'))
    H, W = low.shape[:2]
    offs = [c[0] for c in AURORA_CURTAINS[:e['curtains']]]
    reach = min(89.0, e['oval'] + e['wobble'] + max(offs) * e['spread'] + 3 * e['width'] + max(e['north_tilt'], e['south_tilt']) + 6)
    yy, xx = np.mgrid[0:S, 0:S]
    X = (xx - S / 2 + 0.5) / (S / 2); Y = (yy - S / 2 + 0.5) / (S / 2); R = np.sqrt(X * X + Y * Y)
    if bg is not None:
        bgf = np.asarray(Image.fromarray(np.asarray(bg, np.uint8)).resize((W, H), Image.BILINEAR), np.float32) / 255 * 0.08
    else:
        bgf = np.zeros((H, W, 3), np.float32) + np.array([0.02, 0.03, 0.06], np.float32)
    panels = []
    for sgn in (1, -1):
        col = np.radians(R * reach)
        lo = (np.arctan2(Y, X) * sgn) % (2 * np.pi)
        fy = (col / np.pi if sgn > 0 else 1 - col / np.pi) * H
        py_ = np.clip(fy, 0, H - 1).astype(int); px_ = np.clip(lo / (2 * np.pi) * W, 0, W - 1).astype(int)
        o = aurora_composite(e, low[py_, px_], top[py_, px_], bgf[py_, px_])
        edge = np.clip((1 - R) * S / 2, 0, 1)[..., None]
        o = o * edge + np.array([13, 15, 20], np.float32) / 255 * (1 - edge)
        panels.append(o)
    gap = np.zeros((S, 24, 3), np.float32) + np.array([13, 15, 20], np.float32) / 255
    pv = np.concatenate([panels[0], gap, panels[1]], 1)
    return Image.fromarray(aurora_u8(pv))


def save_aurora(m, path, fmt, flip=True):
    u = aurora_u8(m)
    if path.lower().endswith('.dds'):
        if flip:
            u = np.ascontiguousarray(u[::-1])
        save_mips(Image.fromarray(u, 'RGBA'), path, 'DXT5')
    else:
        Image.fromarray(u, 'RGBA').save(path, 'PNG')

def gamedata_rel(d):
    d = os.path.abspath(d)
    parts = d.split(os.sep)
    low = [p.lower() for p in parts]
    if 'gamedata' in low:
        i = len(low) - 1 - low[::-1].index('gamedata')
        rest = parts[i + 1:]
        if rest:
            return '/'.join(rest)
    return ''


def default_cfg_path(folder):
    rel = gamedata_rel(folder) if folder else ''
    if not rel:
        td = texture_dir()
        rel = gamedata_rel(td) if td else ''
    return rel or 'MyMod/Textures'


def tex_path(folder, fname, base=None):
    rel = default_cfg_path(folder) if base is None else base.strip().replace('\\', '/').strip('/')
    return (rel + '/' if rel else '') + fname


def export_target(folder, base, fmt):
    return os.path.join(folder, base + FMT_EXT[fmt])


def planets_file(folder, name):
    return os.path.join(folder, 'planetsList_%s.cfg' % name)


def aurora_files(folder, base, fmt):
    ext = FMT_EXT[fmt]
    return (os.path.join(folder, base + ext), os.path.join(folder, base + '_top' + ext), os.path.join(folder, base + '.cfg'))


def export_aurora(P, name, base, fmt, folder, flip=True, log=print, cfg_path=None, cancel=None):
    lp, tp, cp = aurora_files(folder, base, fmt)
    log('making the aurora at %d x %d' % (aurora_entry(P.get('aurora'))['size'], aurora_entry(P.get('aurora'))['size'] // 2))
    low, top = aurora_maps(P, cancel=cancel)
    save_aurora(low, lp, fmt, flip)
    save_aurora(top, tp, fmt, flip)
    del low, top
    with open(cp, 'w', newline='\n') as f:
        f.write(aurora_cfg(P, name, tex_path(folder, base, cfg_path), tex_path(folder, base + '_top', cfg_path)))
    return [lp, tp, cp]


def export_maps(src_dir, name, P, jobs, folder, size=None, flip=True, log=print):
    os.makedirs(folder, exist_ok=True)
    c = None
    if any(k not in ('atmo', 'preview', 'ring', 'aurora') for k, _, _ in jobs):
        c = np.asarray(Image.open(os.path.join(src_dir, name + '_color.png')).convert('RGB'))
        if size and size != c.shape[1]:
            c = np.asarray(Image.fromarray(c).resize((size, size // 2), Image.LANCZOS))
    written = []
    for kind, base, fmt in jobs:
        path = export_target(folder, base, fmt)
        if kind == 'aurora':
            if not has_aurora(P):
                log('no aurora on this planet - skipped')
                continue
            for w in export_aurora(P, name, base, fmt, folder, flip, log):
                written.append(w)
                log('exported ' + w)
            continue
        if kind == 'atmo':
            if not has_atmo(P):
                log('no atmosphere on this planet - skipped')
                continue
            with open(path, 'w', newline='\n') as f:
                f.write(atmo_cfg(P, name))
            pl = planets_file(folder, name)
            with open(pl, 'w', newline='\n') as f:
                f.write(atmo_planets(P, name))
            written.append(pl)
            log('exported ' + pl)
        elif kind == 'color':
            if fmt.startswith('DDS'):
                save_colour_dds(c, path, DDS_CODEC.get(fmt, 'DXT1'), flip)
            elif fmt == 'JPG':
                Image.fromarray(c).save(path, 'JPEG', quality=95)
            else:
                Image.fromarray(c).save(path, PIL_FMT[fmt])
        elif kind == 'normal':
            if fmt == DDS_BC5:
                write_normal_bc5(c, path, float(P['normal_strength']), flip)
            elif fmt.startswith('DDS'):
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
                save_colour_dds(e, path, DDS_CODEC.get(fmt, 'DXT1'), flip)
            else:
                Image.fromarray(e).save(path, 'PNG')
        elif kind == 'ring':
            rp = os.path.join(src_dir, name + '_ring.png')
            if not os.path.isfile(rp):
                log('no ring texture in this build - skipped')
                continue
            r = np.asarray(Image.open(rp).convert('RGBA'))
            if fmt == DDS_BC7:
                save_bc(np.ascontiguousarray(r), path, 'BC7')
            elif fmt.startswith('DDS'):
                save_mips(Image.fromarray(r, 'RGBA'), path, 'DXT5')
            else:
                Image.fromarray(r, 'RGBA').save(path, 'PNG')
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


def render_sphere(tex, S, tilt, vlat, vlon, emis=None, light=None):
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
    L = np.array(light or [0.55, 0.25, 0.8], float); L /= np.linalg.norm(L)
    nd = np.clip(u * L[0] + v * L[1] + z * L[2], 0, 1)
    c = c * ((0.06 if light else 0.18) + 0.95 * nd ** 0.8)[..., None]
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
    if has_atmo(P):
        t2 = tex if tex.shape[1] <= 2048 else np.asarray(Image.fromarray(cimg).resize((2048, 1024), Image.LANCZOS)).astype(np.float32) / 255
        e2 = em if em is None or em.shape[1] <= 2048 else np.asarray(Image.fromarray(eimg).resize((2048, 1024), Image.LANCZOS)).astype(np.float32) / 255
        sheet.paste(render_atmo(P, t2, e2, view='planet', w=800, h=800, steps=24), (0, 0))
    else:
        sheet.paste(render_sphere(tex, 800, pv['tilt'], pv['view_lat'], pv['view_lon'], em, NIGHT_LIGHT if has_heat(P) else None), (0, 0))
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
        glows = has_emission(P)
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
            rk2 = needs_rk2(P)
            adapt = 1.0 if has_poles(P) else 0
            zone = pole_zone(P)
            bi, n = st.get('b', 0), st['n']
            last = -1
            while bi < NB:
                r0, r1 = bi * BR, min(H, (bi + 1) * BR)
                x = np.array(xm[r0:r1]); y = np.array(ym[r0:r1])
                try:
                    while n > 0:
                        need(clock, res, 'step', (r1 - r0) * W * (3 if adapt else 2 if rk2 else 1))
                        x, y = trace_step(KF, K, STEPS, n, x, y, dt, rk2, adapt, W, zone)
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
                nb = None
                if fld.poles:
                    nb = ((np.array(xm[r0 - 1]), np.array(ym[r0 - 1])) if r0 > 0 else None,
                          (np.array(xm[r1]), np.array(ym[r1])) if r1 < H else None)
                cb, eb = fld.color(np.array(xm[r0:r1]), np.array(ym[r0:r1]), r0, r1, nb)
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
            ring_png = os.path.join(od, name + '_ring.png')
            if has_rings(P):
                Image.fromarray(ring_image(P), 'RGBA').save(ring_png)
            elif os.path.isfile(ring_png):
                os.remove(ring_png)
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
    pick = {'color': {'dds': DDS_BC1, 'bc1': DDS_BC1, 'bc3': DDS_BC3, 'bc7': DDS_BC7, 'png': 'PNG', 'jpg': 'JPG', 'tga': 'TGA', 'bmp': 'BMP'},
            'normal': {'dds': DDS_NM, 'bc5': DDS_BC5, 'png': 'PNG'},
            'flow': {'truecolor': 'truecolor (EVE)', 'png': 'PNG'},
            'emissive': {'dds': DDS_BC1, 'bc1': DDS_BC1, 'bc3': DDS_BC3, 'bc7': DDS_BC7, 'png': 'PNG'},
            'preview': {'png': 'PNG', 'jpg': 'JPG'},
            'ring': {'dds': DDS_BC3, 'bc3': DDS_BC3, 'bc7': DDS_BC7, 'png': 'PNG'},
            'atmo': {'cfg': 'Scatterer cfg'},
            'aurora': {'dds': DDS_BC3, 'png': 'PNG'}}
    jobs = []
    for kind in ('color', 'normal', 'flow', 'emissive', 'preview', 'ring', 'atmo', 'aurora'):
        f = getattr(a, kind)
        if f and f != 'none':
            if kind == 'atmo' and not has_atmo(P):
                continue
            if kind == 'aurora' and not has_aurora(P):
                continue
            jobs.append((kind, '%s_%s' % (name, kind), pick[kind][f]))
    export_maps(src, name, P, jobs, a.to, a.size or None, not a.no_flip)


def cmd_install(a):
    P, raw = load_preset(a.preset)
    od = out_dir(P, a.res)
    name = P['name']
    src = {'color': name + '_color.dds', 'normal': name + '_normal.dds', 'flow': name + '_flow.truecolor', 'emissive': name + '_emissive.dds',
           'ring': name + '_ring.png'}
    what = [w for w in (a.only.split(',') if a.only else ['color', 'normal', 'flow', 'emissive', 'ring']) if P['files'].get(w)]
    if 'emissive' in what and not has_emission(P):
        what.remove('emissive')
    if 'ring' in what and not has_rings(P):
        what.remove('ring')
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
        if w == 'ring' and dst.lower().endswith('.dds'):
            save_mips(Image.open(os.path.join(od, src[w])).convert('RGBA'), dst, 'DXT5')
        else:
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
    if raw.get('emission') or has_heat(raw):
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
    e.add_argument('--color', default='dds', choices=['dds', 'bc1', 'bc3', 'bc7', 'png', 'jpg', 'tga', 'bmp', 'none'])
    e.add_argument('--normal', default='dds', choices=['dds', 'bc5', 'png', 'none'])
    e.add_argument('--flow', default='truecolor', choices=['truecolor', 'png', 'none'])
    e.add_argument('--emissive', default='dds', choices=['dds', 'bc1', 'bc3', 'bc7', 'png', 'none'])
    e.add_argument('--preview', default='none', choices=['png', 'jpg', 'none'])
    e.add_argument('--ring', default='dds', choices=['dds', 'bc3', 'bc7', 'png', 'none'])
    e.add_argument('--atmo', default='cfg', choices=['cfg', 'none'])
    e.add_argument('--aurora', default='dds', choices=['dds', 'png', 'none'])
    e.add_argument('--size', type=int, default=0); e.add_argument('--no-flip', action='store_true')
    a = ap.parse_args()
    r = {'make': cmd_make, 'install': cmd_install, 'sample': cmd_sample, 'new': cmd_new, 'flow': cmd_flow, 'export': cmd_export}[a.cmd](a)
    sys.exit(r or 0)


if __name__ == '__main__':
    main()
