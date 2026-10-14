import os, sys, json, copy, queue, random, threading, subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser, simpledialog
import numpy as np
from PIL import Image, ImageTk, ImageDraw
try:
    import PIL._tkinter_finder
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gasgiant as gg

GEN = os.path.join(gg.TOOL, 'gasgiant.py')
RES = ['512', '1024', '2048', '4096', '8192', '16384']
RES_INFO = {'512': 'about 10 s', '1024': 'about 30 s', '2048': 'about 1\u20132 min',
            '4096': 'about 4 min', '8192': 'about 20\u201340 min', '16384': 'about 1\u20133 hours'}
BG = '#1b1f27'
PANEL = '#232934'
FIELD = '#2c3340'
FG = '#d9dee8'
DIM = '#8a93a6'
ACC = '#6fa8ff'
WARM = '#ffb36b'
LINE = '#3a4252'
NOWIN = 0x08000000 if os.name == 'nt' else 0
FONT = 'Segoe UI' if os.name == 'nt' else 'DejaVu Sans'
MONO = 'Consolas' if os.name == 'nt' else 'DejaVu Sans Mono'


SETTINGS = os.path.join(gg.TOOL, 'studio_settings.json')


def load_settings():
    try:
        with open(SETTINGS) as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(d):
    try:
        with open(SETTINGS, 'w') as f:
            json.dump(d, f, indent=1)
    except Exception:
        pass


def open_folder(d):
    if os.name == 'nt':
        os.startfile(d)
    else:
        subprocess.Popen(['xdg-open', d])


def hexcol(c):
    return '#%02x%02x%02x' % tuple(int(max(0, min(255, round(v)))) for v in c)


def getp(d, path):
    for k in path:
        d = d[k]
    return d


def setp(d, path, v):
    for k in path[:-1]:
        d = d[k]
    d[path[-1]] = v


def smooth(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def sorted_copy(P):
    Q = {'bands': copy.deepcopy(P['bands']), 'emission': copy.deepcopy(P.get('emission', [])),
         'band_shapes': copy.deepcopy(P.get('band_shapes', [])), 'band_blend': P['band_blend']}
    gg.sort_bands(Q)
    return Q


def band_image(P, w, h):
    lat = 90 - (np.arange(h) + 0.5) / h * 180
    Q = sorted_copy(P)
    bands = Q['bands']
    bl = max(float(P['band_blend']), 0.01)
    lonc = (np.arange(w) + 0.5) / w * 360
    E = gg.band_edges(Q, lonc.astype(np.float32))
    shaped = any(not np.isscalar(e) for e in E)
    if shaped:
        E2 = [np.broadcast_to(np.asarray(e, float), (w,))[None, :] for e in E]
        la = lat[:, None]
        img = np.zeros((h, w, 3))
        for c in range(3):
            v = np.full((h, w), float(bands[0][1][c]))
            prev = bands[0][1][c]
            for e, (_, cc) in zip(E2, bands[1:]):
                v += (cc[c] - prev) * smooth(e - bl, e + bl, la)
                prev = cc[c]
            img[..., c] = v
    else:
        col = np.zeros((h, 3))
        for c in range(3):
            v = np.full(h, float(bands[0][1][c]))
            prev = bands[0][1][c]
            for e, cc in bands[1:]:
                v += (cc[c] - prev) * smooth(e - bl, e + bl, lat)
                prev = cc[c]
            col[:, c] = v
        img = np.repeat(col[:, None, :], w, 1)
    lon = (np.arange(w) + 0.5) / w * 360
    LA, LO = np.meshgrid(lat, lon, indexing='ij')
    if gg.has_poles(P):
        img = gg.pole_preview({'bands': bands, 'poles': P.get('poles', {})}, np.radians(LA).astype(np.float32),
                              np.radians(LO).astype(np.float32), img.astype(np.float32))
    for k, s in enumerate(P.get('big_storms', [])):
        s = gg.big_storm(s)
        r, th = gg.storm_polar(s, np.radians(LA).astype(np.float32), np.radians(LO).astype(np.float32), P.get('seed', 1), k)
        wgt, arm = gg.storm_marks(s, r, th, P.get('seed', 1), k)
        if arm is not None:
            img = img * (1 - arm[..., None]) + np.array(s.get('arm_color') or s['core_color'], float) * arm[..., None]
        img = img * (1 - wgt[..., None]) + np.array(s['core_color'], float) * wgt[..., None]
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


def glow_image(P, w, h):
    Q = sorted_copy(P)
    bands = Q['bands']
    if not Q['emission'] or not bands:
        return None
    lat = (90 - (np.arange(h) + 0.5) / h * 180)[:, None]
    bl = max(float(P['band_blend']), 0.01)
    E = [np.broadcast_to(np.asarray(e, float), (w,))[None, :] for e in gg.band_edges(Q, ((np.arange(w) + 0.5) / w * 360).astype(np.float32))]
    out = np.zeros((h, w, 3))
    n = len(bands)
    for em in Q['emission']:
        i = int(em.get('band', -1))
        if not 0 <= i < n:
            continue
        lo_w = 1 if i == 0 else smooth(E[i - 1] - bl, E[i - 1] + bl, lat)
        hi_w = 0 if i == n - 1 else smooth(E[i] - bl, E[i] + bl, lat)
        c = np.array(em.get('color') or bands[i][1], float) * float(em.get('brightness', 1.0))
        out += np.clip(lo_w - hi_w, 0, 1)[..., None] * c
    return out if out.any() else None


def pole_disc(img, sgn, size, cmax=32.0):
    a = np.asarray(img).astype(np.float32)
    H, W = a.shape[:2]
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    u = (xx + 0.5) / size * 2 - 1
    v = 1 - (yy + 0.5) / size * 2
    rr = np.sqrt(u * u + v * v)
    az = np.degrees(np.arctan2(v * sgn, u)) % 360
    lat = sgn * (90 - rr * cmax)
    fy = np.clip((90 - lat) / 180 * H - 0.5, 0, H - 1.001)
    fx = az / 360 * W - 0.5
    x0 = np.floor(fx).astype(int); y0 = np.floor(fy).astype(int)
    tx = (fx - x0)[..., None]; ty = (fy - y0)[..., None]
    x0 %= W; x1 = (x0 + 1) % W; y1 = np.minimum(y0 + 1, H - 1)
    c = (a[y0, x0] * (1 - tx) + a[y0, x1] * tx) * (1 - ty) + (a[y1, x0] * (1 - tx) + a[y1, x1] * tx) * ty
    alpha = np.clip((1 - rr) * size / 2, 0, 1)[..., None]
    c = c * alpha + np.array([13, 15, 20], np.float32) * (1 - alpha)
    return Image.fromarray(np.clip(c, 0, 255).astype(np.uint8))


def band_labels(bands):
    def f(v):
        return ('%.1f' % v).rstrip('0').rstrip('.')
    out = []
    for i, b in enumerate(bands):
        above = [x[0] for x in bands if x[0] > b[0]]
        out.append('%d:  %s\u00b0 to %s\u00b0' % (i + 1, f(b[0]), f(min(above) if above else 90)))
    return out


def make_style(root):
    st = ttk.Style(root)
    st.theme_use('clam')
    st.configure('.', background=BG, foreground=FG, fieldbackground=FIELD, bordercolor=LINE, lightcolor=PANEL,
                 darkcolor=BG, troughcolor=FIELD, focuscolor=ACC, selectbackground=ACC, selectforeground='#0b1020',
                 insertcolor=FG, font=(FONT, 10))
    st.configure('TFrame', background=BG)
    st.configure('Card.TFrame', background=PANEL)
    st.configure('Bar.TFrame', background=PANEL)
    st.configure('TLabel', background=BG, foreground=FG)
    st.configure('Dim.TLabel', background=BG, foreground=DIM)
    st.configure('Bar.TLabel', background=PANEL, foreground=FG)
    st.configure('BarDim.TLabel', background=PANEL, foreground=DIM)
    st.configure('CardDim.TLabel', background=PANEL, foreground=DIM)
    st.configure('CardHead.TLabel', background=PANEL, foreground=FG, font=(FONT, 11, 'bold'))
    st.configure('Head.TLabel', background=BG, foreground=FG, font=(FONT, 11, 'bold'))
    st.configure('Title.TLabel', background=PANEL, foreground=FG, font=(FONT, 12, 'bold'))
    st.configure('TButton', background=PANEL, foreground=FG, padding=(10, 4), bordercolor=LINE)
    st.map('TButton', background=[('disabled', BG), ('active', '#2f3746')], foreground=[('disabled', '#5a6272')])
    st.configure('Accent.TButton', background='#2d5fa8', foreground='white')
    st.map('Accent.TButton', background=[('disabled', '#253246'), ('active', '#3a72c4')])
    st.configure('Small.TButton', padding=(5, 1))
    st.configure('TNotebook', background=BG, bordercolor=LINE, tabmargins=(4, 6, 4, 0))
    st.configure('TNotebook.Tab', background=PANEL, foreground=DIM, padding=(12, 5), bordercolor=LINE)
    st.map('TNotebook.Tab', background=[('selected', BG)], foreground=[('selected', FG)])
    st.configure('TLabelframe', background=BG, bordercolor=LINE)
    st.configure('TLabelframe.Label', background=BG, foreground=DIM)
    st.configure('TEntry', fieldbackground=FIELD, foreground=FG)
    st.configure('TSpinbox', fieldbackground=FIELD, foreground=FG, arrowcolor=FG, background=PANEL)
    st.configure('TCombobox', fieldbackground=FIELD, foreground=FG, arrowcolor=FG, background=PANEL)
    st.map('TCombobox', fieldbackground=[('readonly', FIELD)], foreground=[('readonly', FG)],
           selectbackground=[('readonly', FIELD)], selectforeground=[('readonly', FG)])
    st.configure('Horizontal.TScale', background=PANEL, troughcolor=FIELD, bordercolor=LINE)
    st.configure('TCheckbutton', background=BG, foreground=FG)
    st.map('TCheckbutton', background=[('active', BG)])
    st.configure('Toolbutton', background=PANEL, foreground=DIM, padding=(10, 4))
    st.map('Toolbutton', background=[('selected', '#2d5fa8'), ('active', '#2f3746')], foreground=[('selected', 'white')])
    st.configure('Horizontal.TProgressbar', background=ACC, troughcolor=FIELD, bordercolor=LINE, lightcolor=ACC, darkcolor=ACC)
    st.configure('Vertical.TScrollbar', background=PANEL, troughcolor=BG, arrowcolor=DIM, bordercolor=BG,
                 lightcolor=PANEL, darkcolor=PANEL, gripcount=0)
    st.map('Vertical.TScrollbar', background=[('active', '#3a4456')])
    root.option_add('*TCombobox*Listbox.background', FIELD)
    root.option_add('*TCombobox*Listbox.foreground', FG)
    root.option_add('*TCombobox*Listbox.selectBackground', ACC)


class ScrollFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, bg=BG)
        self.vsb = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, padding=(4, 6, 8, 12))
        self.inner.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self.win, width=e.width))
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.vsb.pack(side='right', fill='y')
        self.bind('<Enter>', self._on)
        self.bind('<Leave>', self._off)

    def _on(self, _e=None):
        self.canvas.bind_all('<MouseWheel>', self._wheel)
        self.canvas.bind_all('<Button-4>', lambda e: self.canvas.yview_scroll(-2, 'units'))
        self.canvas.bind_all('<Button-5>', lambda e: self.canvas.yview_scroll(2, 'units'))

    def _off(self, _e=None):
        self.canvas.unbind_all('<MouseWheel>')
        self.canvas.unbind_all('<Button-4>')
        self.canvas.unbind_all('<Button-5>')

    def _wheel(self, e):
        self.canvas.yview_scroll(-1 * int(e.delta / 120) if abs(e.delta) >= 120 else (-1 if e.delta > 0 else 1), 'units')


class Slider:
    def __init__(self, app, parent, row, label, path, lo, hi, step, isint=False, tip=None, src=None, notify=None, registry=None):
        self.app, self.path, self.lo, self.hi, self.step, self.isint = app, path, lo, hi, step, isint
        self.src = src or (lambda: app.P)
        self.notify = notify or app.changed
        self.busy = False
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', padx=(8, 8), pady=(4, 0))
        self.var = tk.DoubleVar()
        self.scale = ttk.Scale(parent, from_=lo, to=hi, orient='horizontal', variable=self.var, command=self.moved)
        self.scale.grid(row=row, column=1, sticky='ew', pady=(4, 0))
        self.txt = tk.StringVar()
        en = ttk.Entry(parent, textvariable=self.txt, width=9, justify='right')
        en.grid(row=row, column=2, padx=(8, 4), pady=(4, 0))
        en.bind('<Return>', self.typed)
        en.bind('<FocusOut>', self.typed)
        if tip:
            ttk.Label(parent, text=tip, style='Dim.TLabel', font=(FONT, 8)).grid(row=row + 1, column=0, columnspan=3, sticky='w', padx=(8, 0))
        (registry if registry is not None else app.sliders).append(self)

    def fmt(self, v):
        if self.isint:
            return str(int(round(v)))
        dec = max(0, -int(np.floor(np.log10(self.step)))) if self.step < 1 else 0
        return ('%.' + str(dec) + 'f') % v

    def snap(self, v):
        v = round(v / self.step) * self.step
        return int(round(v)) if self.isint else float(self.fmt(v))

    def refresh(self):
        v = getp(self.src(), self.path)
        self.busy = True
        self.var.set(min(max(v, self.lo), self.hi))
        self.txt.set(self.fmt(v))
        self.busy = False

    def moved(self, _=None):
        if self.busy:
            return
        v = self.snap(self.var.get())
        self.txt.set(self.fmt(v))
        if v != getp(self.src(), self.path):
            setp(self.src(), self.path, v)
            self.notify()

    def typed(self, _=None):
        try:
            v = self.snap(float(self.txt.get().replace(',', '.')))
        except ValueError:
            self.refresh()
            return
        self.busy = True
        self.var.set(min(max(v, self.lo), self.hi))
        self.busy = False
        self.txt.set(self.fmt(v))
        if v != getp(self.src(), self.path):
            setp(self.src(), self.path, v)
            self.notify()


class Swatch:
    def __init__(self, app, parent, path):
        self.app, self.path = app, path
        self.lab = tk.Label(parent, width=6, relief='solid', bd=1, cursor='hand2')
        self.lab.bind('<Button-1>', self.pick)
        app.swatches.append(self)

    def refresh(self):
        self.lab.configure(bg=hexcol(getp(self.app.P, self.path)))

    def pick(self, _e=None):
        c = colorchooser.askcolor(color=hexcol(getp(self.app.P, self.path)), parent=self.app)
        if c and c[0]:
            setp(self.app.P, self.path, [int(round(x)) for x in c[0]])
            self.refresh()
            self.app.changed()


def num(label, key, lo, hi, inc, fmt, default=0.0, isint=False, width=7):
    def g(it):
        return it[key] if isinstance(it, list) else it.get(key, default)

    def s(it, v):
        it[key] = v
    return {'label': label, 'get': g, 'set': s, 'lo': lo, 'hi': hi, 'inc': inc, 'fmt': fmt, 'int': isint, 'width': width}


def colf(label, key, default=(128, 128, 128)):
    def g(it):
        return it[key] if isinstance(it, list) else it.get(key, list(default))

    def s(it, v):
        it[key] = v
    return {'label': label, 'get': g, 'set': s, 'kind': 'color'}


def spinf(label, key, default=1):
    def g(it):
        return it.get(key, default)

    def s(it, v):
        it[key] = v
    return {'label': label, 'get': g, 'set': s, 'kind': 'choice', 'values': ['1', '-1'], 'conv': int}


class ListEditor:
    def __init__(self, app, parent, items_fn, fields, new_item, card=False, cols=5, add_text='Add', notify=None, registry=None, on_remove=None):
        self.app, self.items_fn, self.fields, self.new_item, self.card, self.cols = app, items_fn, fields, new_item, card, cols
        self.notify = notify or app.changed
        self.on_remove = on_remove
        self.frame = ttk.Frame(parent)
        self.body = ttk.Frame(self.frame)
        self.body.pack(fill='x')
        self.bar = ttk.Frame(self.frame)
        self.bar.pack(fill='x', pady=(6, 0))
        ttk.Button(self.bar, text=add_text, command=self.add).pack(side='left')
        (registry if registry is not None else app.editors).append(self)

    def rebuild(self):
        for w in self.body.winfo_children():
            w.destroy()
        items = self.items_fn()
        if not self.card:
            if items:
                for j, f in enumerate(self.fields):
                    ttk.Label(self.body, text=f['label'], style='Dim.TLabel').grid(row=0, column=j, padx=4, sticky='w')
            for i, it in enumerate(items):
                for j, f in enumerate(self.fields):
                    self.widget(self.body, it, f).grid(row=i + 1, column=j, padx=4, pady=2, sticky='w')
                ttk.Button(self.body, text='✕', width=3, style='Small.TButton',
                           command=lambda i=i: self.remove(i)).grid(row=i + 1, column=len(self.fields), padx=4)
        else:
            for i, it in enumerate(items):
                card = ttk.Frame(self.body, style='Card.TFrame', padding=8)
                card.pack(fill='x', pady=4)
                for j, f in enumerate(self.fields):
                    r, c = divmod(j, self.cols)
                    ttk.Label(card, text=f['label'], style='CardDim.TLabel').grid(row=r * 2, column=c, sticky='w', padx=4)
                    self.widget(card, it, f).grid(row=r * 2 + 1, column=c, sticky='w', padx=4, pady=(0, 6))
                ttk.Button(card, text='✕', width=3, style='Small.TButton',
                           command=lambda i=i: self.remove(i)).grid(row=1, column=self.cols, padx=(2, 0), sticky='w')

    def widget(self, parent, item, f):
        kind = f.get('kind', 'num')
        if kind == 'custom':
            return f['make'](parent, item)
        if kind == 'color':
            lab = tk.Label(parent, bg=hexcol(f['get'](item)), width=6, relief='solid', bd=1, cursor='hand2')

            def pick(_e=None, lab=lab):
                c = colorchooser.askcolor(color=hexcol(f['get'](item)), parent=self.app)
                if c and c[0]:
                    v = [int(round(x)) for x in c[0]]
                    f['set'](item, v)
                    lab.configure(bg=hexcol(v))
                    self.notify()
            lab.bind('<Button-1>', pick)
            return lab
        if kind == 'choice':
            var = tk.StringVar(value=str(f['get'](item)))
            cb = ttk.Combobox(parent, textvariable=var, values=f['values'], width=4, state='readonly')

            def sel(_e=None, var=var):
                f['set'](item, f.get('conv', str)(var.get()))
                self.notify()
            cb.bind('<<ComboboxSelected>>', sel)
            return cb
        fmt = f['fmt']
        var = tk.StringVar(value=fmt % f['get'](item))
        sp = ttk.Spinbox(parent, textvariable=var, from_=f['lo'], to=f['hi'], increment=f['inc'], width=f['width'], format=fmt)

        def commit(_e=None, var=var):
            try:
                v = float(var.get().replace(',', '.'))
            except ValueError:
                var.set(fmt % f['get'](item))
                return
            if f.get('int'):
                v = int(round(v))
            if v != f['get'](item):
                f['set'](item, v)
                self.notify()
        sp.configure(command=commit)
        sp.bind('<Return>', commit)
        sp.bind('<FocusOut>', commit)
        return sp

    def add(self):
        self.items_fn().append(self.new_item())
        self.rebuild()
        self.notify()

    def remove(self, i):
        items = self.items_fn()
        if self.items_fn is self.app.bands_fn and len(items) <= 1:
            return
        items.pop(i)
        if self.on_remove:
            self.on_remove(i)
        self.rebuild()
        self.notify()


class BandShapeEditor:
    CW, CH = 540, 160
    X0, X1, Y0, Y1 = 40, 518, 10, 136

    def __init__(self, app, parent):
        self.app = app
        self.sel = 0
        self.sel_obj = None
        self.drag = None
        bar = ttk.Frame(parent)
        bar.pack(fill='x', pady=(6, 4))
        ttk.Label(bar, text='Band').pack(side='left', padx=(0, 6))
        self.var = tk.StringVar()
        self.cb = ttk.Combobox(bar, textvariable=self.var, width=18, state='readonly')
        self.cb.pack(side='left')
        self.cb.bind('<<ComboboxSelected>>', self.pick)
        ttk.Button(bar, text='Add gap', style='Small.TButton', command=self.add_gap).pack(side='left', padx=(10, 0))
        ttk.Button(bar, text='Random', style='Small.TButton', command=self.random).pack(side='left', padx=4)
        ttk.Button(bar, text='Reset', style='Small.TButton', command=self.reset).pack(side='left')
        self.cv = tk.Canvas(parent, width=self.CW, height=self.CH, bg=FIELD, highlightthickness=1, highlightbackground=LINE)
        self.cv.pack(anchor='w', pady=(0, 4))
        self.cv.bind('<Button-1>', self.press)
        self.cv.bind('<B1-Motion>', self.move)
        self.cv.bind('<ButtonRelease-1>', self.release)
        self.cv.bind('<Button-3>', self.remove)
        self.cv.bind('<Double-Button-1>', self.remove)
        self.info = ttk.Label(parent, text='', style='Dim.TLabel')
        self.info.pack(anchor='w')

    def entry(self, create=False):
        sh = self.app.P.setdefault('band_shapes', [])
        for e in sh:
            if e.get('band') == self.sel:
                return e
        if create:
            e = {'band': self.sel, 'points': []}
            sh.append(e)
            return e
        return None

    def points(self):
        e = self.entry()
        return e['points'] if e else []

    def tx(self, lon):
        return self.X0 + lon / 360.0 * (self.X1 - self.X0)

    def ty(self, f):
        return self.Y1 - min(max(f, 0), 2) / 2.0 * (self.Y1 - self.Y0)

    def fx(self, x):
        return min(max((x - self.X0) / float(self.X1 - self.X0) * 360.0, 0.0), 359.9)

    def fy(self, y):
        return round(round(min(max((self.Y1 - y) / float(self.Y1 - self.Y0) * 2.0, 0.0), 2.0) / 0.05) * 0.05, 2)

    def refresh(self):
        bands = self.app.P['bands']
        labels = band_labels(bands)
        self.cb.configure(values=labels)
        if not bands:
            return
        hit = [i for i, b in enumerate(bands) if b is self.sel_obj]
        self.sel = hit[0] if hit else min(max(self.sel, 0), len(bands) - 1)
        self.sel_obj = bands[self.sel]
        self.var.set(labels[self.sel])
        self.draw()

    def pick(self, _e=None):
        labels = band_labels(self.app.P['bands'])
        if self.var.get() in labels:
            self.sel = labels.index(self.var.get())
            self.sel_obj = self.app.P['bands'][self.sel]
            self.draw()

    def draw(self):
        cv = self.cv
        cv.delete('all')
        for lon in (0, 90, 180, 270, 360):
            x = self.tx(lon)
            cv.create_line(x, self.Y0, x, self.Y1, fill=LINE)
            cv.create_text(x, self.Y1 + 12, text='%d\u00b0' % lon, fill=DIM, font=(FONT, 8))
        for f, t in ((0, '0%'), (1, '100%'), (2, '200%')):
            y = self.ty(f)
            cv.create_line(self.X0, y, self.X1, y, fill=ACC if f == 1 else LINE, dash=(3, 3) if f == 1 else None)
            cv.create_text(self.X0 - 6, y, text=t, fill=DIM, anchor='e', font=(FONT, 8))
        bands = self.app.P['bands']
        if not bands:
            return
        pts = self.points()
        lons = np.linspace(0, 360, 241)
        f = gg.shape_factor(pts, lons) if pts else np.ones_like(lons)
        poly = [self.X0, self.Y1]
        for lo, v in zip(lons, f):
            poly += [self.tx(lo), self.ty(float(v))]
        poly += [self.X1, self.Y1]
        cv.create_polygon(*poly, fill=hexcol(bands[self.sel][1]), outline='')
        cv.create_line(*poly[2:-2], fill=FG, width=2)
        for lo, v in pts:
            x, y = self.tx(lo), self.ty(v)
            cv.create_oval(x - 5, y - 5, x + 5, y + 5, fill=WARM, outline=BG)
        if pts:
            self.info.configure(text='%d point%s  \u00b7  thinnest %d%%, thickest %d%%' % (len(pts), '' if len(pts) == 1 else 's', round(f.min() * 100), round(f.max() * 100)))
        else:
            self.info.configure(text='same thickness all the way round')

    def near(self, x, y):
        best = None
        for i, (lo, v) in enumerate(self.points()):
            d = (self.tx(lo) - x) ** 2 + (self.ty(v) - y) ** 2
            if d < 81 and (best is None or d < best[0]):
                best = (d, i)
        return None if best is None else best[1]

    def press(self, e):
        if not self.app.P['bands']:
            return
        i = self.near(e.x, e.y)
        ent = self.entry(create=True)
        if i is None:
            ent['points'].append([round(self.fx(e.x), 1), self.fy(e.y)])
            i = len(ent['points']) - 1
        self.drag = ent['points'][i]
        self.draw()
        self.app.changed()

    def move(self, e):
        if self.drag is None:
            return
        self.drag[0] = round(self.fx(e.x), 1)
        self.drag[1] = self.fy(e.y)
        self.draw()
        self.app.changed()

    def release(self, _e=None):
        if self.drag is not None:
            ent = self.entry()
            if ent:
                ent['points'].sort()
            self.drag = None
            self.draw()

    def remove(self, e):
        i = self.near(e.x, e.y)
        ent = self.entry()
        if i is None or not ent:
            return
        ent['points'].pop(i)
        if not ent['points']:
            self.app.P['band_shapes'].remove(ent)
        self.drag = None
        self.draw()
        self.app.changed()

    def set_points(self, pts):
        self.app.snapshot()
        ent = self.entry(create=True)
        ent['points'] = sorted(pts)
        self.draw()
        self.app.changed()

    def add_gap(self):
        c = random.uniform(0, 360)
        w = random.uniform(25, 45)
        pts = [p for p in self.points() if min(abs(p[0] - c) % 360, 360 - abs(p[0] - c) % 360) > w + 25]
        pts += [[round((c - w - 20) % 360, 1), 1.0], [round((c - w) % 360, 1), 0.0],
                [round((c + w) % 360, 1), 0.0], [round((c + w + 20) % 360, 1), 1.0]]
        self.set_points(pts)

    def random(self):
        n = random.randint(3, 6)
        start = random.uniform(0, 360)
        self.set_points([[round((start + i * 360.0 / n + random.uniform(-20, 20)) % 360, 1),
                          round(round(random.uniform(0.55, 1.5) / 0.05) * 0.05, 2)] for i in range(n)])

    def reset(self):
        ent = self.entry()
        if ent:
            self.app.snapshot()
            self.app.P['band_shapes'].remove(ent)
            self.draw()
            self.app.changed()


POLE_TYPES = [('none', 'Nothing'), ('hexagon', 'Hexagon'), ('cyclones', 'Cyclones')]


class PoleEditor:
    HEX = [num('Latitude', 'lat', 55, 88, 0.5, '%.1f'), num('Sides', 'sides', 3, 12, 1, '%.0f', isint=True),
           num('Roundness', 'roundness', 0, 1, 0.05, '%.2f'), num('Rotation', 'rotation', 0, 360, 1, '%.0f'),
           num('Jet speed', 'jet', 0, 3, 0.1, '%.1f'), num('Band width (\u00b0)', 'band_width', 1, 10, 0.5, '%.1f'),
           num('Band brightness', 'band', 0, 1, 0.05, '%.2f'), num('Wobble', 'wobble', 0, 1, 0.05, '%.2f'),
           num('Inner turns', 'turns', 0, 3, 0.1, '%.1f'), spinf('Spin', 'spin'),
           num('Cloud texture', 'texture', 0, 1.5, 0.05, '%.2f'), num('Dark eye', 'eye', 0, 1, 0.05, '%.2f'),
           num('Eye size', 'eye_size', 0.1, 1.5, 0.05, '%.2f')]
    CYC = [num('Ring latitude', 'ring_lat', 60, 89, 0.5, '%.1f'), num('Count', 'count', 0, 12, 1, '%.0f', isint=True),
           num('Size', 'size', 0.004, 0.03, 0.001, '%.3f'),
           {'label': 'Centre storm', 'get': lambda it: 'yes' if int(it.get('centre', 1)) else 'no',
            'set': lambda it, v: it.__setitem__('centre', v), 'kind': 'choice', 'values': ['yes', 'no'],
            'conv': lambda v: 1 if v == 'yes' else 0},
           num('Rotation', 'rotation', 0, 360, 1, '%.0f'), num('Turns', 'turns', 0, 3, 0.1, '%.1f'), spinf('Spin', 'spin'),
           num('Cap edge latitude', 'cap_lat', 40, 85, 0.5, '%.1f'), num('Wobble', 'wobble', 0, 1, 0.05, '%.2f'),
           num('Cloud texture', 'texture', 0, 1.5, 0.05, '%.2f'), num('Dark eyes', 'eye', 0, 1, 0.05, '%.2f'),
           num('Eye size', 'eye_size', 0.1, 1.5, 0.05, '%.2f')]
    COLS = {'hexagon': [('cap_color', 'Cap colour'), ('band_color', 'Band colour'), ('texture_color', 'Texture colour'),
                        ('eye_color', 'Eye colour')],
            'cyclones': [('cap_color', 'Cap colour'), ('texture_color', 'Texture colour'), ('eye_color', 'Eye colour')]}

    def __init__(self, app, parent, key, title):
        self.app, self.key = app, key
        self.notify = app.changed
        self.card = ttk.Frame(parent, style='Card.TFrame', padding=8)
        self.card.pack(fill='x', pady=4)
        top = ttk.Frame(self.card, style='Card.TFrame')
        top.pack(fill='x')
        ttk.Label(top, text=title, style='CardHead.TLabel').pack(side='left', padx=(4, 12))
        self.var = tk.StringVar()
        self.cb = ttk.Combobox(top, textvariable=self.var, values=[t for _, t in POLE_TYPES], width=12, state='readonly')
        self.cb.pack(side='left')
        self.cb.bind('<<ComboboxSelected>>', self.pick)
        self.body = ttk.Frame(self.card, style='Card.TFrame')
        self.body.pack(fill='x', pady=(6, 0))
        app.swatches.append(self)

    def entry(self):
        po = self.app.P.setdefault('poles', {})
        e = po.get(self.key)
        if not e or set(gg.POLE) - set(e):
            e = gg.pole_entry(e, south=(self.key == 'south'))
            po[self.key] = e
        return e

    def pick(self, _e=None):
        names = [t for _, t in POLE_TYPES]
        if self.var.get() not in names:
            return
        t = POLE_TYPES[names.index(self.var.get())][0]
        e = self.entry()
        if t != e['type']:
            self.app.snapshot()
            e['type'] = t
            self.refresh()
            self.app.changed()

    def refresh(self):
        e = self.entry()
        self.var.set(dict(POLE_TYPES)[e['type']])
        for w in self.body.winfo_children():
            w.destroy()
        if e['type'] == 'none':
            return
        fields = self.HEX if e['type'] == 'hexagon' else self.CYC
        fields = fields + [{'label': lab, 'kind': 'custom', 'make': (lambda parent, item, k=k: self.colour_pick(parent, item, k))}
                           for k, lab in self.COLS[e['type']]]
        cols = 4
        for j, f in enumerate(fields):
            r, c = divmod(j, cols)
            ttk.Label(self.body, text=f['label'], style='CardDim.TLabel').grid(row=r * 2, column=c, sticky='w', padx=4)
            ListEditor.widget(self, self.body, e, f).grid(row=r * 2 + 1, column=c, sticky='w', padx=4, pady=(0, 6))

    def colour_pick(self, parent, item, k):
        fr = ttk.Frame(parent, style='Card.TFrame')
        Q = sorted_copy(self.app.P)
        cap, tex, band, eye = gg.pole_colours(Q, self.key, item)
        auto = {'cap_color': cap, 'texture_color': tex, 'band_color': band, 'eye_color': eye}[k]
        lab = tk.Label(fr, bg=hexcol(item.get(k) or auto), width=6, relief='solid', bd=1, cursor='hand2')
        lab.pack(side='left')

        def pick(_e=None):
            c = colorchooser.askcolor(color=hexcol(item.get(k) or auto), parent=self.app)
            if c and c[0]:
                item[k] = [int(round(x)) for x in c[0]]
                self.refresh()
                self.app.changed()

        def reset():
            item[k] = None
            self.refresh()
            self.app.changed()
        lab.bind('<Button-1>', pick)
        if item.get(k):
            ttk.Button(fr, text='\u21ba', width=2, style='Small.TButton', command=reset).pack(side='left', padx=(4, 0))
        else:
            ttk.Label(fr, text='auto', style='CardDim.TLabel').pack(side='left', padx=(6, 0))
        return fr


class SampleWin(tk.Toplevel):
    def __init__(self, app, path):
        super().__init__(app)
        self.app = app
        self.title('Colours from a picture')
        self.configure(bg=BG)
        self.src = Image.open(path).convert('RGB')
        self.arr = np.asarray(self.src).astype(np.float32)
        iw, ih = self.src.size
        self.s = min(900 / iw, 640 / ih)
        disp = self.src.resize((max(1, int(iw * self.s)), max(1, int(ih * self.s))), Image.LANCZOS)
        self.tkimg = ImageTk.PhotoImage(disp)
        left = ttk.Frame(self, padding=10)
        left.pack(side='left', fill='both', expand=True)
        ttk.Label(left, text='Click the NORTH end, then the SOUTH end of a line straight across the bands.',
                  style='Head.TLabel').pack(anchor='w', pady=(0, 8))
        self.cv = tk.Canvas(left, width=disp.width, height=disp.height, bg='black', highlightthickness=0, cursor='crosshair')
        self.cv.pack()
        self.cv.create_image(0, 0, image=self.tkimg, anchor='nw')
        self.cv.bind('<Button-1>', self.click)
        right = ttk.Frame(self, padding=10)
        right.pack(side='left', fill='y')
        self.n = tk.IntVar(value=17)
        self.la0 = tk.DoubleVar(value=70.0)
        self.la1 = tk.DoubleVar(value=-70.0)
        self.gain = tk.DoubleVar(value=1.12)
        self.box = tk.IntVar(value=4)
        self.auto = tk.BooleanVar(value=True)
        rows = [('Samples', self.n, 5, 40, 1), ('Latitude at north click', self.la0, -89, 89, 1),
                ('Latitude at south click', self.la1, -89, 89, 1), ('Brightness', self.gain, 0.6, 1.8, 0.02),
                ('Averaging (px)', self.box, 1, 12, 1)]
        for i, (lab, var, lo, hi, inc) in enumerate(rows):
            ttk.Label(right, text=lab).grid(row=i, column=0, sticky='w', pady=3)
            sp = ttk.Spinbox(right, textvariable=var, from_=lo, to=hi, increment=inc, width=7, command=self.draw)
            sp.grid(row=i, column=1, padx=6, pady=3)
            sp.bind('<Return>', self.draw)
            sp.bind('<FocusOut>', self.draw)
        ttk.Checkbutton(right, text='Also place curls where the colour\nchanges a lot', variable=self.auto).grid(row=6, column=0, columnspan=2, sticky='w', pady=8)
        self.strip = tk.Canvas(right, width=90, height=300, bg=BG, highlightthickness=1, highlightbackground=LINE)
        self.strip.grid(row=7, column=0, columnspan=2, pady=8)
        bar = ttk.Frame(right)
        bar.grid(row=8, column=0, columnspan=2, sticky='ew', pady=(8, 0))
        ttk.Button(bar, text='Clear', command=self.clear).pack(side='left')
        self.use_btn = ttk.Button(bar, text='Use these colours', style='Accent.TButton', command=self.use, state='disabled')
        self.use_btn.pack(side='left', padx=6)
        self.pts = []
        self.stripimg = None
        self.transient(app)

    def click(self, e):
        if len(self.pts) >= 2:
            self.pts = []
        self.pts.append((e.x / self.s, e.y / self.s))
        self.draw()

    def clear(self):
        self.pts = []
        self.draw()

    def compute(self):
        (x1, y1), (x2, y2) = self.pts
        return gg.sample_bands(self.arr, x1, y1, x2, y2, max(2, int(self.n.get())), float(self.la0.get()),
                               float(self.la1.get()), float(self.gain.get()), max(1, int(self.box.get())))

    def draw(self, _e=None):
        self.cv.delete('mark')
        for x, y in self.pts:
            self.cv.create_oval(x * self.s - 5, y * self.s - 5, x * self.s + 5, y * self.s + 5, outline=ACC, width=2, tags='mark')
        self.strip.delete('all')
        if len(self.pts) == 2:
            (x1, y1), (x2, y2) = self.pts
            self.cv.create_line(x1 * self.s, y1 * self.s, x2 * self.s, y2 * self.s, fill=ACC, width=2, dash=(6, 4), tags='mark')
            try:
                bands = self.compute()
            except Exception:
                return
            P = {'bands': bands, 'band_blend': self.app.P['band_blend'], 'big_storms': []}
            self.stripimg = ImageTk.PhotoImage(band_image(P, 90, 300))
            self.strip.create_image(0, 0, image=self.stripimg, anchor='nw')
            self.use_btn.configure(state='normal')
        else:
            self.use_btn.configure(state='disabled')

    def use(self):
        bands = self.compute()
        self.app.P['bands'] = bands
        if self.auto.get():
            self.app.P['edges'] = gg.auto_edges(bands, limit=float(self.app.P['polar_calm'][0]))
        self.app.refresh_all()
        self.app.changed()
        self.destroy()


class ExportDialog(tk.Toplevel):
    KINDS = (('color', 'Colour map'), ('normal', 'Normal map'), ('flow', 'Flow map'), ('emissive', 'Emissive map'), ('preview', 'Preview sheet'))
    SIZES = ['Same as build', '16384 \u00d7 8192', '8192 \u00d7 4096', '4096 \u00d7 2048', '2048 \u00d7 1024', '1024 \u00d7 512']

    def __init__(self, app, builds):
        super().__init__(app)
        self.app = app
        self.P = copy.deepcopy(app.P)
        self.name = self.P['name']
        self.builds = builds
        self.S = load_settings()
        self.title('Export \u2013 %s' % self.name)
        self.configure(bg=BG)
        self.transient(app)
        self.resizable(False, False)
        self.q = queue.Queue()
        f = ttk.Frame(self, padding=18)
        f.pack(fill='both', expand=True)
        ttk.Label(f, text='Export %s' % self.name, style='Head.TLabel').grid(row=0, column=0, columnspan=4, sticky='w', pady=(0, 10))
        ttk.Label(f, text='From build').grid(row=1, column=0, sticky='w', pady=4)
        self.v_build = tk.StringVar()
        labels = ['%s \u00d7 %d' % (r, int(r) // 2) for r in builds]
        cb = ttk.Combobox(f, textvariable=self.v_build, values=labels, width=14, state='readonly')
        cb.grid(row=1, column=1, sticky='w', pady=4)
        cb.bind('<<ComboboxSelected>>', lambda e: self.update_rows())
        pref = app.res.get()
        self.v_build.set(labels[builds.index(pref)] if pref in builds else labels[0])
        ttk.Label(f, text='Folder').grid(row=2, column=0, sticky='w', pady=4)
        self.v_dir = tk.StringVar(value=self.S.get('export_dir') or os.path.join(gg.TOOL, 'export'))
        ttk.Entry(f, textvariable=self.v_dir, width=52).grid(row=2, column=1, columnspan=2, sticky='we', pady=4)
        ttk.Button(f, text='Browse\u2026', command=self.browse).grid(row=2, column=3, padx=(6, 0))
        ttk.Label(f, text='File name', style='Dim.TLabel').grid(row=3, column=1, sticky='w', pady=(12, 2))
        ttk.Label(f, text='Format', style='Dim.TLabel').grid(row=3, column=2, sticky='w', pady=(12, 2))
        self.rows = {}
        defaults = {'color': True, 'normal': True, 'flow': True, 'emissive': True, 'preview': False}
        for i, (k, lab) in enumerate(self.KINDS):
            on = tk.BooleanVar(value=self.S.get('on_' + k, defaults[k]))
            chk = ttk.Checkbutton(f, text=lab, variable=on)
            chk.grid(row=4 + i, column=0, sticky='w', pady=3)
            fn = self.P['files'].get(k) or ''
            base = os.path.splitext(os.path.basename(fn))[0] if fn else '%s_%s' % (self.name, k)
            v_name = tk.StringVar(value=base)
            ttk.Entry(f, textvariable=v_name, width=30).grid(row=4 + i, column=1, sticky='w', pady=3)
            v_fmt = tk.StringVar(value=self.S.get('fmt_' + k) if self.S.get('fmt_' + k) in gg.EXPORT_FORMATS[k] else gg.EXPORT_FORMATS[k][0])
            fc = ttk.Combobox(f, textvariable=v_fmt, values=gg.EXPORT_FORMATS[k], width=27, state='readonly')
            fc.grid(row=4 + i, column=2, sticky='w', pady=3)
            note = ttk.Label(f, text='', style='Dim.TLabel')
            note.grid(row=4 + i, column=3, sticky='w', padx=(6, 0))
            self.rows[k] = (on, chk, v_name, v_fmt, note)
        ttk.Label(f, text='Size').grid(row=9, column=0, sticky='w', pady=(12, 4))
        self.v_size = tk.StringVar(value=self.S.get('size') if self.S.get('size') in self.SIZES else self.SIZES[0])
        ttk.Combobox(f, textvariable=self.v_size, values=self.SIZES, width=14, state='readonly').grid(row=9, column=1, sticky='w', pady=(12, 4))
        self.v_flip = tk.BooleanVar(value=self.S.get('flip', True))
        ttk.Checkbutton(f, text='Flip DDS files upside down (KSP needs this)', variable=self.v_flip).grid(row=10, column=0, columnspan=3, sticky='w', pady=4)
        ttk.Label(f, text='Which DDS?  Colour and emissive maps: BC1 / DXT1 is what KSP uses by default, BC7 looks '
                          'best but the file is twice as big, BC3 / DXT5 if you need an alpha channel.  Normal map: '
                          'DXT5nm for KSP\u2019s own planet shaders, BC5 for shaders that ask for it.  BC5 and BC7 '
                          'need a texture loader that reads them, such as KSPTextureLoader.',
                  style='Dim.TLabel', wraplength=640, justify='left').grid(row=11, column=0, columnspan=4, sticky='w', pady=(8, 0))
        self.stat = ttk.Label(f, text='', style='Dim.TLabel', wraplength=640, justify='left')
        self.stat.grid(row=12, column=0, columnspan=4, sticky='w', pady=(10, 0))
        bar = ttk.Frame(f)
        bar.grid(row=13, column=0, columnspan=4, sticky='e', pady=(14, 0))
        self.open_btn = ttk.Button(bar, text='Open folder', command=lambda: open_folder(self.v_dir.get()), state='disabled')
        self.open_btn.pack(side='left', padx=(0, 6))
        self.go_btn = ttk.Button(bar, text='Export', style='Accent.TButton', command=self.go)
        self.go_btn.pack(side='left', padx=(0, 6))
        self.close_btn = ttk.Button(bar, text='Close', command=self.destroy)
        self.close_btn.pack(side='left')
        self.update_rows()
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = app.winfo_rootx() + max(0, (app.winfo_width() - w) // 2)
        y = app.winfo_rooty() + max(0, (app.winfo_height() - h) // 3)
        self.geometry('+%d+%d' % (x, y))
        self.grab_set()

    def res(self):
        return self.v_build.get().split(' ')[0]

    def src(self):
        return self.app.out_path(self.res())

    def update_rows(self):
        src = self.src()
        has = {'color': True, 'normal': True,
               'flow': os.path.isfile(os.path.join(src, self.name + '_flow.truecolor')),
               'emissive': os.path.isfile(os.path.join(src, self.name + '_emissive.png')),
               'preview': os.path.isfile(os.path.join(src, self.name + '_preview.png'))}
        for k, (on, chk, v_name, v_fmt, note) in self.rows.items():
            if has[k]:
                chk.state(['!disabled'])
                note.configure(text='')
            else:
                on.set(False)
                chk.state(['disabled'])
                note.configure(text='not in this build')
        st = self.app.is_stale(self.res())
        self.stat.configure(text='Note: the settings changed after this build \u2013 the export shows the build, not the new settings.' if st else '')

    def browse(self):
        d = filedialog.askdirectory(parent=self, title='Export to folder', initialdir=self.v_dir.get() if os.path.isdir(self.v_dir.get()) else gg.TOOL)
        if d:
            self.v_dir.set(d)

    def go(self):
        folder = self.v_dir.get().strip()
        if not folder:
            messagebox.showerror('Folder', 'Please choose a folder.', parent=self)
            return
        jobs = []
        for k, (on, chk, v_name, v_fmt, note) in self.rows.items():
            if on.get():
                base = v_name.get().strip()
                if not base or any(ch in base for ch in '\\/:*?"<>|'):
                    messagebox.showerror('File name', 'Please give the %s a valid file name.' % k, parent=self)
                    return
                jobs.append((k, base, v_fmt.get()))
        if not jobs:
            messagebox.showinfo('Nothing to export', 'Tick at least one file.', parent=self)
            return
        exist = [gg.export_target(folder, b, fm) for _, b, fm in jobs if os.path.exists(gg.export_target(folder, b, fm))]
        if exist and not messagebox.askyesno('Replace files?', 'These files already exist and will be replaced:\n\n' + '\n'.join(os.path.basename(x) for x in exist), parent=self):
            return
        sz = self.v_size.get()
        size = None if sz == self.SIZES[0] else int(sz.split(' ')[0])
        if size and size > int(self.res()):
            if not messagebox.askyesno('Bigger than the build', 'This stretches the %s build to %d. It will not gain any detail, '
                                       'it only gets bigger and softer.\n\nFor real detail, build at %d first.\n\nExport anyway?'
                                       % (self.res(), size, size), parent=self):
                return
        self.S.update({'export_dir': folder, 'size': sz, 'flip': bool(self.v_flip.get())})
        for k, (on, chk, v_name, v_fmt, note) in self.rows.items():
            self.S['fmt_' + k] = v_fmt.get()
            if str(chk.state()).find('disabled') < 0:
                self.S['on_' + k] = bool(on.get())
        save_settings(self.S)
        self.go_btn.configure(state='disabled')
        self.close_btn.configure(state='disabled')
        self.stat.configure(text='Exporting\u2026')
        src, name, P, flip = self.src(), self.name, self.P, bool(self.v_flip.get())

        def job():
            try:
                w = gg.export_maps(src, name, P, jobs, folder, size, flip, log=lambda m: self.q.put(('log', m)))
                self.q.put(('done', w))
            except Exception as ex:
                self.q.put(('err', str(ex)))
        threading.Thread(target=job, daemon=True).start()
        self.after(100, self.poll)

    def poll(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == 'log':
                    self.app.log(data)
                elif kind == 'done':
                    self.go_btn.configure(state='normal')
                    self.close_btn.configure(state='normal')
                    self.open_btn.configure(state='normal')
                    self.stat.configure(text='Exported %d file%s to %s' % (len(data), '' if len(data) == 1 else 's', self.v_dir.get()))
                    self.app.status('Exported %s' % self.name)
                    return
                else:
                    self.go_btn.configure(state='normal')
                    self.close_btn.configure(state='normal')
                    self.stat.configure(text='Export failed: ' + data)
                    return
        except queue.Empty:
            pass
        self.after(100, self.poll)


class FlowWindow(tk.Toplevel):
    def __init__(self, app, texture=None):
        super().__init__(app)
        self.app = app
        self.title('Flow Map Maker')
        self.configure(bg=BG)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry('%dx%d+40+40' % (min(1460, sw - 80), min(900, sh - 110)))
        self.F = copy.deepcopy(gg.FLOW_DEFAULTS)
        self.sliders, self.editors = [], []
        self.rgb_small = None
        self.flowimg = None
        self.edges_used = []
        self.frames, self.tkframes = [], []
        self.frame_i = 0
        self.anim_id = None
        self.calc_id = None
        self.gen = 0
        self.q = queue.Queue()
        self.busy_jobs = 0
        self.img_box = None
        self.view = tk.StringVar(value='arrows')
        self.history = []
        self.v_tex = tk.StringVar()
        self.v_out = tk.StringVar()
        self.v_auto = tk.BooleanVar(value=True)
        self.v_eq = tk.StringVar(value='East')
        self.build()
        self.show_folder()
        textures = gg.list_textures()
        start = texture if texture in textures else (textures[0] if textures else None)
        if start:
            self.set_texture(start)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.bind('<Control-z>', self.undo)
        self.after(100, self.poll)

    def build(self):
        pw = ttk.PanedWindow(self, orient='horizontal')
        pw.pack(fill='both', expand=True)
        left = ttk.Frame(pw, padding=(8, 8, 0, 8))
        right = ttk.Frame(pw, padding=(8, 8, 12, 8))
        pw.add(left, weight=0)
        pw.add(right, weight=1)
        sf = ScrollFrame(left)
        sf.pack(fill='both', expand=True)
        sf.configure(width=560)
        sf.canvas.configure(width=540)
        p = sf.inner
        src = lambda: self.F
        ttk.Label(p, text='Texture', style='Head.TLabel').pack(anchor='w', pady=(4, 4))
        r = ttk.Frame(p)
        r.pack(fill='x')
        self.tex_cb = ttk.Combobox(r, textvariable=self.v_tex, values=gg.list_textures(), width=34, state='readonly')
        self.tex_cb.pack(side='left', padx=(8, 6))
        self.tex_cb.bind('<<ComboboxSelected>>', lambda e: self.set_texture(self.v_tex.get()))
        ttk.Button(r, text='Browse\u2026', command=self.browse).pack(side='left')
        r = ttk.Frame(p)
        r.pack(fill='x', pady=(6, 0))
        ttk.Button(r, text='Texture folder\u2026', command=self.pick_folder).pack(side='left', padx=(8, 8))
        self.folder_lab = ttk.Label(r, text='', style='Dim.TLabel')
        self.folder_lab.pack(side='left')
        r = ttk.Frame(p)
        r.pack(fill='x', pady=(6, 0))
        ttk.Label(r, text='Flow map file').pack(side='left', padx=(8, 8))
        e = ttk.Entry(r, textvariable=self.v_out, width=40)
        e.pack(side='left')
        e.bind('<Return>', self.commit_out)
        e.bind('<FocusOut>', self.commit_out)
        self.info = ttk.Label(p, text='', style='Dim.TLabel', wraplength=520, justify='left')
        self.info.pack(anchor='w', padx=8, pady=(6, 0))
        ttk.Label(p, text='Band jets', style='Head.TLabel').pack(anchor='w', pady=(14, 4))
        ttk.Label(p, text='Neighbouring bands flow in opposite directions, like on Jupiter. '
                          'Their edges are found in the texture, or you set them yourself.', style='Dim.TLabel', wraplength=520).pack(anchor='w', padx=8)
        ttk.Checkbutton(p, text='Find band edges automatically', variable=self.v_auto, command=self.toggle_auto).pack(anchor='w', padx=8, pady=(6, 0))
        g = ttk.Frame(p)
        g.pack(fill='x')
        g.columnconfigure(1, weight=1)
        Slider(self.app, g, 0, 'Edge sensitivity', ('sensitivity',), 0.05, 0.9, 0.01, tip='lower = finds more, fainter edges', src=src, notify=self.changed, registry=self.sliders)
        Slider(self.app, g, 2, 'Smallest band (°)', ('min_gap',), 1, 20, 0.5, src=src, notify=self.changed, registry=self.sliders)
        self.edge_ed = ListEditor(self.app, p, lambda: self.F['edges'], [num('Edge latitude', 'lat', -89, 89, 0.5, '%.1f', width=8)],
                                  lambda: {'lat': 0.0}, add_text='Add edge', notify=self.edges_changed, registry=self.editors)
        self.edge_ed.frame.pack(fill='x', pady=6, padx=8)
        ttk.Button(self.edge_ed.bar, text='Use the found edges', command=self.copy_edges).pack(side='left', padx=6)
        r = ttk.Frame(p)
        r.pack(fill='x', pady=(4, 0))
        ttk.Label(r, text='Equator flows').pack(side='left', padx=(8, 8))
        cb = ttk.Combobox(r, textvariable=self.v_eq, values=['East', 'West'], width=6, state='readonly')
        cb.pack(side='left')
        cb.bind('<<ComboboxSelected>>', self.commit_eq)
        ttk.Label(p, text='Wind', style='Head.TLabel').pack(anchor='w', pady=(14, 4))
        g = ttk.Frame(p)
        g.pack(fill='x')
        g.columnconfigure(1, weight=1)
        Slider(self.app, g, 0, 'Jet speed', ('jets',), 0, 2, 0.05, src=src, notify=self.changed, registry=self.sliders)
        Slider(self.app, g, 1, 'Jet unevenness', ('jet_variation',), 0, 1, 0.05, src=src, notify=self.changed, registry=self.sliders)
        Slider(self.app, g, 2, 'Wobble', ('wobble',), 0, 0.5, 0.01, tip='small north-south drifting', src=src, notify=self.changed, registry=self.sliders)
        Slider(self.app, g, 4, 'Wobble size', ('wobble_scale',), 1, 10, 0.1, tip='smaller = bigger wobbles', src=src, notify=self.changed, registry=self.sliders)
        Slider(self.app, g, 6, 'Smoothing', ('smooth',), 0, 8, 0.25, src=src, notify=self.changed, registry=self.sliders)
        Slider(self.app, g, 7, 'Overall strength', ('strength',), 10, 127, 1, isint=True, tip='how far from neutral grey the map goes (old maps ≈ 100)', src=src, notify=self.changed, registry=self.sliders)
        Slider(self.app, g, 9, 'Calm poles from (°)', ('calm', 0), 30, 88, 1, isint=True, src=src, notify=self.changed, registry=self.sliders)
        Slider(self.app, g, 10, 'Still at (°)', ('calm', 1), 35, 90, 1, isint=True, src=src, notify=self.changed, registry=self.sliders)
        r = ttk.Frame(p)
        r.pack(fill='x', pady=(6, 0))
        ttk.Button(r, text='Randomize wind', command=self.randomize).pack(side='left', padx=8)
        ttk.Button(r, text='New random wobble', command=self.reseed).pack(side='left')
        ttk.Label(p, text='Storm swirls', style='Head.TLabel').pack(anchor='w', pady=(14, 4))
        ttk.Label(p, text='Makes a storm turn in place. Tip: click on the map on the right to put one there.',
                  style='Dim.TLabel', wraplength=520).pack(anchor='w', padx=8)
        self.storm_ed = ListEditor(self.app, p, lambda: self.F['storms'],
                                   [num('Latitude', 'lat', -85, 85, 0.5, '%.1f'), num('Longitude', 'lon', 0, 360, 1, '%.0f'),
                                    num('Radius (°)', 'radius', 0.5, 40, 0.5, '%.1f', 6.0), num('Stretch', 'aspect', 0.5, 4, 0.1, '%.1f', 1.5),
                                    num('Strength', 'strength', 0, 3, 0.05, '%.2f', 0.8), spinf('Spin', 'spin')],
                                   lambda: {'lat': -20.0, 'lon': 180.0, 'radius': 6.0, 'aspect': 1.5, 'strength': 0.8, 'spin': 1},
                                   card=True, cols=6, add_text='Add storm swirl', notify=self.changed, registry=self.editors)
        self.storm_ed.frame.pack(fill='x', pady=6, padx=8)
        vb = ttk.Frame(right)
        vb.pack(fill='x')
        for val, txt in (('arrows', 'Arrows'), ('anim', 'Animated'), ('map', 'Flow map')):
            ttk.Radiobutton(vb, text=txt, value=val, variable=self.view, style='Toolbutton',
                            command=self.show).pack(side='left', padx=(0, 4))
        self.export_btn = ttk.Button(vb, text='Export…', command=self.export)
        self.export_btn.pack(side='right')
        ttk.Button(vb, text='Save', style='Accent.TButton', command=self.save).pack(side='right', padx=6)
        self.undo_btn = ttk.Button(vb, text='Undo', command=self.undo, state='disabled')
        self.undo_btn.pack(side='right', padx=(0, 12))
        self.canvas = tk.Canvas(right, bg='#0d0f14', highlightthickness=1, highlightbackground=LINE, cursor='crosshair')
        self.canvas.pack(fill='both', expand=True, pady=(8, 8))
        self.canvas.bind('<Configure>', lambda e: self.show())
        self.canvas.bind('<Button-1>', self.click_map)
        g = ttk.Frame(right)
        g.pack(fill='x')
        g.columnconfigure(1, weight=1)
        Slider(self.app, g, 0, 'Preview motion (°)', ('preview_motion',), 1, 40, 0.5,
               tip='only for the animation here – the real amount comes from speed/displacement in the EVE cloud config',
               src=src, notify=self.anim_changed, registry=self.sliders)
        self.stat = ttk.Label(right, text='', style='Dim.TLabel')
        self.stat.pack(fill='x', pady=(6, 0))

    def refresh(self):
        for s in self.sliders:
            s.refresh()
        for e in self.editors:
            e.rebuild()
        self.v_auto.set(bool(self.F['auto_edges']))
        self.v_eq.set('East' if self.F['equator'] > 0 else 'West')
        self.v_out.set(self.F['out'])
        self.update_info()

    def update_info(self):
        hits = gg.eve_flow_info(self.F['out']) if self.F['out'] else []
        if hits:
            t = '\n'.join('Used by %s  (speed %s, displacement %s)' % (p, sp or '?', dp or '?') for p, sp, dp in hits)
        elif not gg.texture_dir():
            t = 'Tip: pick your mod\'s texture folder with "Texture folder\u2026" to list its textures and see which EVE configs use the flow map.'
        else:
            t = 'No EVE cloud config uses this flow map yet, so it will not do anything in game until one does.'
        self.info.configure(text=t)

    def set_texture(self, name):
        self.v_tex.set(name if not os.path.isabs(name) else os.path.basename(name))
        body = gg.body_of(name)
        sp = os.path.join(gg.FLOWS, body + '.json')
        if os.path.isfile(sp):
            try:
                with open(sp) as f:
                    self.F = copy.deepcopy(gg.merge(gg.FLOW_DEFAULTS, json.load(f)))
            except Exception:
                self.F = copy.deepcopy(gg.FLOW_DEFAULTS)
        else:
            self.F = copy.deepcopy(gg.FLOW_DEFAULTS)
        if not self.F.get('out'):
            self.F['out'] = 'GiantFlow/%s_flow.truecolor' % body
        self.F['texture'] = name
        self.body = body
        self.history = []
        self.undo_btn.configure(state='disabled')
        tp = gg.texture_path(name)
        self.rgb_small = None
        self.status('Loading %s…' % os.path.basename(tp))
        self.update_idletasks()
        try:
            full = gg.load_texture(tp)
            self.full_rgb = full
            self.rgb_small = np.asarray(Image.fromarray(full).resize((1024, 512), Image.BOX))
        except Exception as ex:
            self.full_rgb = None
            messagebox.showerror('Could not open texture', str(ex), parent=self)
        self.title('Flow Map Maker – %s' % body)
        self.refresh()
        self.changed()

    def show_folder(self):
        d = gg.texture_dir()
        if not d:
            self.folder_lab.configure(text='no texture folder chosen')
            return
        t = d if len(d) <= 46 else '\u2026' + d[-44:]
        self.folder_lab.configure(text=t)

    def pick_folder(self):
        d = filedialog.askdirectory(parent=self, title='Folder with your colour textures (for example GameData/YourMod/Textures)',
                                    initialdir=gg.texture_dir() or gg.TOOL)
        if not d:
            return
        S = load_settings()
        S['texture_dir'] = d
        save_settings(S)
        tex = gg.list_textures()
        self.tex_cb.configure(values=tex)
        self.show_folder()
        self.status('%d colour textures in %s' % (len(tex), d))
        if tex:
            self.set_texture(tex[0])

    def browse(self):
        p = filedialog.askopenfilename(parent=self, title='Gas giant colour texture', initialdir=gg.texture_dir() or gg.TOOL,
                                       filetypes=[('Textures', '*.dds *.png *.jpg'), ('All files', '*.*')])
        if p:
            self.set_texture(p)

    def commit_out(self, _e=None):
        v = self.v_out.get().strip()
        if v and v != self.F['out']:
            self.F['out'] = v
            self.update_info()

    def commit_eq(self, _e=None):
        self.F['equator'] = 1 if self.v_eq.get() == 'East' else -1
        self.changed()

    def toggle_auto(self):
        self.F['auto_edges'] = bool(self.v_auto.get())
        self.changed()

    def edges_changed(self):
        if self.F['auto_edges']:
            self.F['auto_edges'] = False
            self.v_auto.set(False)
        self.changed()

    def copy_edges(self):
        self.F['edges'] = [{'lat': float(e)} for e in self.edges_used]
        self.F['auto_edges'] = False
        self.v_auto.set(False)
        self.edge_ed.rebuild()
        self.changed()

    def reseed(self):
        self.snapshot()
        self.F['seed'] = random.randint(1, 99999)
        self.changed()

    def snapshot(self):
        self.history.append(copy.deepcopy(self.F))
        del self.history[:-40]
        self.undo_btn.configure(state='normal')

    def undo(self, e=None):
        if e is not None and isinstance(self.focus_get(), (ttk.Entry, ttk.Spinbox, tk.Entry)):
            return
        if not self.history:
            return
        self.F = self.history.pop()
        if not self.history:
            self.undo_btn.configure(state='disabled')
        self.frames = []
        self.refresh()
        self.changed()

    def randomize(self):
        self.snapshot()
        F = self.F
        R = random.uniform
        F['jets'] = round(R(0.6, 1.4), 2)
        F['jet_variation'] = round(R(0.1, 0.5), 2)
        F['wobble'] = round(R(0.03, 0.15), 2)
        F['wobble_scale'] = round(R(2.0, 6.0), 1)
        F['smooth'] = round(R(1.0, 3.0) * 4) / 4
        F['seed'] = random.randint(1, 99999)
        for st in F['storms']:
            st['strength'] = round(R(0.5, 1.2), 2)
        self.frames = []
        self.refresh()
        self.changed()

    def status(self, t):
        self.stat.configure(text=t)

    def changed(self):
        if self.calc_id:
            self.after_cancel(self.calc_id)
        self.calc_id = self.after(300, self.recalc)

    def anim_changed(self):
        if self.view.get() == 'anim':
            if self.calc_id:
                self.after_cancel(self.calc_id)
            self.calc_id = self.after(400, self.make_anim)

    def recalc(self):
        self.calc_id = None
        if self.rgb_small is None:
            return
        self.gen += 1
        g = self.gen
        F = copy.deepcopy(self.F)
        rgb = self.full_rgb
        self.busy_jobs += 1
        self.status('Working…')

        def job():
            try:
                u, v, edges = gg.flow_field(F, 512, 256, rgb)
                self.q.put(('flow', g, gg.encode_flow(u, v, float(F['strength'])), edges))
            except Exception as ex:
                self.q.put(('err', g, str(ex), None))
        threading.Thread(target=job, daemon=True).start()

    def make_anim(self):
        self.calc_id = None
        if self.flowimg is None or self.rgb_small is None:
            return
        self.gen += 1
        g = self.gen
        rgb, fl, mot = self.rgb_small, self.flowimg, float(self.F['preview_motion'])
        self.busy_jobs += 1
        self.status('Making the animation…')
        self.stop_anim()

        def job():
            try:
                self.q.put(('anim', g, gg.flow_frames(rgb, fl, mot, 24, 768), None))
            except Exception as ex:
                self.q.put(('err', g, str(ex), None))
        threading.Thread(target=job, daemon=True).start()

    def poll(self):
        if not self.winfo_exists():
            return
        try:
            while True:
                kind, g, data, extra = self.q.get_nowait()
                self.busy_jobs = max(0, self.busy_jobs - 1)
                if g != self.gen:
                    continue
                if kind == 'flow':
                    self.flowimg = data
                    self.edges_used = extra
                    self.status('Band edges: ' + (', '.join('%g°' % e for e in extra) if extra else 'none'))
                    if self.view.get() == 'anim':
                        self.make_anim()
                    else:
                        self.show()
                elif kind == 'anim':
                    self.frames = data
                    self.tkframes = []
                    self.status('Animation: one loop of the flow map cycle (approximate)')
                    self.show()
                else:
                    self.status('Error: ' + data)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(80, self.poll)

    def stop_anim(self):
        if self.anim_id:
            self.after_cancel(self.anim_id)
            self.anim_id = None

    def fit(self, im):
        cw, ch = max(10, self.canvas.winfo_width()), max(10, self.canvas.winfo_height())
        iw, ih = im.size
        s = min((cw - 16) / iw, (ch - 16) / ih)
        w, h = max(1, int(iw * s)), max(1, int(ih * s))
        self.img_box = ((cw - w) // 2, (ch - h) // 2, w, h)
        return im.resize((w, h), Image.LANCZOS)

    def show(self):
        self.stop_anim()
        self.canvas.delete('all')
        v = self.view.get()
        if self.rgb_small is None or self.flowimg is None:
            return
        if v == 'arrows':
            im = gg.flow_arrows(self.rgb_small, self.flowimg, 1024, 32)
        elif v == 'map':
            im = Image.fromarray(self.flowimg).resize((1024, 512), Image.BILINEAR)
        else:
            if not self.frames:
                self.make_anim()
                return
            self.tkframes = [ImageTk.PhotoImage(self.fit(f)) for f in self.frames]
            self.frame_i = 0
            self.play()
            return
        self.tkimg = ImageTk.PhotoImage(self.fit(im))
        x0, y0, w, h = self.img_box
        self.canvas.create_image(x0, y0, image=self.tkimg, anchor='nw')

    def play(self):
        if self.view.get() != 'anim' or not self.tkframes:
            return
        x0, y0, w, h = self.img_box
        self.canvas.delete('all')
        self.canvas.create_image(x0, y0, image=self.tkframes[self.frame_i % len(self.tkframes)], anchor='nw')
        self.frame_i += 1
        self.anim_id = self.after(70, self.play)

    def click_map(self, e):
        if not self.img_box:
            return
        x0, y0, w, h = self.img_box
        if not (x0 <= e.x < x0 + w and y0 <= e.y < y0 + h):
            return
        lon = round((e.x - x0) / w * 360, 0)
        lat = round(90 - (e.y - y0) / h * 180, 1)
        self.F['storms'].append({'lat': lat, 'lon': lon, 'radius': 6.0, 'aspect': 1.5, 'strength': 0.8, 'spin': 1})
        self.storm_ed.rebuild()
        self.frames = []
        self.changed()
        self.status('Added a storm swirl at %.1f°, %.0f°' % (lat, lon))

    def save(self):
        self.commit_out()
        if not self.F['out']:
            messagebox.showerror('Flow map file', 'Please give the flow map a file name.', parent=self)
            return None
        os.makedirs(gg.FLOWS, exist_ok=True)
        body = gg.body_of(self.F['out'])
        F = copy.deepcopy(self.F)
        if os.path.isabs(F['texture']) and gg.texture_dir() and os.path.dirname(os.path.abspath(F['texture'])) == os.path.abspath(gg.texture_dir()):
            F['texture'] = os.path.basename(F['texture'])
        with open(os.path.join(gg.FLOWS, body + '.json'), 'w') as f:
            json.dump(F, f, indent=1)
        self.status('Saving the full-size flow map…')
        self.update_idletasks()
        u, v, edges = gg.flow_field(self.F, 2048, 1024, self.full_rgb)
        outp = os.path.join(gg.FLOWOUT, body + '_flow.truecolor')
        gg.save_truecolor(gg.encode_flow(u, v, float(self.F['strength'])), outp)
        self.status('Saved %s' % os.path.relpath(outp, gg.TOOL))
        return outp

    def export(self):
        outp = self.save()
        if not outp:
            return
        S = load_settings()
        start = S.get('flow_export_dir') or S.get('export_dir') or gg.FLOWOUT
        body = gg.body_of(self.F['out'])
        p = filedialog.asksaveasfilename(parent=self, title='Export flow map', initialdir=start if os.path.isdir(start) else gg.TOOL,
                                         initialfile=body + '_flow.truecolor', defaultextension='.truecolor',
                                         filetypes=[('EVE flow map', '*.truecolor'), ('PNG image', '*.png')])
        if not p:
            return
        img = np.asarray(Image.open(outp).convert('RGB'))
        if p.lower().endswith('.png'):
            Image.fromarray(img).save(p, 'PNG')
        else:
            gg.save_truecolor(img, p)
        S['flow_export_dir'] = os.path.dirname(p)
        save_settings(S)
        self.status('Exported %s' % p)

    def close(self):
        self.stop_anim()
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Gas Giant Studio')
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry('%dx%d+20+20' % (min(1520, sw - 60), min(940, sh - 90)))
        self.minsize(1100, 680)
        self.configure(bg=BG)
        make_style(self)
        self.P = gg.normalize(copy.deepcopy(gg.DEFAULTS))
        self.P['name'] = 'NewGiant'
        self.preset_file = None
        self.dirty = False
        self.sliders, self.editors, self.swatches = [], [], []
        self.proc = None
        self.q = queue.Queue()
        self.view_src = None
        self.pending = None
        self.redraw_id = None
        self.steps_total = 100
        self.res = tk.StringVar(value='1024')
        self.view = tk.StringVar(value='bands')
        self.bands_fn = lambda: self.P['bands']
        self.history = []
        self.build_ui()
        self.bind('<Control-z>', self.undo)
        names = self.preset_names()
        if names:
            self.load('Pilgrim46' if 'Pilgrim46' in names else names[0])
        else:
            self.refresh_all()
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.set_icon(self)

    @staticmethod
    def set_icon(win):
        if os.name != 'nt':
            return
        for base in (getattr(sys, '_MEIPASS', ''), gg.TOOL):
            ico = os.path.join(base, 'icon.ico') if base else ''
            if ico and os.path.isfile(ico):
                try:
                    win.iconbitmap(ico)
                except Exception:
                    pass
                return

    def preset_names(self):
        os.makedirs(gg.PRESETS, exist_ok=True)
        return sorted(f[:-5] for f in os.listdir(gg.PRESETS) if f.endswith('.json'))

    def build_ui(self):
        top = ttk.Frame(self, style='Bar.TFrame', padding=(12, 8))
        top.pack(fill='x')
        ttk.Label(top, text='Gas Giant Studio', style='Title.TLabel').pack(side='left', padx=(0, 20))
        ttk.Label(top, text='Planet', style='BarDim.TLabel').pack(side='left')
        self.pick = ttk.Combobox(top, state='readonly', width=22)
        self.pick.pack(side='left', padx=6)
        self.pick.bind('<<ComboboxSelected>>', self.on_pick)
        ttk.Button(top, text='New…', command=self.new).pack(side='left', padx=2)
        ttk.Button(top, text='Save', command=lambda: self.save()).pack(side='left', padx=2)
        ttk.Button(top, text='Save as…', command=self.save_as).pack(side='left', padx=2)
        ttk.Button(top, text='Open output folder', command=self.open_out).pack(side='right')
        ttk.Button(top, text='Flow maps…', command=self.open_flow).pack(side='right', padx=6)
        self.undo_btn = ttk.Button(top, text='Undo', command=self.undo, state='disabled')
        self.undo_btn.pack(side='left', padx=(18, 2))
        ttk.Button(top, text='Surprise me', command=lambda: self.randomize('all')).pack(side='left', padx=2)
        pw = ttk.PanedWindow(self, orient='horizontal')
        pw.pack(fill='both', expand=True)
        left = ttk.Frame(pw, padding=(8, 4, 0, 8))
        right = ttk.Frame(pw, padding=(8, 8, 12, 8))
        pw.add(left, weight=0)
        pw.add(right, weight=1)
        self.nb = ttk.Notebook(left, width=600)
        self.nb.pack(fill='both', expand=True)
        self.tab_bands()
        self.tab_curls()
        self.tab_motion()
        self.tab_detail()
        self.tab_storms()
        self.tab_poles()
        self.tab_body()
        vb = ttk.Frame(right)
        vb.pack(fill='x')
        for val, txt in (('bands', 'Bands (instant)'), ('preview', 'Preview sheet'), ('flat', 'Flat map')):
            ttk.Radiobutton(vb, text=txt, value=val, variable=self.view, style='Toolbutton',
                            command=self.update_view).pack(side='left', padx=(0, 4))
        self.export_btn = ttk.Button(vb, text='Export…', command=self.export)
        self.export_btn.pack(side='right')
        self.canvas = tk.Canvas(right, bg='#0d0f14', highlightthickness=1, highlightbackground=LINE)
        self.canvas.pack(fill='both', expand=True, pady=(8, 8))
        self.canvas.bind('<Configure>', lambda e: self.schedule_redraw())
        sb = ttk.Frame(right)
        sb.pack(fill='x')
        ttk.Label(sb, text='Resolution', style='Dim.TLabel').pack(side='left')
        ttk.Combobox(sb, textvariable=self.res, values=RES, width=7, state='readonly').pack(side='left', padx=6)
        self.res.trace_add('write', lambda *a: (self.update_view(), self.update_res_info()))
        self.build_btn = ttk.Button(sb, text='Build', style='Accent.TButton', command=self.build)
        self.build_btn.pack(side='left')
        self.cancel_btn = ttk.Button(sb, text='Cancel', command=self.cancel, state='disabled')
        self.cancel_btn.pack(side='left', padx=6)
        self.prog = ttk.Progressbar(sb, mode='determinate', maximum=100)
        self.prog.pack(side='left', fill='x', expand=True, padx=(6, 0))
        self.res_info = ttk.Label(right, text='', style='Dim.TLabel', wraplength=820, justify='left')
        self.res_info.pack(fill='x', pady=(6, 0))
        self.stat = ttk.Label(right, text='Ready', style='Dim.TLabel')
        self.stat.pack(fill='x', pady=(2, 0))
        self.logbox = tk.Text(right, height=6, bg=FIELD, fg=DIM, insertbackground=FG, relief='flat',
                              font=(MONO, 9), state='disabled', wrap='none')
        self.logbox.pack(fill='x', pady=(6, 0))

    def rand_bar(self, parent, text, what, hint):
        r = ttk.Frame(parent)
        r.pack(fill='x', pady=(2, 0))
        ttk.Button(r, text=text, command=lambda: self.randomize(what)).pack(side='left', padx=(0, 8))
        ttk.Label(r, text=hint, style='Dim.TLabel').pack(side='left')

    def snapshot(self):
        self.history.append(copy.deepcopy(self.P))
        del self.history[:-40]
        self.undo_btn.configure(state='normal')

    def undo(self, e=None):
        if e is not None and isinstance(self.focus_get(), (ttk.Entry, ttk.Spinbox, tk.Entry)):
            return
        if not self.history:
            return
        self.P = self.history.pop()
        if not self.history:
            self.undo_btn.configure(state='disabled')
        self.refresh_all()
        self.changed()
        self.status('Undone')

    def randomize(self, what):
        self.commit_entries()
        self.snapshot()
        P = self.P
        R = random.uniform
        if what == 'bands':
            common = [R(-6, 6) for _ in range(3)]
            for i, b in enumerate(P['bands']):
                if i > 0:
                    b[0] = round(max(-89.0, min(89.0, b[0] + R(-1.5, 1.5))), 1)
                b[1] = [int(max(0, min(255, round(c + common[k] + R(-10, 10))))) for k, c in enumerate(b[1])]
            gg.sort_bands(P)
            P['band_blend'] = round(max(0.5, P['band_blend'] * R(0.8, 1.25)), 1)
        if what in ('curls', 'all'):
            if not P['edges']:
                P['edges'] = gg.auto_edges(P['bands'], limit=float(P['polar_calm'][0]))
            P['curl_strength'] = round(R(7, 14) * 2) / 2
            P['curl_spacing'] = round(R(5, 10) * 2) / 2
            P['curl_window'] = round(R(5, 9) * 2) / 2
            P['edge_wobble'] = round(R(1, 4), 1)
            for e in P['edges']:
                e['width'] = round(round(R(0.003, 0.007) / 0.0005) * 0.0005, 4)
                e['curl'] = round(round(R(0.2, 0.6) / 0.05) * 0.05, 2)
        if what in ('motion', 'all'):
            P['jets'] = round(R(0.05, 0.2), 2)
            P['turbulence'] = round(round(R(0.0002, 0.0012) / 0.00005) * 0.00005, 5)
            P['turbulence_scale'] = round(R(2.5, 7), 1)
            P['keyframes'] = random.randint(3, 6)
            c0 = random.randint(55, 68)
            P['polar_calm'] = [c0, min(90, c0 + random.randint(12, 18))]
        if what in ('detail', 'all'):
            P['band_wobble'] = round(R(0.5, 2.5), 1)
            P['stripes'] = [round(R(0.5, 2.5), 1), round(R(0.2, 1.0), 2)]
            P['sub_bands'] = round(R(0.01, 0.06), 3)
            P['mottle'] = round(R(0.01, 0.05), 3)
            P['threads'] = round(R(0.03, 0.2), 2)
            P['thread_width'] = round(R(0.05, 0.1), 3)
            s0 = random.randint(45, 60)
            P['polar_smooth'] = [s0, s0 + random.randint(12, 16)]
        if what in ('storms', 'all'):
            st = P['storms']
            st['count'] = random.randint(0, 14)
            st['lat_range'] = [-random.randint(30, 50), random.randint(30, 50)]
            st['size'] = [round(R(0.003, 0.004), 4), round(R(0.005, 0.007), 4)]
            st['turns'] = round(R(1.5, 3.0), 1)
            st['core'] = round(R(0.1, 0.4), 2)
            for b in P['big_storms']:
                b['turns'] = round(R(0.7, 1.4), 1)
                b['core'] = round(R(0.35, 0.65), 2)
                b['core_size'] = round(R(0.35, 0.6), 2)
                b['ragged'] = round(R(0.1, 0.3), 2)
                b['aspect'] = round(R(1.0, 1.6), 1)
                b['arm_length'] = round(R(1.8, 3.2), 1)
                b['arm_width'] = round(R(0.12, 0.3), 2)
                b['arm_curl'] = round(R(0.6, 1.4), 1)
        if what in ('poles', 'all'):
            for key, e in P.get('poles', {}).items():
                if e.get('type') == 'hexagon':
                    e.update({'lat': round(R(72, 80) * 2) / 2, 'sides': random.choice([5, 6, 6, 6, 6, 7, 8]),
                              'roundness': round(R(0.15, 0.45), 2), 'rotation': random.randint(0, 359),
                              'jet': round(R(0.7, 1.4), 1), 'wobble': round(R(0.05, 0.3), 2), 'band': round(R(0.3, 0.8), 2),
                              'band_width': round(R(3, 5.5) * 2) / 2, 'turns': round(R(0.5, 1.2), 1)})
                elif e.get('type') == 'cyclones':
                    e.update({'ring_lat': round(R(77, 83) * 2) / 2, 'count': random.randint(5, 9),
                              'size': round(R(0.008, 0.014), 3), 'centre': random.choice([1, 1, 1, 0]),
                              'rotation': random.randint(0, 359), 'turns': round(R(0.6, 1.1), 1),
                              'cap_lat': round(R(60, 70) * 2) / 2, 'wobble': round(R(0.1, 0.25), 2),
                              'texture': round(R(0.6, 1.0), 2), 'eye': round(R(0.3, 0.6), 2)})
            if what == 'poles' and not gg.has_poles(P):
                self.history.pop()
                if not self.history:
                    self.undo_btn.configure(state='disabled')
                self.status('Pick Hexagon or Cyclones for a pole first')
                return
        if what == 'all':
            P['seed'] = random.randint(1, 99999)
        self.refresh_all()
        self.changed()
        msg = 'Randomized %s – press Build to see the swirls, or Undo to go back' % ('everything' if what == 'all' else what)
        self.after(300, lambda: self.status(msg))

    def section(self, parent, text):
        ttk.Label(parent, text=text, style='Head.TLabel').pack(anchor='w', pady=(12, 4))

    def grid_box(self, parent):
        g = ttk.Frame(parent)
        g.pack(fill='x')
        g.columnconfigure(1, weight=1)
        return g

    def tab_bands(self):
        sf = ScrollFrame(self.nb)
        self.nb.add(sf, text='Bands')
        p = sf.inner
        self.rand_bar(p, 'Randomize', 'bands', 'small random changes to the colours and band positions')
        self.section(p, 'Band colours')
        ttk.Label(p, text='Each colour starts at its latitude and runs north to the next one. 90 = north pole.',
                  style='Dim.TLabel', wraplength=520).pack(anchor='w')
        ed = ListEditor(self, p, self.bands_fn,
                        [{'label': 'Band', 'kind': 'custom', 'make': self.band_number},
                         num('From latitude', 0, -90, 90, 0.5, '%.1f', width=8), colf('Colour', 1)],
                        lambda: [0.0, [150, 150, 170]], add_text='Add band', notify=self.bands_changed,
                        on_remove=self.band_removed)
        ed.frame.pack(fill='x', pady=6)
        self.band_ed = ed
        ttk.Button(ed.bar, text='Sort', command=self.sort_lists).pack(side='left', padx=6)
        ttk.Button(ed.bar, text='Colours from picture\u2026', command=self.sample).pack(side='left')
        g = self.grid_box(p)
        Slider(self, g, 0, 'Band softness (\u00b0)', ('band_blend',), 0.3, 10, 0.1)
        Slider(self, g, 1, 'Band edge wobble (\u00b0)', ('band_wobble',), 0, 5, 0.1)
        self.section(p, 'Glowing bands')
        ttk.Label(p, text='Pick a band that glows. Its swirls go into an extra emissive map: the glow colour where '
                          'the band is, black everywhere else. The glow colour starts as the band colour.',
                  style='Dim.TLabel', wraplength=520).pack(anchor='w')
        ge = ListEditor(self, p, lambda: self.P['emission'],
                        [{'label': 'Band', 'kind': 'custom', 'make': self.glow_band_pick},
                         {'label': 'Glow colour', 'kind': 'custom', 'make': self.glow_colour_pick},
                         num('Brightness', 'brightness', 0, 2, 0.05, '%.2f', 0.5)],
                        self.new_glow, add_text='Add glowing band')
        ge.frame.pack(fill='x', pady=6)
        self.glow_ed = ge
        self.section(p, 'Night-side glow')
        ttk.Label(p, text='A heat glow over the whole planet that shows on the night side, like a hot Jupiter. '
                          'Darker clouds are deeper and hotter, so they glow more, and the glow follows every swirl. '
                          'It goes into the emissive map together with the glowing bands. Strength 0 = off.',
                  style='Dim.TLabel', wraplength=520).pack(anchor='w')
        g = self.grid_box(p)
        Slider(self, g, 0, 'Glow strength', ('heat_glow', 'strength'), 0, 2, 0.05, tip='0 = off, about 0.6\u20131 for a hot Jupiter')
        Slider(self, g, 2, 'Dark clouds glow more', ('heat_glow', 'dark'), 0, 1, 0.05, tip='0 = even glow everywhere')
        Slider(self, g, 4, 'Cooler poles', ('heat_glow', 'poles'), 0, 1, 0.05)
        Slider(self, g, 5, 'Hot and cool patches', ('heat_glow', 'patches'), 0, 1, 0.05)
        tr = ttk.Frame(p)
        tr.pack(fill='x', pady=(6, 0))
        ttk.Label(tr, text='Dim colour').pack(side='left', padx=(8, 10))
        Swatch(self, tr, ('heat_glow', 'dim_color')).lab.pack(side='left')
        ttk.Label(tr, text='   Bright colour').pack(side='left', padx=(16, 10))
        Swatch(self, tr, ('heat_glow', 'bright_color')).lab.pack(side='left')
        self.section(p, 'Band thickness around the planet')
        ttk.Label(p, text='Make a band thicker or thinner along its length. 100% = normal, 0% = the band stops '
                          'there and the bands next to it meet. Click to add a point, drag to move it, '
                          'right-click to remove it. One point = the same thickness all the way round.',
                  style='Dim.TLabel', wraplength=520).pack(anchor='w')
        self.shape_ed = BandShapeEditor(self, p)
        self.swatches.append(self.shape_ed)

    def band_number(self, parent, item):
        n = next((i for i, b in enumerate(self.P['bands']) if b is item), -1)
        return ttk.Label(parent, text=str(n + 1), style='Dim.TLabel', width=4, anchor='center')

    def bands_changed(self):
        if getattr(self, 'glow_ed', None):
            self.glow_ed.rebuild()
        if getattr(self, 'shape_ed', None):
            self.shape_ed.refresh()
        self.changed()

    def band_removed(self, i):
        keep = []
        for em in self.P['emission']:
            b = em.get('band', -1)
            if b == i:
                continue
            if b > i:
                em['band'] = b - 1
            keep.append(em)
        self.P['emission'][:] = keep
        keep = []
        for sh in self.P.get('band_shapes', []):
            b = sh.get('band', -1)
            if b == i:
                continue
            if b > i:
                sh['band'] = b - 1
            keep.append(sh)
        self.P['band_shapes'] = keep
        self.glow_ed.rebuild()
        self.shape_ed.refresh()

    def new_glow(self):
        bands = self.P['bands']
        used = {em.get('band') for em in self.P['emission']}
        free = [i for i in range(len(bands)) if i not in used] or list(range(len(bands)))
        mid = min(free, key=lambda i: abs(bands[i][0] + 10))
        return {'band': mid, 'color': None, 'brightness': 0.5}

    def glow_band_pick(self, parent, item):
        labels = band_labels(self.P['bands'])
        b = item.get('band', -1)
        var = tk.StringVar(value=labels[b] if 0 <= b < len(labels) else '')
        cb = ttk.Combobox(parent, textvariable=var, values=labels, width=20, state='readonly')

        def sel(_e=None):
            if var.get() in labels:
                item['band'] = labels.index(var.get())
                self.glow_ed.rebuild()
                self.changed()
        cb.bind('<<ComboboxSelected>>', sel)
        return cb

    def glow_colour_pick(self, parent, item):
        fr = ttk.Frame(parent)
        bands = self.P['bands']
        b = item.get('band', -1)
        band_col = bands[b][1] if 0 <= b < len(bands) else [128, 128, 128]
        cur = item.get('color') or band_col
        lab = tk.Label(fr, bg=hexcol(cur), width=6, relief='solid', bd=1, cursor='hand2')
        lab.pack(side='left')

        def pick(_e=None):
            c = colorchooser.askcolor(color=hexcol(item.get('color') or band_col), parent=self)
            if c and c[0]:
                item['color'] = [int(round(x)) for x in c[0]]
                self.glow_ed.rebuild()
                self.changed()

        def reset():
            item['color'] = None
            self.glow_ed.rebuild()
            self.changed()
        lab.bind('<Button-1>', pick)
        if item.get('color'):
            ttk.Button(fr, text='Band colour', style='Small.TButton', command=reset).pack(side='left', padx=(6, 0))
        else:
            ttk.Label(fr, text='band colour', style='Dim.TLabel').pack(side='left', padx=(6, 0))
        return fr

    def tab_curls(self):
        sf = ScrollFrame(self.nb)
        self.nb.add(sf, text='Curls')
        p = sf.inner
        self.rand_bar(p, 'Randomize curls', 'curls', 'new curl sizes, roll-up and spacing (edge positions stay)')
        self.section(p, 'Curl edges')
        ttk.Label(p, text='Rows of swirls along a latitude. Put them where two band colours meet. '
                          'Alternate the spin from one edge to the next.', style='Dim.TLabel', wraplength=520).pack(anchor='w')
        ed = ListEditor(self, p, lambda: self.P['edges'],
                        [num('Latitude', 'lat', -89, 89, 0.5, '%.1f'), spinf('Spin', 'spin'),
                         num('Curl size', 'width', 0.001, 0.015, 0.0005, '%.4f', 0.0045),
                         num('Roll-up', 'curl', 0, 0.85, 0.05, '%.2f', 0.4)],
                        self.new_edge, add_text='Add edge')
        ed.frame.pack(fill='x', pady=6)
        ttk.Button(ed.bar, text='Sort', command=self.sort_lists).pack(side='left', padx=6)
        ttk.Button(ed.bar, text='Alternate spins', command=self.alt_spins).pack(side='left')
        ttk.Button(ed.bar, text='Auto-place', command=self.auto_edges).pack(side='left', padx=6)
        g = self.grid_box(p)
        Slider(self, g, 0, 'Curl turns', ('curl_strength',), 2, 25, 0.5, tip='7–12 loose waves, 20+ tight spirals')
        Slider(self, g, 2, 'Curl spacing', ('curl_spacing',), 3, 15, 0.5, tip='smaller = more curls along an edge')
        Slider(self, g, 4, 'Curl reach', ('curl_window',), 3, 12, 0.5)
        Slider(self, g, 5, 'Edge waviness (°)', ('edge_wobble',), 0, 6, 0.1)

    def tab_motion(self):
        sf = ScrollFrame(self.nb)
        self.nb.add(sf, text='Motion')
        p = sf.inner
        self.rand_bar(p, 'Randomize motion', 'motion', 'new jets, turbulence and calm poles')
        self.section(p, 'Flow')
        g = self.grid_box(p)
        Slider(self, g, 0, 'Jet streaks', ('jets',), 0, 0.4, 0.01, tip='stretches the bands into long streaks')
        Slider(self, g, 2, 'Turbulence', ('turbulence',), 0, 0.003, 0.00005, tip='general wobbling and mixing')
        Slider(self, g, 4, 'Turbulence size', ('turbulence_scale',), 1, 10, 0.1, tip='smaller = bigger wobbles')
        Slider(self, g, 6, 'Flow steps', ('steps',), 20, 200, 5, isint=True, tip='more = smoother and slower to build')
        Slider(self, g, 8, 'Flow changes', ('keyframes',), 2, 8, 1, isint=True)
        self.section(p, 'Calm poles')
        g = self.grid_box(p)
        Slider(self, g, 0, 'Motion fades from (°)', ('polar_calm', 0), 30, 88, 1, isint=True)
        Slider(self, g, 1, 'Motion gone at (°)', ('polar_calm', 1), 35, 90, 1, isint=True)

    def tab_detail(self):
        sf = ScrollFrame(self.nb)
        self.nb.add(sf, text='Detail')
        p = sf.inner
        self.rand_bar(p, 'Randomize detail', 'detail', 'new streaks, threads and patches')
        self.section(p, 'Streaks and filaments')
        g = self.grid_box(p)
        Slider(self, g, 0, 'Coarse streaks', ('stripes', 0), 0, 4, 0.1)
        Slider(self, g, 1, 'Fine streaks', ('stripes', 1), 0, 2, 0.05)
        Slider(self, g, 2, 'Sub-bands', ('sub_bands',), 0, 0.15, 0.005)
        Slider(self, g, 3, 'Soft patches', ('mottle',), 0, 0.12, 0.005)
        Slider(self, g, 4, 'Threads', ('threads',), 0, 0.4, 0.01, tip='thin light filaments')
        Slider(self, g, 6, 'Thread width', ('thread_width',), 0.02, 0.2, 0.005)
        tr = ttk.Frame(p)
        tr.pack(fill='x', pady=(6, 0))
        ttk.Label(tr, text='Thread colour').pack(side='left', padx=(8, 10))
        sw = Swatch(self, tr, ('thread_color',))
        sw.lab.pack(side='left')
        ttk.Label(tr, text='   Sub-band tint').pack(side='left', padx=(16, 10))
        for i in range(3):
            self.small_spin(tr, ('sub_band_warm', i), -30, 30)
        self.section(p, 'Calm poles')
        g = self.grid_box(p)
        Slider(self, g, 0, 'Detail fades from (°)', ('polar_smooth', 0), 30, 88, 1, isint=True)
        Slider(self, g, 1, 'Detail gone at (°)', ('polar_smooth', 1), 35, 90, 1, isint=True)
        self.section(p, 'Finish')
        g = self.grid_box(p)
        Slider(self, g, 0, 'Softening (px)', ('blur',), 0, 2, 0.05)
        Slider(self, g, 1, 'Normal map relief', ('normal_strength',), 0, 20, 0.5)

    def small_spin(self, parent, path, lo, hi):
        var = tk.StringVar()
        sp = ttk.Spinbox(parent, textvariable=var, from_=lo, to=hi, increment=1, width=4)
        sp.pack(side='left', padx=2)

        def commit(_e=None):
            try:
                v = int(round(float(var.get())))
            except ValueError:
                var.set(str(getp(self.P, path)))
                return
            if v != getp(self.P, path):
                setp(self.P, path, v)
                self.changed()
        sp.configure(command=commit)
        sp.bind('<Return>', commit)
        sp.bind('<FocusOut>', commit)
        self.swatches.append(type('S', (), {'refresh': lambda s=None: var.set(str(getp(self.P, path)))})())

    def tab_storms(self):
        sf = ScrollFrame(self.nb)
        self.nb.add(sf, text='Storms')
        p = sf.inner
        self.rand_bar(p, 'Randomize storms', 'storms', 'new small storms; big storms keep their place')
        self.section(p, 'Small storms')
        g = self.grid_box(p)
        Slider(self, g, 0, 'Count', ('storms', 'count'), 0, 40, 1, isint=True)
        Slider(self, g, 1, 'From latitude', ('storms', 'lat_range', 0), -80, 80, 1)
        Slider(self, g, 2, 'To latitude', ('storms', 'lat_range', 1), -80, 80, 1)
        Slider(self, g, 3, 'Smallest', ('storms', 'size', 0), 0.001, 0.015, 0.0005)
        Slider(self, g, 4, 'Largest', ('storms', 'size', 1), 0.001, 0.015, 0.0005)
        Slider(self, g, 5, 'Turns', ('storms', 'turns'), 0, 6, 0.1)
        Slider(self, g, 6, 'Bright centre', ('storms', 'core'), 0, 1, 0.05)
        Slider(self, g, 7, 'Centre size', ('storms', 'core_size'), 0.1, 1, 0.05)
        tr = ttk.Frame(p)
        tr.pack(fill='x', pady=(6, 0))
        ttk.Label(tr, text='Centre colour').pack(side='left', padx=(8, 10))
        Swatch(self, tr, ('storms', 'core_color')).lab.pack(side='left')
        self.section(p, 'Big storms')
        ttk.Label(p, text='Big versions of the small storms at a fixed place (lon 0\u2013360): a spiral with a bright '
                          'centre. Stretch makes it an oval. Turns about 0.7\u20131.4; above about 1.5 the bands '
                          'wind into rings around the storm.',
                  style='Dim.TLabel', wraplength=520).pack(anchor='w')
        ttk.Label(p, text='Arms are spiral cloud arms coming out of the storm (0 = none). They curl the way the '
                          'storm turns; their colour starts as the centre colour.',
                  style='Dim.TLabel', wraplength=520).pack(anchor='w', pady=(4, 0))
        bdef = gg.BIG_STORM
        be = ListEditor(self, p, lambda: self.P['big_storms'],
                        [num('Latitude', 'lat', -85, 85, 0.5, '%.1f'), num('Longitude', 'lon', 0, 360, 1, '%.0f'),
                         num('Size', 'size', 0.005, 0.08, 0.001, '%.3f', bdef['size']),
                         num('Stretch', 'aspect', 1, 4, 0.1, '%.1f', bdef['aspect']),
                         num('Turns', 'turns', 0, 3, 0.1, '%.1f', bdef['turns']), spinf('Spin', 'spin'),
                         num('Ragged', 'ragged', 0, 0.6, 0.05, '%.2f', bdef['ragged']),
                         num('Bright centre', 'core', 0, 1, 0.05, '%.2f', bdef['core']),
                         num('Centre size', 'core_size', 0.1, 1.5, 0.05, '%.2f', bdef['core_size']),
                         colf('Centre colour', 'core_color', tuple(bdef['core_color'])),
                         num('Arms', 'arms', 0, 6, 1, '%.0f', bdef['arms'], isint=True),
                         num('Arm length', 'arm_length', 0.5, 6, 0.1, '%.1f', bdef['arm_length']),
                         num('Arm width', 'arm_width', 0.05, 1, 0.01, '%.2f', bdef['arm_width']),
                         num('Arm curl', 'arm_curl', 0, 3, 0.1, '%.1f', bdef['arm_curl']),
                         num('Arm strength', 'arm_strength', 0, 1, 0.05, '%.2f', bdef['arm_strength']),
                         {'label': 'Arm colour', 'kind': 'custom', 'make': self.arm_colour_pick}],
                        self.new_big_storm, card=True, cols=4, add_text='Add big storm')
        be.frame.pack(fill='x', pady=6)
        self.storm_ed = be

    def tab_poles(self):
        sf = ScrollFrame(self.nb)
        self.nb.add(sf, text='Poles')
        p = sf.inner
        self.rand_bar(p, 'Randomize poles', 'poles', 'new sizes and shapes for the poles that are switched on')
        self.section(p, 'Polar features')
        ttk.Label(p, text='Hexagon: a jet stream with straight sides around the pole, like Saturn\u2019s, with a '
                          'spinning storm inside. Cyclones: a ring of round storms around the pole with one in the '
                          'middle, like Jupiter\u2019s. Colours left on auto follow the band at that pole.',
                  style='Dim.TLabel', wraplength=520).pack(anchor='w')
        ttk.Label(p, text='Builds with polar features take about 1.5\u20132\u00d7 longer. Latitudes are '
                          'degrees from the equator: 76 = 14\u00b0 from the pole (the south pole uses the same '
                          'numbers).', style='Dim.TLabel', wraplength=520).pack(anchor='w', pady=(4, 0))
        self.pole_eds = [PoleEditor(self, p, 'north', 'North pole'), PoleEditor(self, p, 'south', 'South pole')]

    def arm_colour_pick(self, parent, item):
        fr = ttk.Frame(parent, style='Card.TFrame')
        cur = item.get('arm_color') or item.get('core_color') or [244, 226, 214]
        lab = tk.Label(fr, bg=hexcol(cur), width=6, relief='solid', bd=1, cursor='hand2')
        lab.pack(side='left')

        def pick(_e=None):
            c = colorchooser.askcolor(color=hexcol(item.get('arm_color') or item.get('core_color') or cur), parent=self)
            if c and c[0]:
                item['arm_color'] = [int(round(x)) for x in c[0]]
                self.storm_ed.rebuild()
                self.changed()

        def reset():
            item['arm_color'] = None
            self.storm_ed.rebuild()
            self.changed()
        lab.bind('<Button-1>', pick)
        if item.get('arm_color'):
            ttk.Button(fr, text='\u21ba', width=2, style='Small.TButton', command=reset).pack(side='left', padx=(4, 0))
        return fr

    def tab_body(self):
        sf = ScrollFrame(self.nb)
        self.nb.add(sf, text='Planet')
        p = sf.inner
        self.section(p, 'Name and randomness')
        g = ttk.Frame(p)
        g.pack(fill='x')
        self.v_name = tk.StringVar()
        self.v_seed = tk.StringVar()
        ttk.Label(g, text='Name').grid(row=0, column=0, sticky='w', padx=8, pady=4)
        en = ttk.Entry(g, textvariable=self.v_name, width=24)
        en.grid(row=0, column=1, sticky='w', pady=4)
        en.bind('<Return>', self.commit_name)
        en.bind('<FocusOut>', self.commit_name)
        ttk.Label(g, text='Seed').grid(row=1, column=0, sticky='w', padx=8, pady=4)
        es = ttk.Entry(g, textvariable=self.v_seed, width=10)
        es.grid(row=1, column=1, sticky='w', pady=4)
        es.bind('<Return>', self.commit_seed)
        es.bind('<FocusOut>', self.commit_seed)
        ttk.Button(g, text='New random seed', command=self.random_seed).grid(row=1, column=2, padx=6)
        self.section(p, 'File names')
        ttk.Label(p, text='Starting names for Export. You choose the folder and the format each time you export.',
                  style='Dim.TLabel', wraplength=520).pack(anchor='w')
        g = ttk.Frame(p)
        g.pack(fill='x', pady=4)
        self.v_files = {}
        for i, (k, lab) in enumerate((('color', 'Colour map'), ('normal', 'Normal map'), ('flow', 'Flow map'), ('emissive', 'Emissive map'))):
            ttk.Label(g, text=lab).grid(row=i, column=0, sticky='w', padx=8, pady=4)
            v = tk.StringVar()
            e = ttk.Entry(g, textvariable=v, width=40)
            e.grid(row=i, column=1, sticky='w', pady=4)
            e.bind('<Return>', self.commit_files)
            e.bind('<FocusOut>', self.commit_files)
            self.v_files[k] = v
        self.v_flow = tk.BooleanVar(value=True)
        ttk.Checkbutton(g, text='Make an EVE flow map', variable=self.v_flow, command=self.commit_files).grid(row=4, column=1, sticky='w', pady=4)
        self.section(p, 'Preview camera')
        g = self.grid_box(p)
        Slider(self, g, 0, 'Tilt', ('preview', 'tilt'), -90, 90, 1)
        Slider(self, g, 1, 'View latitude', ('preview', 'view_lat'), -90, 90, 1)
        Slider(self, g, 2, 'View longitude', ('preview', 'view_lon'), 0, 360, 5)

    def new_big_storm(self):
        s = gg.big_storm({})
        s['core_color'] = list(self.P['storms']['core_color'])
        return s

    def new_edge(self):
        e = self.P['edges']
        spin = -e[-1].get('spin', 1) if e else 1
        return {'lat': 0.0, 'spin': spin, 'width': 0.0045, 'curl': 0.4}

    def refresh_all(self):
        for s in self.sliders:
            s.refresh()
        for e in self.editors:
            e.rebuild()
        for s in self.swatches:
            s.refresh()
        self.v_name.set(self.P['name'])
        self.v_seed.set(str(self.P['seed']))
        for k, v in self.v_files.items():
            v.set(self.P['files'].get(k, '') or '')
        self.v_flow.set(bool(self.P['files'].get('flow')))
        if not self.v_files['flow'].get():
            self.v_files['flow'].set('GiantFlow/%s_flow.truecolor' % self.P['name'])
        if not self.v_files['emissive'].get():
            self.v_files['emissive'].set('%s_emissive.dds' % self.P['name'])
        self.pick.configure(values=self.preset_names())
        self.pick.set(self.P['name'])
        self.update_title()
        self.update_view()
        self.update_res_info()

    def update_res_info(self):
        r = self.res.get()
        txt = '%s \u00d7 %d  \u00b7  %s' % (r, int(r) // 2, RES_INFO.get(r, ''))
        if self.P.get('big_storms'):
            txt += '  \u00b7  big storms: about 1.3\u00d7 longer'
        if gg.has_poles(self.P):
            txt += '  \u00b7  polar features: about 1.5\u20132\u00d7 longer'
        if r == '16384':
            txt += '  \u00b7  largest size KSP can load, very heavy in game'
        elif r == '8192':
            txt += '  \u00b7  big in game'
        self.res_info.configure(text=txt)

    def update_title(self):
        self.title('Gas Giant Studio %s \u2013 %s%s' % (gg.APP_VERSION, self.P['name'], ' *' if self.dirty else ''))

    def changed(self):
        self.dirty = True
        self.update_title()
        self.update_res_info()
        if self.view.get() == 'bands':
            if self.pending:
                self.after_cancel(self.pending)
            self.pending = self.after(180, self.update_view)
        else:
            self.update_stale()

    def commit_name(self, _e=None):
        new = self.v_name.get().strip()
        old = self.P['name']
        if not new or new == old:
            self.v_name.set(old)
            return
        for k, v in list(self.P['files'].items()):
            if v and old in v:
                self.P['files'][k] = v.replace(old, new)
        self.P['name'] = new
        for k, v in self.v_files.items():
            if old in v.get():
                v.set(v.get().replace(old, new))
        self.changed()

    def commit_seed(self, _e=None):
        try:
            s = int(self.v_seed.get())
        except ValueError:
            self.v_seed.set(str(self.P['seed']))
            return
        if s != self.P['seed']:
            self.P['seed'] = s
            self.changed()

    def random_seed(self):
        self.P['seed'] = random.randint(1, 99999)
        self.v_seed.set(str(self.P['seed']))
        self.changed()

    def commit_files(self, _e=None):
        new = {'color': self.v_files['color'].get().strip(), 'normal': self.v_files['normal'].get().strip(),
               'flow': self.v_files['flow'].get().strip() if self.v_flow.get() else ''}
        em = self.v_files['emissive'].get().strip()
        if em and ('emissive' in self.P['files'] or self.P['emission'] or gg.has_heat(self.P) or em != '%s_emissive.dds' % self.P['name']):
            new['emissive'] = em
        new = {k: v for k, v in new.items() if v}
        if new != {k: v for k, v in self.P['files'].items() if v}:
            self.P['files'] = new
            self.changed()

    def commit_entries(self):
        self.commit_name()
        self.commit_seed()
        self.commit_files()
        self.focus_set()

    def sort_lists(self):
        gg.sort_bands(self.P)
        self.P['edges'].sort(key=lambda e: -e['lat'])
        for e in self.editors:
            e.rebuild()
        self.shape_ed.refresh()

    def alt_spins(self):
        self.P['edges'].sort(key=lambda e: -e['lat'])
        for i, e in enumerate(self.P['edges']):
            e['spin'] = 1 if i % 2 == 0 else -1
        for e in self.editors:
            e.rebuild()
        self.changed()

    def auto_edges(self):
        if self.P['edges'] and not messagebox.askyesno('Auto curls', 'Replace the current curl edges with new ones at the band colour changes?', parent=self):
            return
        self.P['edges'] = gg.auto_edges(self.P['bands'], limit=float(self.P['polar_calm'][0]))
        for e in self.editors:
            e.rebuild()
        self.changed()

    def sample(self):
        path = filedialog.askopenfilename(parent=self, title='Reference picture',
                                          filetypes=[('Pictures', '*.png *.jpg *.jpeg *.bmp *.tga *.webp'), ('All files', '*.*')])
        if path:
            try:
                SampleWin(self, path)
            except Exception as ex:
                messagebox.showerror('Could not open picture', str(ex), parent=self)

    def ask_save(self):
        if not self.dirty:
            return True
        r = messagebox.askyesnocancel('Unsaved changes', 'Save the changes to %s first?' % self.P['name'], parent=self)
        if r is None:
            return False
        if r:
            return self.save()
        return True

    def on_pick(self, _e=None):
        name = self.pick.get()
        if name == self.P['name'] and self.preset_file:
            return
        if not self.ask_save():
            self.pick.set(self.P['name'])
            return
        self.load(name)

    def load(self, name):
        path = os.path.join(gg.PRESETS, name + '.json')
        try:
            with open(path) as f:
                raw = json.load(f)
        except Exception as ex:
            messagebox.showerror('Could not load', str(ex), parent=self)
            return
        P = gg.normalize(copy.deepcopy(gg.merge(gg.DEFAULTS, raw)))
        P['name'] = raw.get('name', name)
        self.P = P
        self.preset_file = path
        self.dirty = False
        self.history = []
        self.undo_btn.configure(state='disabled')
        self.refresh_all()

    def save(self, quiet=False):
        self.commit_entries()
        name = self.P['name'].strip()
        if not name or any(ch in name for ch in '\\/:*?"<>|'):
            messagebox.showerror('Name', 'Please give the planet a valid name.', parent=self)
            return False
        path = os.path.join(gg.PRESETS, name + '.json')
        if os.path.exists(path) and os.path.abspath(path) != os.path.abspath(self.preset_file or ''):
            if not messagebox.askyesno('Overwrite', '%s already exists. Overwrite it?' % name, parent=self):
                return False
        gg.sort_bands(self.P)
        self.P['edges'].sort(key=lambda e: -e['lat'])
        with open(path, 'w') as f:
            json.dump(self.P, f, indent=1)
        self.preset_file = path
        self.dirty = False
        for e in self.editors:
            e.rebuild()
        self.shape_ed.refresh()
        self.pick.configure(values=self.preset_names())
        self.pick.set(name)
        self.update_title()
        if not quiet:
            self.status('Saved %s' % os.path.relpath(path, gg.TOOL))
        return True

    def new(self):
        if not self.ask_save():
            return
        name = simpledialog.askstring('New gas giant', 'Name (for example Pilgrim50).\nIt starts as a copy of %s.' % self.P['name'], parent=self)
        if not name:
            return
        name = name.strip()
        if os.path.exists(os.path.join(gg.PRESETS, name + '.json')):
            messagebox.showerror('New', '%s already exists.' % name, parent=self)
            return
        P = copy.deepcopy(self.P)
        P['name'] = name
        P['seed'] = random.randint(1, 99999)
        P['files'] = {'color': name + '_color.dds', 'normal': name + '_normal.dds', 'flow': 'GiantFlow/' + name + '_flow.truecolor'}
        self.P = P
        self.preset_file = None
        self.dirty = True
        self.refresh_all()
        self.save()

    def save_as(self):
        name = simpledialog.askstring('Save as', 'New name:', parent=self, initialvalue=self.P['name'])
        if not name or name.strip() == self.P['name']:
            return
        self.v_name.set(name.strip())
        self.commit_name()
        self.preset_file = None
        self.save()

    def open_flow(self):
        tex = self.P['files'].get('color')
        FlowWindow(self, tex if tex in gg.list_textures() else None)

    def out_path(self, res=None):
        res = int(res or self.res.get())
        n = self.P['name']
        return os.path.join(gg.OUTROOT, n if res == 4096 else '%s_%d' % (n, res))

    def open_out(self):
        d = self.out_path()
        if not os.path.isdir(d):
            d = gg.OUTROOT
        os.makedirs(d, exist_ok=True)
        open_folder(d)

    def is_stale(self, res=None):
        f = os.path.join(self.out_path(res), self.P['name'] + '_preset.json')
        if not os.path.isfile(f):
            return None
        try:
            with open(f) as fh:
                built = gg.normalize(gg.merge(gg.DEFAULTS, json.load(fh)))
        except Exception:
            return None
        return json.dumps(built, sort_keys=True) != json.dumps(self.P, sort_keys=True)

    def update_stale(self):
        if self.proc:
            return
        v = self.view.get()
        if v in ('preview', 'flat') and self.is_stale():
            self.status('Settings changed since this build – press Build to update')

    def update_view(self):
        self.pending = None
        v = self.view.get()
        if v == 'bands':
            try:
                strip = band_image(self.P, 1024, 512)
            except Exception:
                return
            tex = np.asarray(strip).astype(np.float32) / 255
            pv = self.P['preview']
            gl = glow_image(self.P, 1024, 512)
            em = (gl / 255.0).astype(np.float32) if gl is not None else None
            heat = gg.has_heat(self.P)
            if heat:
                la = np.radians(90 - (np.arange(512) + 0.5) / 512 * 180).astype(np.float32)[:, None]
                he = gg.heat_emission(self.P, np.asarray(strip).astype(np.float32), la) / 255.0
                em = he.astype(np.float32) if em is None else np.clip(em + he, 0, 1).astype(np.float32)
            sph = gg.render_sphere(tex, 512, pv['tilt'], pv['view_lat'], pv['view_lon'], em, gg.NIGHT_LIGHT if heat else None)
            flat = strip.copy()
            d = ImageDraw.Draw(flat)
            for g in self.P['emission']:
                b = g.get('band', -1)
                if not 0 <= b < len(self.P['bands']):
                    continue
                lo = self.P['bands'][b][0]
                above = [x[0] for x in self.P['bands'] if x[0] > lo]
                y = (90 - (lo + (min(above) if above else 90)) / 2) / 180 * 512
                c = hexcol(g.get('color') or self.P['bands'][b][1])
                for x in (26, 997):
                    d.polygon([(x, y - 8), (x + 8, y), (x, y + 8), (x - 8, y)], fill=c, outline='white')
            for e in self.P['edges']:
                y = (90 - e['lat']) / 180 * 512
                c = ACC if e.get('spin', 1) > 0 else WARM
                d.polygon([(0, y - 7), (14, y), (0, y + 7)], fill=c)
                d.polygon([(1023, y - 7), (1009, y), (1023, y + 7)], fill=c)
            poles = [(sgn, key) for sgn, key in ((1, 'north'), (-1, 'south'))
                     if self.P.get('poles', {}).get(key, {}).get('type', 'none') != 'none']
            sheet = Image.new('RGB', (1024 + 512 + 24, 512 + (250 if poles else 0)), (13, 15, 20))
            sheet.paste(sph, (0, 0))
            sheet.paste(flat, (512 + 24, 0))
            if poles:
                d = ImageDraw.Draw(sheet)
                for i, (sgn, key) in enumerate(poles):
                    x = 536 + i * 260
                    sheet.paste(pole_disc(strip, sgn, 220), (x, 530))
                    d.text((x, 516), '%s pole (from above)' % key.capitalize(), fill=DIM)
            self.view_src = sheet
            self.status('Bands only – swirls appear when you press Build' if not self.proc else self.stat.cget('text'))
        else:
            f = os.path.join(self.out_path(), self.P['name'] + ('_preview.png' if v == 'preview' else '_color.png'))
            if os.path.isfile(f):
                try:
                    self.view_src = Image.open(f).convert('RGB')
                    self.view_src.load()
                except Exception:
                    self.view_src = None
                if not self.proc:
                    self.status('Settings changed since this build – press Build to update' if self.is_stale()
                                else 'Showing build at %s' % self.res.get())
            else:
                self.view_src = None
                if not self.proc:
                    self.status('Nothing built at %s yet – press Build' % self.res.get())
        self.update_export_state()
        self.redraw()

    def schedule_redraw(self):
        if self.redraw_id:
            self.after_cancel(self.redraw_id)
        self.redraw_id = self.after(60, self.redraw)

    def redraw(self):
        self.redraw_id = None
        self.canvas.delete('all')
        cw, ch = max(10, self.canvas.winfo_width()), max(10, self.canvas.winfo_height())
        if self.view_src is None:
            self.canvas.create_text(cw // 2, ch // 2, text='No picture yet', fill=DIM, font=(FONT, 12))
            return
        iw, ih = self.view_src.size
        s = min((cw - 16) / iw, (ch - 16) / ih)
        im = self.view_src.resize((max(1, int(iw * s)), max(1, int(ih * s))), Image.LANCZOS)
        self.tkimg = ImageTk.PhotoImage(im)
        self.canvas.create_image(cw // 2, ch // 2, image=self.tkimg)

    def status(self, t):
        self.stat.configure(text=t)

    def log(self, line):
        self.logbox.configure(state='normal')
        self.logbox.insert('end', line + '\n')
        self.logbox.see('end')
        self.logbox.configure(state='disabled')

    def builds(self):
        return [r for r in RES[::-1] if os.path.isfile(os.path.join(self.out_path(r), self.P['name'] + '_color.png'))]

    def update_export_state(self):
        self.export_btn.configure(state='normal' if self.builds() and not self.proc else 'disabled')

    def set_busy(self, busy):
        self.build_btn.configure(state='disabled' if busy else 'normal')
        self.cancel_btn.configure(state='normal' if busy else 'disabled')
        self.update_export_state()

    def run(self, args, done):
        if self.proc:
            return
        cmd = ([sys.executable] if gg.FROZEN else [sys.executable, '-u', GEN]) + args
        self.log('> ' + ' '.join(args[:1] + [os.path.basename(a) for a in args[1:]]))
        try:
            env = dict(os.environ, PYTHONUNBUFFERED='1')
            self.proc = subprocess.Popen(cmd, cwd=gg.TOOL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, text=True, bufsize=1, creationflags=NOWIN, env=env)
        except Exception as ex:
            messagebox.showerror('Could not start', str(ex), parent=self)
            return
        self.done_cb = done
        threading.Thread(target=self.reader, args=(self.proc,), daemon=True).start()
        self.set_busy(True)
        self.after(100, self.poll)

    def reader(self, p):
        for line in p.stdout:
            self.q.put(line.rstrip('\n'))
        p.wait()
        self.q.put(None)

    def poll(self):
        finished = False
        try:
            while True:
                line = self.q.get_nowait()
                if line is None:
                    finished = True
                    break
                self.log(line)
                self.progress(line)
        except queue.Empty:
            pass
        if finished:
            rc = self.proc.returncode
            self.proc = None
            self.set_busy(False)
            self.done_cb(rc)
        else:
            self.after(100, self.poll)

    def progress(self, line):
        w = line.split()
        try:
            if 'keyframe' in w:
                i = w.index('keyframe')
                k, K = int(w[i + 1]), int(w[i + 3])
                self.prog['value'] = 25 * k / K
                self.status('Building flow field %d of %d' % (k, K))
            elif 'trace' in w:
                pct = int(w[w.index('trace') + 1].rstrip('%'))
                self.prog['value'] = 25 + 0.55 * pct
                self.status('Moving the clouds \u2013 %d%%' % pct)
            elif 'color' in w and w[-1].endswith('%'):
                pct = int(w[-1].rstrip('%'))
                self.prog['value'] = 80 + 0.12 * pct
                self.status('Colouring \u2013 %d%%' % pct)
            elif 'color' in w and 'done' in w:
                self.prog['value'] = 92
                self.status('Writing game files')
            elif 'dds' in w and 'done' in w:
                self.prog['value'] = 97
                self.status('Making preview')
            elif 'DONE' in w:
                self.prog['value'] = 100
        except (ValueError, IndexError):
            pass

    def build(self):
        if not self.save(quiet=True):
            return
        self.steps_total = int(self.P['steps'])
        self.prog['value'] = 0
        self.status('Starting…')
        self.run(['make', self.preset_file, '--res', self.res.get()], self.built)

    def built(self, rc):
        if self.cancelled:
            self.cancelled = False
            self.status('Cancelled – Build again continues where it stopped')
        elif rc == 0:
            self.prog['value'] = 100
            self.view.set('preview')
            self.update_view()
            self.status('Done – %s at %s' % (self.P['name'], self.res.get()))
        else:
            self.status('Build failed – see the log below')
            if messagebox.askyesno('Build failed', 'The build stopped with an error (details in the log).\n\nTry again from scratch?', parent=self):
                self.prog['value'] = 0
                self.run(['make', self.preset_file, '--res', self.res.get(), '--fresh'], self.built)

    cancelled = False

    def cancel(self):
        if self.proc:
            self.cancelled = True
            self.proc.terminate()

    def export(self):
        self.commit_entries()
        b = self.builds()
        if not b:
            messagebox.showinfo('Build first', 'Press Build first \u2013 Export saves the files of a build.', parent=self)
            return
        ExportDialog(self, b)

    def close(self):
        if self.proc:
            if not messagebox.askyesno('Building', 'A build is running. Stop it and quit?', parent=self):
                return
            self.proc.terminate()
        if not self.ask_save():
            return
        self.destroy()


def main():
    if len(sys.argv) > 1 and sys.argv[1] in gg.COMMANDS:
        gg.main()
        return
    if os.name == 'nt':
        try:
            import ctypes
            if gg.FROZEN:
                hwnd = ctypes.windll.kernel32.GetConsoleWindow()
                if hwnd:
                    ctypes.windll.user32.ShowWindow(hwnd, 0)
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    App().mainloop()


if __name__ == '__main__':
    main()
