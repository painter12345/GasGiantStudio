import sys, os, io, json, copy, time, shutil, struct, hashlib, tempfile, argparse
import numpy as np
from PIL import Image, ImageFilter, ImageDraw
Image.MAX_IMAGE_PIXELS = None

APP_NAME = 'Gas Giant Studio'
APP_VERSION = '1.1.6'
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
    'band_shapes': [],
    'poles': {'north': {'type': 'none'}, 'south': {'type': 'none'}},
    'heat_glow': {'strength': 0.0},
    'storm_chains': [],
    'rings': {'enabled': False},
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
                ac = bs.get('arm_color') or bs['core_color']
                col = col * (1 - aw[..., None]) + np.array(ac, np.float32) * aw[..., None]
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
}
FMT_EXT = {DDS_BC1: '.dds', DDS_BC3: '.dds', DDS_BC7: '.dds', DDS_NM: '.dds', DDS_BC5: '.dds', 'PNG': '.png',
           'JPG': '.jpg', 'TGA': '.tga', 'BMP': '.bmp', 'truecolor (EVE)': '.truecolor'}
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
            'ring': {'dds': DDS_BC3, 'bc3': DDS_BC3, 'bc7': DDS_BC7, 'png': 'PNG'}}
    jobs = []
    for kind in ('color', 'normal', 'flow', 'emissive', 'preview', 'ring'):
        f = getattr(a, kind)
        if f and f != 'none':
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
    e.add_argument('--size', type=int, default=0); e.add_argument('--no-flip', action='store_true')
    a = ap.parse_args()
    r = {'make': cmd_make, 'install': cmd_install, 'sample': cmd_sample, 'new': cmd_new, 'flow': cmd_flow, 'export': cmd_export}[a.cmd](a)
    sys.exit(r or 0)


if __name__ == '__main__':
    main()
