import os, sys, json, copy, queue, random, threading, subprocess, time, colorsys, shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import numpy as np
from PIL import Image, ImageTk, ImageDraw, ImageFont
try:
    import PIL._tkinter_finder
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gasgiant as gg

GEN = os.path.join(gg.TOOL, 'gasgiant.py')
RES = ['512', '1024', '2048', '4096', '8192', '16384']
LIVE_RES = ['512', '1024']
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
    for k, s in enumerate(gg.all_big(P)):
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


def sheet_font(size):
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


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


def sv_image(h, n=256):
    c = np.array(colorsys.hsv_to_rgb(h, 1.0, 1.0), np.float32)
    sat = np.linspace(0, 1, n, dtype=np.float32)[None, :, None]
    val = np.linspace(1, 0, n, dtype=np.float32)[:, None, None]
    img = val * ((1 - sat) + sat * c[None, None, :])
    return Image.fromarray((img * 255 + 0.5).astype(np.uint8))


def hue_image(w=26, n=256):
    rows = np.array([colorsys.hsv_to_rgb(y / float(n), 1.0, 1.0) for y in range(n)], np.float32)
    return Image.fromarray((np.repeat(rows[:, None, :], w, 1) * 255 + 0.5).astype(np.uint8))


def recent_colours():
    out = []
    for c in load_settings().get('recent_colours', []):
        try:
            v = [int(max(0, min(255, x))) for x in c][:3]
            if len(v) == 3:
                out.append(v)
        except (TypeError, ValueError):
            pass
    return out[:14]


def remember_colour(rgb):
    S = load_settings()
    rc = [list(rgb)] + [c for c in recent_colours() if list(c) != list(rgb)]
    S['recent_colours'] = rc[:14]
    save_settings(S)


class PixelPicker(tk.Toplevel):
    Z = 11

    def __init__(self, master, img, done, fullscreen=False):
        super().__init__(master)
        self.img = img
        self.arr = np.asarray(img).astype(np.float32)
        self.done = done
        self.finished = False
        self.configure(bg='black')
        iw, ih = img.size
        if fullscreen:
            self.overrideredirect(True)
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            self.geometry('%dx%d+0+0' % (sw, sh))
            dw, dh = sw, sh
        else:
            self.title('Click a colour in the picture')
            sc = min(1100.0 / iw, 760.0 / ih, 1.0 if max(iw, ih) > 300 else 4.0)
            dw, dh = max(1, int(iw * sc)), max(1, int(ih * sc))
        self.sx, self.sy = iw / float(dw), ih / float(dh)
        disp = img.resize((dw, dh), Image.LANCZOS) if (dw, dh) != (iw, ih) else img
        self.tkimg = ImageTk.PhotoImage(disp)
        self.cv = tk.Canvas(self, width=dw, height=dh, bg='black', highlightthickness=0, cursor='crosshair')
        self.cv.pack()
        self.cv.create_image(0, 0, image=self.tkimg, anchor='nw')
        self.loupe_img = None
        self.lp = self.cv.create_image(0, 0, anchor='nw')
        self.lbox = self.cv.create_rectangle(0, 0, 0, 0, outline='white', width=2)
        self.lfr = self.cv.create_rectangle(0, 0, 0, 0, outline='white', width=1)
        self.ltxt_bg = self.cv.create_rectangle(0, 0, 0, 0, fill='#101318', outline='')
        self.ltxt = self.cv.create_text(0, 0, anchor='nw', fill='white', font=(MONO, 10))
        self.cv.create_rectangle(dw // 2 - 210, 2, dw // 2 + 210, 28, fill='#101318', outline=LINE)
        self.cv.create_text(dw // 2, 15, text='Click a colour  \u00b7  Esc or right-click = cancel', fill='white',
                            font=(FONT, 11, 'bold'))
        self.cv.bind('<Motion>', self.move)
        self.cv.bind('<Button-1>', self.click)
        self.cv.bind('<Button-3>', lambda e: self.close(None))
        self.bind('<Escape>', lambda e: self.close(None))
        self.protocol('WM_DELETE_WINDOW', lambda: self.close(None))
        self.after(50, self.take_focus)

    def take_focus(self):
        try:
            self.lift()
            self.focus_force()
            self.grab_set()
        except tk.TclError:
            pass

    def at(self, x, y):
        H, W = self.arr.shape[:2]
        return min(max(int(x * self.sx), 0), W - 1), min(max(int(y * self.sy), 0), H - 1)

    def colour(self, ix, iy):
        H, W = self.arr.shape[:2]
        a = self.arr[max(iy - 1, 0):min(iy + 2, H), max(ix - 1, 0):min(ix + 2, W)]
        return [int(round(v)) for v in a.reshape(-1, 3).mean(0)]

    def move(self, e):
        ix, iy = self.at(e.x, e.y)
        r = self.Z // 2
        H, W = self.arr.shape[:2]
        ys = np.clip(np.arange(iy - r, iy + r + 1), 0, H - 1)
        xs = np.clip(np.arange(ix - r, ix + r + 1), 0, W - 1)
        crop = self.arr[ys][:, xs].astype(np.uint8)
        big = Image.fromarray(crop).resize((self.Z * 10, self.Z * 10), Image.NEAREST)
        self.loupe_img = ImageTk.PhotoImage(big)
        cw, ch = int(self.cv.cget('width')), int(self.cv.cget('height'))
        lx = e.x + 24 if e.x + 24 + 110 < cw else e.x - 24 - 110
        ly = e.y + 24 if e.y + 24 + 140 < ch else e.y - 24 - 140
        self.cv.itemconfigure(self.lp, image=self.loupe_img)
        self.cv.coords(self.lp, lx, ly)
        self.cv.coords(self.lfr, lx, ly, lx + 110, ly + 110)
        self.cv.coords(self.lbox, lx + 50, ly + 50, lx + 60, ly + 60)
        c = self.colour(ix, iy)
        self.cv.coords(self.ltxt_bg, lx, ly + 112, lx + 110, ly + 134)
        self.cv.coords(self.ltxt, lx + 6, ly + 115)
        self.cv.itemconfigure(self.ltxt, text=hexcol(c))
        for it in (self.lp, self.lfr, self.lbox, self.ltxt_bg, self.ltxt):
            self.cv.tag_raise(it)

    def click(self, e):
        self.close(self.colour(*self.at(e.x, e.y)))

    def close(self, rgb):
        if self.finished:
            return
        self.finished = True
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        self.done(rgb)


class ColourPicker(tk.Toplevel):
    def __init__(self, app, initial, title, live=None):
        super().__init__(app)
        self.app = app
        self.live = live
        self.result = None
        self.title(title)
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(app)
        self.initial = [int(round(float(v))) for v in initial][:3]
        self.rgb = list(self.initial)
        self.h, self.s, self.v = colorsys.rgb_to_hsv(*[c / 255.0 for c in self.rgb])
        body = ttk.Frame(self, padding=12)
        body.pack(fill='both')
        self.sv = tk.Canvas(body, width=256, height=256, highlightthickness=1, highlightbackground=LINE, cursor='crosshair', bg=BG)
        self.sv.grid(row=0, column=0, sticky='n')
        self.hue = tk.Canvas(body, width=26, height=256, highlightthickness=1, highlightbackground=LINE, cursor='sb_v_double_arrow', bg=BG)
        self.hue.grid(row=0, column=1, sticky='n', padx=(8, 14))
        self.hue_tk = ImageTk.PhotoImage(hue_image())
        self.hue.create_image(0, 0, image=self.hue_tk, anchor='nw')
        self.hue_mark = self.hue.create_rectangle(0, 0, 27, 4, outline='white', width=2)
        self.sv_img = self.sv.create_image(0, 0, anchor='nw')
        self.sv_mark = self.sv.create_oval(0, 0, 0, 0, outline='white', width=2)
        self.sv_mark2 = self.sv.create_oval(0, 0, 0, 0, outline='black', width=1)
        for ev in ('<Button-1>', '<B1-Motion>'):
            self.sv.bind(ev, self.sv_click)
            self.hue.bind(ev, self.hue_click)
        right = ttk.Frame(body)
        right.grid(row=0, column=2, sticky='n')
        self.cmp = tk.Canvas(right, width=150, height=56, highlightthickness=1, highlightbackground=LINE, bg=BG)
        self.cmp.grid(row=0, column=0, columnspan=4, sticky='w')
        self.cmp_old = self.cmp.create_rectangle(0, 0, 75, 57, outline='')
        self.cmp_new = self.cmp.create_rectangle(75, 0, 151, 57, outline='')
        self.cmp.tag_bind(self.cmp_old, '<Button-1>', lambda e: self.set_rgb(self.initial))
        ttk.Label(right, text='before          now', style='Dim.TLabel').grid(row=1, column=0, columnspan=4, sticky='w', pady=(2, 8))
        ttk.Label(right, text='Hex').grid(row=2, column=0, sticky='w')
        self.hexv = tk.StringVar()
        he = ttk.Entry(right, textvariable=self.hexv, width=9)
        he.grid(row=2, column=1, columnspan=3, sticky='w', pady=2)
        he.bind('<Return>', self.hex_typed)
        he.bind('<FocusOut>', self.hex_typed)
        self.chv = []
        for i, nm in enumerate('RGB'):
            ttk.Label(right, text=nm).grid(row=3 + i, column=0, sticky='w')
            v = tk.StringVar()
            sp = ttk.Spinbox(right, textvariable=v, from_=0, to=255, increment=1, width=6, command=self.ch_typed)
            sp.grid(row=3 + i, column=1, columnspan=3, sticky='w', pady=2)
            sp.bind('<Return>', self.ch_typed)
            sp.bind('<FocusOut>', self.ch_typed)
            self.chv.append(v)
        ttk.Button(right, text='Pick from screen', command=self.pick_screen).grid(row=6, column=0, columnspan=4, sticky='ew', pady=(12, 3))
        ttk.Button(right, text='Pick from picture\u2026', command=self.pick_picture).grid(row=7, column=0, columnspan=4, sticky='ew')
        low = ttk.Frame(self, padding=(12, 0, 12, 12))
        low.pack(fill='x')
        bands = sorted(app.P.get('bands', []), key=lambda b: b[0])
        self.swatch_row(low, 'This planet', [b[1] for b in bands], 0)
        self.swatch_row(low, 'Recent', recent_colours(), 1)
        bar = ttk.Frame(low)
        bar.grid(row=2, column=0, columnspan=2, sticky='e', pady=(10, 0))
        ttk.Button(bar, text='Cancel', command=self.cancel).pack(side='right')
        ttk.Button(bar, text='OK', style='Accent.TButton', command=self.ok).pack(side='right', padx=6)
        self.bind('<Escape>', lambda e: self.cancel())
        self.bind('<Return>', lambda e: self.ok() if not isinstance(self.focus_get(), (ttk.Entry, ttk.Spinbox)) else None)
        self.protocol('WM_DELETE_WINDOW', self.cancel)
        self.draw_sv()
        self.refresh(notify=False)
        self.update_idletasks()
        try:
            x = app.winfo_rootx() + max(0, (app.winfo_width() - self.winfo_reqwidth()) // 2)
            y = app.winfo_rooty() + max(0, (app.winfo_height() - self.winfo_reqheight()) // 3)
            self.geometry('+%d+%d' % (x, y))
        except tk.TclError:
            pass
        self.grab_set()
        self.focus_set()

    def swatch_row(self, parent, label, cols, row):
        ttk.Label(parent, text=label, style='Dim.TLabel', width=11).grid(row=row, column=0, sticky='w', pady=(6, 0))
        fr = ttk.Frame(parent)
        fr.grid(row=row, column=1, sticky='w', pady=(6, 0))
        if not cols:
            ttk.Label(fr, text='\u2013', style='Dim.TLabel').pack(side='left')
        for c in cols[:14]:
            c = [int(round(float(v))) for v in c][:3]
            lab = tk.Label(fr, bg=hexcol(c), width=2, relief='solid', bd=1, cursor='hand2')
            lab.pack(side='left', padx=(0, 3))
            lab.bind('<Button-1>', lambda e, c=c: self.set_rgb(c))

    def draw_sv(self):
        self.sv_tk = ImageTk.PhotoImage(sv_image(self.h))
        self.sv.itemconfigure(self.sv_img, image=self.sv_tk)

    def refresh(self, notify=True):
        x, y = self.s * 255, (1 - self.v) * 255
        self.sv.coords(self.sv_mark, x - 6, y - 6, x + 6, y + 6)
        self.sv.coords(self.sv_mark2, x - 7, y - 7, x + 7, y + 7)
        hy = self.h * 255
        self.hue.coords(self.hue_mark, 1, hy - 3, 27, hy + 3)
        self.cmp.itemconfigure(self.cmp_old, fill=hexcol(self.initial))
        self.cmp.itemconfigure(self.cmp_new, fill=hexcol(self.rgb))
        self.hexv.set(hexcol(self.rgb))
        for v, c in zip(self.chv, self.rgb):
            v.set(str(c))
        if notify and self.live:
            self.live(list(self.rgb))

    def from_hsv(self):
        self.rgb = [int(round(c * 255)) for c in colorsys.hsv_to_rgb(self.h, self.s, self.v)]
        self.refresh()

    def set_rgb(self, rgb):
        self.rgb = [int(max(0, min(255, round(float(c))))) for c in rgb][:3]
        h, s, v = colorsys.rgb_to_hsv(*[c / 255.0 for c in self.rgb])
        if s > 0 and v > 0:
            if abs(h - self.h) > 1e-4:
                self.h = h
                self.draw_sv()
        self.s, self.v = s, v
        self.refresh()

    def sv_click(self, e):
        self.s = min(max(e.x / 255.0, 0.0), 1.0)
        self.v = 1 - min(max(e.y / 255.0, 0.0), 1.0)
        self.from_hsv()

    def hue_click(self, e):
        self.h = min(max(e.y / 256.0, 0.0), 0.999)
        self.draw_sv()
        self.from_hsv()

    def hex_typed(self, _e=None):
        t = self.hexv.get().strip().lstrip('#')
        if len(t) == 3:
            t = ''.join(ch * 2 for ch in t)
        try:
            if len(t) != 6:
                raise ValueError
            c = [int(t[i:i + 2], 16) for i in (0, 2, 4)]
        except ValueError:
            self.hexv.set(hexcol(self.rgb))
            return
        if c != self.rgb:
            self.set_rgb(c)

    def ch_typed(self, _e=None):
        try:
            c = [int(round(float(v.get().replace(',', '.')))) for v in self.chv]
        except ValueError:
            self.refresh(notify=False)
            return
        c = [max(0, min(255, x)) for x in c]
        if c != self.rgb:
            self.set_rgb(c)

    def picked(self, rgb):
        try:
            self.deiconify()
            self.lift()
            self.grab_set()
            self.focus_set()
        except tk.TclError:
            return
        if rgb:
            self.set_rgb(rgb)

    def pick_screen(self):
        try:
            from PIL import ImageGrab
        except Exception as ex:
            messagebox.showerror('Pick from screen', 'Screen capture is not available here.\n%s' % ex, parent=self)
            return
        self.grab_release()
        self.withdraw()

        def grab():
            try:
                img = ImageGrab.grab().convert('RGB')
            except Exception as ex:
                self.picked(None)
                messagebox.showerror('Pick from screen', 'Could not capture the screen.\n%s' % ex, parent=self)
                return
            PixelPicker(self, img, self.picked, fullscreen=True)
        self.after(250, grab)

    def pick_picture(self):
        path = filedialog.askopenfilename(parent=self, title='Picture to pick a colour from',
                                          filetypes=[('Pictures', '*.png *.jpg *.jpeg *.bmp *.tga *.webp *.dds'), ('All files', '*.*')])
        if not path:
            return
        try:
            img = Image.open(path).convert('RGB')
        except Exception as ex:
            messagebox.showerror('Could not open picture', str(ex), parent=self)
            return
        self.grab_release()
        PixelPicker(self, img, self.picked, fullscreen=False)

    def ok(self):
        self.ch_typed()
        self.result = list(self.rgb)
        self.grab_release()
        self.destroy()

    def cancel(self):
        self.result = None
        self.grab_release()
        self.destroy()


def pick_colour(app, initial, title='Pick a colour', live=None, restore=None):
    snap = getattr(app, 'snapshot', None)
    if snap:
        snap()
    dlg = ColourPicker(app, initial, title, live)
    app.wait_window(dlg)
    res = dlg.result
    same = res is not None and list(res) == [int(round(float(v))) for v in initial][:3]
    if res is None or same:
        if snap and app.history:
            app.history.pop()
            if not app.history:
                app.undo_btn.configure(state='disabled')
        if restore:
            restore()
        return None
    remember_colour(res)
    return res


class Swatch:
    def __init__(self, app, parent, path):
        self.app, self.path = app, path
        self.lab = tk.Label(parent, width=6, relief='solid', bd=1, cursor='hand2')
        self.lab.bind('<Button-1>', self.pick)
        app.swatches.append(self)

    def refresh(self):
        self.lab.configure(bg=hexcol(getp(self.app.P, self.path)))

    def pick(self, _e=None):
        old = copy.deepcopy(getp(self.app.P, self.path))

        def live(v):
            setp(self.app.P, self.path, v)
            self.refresh()
            self.app.changed()

        def restore():
            live(old)
        c = pick_colour(self.app, old, live=live, restore=restore)
        if c:
            live(c)


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
        self.body.configure(height=1, width=1)
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
                old = copy.deepcopy(f['get'](item))

                def live(v):
                    f['set'](item, v)
                    try:
                        lab.configure(bg=hexcol(v))
                    except tk.TclError:
                        pass
                    self.notify()

                def restore():
                    live(old)
                c = pick_colour(self.app, old, live=live, restore=restore)
                if c:
                    live(c)
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
        self.body.configure(height=1, width=1)
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
            old = copy.deepcopy(item.get(k))

            def live(v):
                item[k] = v
                lab.configure(bg=hexcol(v))
                self.app.changed()

            def restore():
                item[k] = old
            c = pick_colour(self.app, old or [int(round(float(x))) for x in auto], live=live, restore=restore)
            if c:
                item[k] = c
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
    KINDS = (('color', 'Colour map'), ('normal', 'Normal map'), ('flow', 'Flow map'), ('emissive', 'Emissive map'), ('ring', 'Ring texture'), ('atmo', 'Scatterer config'), ('preview', 'Preview sheet'))
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
        defaults = {'color': True, 'normal': True, 'flow': True, 'emissive': True, 'ring': True, 'atmo': True, 'preview': False}
        for i, (k, lab) in enumerate(self.KINDS):
            on = tk.BooleanVar(value=self.S.get('on_' + k, defaults[k]))
            chk = ttk.Checkbutton(f, text=lab, variable=on)
            chk.grid(row=4 + i, column=0, sticky='w', pady=3)
            fn = self.P['files'].get(k) or ''
            base = os.path.splitext(os.path.basename(fn))[0] if fn and k != 'atmo' else '%s_%s' % (self.name, k)
            v_name = tk.StringVar(value=base)
            ttk.Entry(f, textvariable=v_name, width=30).grid(row=4 + i, column=1, sticky='w', pady=3)
            v_fmt = tk.StringVar(value=self.S.get('fmt_' + k) if self.S.get('fmt_' + k) in gg.EXPORT_FORMATS[k] else gg.EXPORT_FORMATS[k][0])
            fc = ttk.Combobox(f, textvariable=v_fmt, values=gg.EXPORT_FORMATS[k], width=27, state='readonly')
            fc.grid(row=4 + i, column=2, sticky='w', pady=3)
            note = ttk.Label(f, text='', style='Dim.TLabel')
            note.grid(row=4 + i, column=3, sticky='w', padx=(6, 0))
            self.rows[k] = (on, chk, v_name, v_fmt, note)
        nk = 4 + len(self.KINDS)
        ttk.Label(f, text='Size').grid(row=nk, column=0, sticky='w', pady=(12, 4))
        self.v_size = tk.StringVar(value=self.S.get('size') if self.S.get('size') in self.SIZES else self.SIZES[0])
        ttk.Combobox(f, textvariable=self.v_size, values=self.SIZES, width=14, state='readonly').grid(row=nk, column=1, sticky='w', pady=(12, 4))
        self.v_flip = tk.BooleanVar(value=self.S.get('flip', True))
        ttk.Checkbutton(f, text='Flip DDS files upside down (KSP needs this)', variable=self.v_flip).grid(row=nk + 1, column=0, columnspan=3, sticky='w', pady=4)
        ttk.Label(f, text='Which DDS?  Colour and emissive maps: BC1 / DXT1 is what KSP uses by default, BC7 looks '
                          'best but the file is twice as big, BC3 / DXT5 if you need an alpha channel.  Normal map: '
                          'DXT5nm for KSP\u2019s own planet shaders, BC5 for shaders that ask for it.  BC5 and BC7 '
                          'need a texture loader that reads them, such as KSPTextureLoader.',
                  style='Dim.TLabel', wraplength=640, justify='left').grid(row=nk + 2, column=0, columnspan=4, sticky='w', pady=(8, 0))
        self.stat = ttk.Label(f, text='', style='Dim.TLabel', wraplength=640, justify='left')
        self.stat.grid(row=nk + 3, column=0, columnspan=4, sticky='w', pady=(10, 0))
        bar = ttk.Frame(f)
        bar.grid(row=nk + 4, column=0, columnspan=4, sticky='e', pady=(14, 0))
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
               'ring': os.path.isfile(os.path.join(src, self.name + '_ring.png')),
               'atmo': gg.has_atmo(self.P),
               'preview': os.path.isfile(os.path.join(src, self.name + '_preview.png'))}
        for k, (on, chk, v_name, v_fmt, note) in self.rows.items():
            if has[k]:
                chk.state(['!disabled'])
                note.configure(text='')
            else:
                on.set(False)
                chk.state(['disabled'])
                note.configure(text='no atmosphere' if k == 'atmo' else 'not in this build')
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
        targets = [gg.export_target(folder, b, fm) for _, b, fm in jobs]
        if any(k == 'atmo' for k, _, _ in jobs):
            targets.append(gg.planets_file(folder, self.name))
        exist = [t for t in targets if os.path.exists(t)]
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
        st = load_settings()
        self.live_on = tk.BooleanVar(value=bool(st.get('live_swirls', True)))
        self.live_size = tk.StringVar(value=str(st.get('live_size', 512)) if str(st.get('live_size', 512)) in LIVE_RES else '512')
        self.live_lock = threading.Lock()
        self.live_q = queue.Queue()
        self.live_cache = {}
        self.live_gen = 0
        self.live_req = None
        self.live_thread = None
        self.live_last = None
        self.live_after = None
        self.live_err = None
        self.live_view = None
        self.rot = [0.0, 0.0]
        self.drag = None
        self.sdrag = None
        self.map_tool = tk.StringVar(value='turn')
        self.cdrag = None
        self.bdrag = None
        self.view_geom = None
        self.atmo_lock = threading.Lock()
        self.atmo_q = queue.Queue()
        self.atmo_gen = 0
        self.atmo_req = None
        self.atmo_thread = None
        self.atmo_img = None
        self.atmo_key = None
        self.atmo_want = None
        self.atmo_err = None
        self.atmo_texc = {}
        self.adrag = None
        self.build_ui()
        self.after(150, self.live_poll)
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
        self.tab_rings()
        self.tab_atmo()
        self.tab_body()
        vb = ttk.Frame(right)
        vb.pack(fill='x')
        for val, txt in (('bands', 'Live preview'), ('atmo', 'In game'), ('preview', 'Preview sheet'), ('flat', 'Flat map')):
            ttk.Radiobutton(vb, text=txt, value=val, variable=self.view, style='Toolbutton',
                            command=self.update_view).pack(side='left', padx=(0, 4))
        ttk.Checkbutton(vb, text='Swirls', variable=self.live_on, command=self.toggle_live).pack(side='left', padx=(10, 4))
        lcb = ttk.Combobox(vb, textvariable=self.live_size, values=LIVE_RES, width=5, state='readonly')
        lcb.pack(side='left', padx=(0, 8))
        lcb.bind('<<ComboboxSelected>>', self.live_size_changed)
        self.export_btn = ttk.Button(vb, text='Export…', command=self.export)
        self.export_btn.pack(side='right')
        tb = ttk.Frame(right)
        tb.pack(fill='x', pady=(6, 0))
        ttk.Label(tb, text='On the map', style='Dim.TLabel').pack(side='left', padx=(0, 8))
        for val, txt in (('turn', 'Turn globe'), ('storms', 'Place storms'), ('chain', 'Storm chain'), ('bands', 'Move bands')):
            ttk.Radiobutton(tb, text=txt, value=val, variable=self.map_tool, style='Toolbutton',
                            command=self.tool_changed).pack(side='left', padx=(0, 4))
        self.live_lab = ttk.Label(tb, text='', style='Dim.TLabel')
        self.live_lab.pack(side='right')
        self.canvas = tk.Canvas(right, bg='#0d0f14', highlightthickness=1, highlightbackground=LINE)
        self.canvas.pack(fill='both', expand=True, pady=(8, 8))
        self.canvas.bind('<Configure>', lambda e: self.schedule_redraw())
        self.canvas.bind('<ButtonPress-1>', self.drag_start)
        self.canvas.bind('<B1-Motion>', self.drag_move)
        self.canvas.bind('<ButtonRelease-1>', self.drag_end)
        self.canvas.bind('<Double-Button-1>', self.drag_reset)
        self.canvas.bind('<Button-3>', self.storm_remove_click)
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
        if what == 'rings':
            r = P['rings']
            r.update({'zones': random.randint(2, 6), 'ringlets': round(R(0.3, 0.9), 2), 'detail': round(R(0.6, 1.8), 2),
                      'opacity': round(R(0.6, 0.95), 2), 'edge': round(R(0.1, 0.6), 2), 'variation': round(R(0.2, 0.6), 2),
                      'pattern': random.randint(0, 9999)})
            k = random.randint(1, 3)
            gaps = [[round(R(0.35, 0.75), 3), round(R(0.02, 0.05), 3), round(R(0.85, 1.0), 2)]]
            for _ in range(k - 1):
                gaps.append([round(R(0.12, 0.96), 3), round(R(0.003, 0.012), 3), round(R(0.6, 1.0), 2)])
            r['gaps'] = sorted(gaps)
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
        ttk.Button(ed.bar, text='Move on the map', command=lambda: self.set_tool('bands')).pack(side='left', padx=6)
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
            old = copy.deepcopy(item.get('color'))

            def live(v):
                item['color'] = v
                lab.configure(bg=hexcol(v))
                self.changed()

            def restore():
                item['color'] = old
            c = pick_colour(self, old or band_col, live=live, restore=restore)
            if c:
                item['color'] = c
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
        ttk.Button(be.bar, text='Place on the map', command=self.place_from_tab).pack(side='left', padx=6)
        self.section(p, 'Storm chains')
        ttk.Label(p, text='A row of storms along a latitude, like Jupiter\u2019s \u201cstring of pearls\u201d. Length 360 = all the '
                          'way round. Jitter makes them a little uneven. Draw one on the map with \u201cStorm chain\u201d '
                          'above the preview.', style='Dim.TLabel', wraplength=520).pack(anchor='w')
        cdef = gg.CHAIN
        ce = ListEditor(self, p, lambda: self.P['storm_chains'],
                        [num('Latitude', 'lat', -85, 85, 0.5, '%.1f'), num('End latitude', 'lat_end', -85, 85, 0.5, '%.1f'),
                         num('Longitude', 'lon', 0, 360, 1, '%.0f'), num('Length (\u00b0)', 'length', 1, 360, 1, '%.0f', cdef['length']),
                         num('Count', 'count', 1, 40, 1, '%.0f', cdef['count'], isint=True),
                         num('Size', 'size', 0.004, 0.05, 0.001, '%.3f', cdef['size']),
                         num('Stretch', 'aspect', 1, 4, 0.1, '%.1f', cdef['aspect']),
                         num('Turns', 'turns', 0, 3, 0.1, '%.1f', cdef['turns']), spinf('Spin', 'spin'),
                         num('Ragged', 'ragged', 0, 0.6, 0.05, '%.2f', cdef['ragged']),
                         num('Bright centre', 'core', 0, 1, 0.05, '%.2f', cdef['core']),
                         num('Centre size', 'core_size', 0.1, 1.5, 0.05, '%.2f', cdef['core_size']),
                         colf('Centre colour', 'core_color', tuple(cdef['core_color'])),
                         num('Jitter', 'jitter', 0, 1, 0.05, '%.2f', cdef['jitter'])],
                        self.new_chain, card=True, cols=4, add_text='Add storm chain')
        ce.frame.pack(fill='x', pady=6)
        self.chain_ed = ce
        ttk.Button(ce.bar, text='Draw on the map', command=lambda: self.set_tool('chain')).pack(side='left', padx=6)

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
            old = copy.deepcopy(item.get('arm_color'))

            def live(v):
                item['arm_color'] = v
                lab.configure(bg=hexcol(v))
                self.changed()

            def restore():
                item['arm_color'] = old
            c = pick_colour(self, old or item.get('core_color') or cur, live=live, restore=restore)
            if c:
                item['arm_color'] = c
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
        for i, (k, lab) in enumerate((('color', 'Colour map'), ('normal', 'Normal map'), ('flow', 'Flow map'), ('emissive', 'Emissive map'), ('ring', 'Ring texture'))):
            ttk.Label(g, text=lab).grid(row=i, column=0, sticky='w', padx=8, pady=4)
            v = tk.StringVar()
            e = ttk.Entry(g, textvariable=v, width=40)
            e.grid(row=i, column=1, sticky='w', pady=4)
            e.bind('<Return>', self.commit_files)
            e.bind('<FocusOut>', self.commit_files)
            self.v_files[k] = v
        self.v_flow = tk.BooleanVar(value=True)
        ttk.Checkbutton(g, text='Make an EVE flow map', variable=self.v_flow, command=self.commit_files).grid(row=5, column=1, sticky='w', pady=4)
        self.section(p, 'Preview camera')
        g = self.grid_box(p)
        Slider(self, g, 0, 'Tilt', ('preview', 'tilt'), -90, 90, 1)
        Slider(self, g, 1, 'View latitude', ('preview', 'view_lat'), -90, 90, 1)
        Slider(self, g, 2, 'View longitude', ('preview', 'view_lon'), 0, 360, 5)

    def new_chain(self):
        c = gg.chain_entry({})
        c['core_color'] = [int(min(255, v + 10)) for v in self.P['storms']['core_color']]
        return c

    def tab_rings(self):
        sf = ScrollFrame(self.nb)
        self.nb.add(sf, text='Rings')
        self.rings_tab = sf
        p = sf.inner
        top = ttk.Frame(p)
        top.pack(fill='x', pady=(2, 0))
        self.ring_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text='This planet has rings', variable=self.ring_on, command=self.ring_toggle).pack(side='left')
        ttk.Button(top, text='Randomize rings', command=lambda: self.randomize('rings')).pack(side='right')
        ttk.Button(top, text='New pattern', command=self.ring_new_pattern).pack(side='right', padx=6)
        self.ring_cv = tk.Canvas(p, width=560, height=300, bg='#0d0f14', highlightthickness=1, highlightbackground=LINE)
        self.ring_cv.pack(anchor='w', pady=(8, 4))
        self.ring_strip = tk.Canvas(p, width=560, height=24, bg='#0d0f14', highlightthickness=1, highlightbackground=LINE)
        self.ring_strip.pack(anchor='w')
        lr = ttk.Frame(p)
        lr.pack(fill='x')
        ttk.Label(lr, text='inner edge', style='Dim.TLabel').pack(side='left')
        ttk.Label(lr, text='outer edge', style='Dim.TLabel').pack(side='left', padx=(450, 0))
        self.section(p, 'Size and tilt')
        g = self.grid_box(p)
        Slider(self, g, 0, 'Inner edge (planet radii)', ('rings', 'inner'), 1.0, 4.0, 0.01)
        Slider(self, g, 1, 'Outer edge (planet radii)', ('rings', 'outer'), 1.1, 8.0, 0.01)
        Slider(self, g, 2, 'Tilt (\u00b0)', ('rings', 'angle'), 0, 90, 0.5, tip='against the equator; goes into the config as angle')
        Slider(self, g, 4, 'View from (\u00b0)', ('rings', 'view'), 2, 80, 1, tip='only for this picture')
        self.section(p, 'Structure')
        g = self.grid_box(p)
        Slider(self, g, 0, 'Wide zones', ('rings', 'zones'), 1, 8, 1, isint=True)
        Slider(self, g, 1, 'Ringlets', ('rings', 'ringlets'), 0, 1, 0.05)
        Slider(self, g, 2, 'Ringlet detail', ('rings', 'detail'), 0.3, 3, 0.05)
        Slider(self, g, 3, 'Opacity', ('rings', 'opacity'), 0, 1, 0.05)
        Slider(self, g, 4, 'Soft edges', ('rings', 'edge'), 0, 1, 0.05)
        Slider(self, g, 5, 'Colour variation', ('rings', 'variation'), 0, 1, 0.05)
        self.section(p, 'Gaps')
        ttk.Label(p, text='Position 0 = inner edge, 1 = outer edge. Width in the same units. Depth 1 = empty.',
                  style='Dim.TLabel', wraplength=520).pack(anchor='w')
        ge = ListEditor(self, p, lambda: self.P['rings']['gaps'],
                        [num('Position', 0, 0, 1, 0.005, '%.3f', width=8), num('Width', 1, 0.001, 0.3, 0.001, '%.3f', width=8),
                         num('Depth', 2, 0, 1, 0.05, '%.2f')],
                        lambda: [round(random.uniform(0.2, 0.9), 3), 0.01, 1.0], add_text='Add gap')
        ge.frame.pack(fill='x', pady=6)
        self.gap_ed = ge
        ttk.Button(ge.bar, text='Random gaps', command=self.ring_random_gaps).pack(side='left', padx=6)
        self.section(p, 'Colours')
        ttk.Label(p, text='Left on auto, the ring colours come from the planet\u2019s bands.', style='Dim.TLabel').pack(anchor='w')
        self.ring_cols = ttk.Frame(p)
        self.ring_cols.pack(fill='x', pady=(4, 0))
        self.section(p, 'Texture and Kopernicus config')
        g = ttk.Frame(p)
        g.pack(fill='x')
        ttk.Label(g, text='Texture width').pack(side='left', padx=(8, 8))
        self.ring_size = tk.StringVar(value='2048')
        rc = ttk.Combobox(g, textvariable=self.ring_size, values=['1024', '2048', '4096'], width=6, state='readonly')
        rc.pack(side='left')
        rc.bind('<<ComboboxSelected>>', self.ring_size_changed)
        ttk.Label(p, text='Build writes the ring texture with the other maps; Export saves it as DDS (BC3 / DXT5 with '
                          'alpha, or BC7) or PNG. The left end of the file is the outer edge of the ring, which is how '
                          'Kopernicus maps it. Paste this into the planet\u2019s Body node:',
                  style='Dim.TLabel', wraplength=520, justify='left').pack(anchor='w', pady=(6, 4))
        self.ring_cfg = tk.Text(p, height=13, width=64, bg=FIELD, fg=FG, insertbackground=FG, relief='flat', font=(MONO, 9))
        self.ring_cfg.pack(anchor='w')
        ttk.Button(p, text='Copy config', command=self.ring_copy).pack(anchor='w', pady=(6, 0))
        self.swatches.append(type('R', (), {'refresh': lambda s=None: self.ring_refresh()})())
        self.nb.bind('<<NotebookTabChanged>>', lambda e: self.ring_schedule(), add='+')

    def ring_visible(self):
        try:
            return self.nb.select() == str(self.rings_tab)
        except (tk.TclError, AttributeError):
            return False

    def ring_schedule(self, delay=150):
        if not self.ring_visible():
            return
        if getattr(self, 'ring_after', None):
            self.after_cancel(self.ring_after)
        self.ring_after = self.after(delay, self.ring_draw)

    def ring_refresh(self):
        r = self.P['rings']
        self.ring_on.set(bool(r.get('enabled')))
        self.ring_size.set(str(r.get('size', 2048)))
        for w in self.ring_cols.winfo_children():
            w.destroy()
        for i, (k, lab) in enumerate((('inner_color', 'Inner'), ('middle_color', 'Middle'), ('outer_color', 'Outer'))):
            ttk.Label(self.ring_cols, text=lab).grid(row=0, column=i * 2, sticky='w', padx=(8, 6))
            self.ring_colour_pick(self.ring_cols, k).grid(row=0, column=i * 2 + 1, sticky='w', padx=(0, 18))
        self.ring_text()
        self.ring_schedule(10)

    def ring_colour_pick(self, parent, k):
        fr = ttk.Frame(parent)
        r = self.P['rings']
        auto = gg.ring_colours(self.P, gg.ring_entry(r))[('inner_color', 'middle_color', 'outer_color').index(k)]
        auto = [int(round(float(v))) for v in auto]
        lab = tk.Label(fr, bg=hexcol(r.get(k) or auto), width=6, relief='solid', bd=1, cursor='hand2')
        lab.pack(side='left')

        def pick(_e=None):
            old = copy.deepcopy(r.get(k))

            def live(v):
                r[k] = v
                lab.configure(bg=hexcol(v))
                self.changed()

            def restore():
                r[k] = old
            c = pick_colour(self, old or auto, live=live, restore=restore)
            if c:
                r[k] = c
            self.ring_refresh()
            self.changed()

        def reset():
            r[k] = None
            self.ring_refresh()
            self.changed()
        lab.bind('<Button-1>', pick)
        if r.get(k):
            ttk.Button(fr, text='\u21ba', width=2, style='Small.TButton', command=reset).pack(side='left', padx=(4, 0))
        else:
            ttk.Label(fr, text='auto', style='Dim.TLabel').pack(side='left', padx=(6, 0))
        return fr

    def ring_path(self):
        fn = self.P['files'].get('ring') or '%s_ring.dds' % self.P['name']
        base = os.path.splitext(fn)[0].replace('\\', '/')
        d = gg.texture_dir() if hasattr(gg, 'texture_dir') else None
        pre = 'MyPlanets/Textures'
        if d:
            parts = os.path.normpath(d).split(os.sep)
            low = [x.lower() for x in parts]
            if 'gamedata' in low:
                i = len(low) - 1 - low[::-1].index('gamedata')
                if i + 1 < len(parts):
                    pre = '/'.join(parts[i + 1:])
        return pre + '/' + base

    def ring_text(self):
        self.ring_cfg.configure(state='normal')
        self.ring_cfg.delete('1.0', 'end')
        self.ring_cfg.insert('1.0', gg.ring_snippet(self.P, self.ring_path()))
        self.ring_cfg.configure(state='disabled')

    def ring_copy(self):
        self.clipboard_clear()
        self.clipboard_append(gg.ring_snippet(self.P, self.ring_path()))
        self.status('Ring config copied')

    def ring_draw(self):
        self.ring_after = None
        try:
            e = gg.ring_entry(self.P['rings'])
            col, a = gg.ring_profile(self.P, 1024)
            L = self.live_last if self.live_on.get() else None
            tex = L['col'] if L is not None else np.asarray(band_image(self.P, 1024, 512))
            img = gg.ring_scene(tex, col, a, e)
            if not e['enabled']:
                img = Image.blend(img, Image.new('RGB', img.size, (13, 15, 20)), 0.55)
                d = ImageDraw.Draw(img)
                d.text((12, 10), 'Rings are off \u2013 tick \u201cThis planet has rings\u201d', fill=(220, 225, 235), font=sheet_font(15))
            self.ring_img = ImageTk.PhotoImage(img)
            self.ring_cv.delete('all')
            self.ring_cv.create_image(0, 0, image=self.ring_img, anchor='nw')
            st = np.concatenate([col, (a * 255)[:, None]], 1)
            ch = np.array([13, 15, 20], np.float32)
            rgb = st[:, :3] * (st[:, 3:] / 255) + ch * (1 - st[:, 3:] / 255)
            strip = Image.fromarray(np.repeat(rgb[None], 24, 0).clip(0, 255).astype(np.uint8)).resize((560, 24), Image.LANCZOS)
            self.ring_strip_img = ImageTk.PhotoImage(strip)
            self.ring_strip.delete('all')
            self.ring_strip.create_image(0, 0, image=self.ring_strip_img, anchor='nw')
        except Exception as ex:
            self.ring_cv.delete('all')
            self.ring_cv.create_text(280, 150, text='Could not draw the rings: %s' % ex, fill=DIM)
        self.ring_text()

    def ring_toggle(self):
        self.snapshot()
        self.P['rings']['enabled'] = bool(self.ring_on.get())
        if self.ring_on.get() and not self.P['files'].get('ring'):
            self.P['files']['ring'] = '%s_ring.dds' % self.P['name']
            if 'ring' in self.v_files:
                self.v_files['ring'].set(self.P['files']['ring'])
        self.changed()
        self.ring_schedule(10)

    def ring_size_changed(self, _e=None):
        self.P['rings']['size'] = int(self.ring_size.get())
        self.changed()

    def ring_new_pattern(self):
        self.snapshot()
        self.P['rings']['pattern'] = int(self.P['rings'].get('pattern', 0)) + 1
        self.changed()
        self.ring_schedule(10)

    def ring_random_gaps(self):
        self.snapshot()
        k = random.randint(1, 4)
        gaps = [[round(random.uniform(0.35, 0.75), 3), round(random.uniform(0.02, 0.05), 3), round(random.uniform(0.85, 1.0), 2)]]
        for _ in range(k - 1):
            gaps.append([round(random.uniform(0.12, 0.96), 3), round(random.uniform(0.003, 0.012), 3), round(random.uniform(0.6, 1.0), 2)])
        self.P['rings']['gaps'] = sorted(gaps)
        self.gap_ed.rebuild()
        self.changed()
        self.ring_schedule(10)

    ATMO_TIPS = {'HR': 'HR \u2013 how fast the air thins out with height (km)',
                 'HM': 'HM \u2013 how fast the haze thins out with height (km)',
                 'm_mieG': 'm_mieG \u2013 how strongly the haze glows when you look towards the sun',
                 'atmosphereStartRadiusScale': 'atmosphereStartRadiusScale \u2013 below 1 the air starts under the cloud tops',
                 'averageGroundReflectance': 'averageGroundReflectance \u2013 light bounced back up from the planet',
                 'godrayStrength': 'godrayStrength \u2013 only in game, not in this preview'}

    def tab_atmo(self):
        sf = ScrollFrame(self.nb)
        self.nb.add(sf, text='Atmosphere')
        self.atmo_tab = sf
        p = sf.inner
        A = ('atmosphere',)
        top = ttk.Frame(p)
        top.pack(fill='x', pady=(2, 0))
        self.atmo_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text='Scatterer atmosphere', variable=self.atmo_on, command=self.atmo_toggle).pack(side='left')
        ttk.Button(top, text='Load from Scatterer config\u2026', command=self.atmo_load).pack(side='right')
        ttk.Label(p, text='The values are the ones in Scatterer\u2019s atmo.cfg. The \u201cIn game\u201d view on the right shows the '
                          'planet with this atmosphere the way KSP\u2019s map view shows it.',
                  style='Dim.TLabel', wraplength=520, justify='left').pack(anchor='w', pady=(4, 0))
        vr = ttk.Frame(p)
        vr.pack(fill='x', pady=(8, 0))
        ttk.Label(vr, text='Show').pack(side='left', padx=(8, 8))
        self.atmo_view = tk.StringVar(value='planet')
        for val, txt in (('planet', 'Whole planet'), ('limb', 'Day-side edge'), ('sunset', 'Sunset edge')):
            ttk.Radiobutton(vr, text=txt, value=val, variable=self.atmo_view, style='Toolbutton',
                            command=self.atmo_view_changed).pack(side='left', padx=(0, 4))
        ttk.Button(vr, text='In game view', command=self.atmo_show).pack(side='right')
        g = self.grid_box(p)
        Slider(self, g, 0, 'Sun angle (\u00b0)', A + ('sun_angle',), 0, 170, 1,
               tip='only for the picture: 0 = sun behind you, 90 = from the side, 150 = from behind the planet')
        pr = ttk.Frame(p)
        pr.pack(fill='x', pady=(8, 0))
        ttk.Label(pr, text='Start from').pack(side='left', padx=(8, 8))
        self.atmo_preset = tk.StringVar(value='The planet\u2019s colours')
        ttk.Combobox(pr, textvariable=self.atmo_preset, values=['The planet\u2019s colours'] + list(gg.ATMO_PRESETS),
                     width=22, state='readonly').pack(side='left')
        ttk.Button(pr, text='Apply', command=self.atmo_apply_preset).pack(side='left', padx=6)
        self.section(p, 'Planet')
        rr = ttk.Frame(p)
        rr.pack(fill='x')
        ttk.Label(rr, text='Radius (km)').pack(side='left', padx=(8, 8))
        self.v_atmo_radius = tk.StringVar()
        en = ttk.Entry(rr, textvariable=self.v_atmo_radius, width=10)
        en.pack(side='left')
        en.bind('<Return>', self.atmo_commit_entries)
        en.bind('<FocusOut>', self.atmo_commit_entries)
        ttk.Button(rr, text='Read from Kopernicus config', command=self.atmo_find_radius).pack(side='left', padx=6)
        ttk.Label(p, text='Scatterer takes the radius from the planet itself; it only matters here for the picture.',
                  style='Dim.TLabel', wraplength=520).pack(anchor='w', pady=(2, 0))
        g = self.grid_box(p)
        Slider(self, g, 0, 'Air starts at (\u00d7 radius)', A + ('atmosphereStartRadiusScale',), 0.95, 1.05, 0.001,
               tip=self.ATMO_TIPS['atmosphereStartRadiusScale'])
        self.section(p, 'Rayleigh scattering \u2013 the colour of the sky')
        ttk.Label(p, text='m_betaR: how strongly the air scatters red, green and blue. Bigger = thicker, brighter air.',
                  style='Dim.TLabel', wraplength=520).pack(anchor='w')
        g = self.grid_box(p)
        Slider(self, g, 0, 'Scale height (km)', A + ('HR',), 0.5, 150, 0.1, tip=self.ATMO_TIPS['HR'])
        for i, c in enumerate(('Red', 'Green', 'Blue')):
            Slider(self, g, 2 + i, c, A + ('m_betaR', i), 0, 0.06, 0.00001, notify=self.atmo_colours_changed)
        cr = ttk.Frame(p)
        cr.pack(fill='x', pady=(6, 0))
        self.atmo_sky_sw = tk.Label(cr, width=6, relief='solid', bd=1, cursor='hand2')
        self.atmo_sky_sw.pack(side='left', padx=(8, 6))
        self.atmo_sky_sw.bind('<Button-1>', lambda e: self.atmo_pick_colour('m_betaR'))
        ttk.Button(cr, text='Sky colour\u2026', command=lambda: self.atmo_pick_colour('m_betaR')).pack(side='left')
        ttk.Button(cr, text='Match the planet', command=self.atmo_match).pack(side='left', padx=6)
        self.section(p, 'Mie scattering \u2013 haze')
        ttk.Label(p, text='BETA_MSca: how much haze there is, for red, green and blue.', style='Dim.TLabel', wraplength=520).pack(anchor='w')
        g = self.grid_box(p)
        Slider(self, g, 0, 'Scale height (km)', A + ('HM',), 0.1, 60, 0.01, tip=self.ATMO_TIPS['HM'])
        for i, c in enumerate(('Red', 'Green', 'Blue')):
            Slider(self, g, 2 + i, c, A + ('BETA_MSca', i), 0, 0.06, 0.00001, notify=self.atmo_colours_changed)
        Slider(self, g, 5, 'Glow towards the sun', A + ('m_mieG',), 0, 0.99, 0.01, tip=self.ATMO_TIPS['m_mieG'])
        cr = ttk.Frame(p)
        cr.pack(fill='x', pady=(6, 0))
        self.atmo_haze_sw = tk.Label(cr, width=6, relief='solid', bd=1, cursor='hand2')
        self.atmo_haze_sw.pack(side='left', padx=(8, 6))
        self.atmo_haze_sw.bind('<Button-1>', lambda e: self.atmo_pick_colour('BETA_MSca'))
        ttk.Button(cr, text='Haze colour\u2026', command=lambda: self.atmo_pick_colour('BETA_MSca')).pack(side='left')
        ttk.Button(cr, text='Grey haze', command=self.atmo_grey_haze).pack(side='left', padx=6)
        self.section(p, 'Absorbing layer (ozone)')
        self.atmo_oz = tk.BooleanVar(value=False)
        ttk.Checkbutton(p, text='useOzone \u2013 a layer that swallows some colours (ozone, methane\u2026)', variable=self.atmo_oz,
                        command=lambda: self.atmo_flag('useOzone', self.atmo_oz)).pack(anchor='w', padx=(8, 0))
        g = self.grid_box(p)
        for i, c in enumerate(('Red', 'Green', 'Blue')):
            Slider(self, g, i, 'Absorbs ' + c.lower(), A + ('ozoneAbsorption', i), 0, 0.005, 0.000001)
        Slider(self, g, 3, 'Height (km)', A + ('ozoneHeight',), 0, 300, 0.5, tip='ozoneHeight \u2013 the middle of the layer')
        Slider(self, g, 5, 'Half thickness (km)', A + ('ozoneFalloff',), 0.5, 200, 0.5, tip='ozoneFalloff')
        self.section(p, 'Light')
        g = self.grid_box(p)
        Slider(self, g, 0, 'Light from below', A + ('averageGroundReflectance',), 0, 1, 0.01, tip=self.ATMO_TIPS['averageGroundReflectance'])
        Slider(self, g, 2, 'Godrays', A + ('godrayStrength',), 0, 1, 0.05, tip=self.ATMO_TIPS['godrayStrength'])
        self.atmo_ms = tk.BooleanVar(value=True)
        ttk.Checkbutton(p, text='multipleScattering \u2013 light that bounces around more than once (softer, brighter)',
                        variable=self.atmo_ms, command=lambda: self.atmo_flag('multipleScattering', self.atmo_ms)).pack(anchor='w', padx=(8, 0), pady=(4, 0))
        self.section(p, 'Seen from orbit (the last config point)')
        g = self.grid_box(p)
        L = A + ('configPoints', -1)
        for i, (k, lab, lo, hi, st, tip) in enumerate((
                ('skyExposure', 'Sky brightness', 0.005, 1.0, 0.005, 'skyExposure \u2013 the glow around the planet'),
                ('scatteringExposure', 'Haze over the planet', 0.005, 1.0, 0.005, 'scatteringExposure \u2013 the light the air adds over the planet'),
                ('extinctionThickness', 'Shade from the air', 0, 1.5, 0.01, 'extinctionThickness \u2013 how much the air darkens the planet below'),
                ('extinctionTint', 'Coloured shade', 0, 1, 0.01, 'extinctionTint \u2013 0 = grey, 1 = in the colours of the air'),
                ('skyAlpha', 'Sky opacity', 0, 1, 0.01, 'skyAlpha'),
                ('skyExtinctionTint', 'Sky shade colour', 0, 1, 0.01, 'skyExtinctionTint \u2013 tints the stars behind the air; not in the picture'))):
            Slider(self, g, i * 2, lab, L + (k,), lo, hi, st, tip=tip, notify=self.atmo_point_changed)
        self.section(p, 'Config points')
        ttk.Label(p, text='Scatterer blends between these by the camera\u2019s height above the planet (in metres). Below the first '
                          'point it uses the first, above the last the last; the map view always uses the last one.',
                  style='Dim.TLabel', wraplength=520, justify='left').pack(anchor='w')
        pts = ListEditor(self, p, lambda: self.P['atmosphere']['configPoints'],
                         [num('altitude', 'altitude', -1e6, 1e9, 1000, '%.0f', width=10),
                          num('skyExposure', 'skyExposure', 0, 5, 0.01, '%.3f'),
                          num('scatteringExposure', 'scatteringExposure', 0, 5, 0.01, '%.3f'),
                          num('skyAlpha', 'skyAlpha', 0, 1, 0.05, '%.2f'),
                          num('skyExtinctionTint', 'skyExtinctionTint', 0, 1, 0.05, '%.2f'),
                          num('extinctionThickness', 'extinctionThickness', 0, 2, 0.05, '%.2f'),
                          num('extinctionTint', 'extinctionTint', 0, 1, 0.05, '%.2f'),
                          num('postProcessAlpha', 'postProcessAlpha', 0, 1, 0.05, '%.2f'),
                          num('postProcessDepth', 'postProcessDepth', 0, 5, 0.05, '%.2f')],
                         self.atmo_new_point, card=True, cols=4, add_text='Add config point', notify=self.atmo_points_changed,
                         registry=[])
        pts.frame.pack(fill='x', pady=6)
        self.atmo_pts = pts
        self.section(p, 'Sun and planet list')
        g = ttk.Frame(p)
        g.pack(fill='x')
        self.v_atmo_sun = tk.StringVar()
        self.v_atmo_casters = tk.StringVar()
        ttk.Label(g, text='Sun (mainSunCelestialBody)').grid(row=0, column=0, sticky='w', padx=8, pady=4)
        e1 = ttk.Entry(g, textvariable=self.v_atmo_sun, width=20)
        e1.grid(row=0, column=1, sticky='w', pady=4)
        ttk.Label(g, text='Sun colour').grid(row=1, column=0, sticky='w', padx=8, pady=4)
        self.atmo_sun_sw = Swatch(self, g, A + ('sun_color',))
        self.atmo_sun_sw.lab.grid(row=1, column=1, sticky='w', pady=4)
        ttk.Label(g, text='Eclipse casters (moons)').grid(row=2, column=0, sticky='w', padx=8, pady=4)
        e2 = ttk.Entry(g, textvariable=self.v_atmo_casters, width=30)
        e2.grid(row=2, column=1, sticky='w', pady=4)
        for w in (e1, e2):
            w.bind('<Return>', self.atmo_commit_entries)
            w.bind('<FocusOut>', self.atmo_commit_entries)
        self.atmo_cloud = tk.BooleanVar(value=True)
        self.atmo_flat = tk.BooleanVar(value=True)
        ttk.Checkbutton(g, text='usesCloudIntegration (EVE clouds get lit by the atmosphere)', variable=self.atmo_cloud,
                        command=lambda: self.atmo_flag('cloud_integration', self.atmo_cloud)).grid(row=3, column=0, columnspan=2, sticky='w', padx=8, pady=2)
        ttk.Checkbutton(g, text='flatScaledSpaceModel', variable=self.atmo_flat,
                        command=lambda: self.atmo_flag('flat_model', self.atmo_flat)).grid(row=4, column=0, columnspan=2, sticky='w', padx=8, pady=2)
        self.section(p, 'Other Scatterer values')
        ttk.Label(p, text='These go into atmo.cfg as they are (rim, shine, cloud and scaled-texture settings). '
                          'One \u201ckey = value\u201d per line.', style='Dim.TLabel', wraplength=520).pack(anchor='w')
        self.atmo_extra = tk.Text(p, height=10, width=64, bg=FIELD, fg=FG, insertbackground=FG, relief='flat', font=(MONO, 9), tabs=('0.9c',))
        self.atmo_extra.pack(anchor='w', pady=(4, 0))
        self.atmo_extra.bind('<FocusOut>', self.atmo_commit_extra)
        self.section(p, 'Scatterer config')
        ttk.Label(p, text='atmo.cfg \u2013 goes into GameData/<your mod>/Scatterer/Planets/<planet>/ (any .cfg name works):',
                  style='Dim.TLabel', wraplength=520).pack(anchor='w')
        self.atmo_cfg = tk.Text(p, height=14, width=64, bg=FIELD, fg=FG, insertbackground=FG, relief='flat', font=(MONO, 9), tabs=('0.9c',))
        self.atmo_cfg.pack(anchor='w', pady=(4, 0))
        br = ttk.Frame(p)
        br.pack(fill='x', pady=(6, 0))
        ttk.Button(br, text='Copy', command=lambda: self.atmo_copy('atmo')).pack(side='left')
        ttk.Button(br, text='Save atmo.cfg\u2026', command=self.atmo_save).pack(side='left', padx=6)
        ttk.Label(p, text='Planet list entry \u2013 Scatterer only draws planets that are in its list:',
                  style='Dim.TLabel', wraplength=520).pack(anchor='w', pady=(10, 0))
        self.atmo_pl = tk.Text(p, height=12, width=64, bg=FIELD, fg=FG, insertbackground=FG, relief='flat', font=(MONO, 9), tabs=('0.9c',))
        self.atmo_pl.pack(anchor='w', pady=(4, 0))
        ttk.Button(p, text='Copy', command=lambda: self.atmo_copy('list')).pack(anchor='w', pady=(6, 12))
        self.swatches.append(type('A', (), {'refresh': lambda s=None: self.atmo_refresh()})())

    def atmo_e(self):
        return self.P['atmosphere']

    def atmo_refresh(self):
        e = self.atmo_e()
        self.atmo_on.set(bool(e.get('enabled')))
        self.atmo_view.set(e.get('view', 'planet'))
        self.atmo_oz.set(bool(e.get('useOzone')))
        self.atmo_ms.set(bool(e.get('multipleScattering')))
        self.atmo_cloud.set(bool(e.get('cloud_integration')))
        self.atmo_flat.set(bool(e.get('flat_model')))
        self.v_atmo_radius.set(gg.cfg_num(e.get('radius', 6000)))
        self.v_atmo_sun.set(e.get('sun', 'Sun'))
        self.v_atmo_casters.set(e.get('eclipse_casters', ''))
        self.atmo_pts.rebuild()
        self.atmo_extra.delete('1.0', 'end')
        self.atmo_extra.insert('1.0', '\n'.join('%s = %s' % (k, v) for k, v in e.get('extra') or []))
        self.atmo_swatches()
        self.atmo_text()

    def atmo_swatches(self):
        e = self.atmo_e()
        self.atmo_sky_sw.configure(bg=hexcol(gg.colour_from_beta(e['m_betaR'])))
        self.atmo_haze_sw.configure(bg=hexcol(gg.colour_from_beta(e['BETA_MSca'])))

    def atmo_text(self):
        for box, txt in ((self.atmo_cfg, gg.atmo_cfg(self.P)), (self.atmo_pl, gg.atmo_planets(self.P))):
            box.configure(state='normal')
            box.delete('1.0', 'end')
            box.insert('1.0', txt)
            box.configure(state='disabled')

    def atmo_copy(self, which):
        self.clipboard_clear()
        self.clipboard_append(gg.atmo_cfg(self.P) if which == 'atmo' else gg.atmo_planets(self.P))
        self.status('Scatterer config copied' if which == 'atmo' else 'Planet list entry copied')

    def atmo_dirty(self):
        if getattr(self, 'atmo_text_after', None):
            self.after_cancel(self.atmo_text_after)
        self.atmo_text_after = self.after(250, self.atmo_text)

    def atmo_colours_changed(self):
        self.atmo_swatches()
        self.changed()

    def atmo_point_changed(self):
        if getattr(self, 'atmo_pts_after', None):
            self.after_cancel(self.atmo_pts_after)
        self.atmo_pts_after = self.after(400, self.atmo_pts.rebuild)
        self.changed()

    def atmo_points_changed(self):
        pts = self.atmo_e()['configPoints']
        if not pts:
            pts.append(dict(gg.ATMO_POINT))
        order = sorted(pts, key=lambda q: float(q.get('altitude', 0)))
        if order != pts:
            pts[:] = order
            self.after_idle(self.atmo_pts.rebuild)
        for sl in self.sliders:
            if sl.path[:2] == ('atmosphere', 'configPoints'):
                sl.refresh()
        self.changed()

    def atmo_new_point(self):
        pts = self.atmo_e()['configPoints']
        q = dict(pts[-1] if pts else gg.ATMO_POINT)
        q['altitude'] = float(q.get('altitude', 0)) + 50000.0
        return q

    def atmo_flag(self, key, var):
        self.snapshot()
        self.atmo_e()[key] = bool(var.get())
        self.changed()

    def atmo_commit_entries(self, _e=None):
        e = self.atmo_e()
        new = {}
        try:
            r = float(self.v_atmo_radius.get().replace(',', '.'))
            if r > 0:
                new['radius'] = r
        except ValueError:
            pass
        new['sun'] = self.v_atmo_sun.get().strip() or 'Sun'
        new['eclipse_casters'] = ', '.join(gg.atmo_casters({'eclipse_casters': self.v_atmo_casters.get()}))
        if any(e.get(k) != v for k, v in new.items()):
            self.snapshot()
            e.update(new)
            self.changed()
        self.v_atmo_radius.set(gg.cfg_num(e['radius']))
        self.v_atmo_casters.set(e['eclipse_casters'])

    def atmo_commit_extra(self, _e=None):
        out = []
        for line in self.atmo_extra.get('1.0', 'end').splitlines():
            line = line.split('//', 1)[0].strip()
            if '=' in line:
                k, v = line.split('=', 1)
                k, v = k.strip(), v.strip()
                if k and k not in gg.ATMO_VALUES and k not in ('name', 'configPoints'):
                    out.append([k, v])
        if out != self.atmo_e().get('extra'):
            self.snapshot()
            self.atmo_e()['extra'] = out
            self.changed()

    def atmo_pick_colour(self, key):
        e = self.atmo_e()
        old = list(e[key])

        def live(v):
            e[key] = gg.beta_from_colour(v, old)
            self.atmo_swatches()
            for sl in self.sliders:
                if sl.path[:2] == ('atmosphere', key):
                    sl.refresh()
            self.changed()

        def restore():
            e[key] = old
            self.atmo_swatches()
            for sl in self.sliders:
                if sl.path[:2] == ('atmosphere', key):
                    sl.refresh()
            self.changed()
        self.snapshot()
        c = pick_colour(self, gg.colour_from_beta(old), title='Sky colour' if key == 'm_betaR' else 'Haze colour', live=live, restore=restore)
        if c:
            live(c)
        else:
            self.drop_snapshot()

    def atmo_match(self):
        self.snapshot()
        e = self.atmo_e()
        e['m_betaR'] = gg.beta_from_colour(gg.planet_tint(self.P), e['m_betaR'])
        self.refresh_atmo_sliders()
        self.changed()
        self.status('Sky colour now matches the planet\u2019s bands')

    def atmo_grey_haze(self):
        self.snapshot()
        e = self.atmo_e()
        m = float(np.mean(e['BETA_MSca']))
        e['BETA_MSca'] = [m, m, m]
        self.refresh_atmo_sliders()
        self.changed()

    def refresh_atmo_sliders(self):
        for sl in self.sliders:
            if sl.path[0] == 'atmosphere':
                sl.refresh()
        self.atmo_swatches()

    def atmo_apply_preset(self):
        self.snapshot()
        e = self.atmo_e()
        name = self.atmo_preset.get()
        if name in gg.ATMO_PRESETS:
            for k, v in gg.ATMO_PRESETS[name].items():
                e[k] = copy.deepcopy(v)
        else:
            for k in ('atmosphereStartRadiusScale', 'HR', 'HM', 'BETA_MSca', 'm_mieG', 'useOzone', 'configPoints'):
                e[k] = copy.deepcopy(gg.ATMO_PRESETS['Jool (stock)'][k])
            e['m_betaR'] = gg.beta_from_colour(gg.planet_tint(self.P), gg.ATMO_PRESETS['Jool (stock)']['m_betaR'])
        self.P['atmosphere'] = gg.atmo_entry(e)
        self.atmo_refresh()
        self.refresh_atmo_sliders()
        self.changed()
        self.status('Atmosphere values from \u201c%s\u201d \u2013 Undo goes back' % name)

    def atmo_fresh(self):
        e = dict(self.atmo_e())
        d = gg.atmo_entry({})
        return all(e.get(k) == d[k] for k in gg.ATMO_VALUES + ('configPoints', 'extra'))

    def atmo_toggle(self):
        self.snapshot()
        e = self.atmo_e()
        e['enabled'] = bool(self.atmo_on.get())
        if e['enabled'] and self.atmo_fresh():
            found = gg.find_atmo_cfg(self.P['name']) if gg.game_mod_dir() else ''
            if found and messagebox.askyesno('Scatterer config found',
                                             'Your mod already has a Scatterer config for %s:\n\n%s\n\nStart from its values?'
                                             % (self.P['name'], gg.nice(found)), parent=self):
                self.atmo_read_file(found)
            else:
                e['m_betaR'] = gg.beta_from_colour(gg.planet_tint(self.P), e['m_betaR'])
            r, _ = gg.find_body_radius(self.P['name']) if gg.game_mod_dir() else (None, '')
            if r:
                self.atmo_e()['radius'] = r
            self.atmo_refresh()
            self.refresh_atmo_sliders()
        self.changed()
        if e['enabled'] and self.view.get() != 'atmo':
            self.atmo_show()

    def atmo_show(self):
        if self.map_tool.get() != 'turn':
            self.map_tool.set('turn')
            self.tool_changed()
        self.view.set('atmo')
        self.update_view()

    def atmo_view_changed(self):
        self.atmo_e()['view'] = self.atmo_view.get()
        self.changed()
        if self.view.get() != 'atmo':
            self.atmo_show()

    def atmo_read_file(self, path):
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                txt = f.read()
        except OSError as ex:
            messagebox.showerror('Could not read', str(ex), parent=self)
            return False
        e, nm = gg.atmo_from_cfg(txt, self.P['name'])
        if e is None:
            messagebox.showerror('No atmosphere', 'There is no Scatterer Atmo node in\n%s' % path, parent=self)
            return False
        old = self.atmo_e()
        for k in ('enabled', 'radius', 'sun', 'sun_color', 'eclipse_casters', 'cloud_integration', 'flat_model', 'sun_angle', 'view'):
            e[k] = old.get(k, e[k])
        e['enabled'] = True
        d = os.path.dirname(path)
        root = d
        for _ in range(4):
            if os.path.basename(root).lower() == 'scatterer':
                break
            root = os.path.dirname(root)
        else:
            root = d
        item, _ = gg.find_planets_item(nm or self.P['name'], root)
        if item:
            e.update(item)
        self.P['atmosphere'] = gg.atmo_entry(e)
        self.status('Loaded the atmosphere of %s from %s' % (nm or '?', os.path.basename(path)))
        return True

    def atmo_load(self):
        found = gg.find_atmo_cfg(self.P['name']) if gg.game_mod_dir() else ''
        sd = gg.scatterer_dir(gg.game_mod_dir())
        init = os.path.dirname(found) if found else (sd or gg.TOOL)
        path = filedialog.askopenfilename(parent=self, title='Scatterer atmosphere config', initialdir=init,
                                          initialfile=os.path.basename(found) if found else '',
                                          filetypes=[('Config', '*.cfg'), ('All files', '*.*')])
        if not path:
            return
        self.snapshot()
        if not self.atmo_read_file(path):
            self.drop_snapshot()
            return
        self.atmo_refresh()
        self.refresh_atmo_sliders()
        self.changed()
        if self.view.get() != 'atmo':
            self.atmo_show()

    def atmo_find_radius(self):
        self.status('Looking for %s in the Kopernicus configs\u2026' % self.P['name'])
        self.update_idletasks()
        r, src = gg.find_body_radius(self.P['name']) if gg.game_mod_dir() else (None, '')
        if not r:
            path = filedialog.askopenfilename(parent=self, title='Kopernicus config of %s' % self.P['name'],
                                              filetypes=[('Config', '*.cfg'), ('All files', '*.*')])
            if not path:
                self.status('Radius not found')
                return
            r, src = gg.find_body_radius(self.P['name'], os.path.dirname(path))
            if not r:
                messagebox.showinfo('Radius', 'No Body called %s with a radius in that folder.' % self.P['name'], parent=self)
                return
        self.snapshot()
        self.atmo_e()['radius'] = r
        self.v_atmo_radius.set(gg.cfg_num(r))
        self.changed()
        self.status('Radius %s km from %s' % (gg.cfg_num(r), os.path.basename(src)))

    def atmo_save(self):
        self.atmo_commit_entries()
        self.atmo_commit_extra()
        name = self.P['name']
        mod = gg.game_mod_dir()
        found = gg.find_atmo_cfg(name) if mod else ''
        sd = gg.scatterer_dir(mod)
        init = os.path.dirname(found) if found else (os.path.join(sd, 'Planets', name) if sd else os.path.join(gg.TOOL, 'export'))
        idir = init
        while idir and not os.path.isdir(idir):
            idir = os.path.dirname(idir)
        path = filedialog.asksaveasfilename(parent=self, title='Save Scatterer atmosphere', initialdir=idir or gg.TOOL,
                                            initialfile='atmo.cfg', defaultextension='.cfg',
                                            filetypes=[('Config', '*.cfg'), ('All files', '*.*')])
        if not path:
            return
        stamp = time.strftime('%Y%m%d_%H%M%S')
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            backed = self.atmo_backup(path, stamp)
            with open(path, 'w', newline='\n') as f:
                f.write(gg.atmo_cfg(self.P))
        except OSError as ex:
            messagebox.showerror('Could not save', str(ex), parent=self)
            return
        msg = 'Saved %s' % path + (' (old file backed up)' if backed else '')
        root = os.path.dirname(path)
        r2 = root
        for _ in range(4):
            if os.path.basename(r2).lower() == 'scatterer':
                root = r2
                break
            r2 = os.path.dirname(r2)
        item, where = gg.find_planets_item(name, root)
        if item:
            msg += ' \u2013 %s is already in the planet list (%s)' % (name, os.path.basename(where))
        else:
            pl = gg.planets_file(root, name)
            if messagebox.askyesno('Planet list', 'Scatterer only draws planets that are in its planet list, and %s isn\u2019t '
                                   'in one in this folder yet.\n\nSave %s next to it?' % (name, gg.nice(pl)), parent=self):
                try:
                    self.atmo_backup(pl, stamp)
                    with open(pl, 'w', newline='\n') as f:
                        f.write(gg.atmo_planets(self.P))
                    msg += ' and %s' % os.path.basename(pl)
                except OSError as ex:
                    messagebox.showerror('Could not save', str(ex), parent=self)
        self.status(msg)
        self.log(msg)

    def atmo_backup(self, path, stamp):
        if not os.path.isfile(path):
            return False
        b = gg.backup_dir(self.P['name'], stamp)
        os.makedirs(b, exist_ok=True)
        shutil.copy2(path, os.path.join(b, os.path.basename(path)))
        return True

    def atmo_texture(self):
        L = self.live_last if self.live_on.get() else None
        st = self.is_stale()
        f = os.path.join(self.out_path(), self.P['name'] + '_color.png')
        if st is False and os.path.isfile(f):
            key = ('build', f, os.path.getmtime(f))
            if self.atmo_texc.get('key') != key:
                try:
                    c = Image.open(f).convert('RGB')
                    if c.width > 2048:
                        c = c.resize((2048, 1024), Image.LANCZOS)
                    ef = os.path.join(self.out_path(), self.P['name'] + '_emissive.png')
                    em = None
                    if os.path.isfile(ef):
                        em = Image.open(ef).convert('RGB').resize(c.size, Image.LANCZOS)
                        em = np.asarray(em).astype(np.float32) / 255
                    self.atmo_texc = {'key': key, 'tex': np.asarray(c).astype(np.float32) / 255, 'em': em}
                except Exception:
                    self.atmo_texc = {}
            if self.atmo_texc.get('key') == key:
                return self.atmo_texc['tex'], self.atmo_texc['em'], key
        if L is not None:
            key = ('live', L['key'], L['W'])
            if self.atmo_texc.get('key') != key:
                em = L['em'].astype(np.float32) / 255 if L['em'] is not None else None
                self.atmo_texc = {'key': key, 'tex': L['col'].astype(np.float32) / 255, 'em': em}
            return self.atmo_texc['tex'], self.atmo_texc['em'], key
        lv = self.live_view
        key = ('bands', self.live_key())
        if lv is not None and self.atmo_texc.get('key') != key:
            self.atmo_texc = {'key': key, 'tex': lv['tex'], 'em': lv['em']}
        elif lv is None:
            strip = band_image(self.P, 1024, 512)
            self.atmo_texc = {'key': key, 'tex': np.asarray(strip).astype(np.float32) / 255, 'em': None}
        return self.atmo_texc['tex'], self.atmo_texc['em'], key

    def atmo_size(self):
        cw, ch = max(10, self.canvas.winfo_width()), max(10, self.canvas.winfo_height())
        w, h = max(200, cw - 16), max(150, ch - 16)
        k = min(1.0, 1300.0 / w, 820.0 / h)
        return int(w * k), int(h * k)

    def atmo_request(self, quick_only=False):
        if not gg.has_atmo(self.P):
            return
        tex, em, tkey = self.atmo_texture()
        w, h = self.atmo_size()
        P = gg.normalize(copy.deepcopy(self.P))
        pv = P['preview']
        key = json.dumps([P['atmosphere'], pv, self.rot, w, h, str(tkey)], sort_keys=True, default=str)
        self.atmo_want = key
        if self.atmo_key == key and not quick_only:
            return
        r = self.atmo_req
        if r is not None and r[1] == key and r[-1] == quick_only:
            return
        self.atmo_err = None
        with self.atmo_lock:
            self.atmo_gen += 1
            self.atmo_req = (self.atmo_gen, key, P, tex, em, w, h, tuple(self.rot), quick_only)
            if self.atmo_thread is None:
                self.atmo_thread = threading.Thread(target=self.atmo_worker, daemon=True)
                self.atmo_thread.start()

    def atmo_worker(self):
        while True:
            with self.atmo_lock:
                req = self.atmo_req
                if req is None:
                    self.atmo_thread = None
                    return
            gen, key, P, tex, em, w, h, rot, quick_only = req

            def cancel(gen=gen):
                r = self.atmo_req
                if r is None or r[0] != gen:
                    raise gg.Cancelled()
            try:
                passes = ((3, 6),) if quick_only else ((3, 6), (1, 14))
                for sc, steps in passes:
                    t0 = time.time()
                    im = gg.render_atmo(P, tex, em, w=max(60, w // sc), h=max(40, h // sc), steps=steps, rot=rot, cancel=cancel)
                    if sc > 1:
                        im = im.resize((w, h), Image.BILINEAR)
                    self.atmo_q.put((gen, key, im, sc == 1, time.time() - t0, None))
            except gg.Cancelled:
                continue
            except Exception as ex:
                self.atmo_q.put((gen, key, None, True, 0, str(ex)))
            with self.atmo_lock:
                if self.atmo_req is not None and self.atmo_req[0] == gen:
                    self.atmo_req = None

    def atmo_poll(self):
        got = False
        try:
            while True:
                gen, key, im, final, dt, err = self.atmo_q.get_nowait()
                if gen != self.atmo_gen:
                    continue
                if err:
                    self.atmo_err = err
                else:
                    self.atmo_img = im
                    self.atmo_err = None
                    if final:
                        self.atmo_key = key
                got = True
        except queue.Empty:
            pass
        if got and self.view.get() == 'atmo':
            self.atmo_present()

    def atmo_present(self):
        if self.atmo_err:
            self.view_src = None
            self.status('Could not draw the atmosphere: %s' % self.atmo_err[:120])
        else:
            self.view_src = self.atmo_img
        self.redraw()

    def atmo_drag_start(self, e):
        if self.view.get() != 'atmo' or not gg.has_atmo(self.P):
            return False
        self.snapshot()
        self.adrag = (e.x, float(self.atmo_e()['sun_angle']), False)
        return True

    def atmo_drag_move(self, e):
        x0, a0, _ = self.adrag
        a = round(max(0.0, min(170.0, a0 + (e.x - x0) * 0.4)))
        if a != self.atmo_e()['sun_angle']:
            self.atmo_e()['sun_angle'] = a
            self.adrag = (x0, a0, True)
            self.atmo_request(quick_only=True)
            self.status('Sun angle %d\u00b0' % a)

    def atmo_drag_end(self):
        moved = self.adrag[2]
        self.adrag = None
        if moved:
            for sl in self.sliders:
                if sl.path == ('atmosphere', 'sun_angle'):
                    sl.refresh()
            self.changed()
        else:
            self.drop_snapshot()

    def live_key(self):
        return json.dumps({k: v for k, v in self.P.items() if k not in ('atmosphere', 'rings')}, sort_keys=True, default=str)

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
        if not self.v_files['ring'].get():
            self.v_files['ring'].set('%s_ring.dds' % self.P['name'])
        self.pick.configure(values=self.preset_names())
        self.pick.set(self.P['name'])
        self.update_title()
        self.update_view()
        self.update_res_info()

    def update_res_info(self):
        r = self.res.get()
        txt = '%s \u00d7 %d  \u00b7  %s' % (r, int(r) // 2, RES_INFO.get(r, ''))
        if self.P.get('big_storms') or self.P.get('storm_chains'):
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
        if hasattr(self, 'ring_cv'):
            self.ring_schedule()
        if hasattr(self, 'atmo_cfg'):
            self.atmo_dirty()
        if self.view.get() in ('bands', 'atmo'):
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
        rg = self.v_files['ring'].get().strip()
        if rg and ('ring' in self.P['files'] or gg.has_rings(self.P) or rg != '%s_ring.dds' % self.P['name']):
            new['ring'] = rg
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
        self.stop_live()
        self.live_last = None
        self.atmo_img = None
        self.atmo_key = None
        self.atmo_texc = {}
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
        a = {k: v for k, v in built.items() if k != 'atmosphere'}
        b = {k: v for k, v in self.P.items() if k != 'atmosphere'}
        return json.dumps(a, sort_keys=True) != json.dumps(b, sort_keys=True)

    def update_stale(self):
        if self.proc:
            return
        v = self.view.get()
        if v in ('preview', 'flat') and self.is_stale():
            self.status('Settings changed since this build – press Build to update')

    def update_view(self, from_live=False):
        self.pending = None
        v = self.view.get()
        if v == 'atmo':
            skey = self.live_key()
            if not from_live:
                self.request_live(skey)
            self.update_live_label(skey)
            if not gg.has_atmo(self.P):
                self.view_src = None
                self.status('No atmosphere yet – tick “Scatterer atmosphere” in the Atmosphere tab')
            else:
                self.atmo_request()
                self.view_src = self.atmo_img
                if not self.proc:
                    self.status('In game: the Scatterer atmosphere as in the map view · drag left or right to move the sun')
            self.update_export_state()
            self.redraw()
            return
        if v == 'bands':
            skey = self.live_key()
            live = self.live_last if self.live_on.get() else None
            heat = gg.has_heat(self.P)
            try:
                if live is not None:
                    strip = Image.fromarray(live['col']).resize((1024, 512), Image.LANCZOS)
                    em = None
                    if live['em'] is not None:
                        em = np.asarray(Image.fromarray(live['em']).resize((1024, 512), Image.LANCZOS)).astype(np.float32) / 255.0
                else:
                    strip = band_image(self.P, 1024, 512)
                    gl = glow_image(self.P, 1024, 512)
                    em = (gl / 255.0).astype(np.float32) if gl is not None else None
                    if heat:
                        la = np.radians(90 - (np.arange(512) + 0.5) / 512 * 180).astype(np.float32)[:, None]
                        he = gg.heat_emission(self.P, np.asarray(strip).astype(np.float32), la) / 255.0
                        em = he.astype(np.float32) if em is None else np.clip(em + he, 0, 1).astype(np.float32)
            except Exception:
                return
            tex = np.asarray(strip).astype(np.float32) / 255
            light = gg.NIGHT_LIGHT if heat else None
            sph = self.sphere_image(tex, em, light, 512)
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
            sheet = Image.new('RGB', (1024 + 512 + 24, 512 + (262 if poles else 34)), (13, 15, 20))
            sheet.paste(flat, (512 + 24, 0))
            d = ImageDraw.Draw(sheet)
            hint = 'drag to turn \u00b7 double-click resets'
            f17 = sheet_font(17)
            d.text((256 - d.textlength(hint, font=f17) / 2, 520), hint, fill=DIM, font=f17)
            if poles:
                for i, (sgn, key) in enumerate(poles):
                    x = 536 + i * 260
                    sheet.paste(pole_disc(strip, sgn, 220), (x, 540))
                    d.text((x, 516), '%s pole (from above)' % key.capitalize(), fill=DIM, font=f17)
            self.live_view = {'tex': tex, 'em': em, 'light': light, 'sheet': sheet}
            sheet = sheet.copy()
            sheet.paste(sph, (0, 0))
            self.view_src = sheet
            if not self.proc and self.map_tool.get() == 'turn':
                self.status('Live preview \u2013 press Build for the full-size map' if self.live_on.get()
                            else 'Bands only \u2013 swirls appear when you press Build')
            if not from_live:
                self.request_live(skey)
            self.update_live_label(skey)
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

    def sphere_image(self, tex, em, light, S):
        pv = self.P['preview']
        vlat = max(-90.0, min(90.0, float(pv['view_lat']) + self.rot[1]))
        return gg.render_sphere(tex, S, pv['tilt'], vlat, float(pv['view_lon']) + self.rot[0], em, light)

    def sheet_xy(self, e):
        if self.view_geom is None:
            return None
        s, ox, oy = self.view_geom
        return (e.x - ox) / s, (e.y - oy) / s

    def view_angles(self):
        pv = self.P['preview']
        t = np.radians(float(pv['tilt']))
        a = np.radians(max(-90.0, min(90.0, float(pv['view_lat']) + self.rot[1])))
        return t, a, float(pv['view_lon']) + self.rot[0]

    @staticmethod
    def flat_lat(y):
        return 90.0 - (y + 0.5) / 512.0 * 180.0

    @staticmethod
    def on_flat(p):
        return p is not None and 536 <= p[0] < 1560 and 0 <= p[1] < 512

    def map_point(self, p):
        if p is None:
            return None
        x, y = p
        if self.on_flat(p):
            return self.flat_lat(y), ((x - 536 + 0.5) / 1024.0 * 360.0) % 360.0
        u = (x + 0.5) / 512.0 * 2 - 1
        v = 1 - (y + 0.5) / 512.0 * 2
        r2 = u * u + v * v
        if r2 >= 1:
            return None
        z = np.sqrt(1 - r2)
        t, a, vlon = self.view_angles()
        u2 = u * np.cos(t) - v * np.sin(t)
        v2 = u * np.sin(t) + v * np.cos(t)
        y3 = v2 * np.cos(a) + z * np.sin(a)
        z3 = -v2 * np.sin(a) + z * np.cos(a)
        lat = float(np.degrees(np.arcsin(np.clip(y3, -1, 1))))
        lon = float((np.degrees(np.arctan2(u2, z3)) + vlon) % 360.0)
        return lat, lon

    def globe_xy(self, lat, lon):
        t, a, vlon = self.view_angles()
        la, lo = np.radians(lat), np.radians(lon - vlon)
        y3 = np.sin(la); u2 = np.cos(la) * np.sin(lo); z3 = np.cos(la) * np.cos(lo)
        v2 = y3 * np.cos(a) - z3 * np.sin(a)
        z = y3 * np.sin(a) + z3 * np.cos(a)
        u = u2 * np.cos(t) + v2 * np.sin(t)
        v = -u2 * np.sin(t) + v2 * np.cos(t)
        return (u + 1) / 2 * 512, (1 - v) / 2 * 512, z

    @staticmethod
    def ang_dist(lat1, lon1, lat2, lon2):
        la1, lo1, la2, lo2 = np.radians([lat1, lon1, lat2, lon2])
        return float(np.degrees(np.arccos(np.clip(np.sin(la1) * np.sin(la2) + np.cos(la1) * np.cos(la2) * np.cos(lo1 - lo2), -1, 1))))

    def storm_near(self, lat, lon):
        best = None
        for i, b in enumerate(self.P.get('big_storms', [])):
            d = self.ang_dist(lat, lon, float(b['lat']), float(b['lon']))
            lim = max(4.0, float(b.get('size', 0.025)) * 360 * 1.3)
            if d <= lim and (best is None or d < best[0]):
                best = (d, i)
        return None if best is None else best[1]

    def chain_near(self, lat, lon):
        best = None
        for ci, c in enumerate(self.P.get('storm_chains', [])):
            lim = max(4.0, float(c.get('size', 0.012)) * 360 * 1.3)
            for la, lo in gg.chain_points(c):
                d = self.ang_dist(lat, lon, la, lo)
                if d <= lim and (best is None or d < best[0]):
                    best = (d, ci)
        return None if best is None else best[1]

    def band_edge_near(self, p):
        if not self.on_flat(p) or self.view_geom is None:
            return None
        tol = 8.0 / self.view_geom[0]
        best = None
        for i, b in enumerate(self.P['bands']):
            if i == 0:
                continue
            yb = (90.0 - float(b[0])) / 180.0 * 512
            d = abs(yb - p[1])
            if d <= tol and (best is None or d < best[0]):
                best = (d, i)
        return None if best is None else best[1]

    TOOL_HINTS = {'turn': None,
                  'storms': 'Click the map or the globe to add a big storm \u00b7 drag a storm to move it \u00b7 right-click removes it',
                  'chain': 'Drag along a latitude to draw a chain of storms \u00b7 a single click makes a ring all the way round '
                           '\u00b7 drag a chain to move it \u00b7 right-click removes it',
                  'bands': 'Drag a band edge up or down (its curls come along) \u00b7 double-click splits a band \u00b7 '
                           'right-click an edge removes it'}

    def tool_changed(self):
        tool = self.map_tool.get()
        if tool != 'turn' and self.view.get() != 'bands':
            self.view.set('bands')
            self.update_view()
        self.canvas.configure(cursor={'turn': '', 'storms': 'crosshair', 'chain': 'crosshair', 'bands': 'sb_v_double_arrow'}[tool])
        hint = self.TOOL_HINTS[tool]
        if hint:
            self.status(hint)
        else:
            self.status('Live preview \u2013 press Build for the full-size map' if self.live_on.get() else 'Bands only \u2013 swirls appear when you press Build')
        self.redraw()

    def set_tool(self, tool):
        self.map_tool.set(tool)
        self.tool_changed()

    def place_from_tab(self):
        self.set_tool('storms')

    def placing(self):
        return self.map_tool.get() != 'turn' and self.view.get() == 'bands' and self.live_view is not None

    def storm_set_pos(self, i, lat, lon):
        b = self.P['big_storms'][i]
        b['lat'] = round(max(-85.0, min(85.0, lat)), 1)
        b['lon'] = round(lon % 360.0, 1)

    def storm_done(self):
        self.storm_ed.rebuild()
        self.changed()

    def chain_done(self):
        self.chain_ed.rebuild()
        self.changed()

    def drop_snapshot(self):
        if self.history:
            self.history.pop()
            if not self.history:
                self.undo_btn.configure(state='disabled')

    def storm_remove_click(self, e):
        if not self.placing():
            return
        p = self.sheet_xy(e)
        tool = self.map_tool.get()
        if tool == 'bands':
            i = self.band_edge_near(p)
            if i is None:
                return
            self.snapshot()
            self.P['bands'].pop(i)
            self.band_removed(i)
            self.band_ed.rebuild()
            self.bands_changed()
            self.redraw()
            self.status('Removed a band edge \u2013 Undo brings it back')
            return
        mp = self.map_point(p)
        if mp is None:
            return
        if tool == 'chain':
            ci = self.chain_near(*mp)
            if ci is None:
                return
            self.snapshot()
            self.P['storm_chains'].pop(ci)
            self.chain_done()
            self.redraw()
            self.status('Removed a storm chain \u2013 Undo brings it back')
            return
        i = self.storm_near(*mp)
        if i is None:
            return
        self.snapshot()
        self.P['big_storms'].pop(i)
        self.storm_done()
        self.redraw()
        self.status('Removed a big storm \u2013 Undo brings it back')

    def drag_start(self, e):
        self.drag = None
        self.sdrag = None
        self.cdrag = None
        self.bdrag = None
        self.adrag = None
        if self.atmo_drag_start(e):
            return
        if self.view.get() != 'bands' or self.live_view is None:
            return
        p = self.sheet_xy(e)
        tool = self.map_tool.get()
        if tool == 'bands':
            if not self.on_flat(p):
                return
            if any(a[0] > b[0] for a, b in zip(self.P['bands'][:-1], self.P['bands'][1:])):
                gg.sort_bands(self.P)
                self.band_ed.rebuild()
            i = self.band_edge_near(p)
            if i is None:
                return
            bands = self.P['bands']
            self.snapshot()
            old = float(bands[i][0])
            lo = max(-89.5, float(bands[i - 1][0]) + 0.5)
            hi = float(bands[i + 1][0]) - 0.5 if i + 1 < len(bands) else 89.5
            linked = [(ed, float(ed['lat'])) for ed in self.P['edges'] if abs(float(ed['lat']) - old) <= 0.75]
            self.bdrag = {'i': i, 'lo': lo, 'hi': hi, 'old': old, 'edges': linked, 'moved': False}
            self.redraw()
            return
        if tool == 'chain':
            mp = self.map_point(p)
            if mp is None:
                return
            self.snapshot()
            ci = self.chain_near(*mp)
            if ci is not None:
                c = self.P['storm_chains'][ci]
                self.cdrag = {'mode': 'move', 'ci': ci, 'start': mp, 'orig': (float(c['lat']), float(c['lat_end']), float(c['lon'])), 'moved': False}
            else:
                self.cdrag = {'mode': 'new', 'a': mp, 'b': mp}
            self.redraw()
            return
        if tool == 'storms':
            mp = self.map_point(p)
            if mp is None:
                return
            self.snapshot()
            i = self.storm_near(*mp)
            if i is None:
                s = self.new_big_storm()
                self.P['big_storms'].append(s)
                i = len(self.P['big_storms']) - 1
                self.storm_set_pos(i, *mp)
                self.status('Added a big storm at %.1f\u00b0, %.0f\u00b0 \u2013 drag to move it, settings in the Storms tab' % (self.P['big_storms'][i]['lat'], self.P['big_storms'][i]['lon']))
                self.sdrag = [i, True]
            else:
                self.sdrag = [i, False]
            self.redraw()
            return
        if p and (p[0] - 256) ** 2 + (p[1] - 256) ** 2 <= 256 ** 2:
            self.drag = (p[0], p[1], self.rot[0], self.rot[1])

    def drag_move(self, e):
        if self.adrag is not None:
            self.atmo_drag_move(e)
            return
        p = self.sheet_xy(e)
        if self.bdrag is not None:
            if p is None:
                return
            d = self.bdrag
            lat = round(min(max(self.flat_lat(p[1]), d['lo']), d['hi']), 1)
            self.P['bands'][d['i']][0] = lat
            for ed, l0 in d['edges']:
                ed['lat'] = round(max(-89.0, min(89.0, l0 + lat - d['old'])), 1)
            d['moved'] = True
            self.redraw(fast=True)
            return
        if self.cdrag is not None:
            mp = self.map_point(p)
            if mp is None:
                return
            d = self.cdrag
            if d['mode'] == 'new':
                d['b'] = mp
            else:
                c = self.P['storm_chains'][d['ci']]
                dlat = mp[0] - d['start'][0]
                dlon = ((mp[1] - d['start'][1] + 180) % 360) - 180
                la0, la1, lo0 = d['orig']
                c['lat'] = round(max(-85.0, min(85.0, la0 + dlat)), 1)
                c['lat_end'] = round(max(-85.0, min(85.0, la1 + dlat)), 1)
                c['lon'] = round((lo0 + dlon) % 360.0, 1)
                d['moved'] = True
            self.redraw(fast=True)
            return
        if self.sdrag is not None:
            mp = self.map_point(p)
            if mp is not None:
                self.storm_set_pos(self.sdrag[0], *mp)
                self.sdrag[1] = True
                self.redraw(fast=True)
            return
        if self.drag is None:
            return
        if not p:
            return
        x0, y0, r0, r1 = self.drag
        self.rot[0] = (r0 - (p[0] - x0) * 0.35) % 360
        self.rot[1] = max(-180.0, min(180.0, r1 + (p[1] - y0) * 0.35))
        if not getattr(self, 'spin_pending', False):
            self.spin_pending = True
            self.after_idle(lambda: self.respin(True))

    def new_chain_from(self, a, b):
        if self.ang_dist(a[0], a[1], b[0], b[1]) < 3.0:
            c = {'lat': round(a[0], 1), 'lat_end': round(a[0], 1), 'lon': round(a[1], 1), 'length': 360.0, 'count': 12}
        else:
            dl = ((b[1] - a[1] + 180) % 360) - 180
            if dl >= 0:
                lon0, length, la0, la1 = a[1], dl, a[0], b[0]
            else:
                lon0, length, la0, la1 = b[1], -dl, b[0], a[0]
            length = max(length, 1.0)
            c = {'lat': round(la0, 1), 'lat_end': round(la1, 1), 'lon': round(lon0 % 360.0, 1), 'length': round(length, 1),
                 'count': int(min(30, max(2, round(length / 11.0) + 1)))}
        c['lat'] = max(-85.0, min(85.0, c['lat']))
        c['lat_end'] = max(-85.0, min(85.0, c['lat_end']))
        new = self.new_chain()
        new.update(c)
        return gg.chain_entry(new)

    def drag_end(self, _e=None):
        if self.adrag is not None:
            self.atmo_drag_end()
            return
        if self.bdrag is not None:
            d = self.bdrag
            self.bdrag = None
            if d['moved']:
                for ed in self.editors:
                    ed.rebuild()
                self.bands_changed()
                self.status('Band edge now at %.1f\u00b0' % self.P['bands'][d['i']][0])
            else:
                self.drop_snapshot()
            self.redraw()
            return
        if self.cdrag is not None:
            d = self.cdrag
            self.cdrag = None
            if d['mode'] == 'new':
                c = self.new_chain_from(d['a'], d['b'])
                self.P['storm_chains'].append(c)
                self.chain_done()
                self.status('Added a chain of %d storms \u2013 count, size and look are in the Storms tab' % c['count'])
            elif d['moved']:
                self.chain_done()
            else:
                self.drop_snapshot()
            self.redraw()
            return
        if self.sdrag is not None:
            i, moved = self.sdrag
            self.sdrag = None
            if moved:
                self.storm_done()
            else:
                self.drop_snapshot()
            self.redraw()
            return
        if self.drag is not None:
            self.drag = None
            self.respin(False)

    def drag_reset(self, e):
        tool = self.map_tool.get()
        p = self.sheet_xy(e)
        if tool == 'bands':
            if not self.placing() or not self.on_flat(p) or self.band_edge_near(p) is not None:
                return
            lat = round(self.flat_lat(p[1]), 1)
            bands = self.P['bands']
            if any(abs(float(b[0]) - lat) < 0.6 for b in bands):
                return
            gg.sort_bands(self.P)
            idx = max(i for i, b in enumerate(self.P['bands']) if float(b[0]) <= lat)
            base = self.P['bands'][idx][1]
            lum = 0.299 * base[0] + 0.587 * base[1] + 0.114 * base[2]
            col = [int(max(0, min(255, round(c * 0.88 if lum > 150 else c * 1.12 + 8)))) for c in base]
            self.snapshot()
            self.P['bands'].append([lat, col])
            gg.sort_bands(self.P)
            for ed in self.editors:
                ed.rebuild()
            self.bands_changed()
            self.redraw()
            self.status('Split the band at %.1f\u00b0 \u2013 pick the new band\u2019s colour in the band list' % lat)
            return
        if tool != 'turn':
            return
        if self.view.get() == 'bands' and self.live_view is not None and p and (p[0] - 256) ** 2 + (p[1] - 256) ** 2 <= 256 ** 2:
            self.rot = [0.0, 0.0]
            self.respin(False)

    def respin(self, quick):
        self.spin_pending = False
        lv = self.live_view
        if lv is None or self.view.get() != 'bands':
            return
        sph = self.sphere_image(lv['tex'], lv['em'], lv['light'], 256 if quick else 512)
        if quick:
            sph = sph.resize((512, 512), Image.BILINEAR)
        sheet = lv['sheet'].copy()
        sheet.paste(sph, (0, 0))
        self.view_src = sheet
        self.redraw(fast=quick)

    def update_live_label(self, key=None):
        if not self.live_on.get():
            txt = ''
        elif self.view.get() not in ('bands', 'atmo'):
            txt = ''
        elif self.proc:
            txt = 'swirls wait while building'
        elif self.live_err:
            txt = 'swirls failed: %s' % self.live_err[:60]
        else:
            key = key or self.live_key()
            L = self.live_last
            if L is not None and L['key'] == key:
                txt = 'swirls %d px \u00b7 %.1f s' % (L['W'], L['dt'])
                if L['W'] < self.live_target():
                    txt += ' \u2013 sharpening\u2026'
            else:
                txt = 'updating swirls\u2026'
        self.live_lab.configure(text=txt)

    def live_target(self):
        try:
            return int(self.live_size.get())
        except ValueError:
            return 512

    def live_size_changed(self, _e=None):
        S = load_settings()
        S['live_size'] = self.live_target()
        save_settings(S)
        self.update_view()

    def request_live(self, key):
        if not self.live_on.get() or self.view.get() not in ('bands', 'atmo'):
            return
        if self.live_after:
            self.after_cancel(self.live_after)
        self.live_after = self.after(350, lambda: self.start_live(key))

    def start_live(self, key):
        self.live_after = None
        if self.proc or not self.live_on.get():
            self.update_live_label(key)
            return
        sizes = (256, self.live_target())
        L = self.live_last
        if L is not None and L['key'] == key and L['W'] >= sizes[-1]:
            return
        P = gg.normalize(copy.deepcopy(self.P))
        if L is not None and L['fk'] == gg.flow_key(P) and L['W'] > sizes[0]:
            sizes = sizes[1:]
        r = self.live_req
        if r is not None and r[1] == key and r[3] == sizes:
            return
        self.live_err = None
        with self.live_lock:
            self.live_gen += 1
            self.live_req = (self.live_gen, key, P, sizes)
            if self.live_thread is None:
                self.live_thread = threading.Thread(target=self.live_worker, daemon=True)
                self.live_thread.start()
        self.update_live_label(key)

    def stop_live(self):
        with self.live_lock:
            self.live_gen += 1
            self.live_req = None

    def live_worker(self):
        while True:
            with self.live_lock:
                req = self.live_req
                if req is None:
                    self.live_thread = None
                    return
            gen, key, P, sizes = req

            def cancel(gen=gen):
                r = self.live_req
                if r is None or r[0] != gen:
                    raise gg.Cancelled()
            try:
                fk = gg.flow_key(P)
                for W in sizes:
                    if W != sizes[-1] and (fk, sizes[-1]) in self.live_cache:
                        continue
                    t0 = time.time()
                    c, e = gg.live_map(P, W, self.live_cache, cancel)
                    self.live_q.put((gen, key, fk, W, c, e, time.time() - t0))
            except gg.Cancelled:
                continue
            except Exception as ex:
                self.live_q.put((gen, key, '', 0, None, str(ex), 0))
            with self.live_lock:
                if self.live_req is not None and self.live_req[0] == gen:
                    self.live_req = None

    def live_poll(self):
        got = False
        try:
            while True:
                gen, key, fk, W, c, e, dt = self.live_q.get_nowait()
                if c is None:
                    if gen == self.live_gen:
                        self.live_err = e
                        got = True
                elif gen == self.live_gen:
                    self.live_last = {'key': key, 'fk': fk, 'W': W, 'col': c, 'em': e, 'dt': dt}
                    got = True
        except queue.Empty:
            pass
        except tk.TclError:
            return
        if got:
            if self.view.get() in ('bands', 'atmo'):
                self.update_view(from_live=True)
            else:
                self.update_live_label()
            self.ring_schedule()
        self.atmo_poll()
        try:
            self.after(120, self.live_poll)
        except tk.TclError:
            pass

    def toggle_live(self):
        S = load_settings()
        S['live_swirls'] = bool(self.live_on.get())
        save_settings(S)
        if not self.live_on.get():
            self.stop_live()
        self.update_view()

    def schedule_redraw(self):
        if self.redraw_id:
            self.after_cancel(self.redraw_id)
        self.redraw_id = self.after(60, self.redraw)
        if self.view.get() == 'atmo':
            if getattr(self, 'atmo_resize', None):
                self.after_cancel(self.atmo_resize)
            self.atmo_resize = self.after(400, self.atmo_request)

    def redraw(self, fast=False):
        self.redraw_id = None
        self.canvas.delete('all')
        cw, ch = max(10, self.canvas.winfo_width()), max(10, self.canvas.winfo_height())
        if self.view_src is None:
            self.view_geom = None
            txt = 'No picture yet'
            if self.view.get() == 'atmo':
                txt = 'Drawing the atmosphere…' if gg.has_atmo(self.P) else 'No atmosphere – tick “Scatterer atmosphere” in the Atmosphere tab'
            self.canvas.create_text(cw // 2, ch // 2, text=txt, fill=DIM, font=(FONT, 12))
            return
        iw, ih = self.view_src.size
        s = min((cw - 16) / iw, (ch - 16) / ih)
        w2, h2 = max(1, int(iw * s)), max(1, int(ih * s))
        im = self.view_src.resize((w2, h2), Image.BILINEAR if fast else Image.LANCZOS)
        self.tkimg = ImageTk.PhotoImage(im)
        self.canvas.create_image(cw // 2, ch // 2, image=self.tkimg)
        self.view_geom = (w2 / float(iw), cw // 2 - w2 / 2.0, ch // 2 - h2 / 2.0)
        if self.view.get() == 'bands' and self.map_tool.get() != 'turn' and self.live_view is not None:
            self.draw_map_marks()

    def flat_xy(self, lat, lon):
        s, ox, oy = self.view_geom
        return ox + (536 + (lon % 360.0) / 360.0 * 1024) * s, oy + (90 - lat) / 180.0 * 512 * s

    def mark_storm(self, lat, lon, size, aspect, col, width=2, globe=True):
        s, ox, oy = self.view_geom
        cv = self.canvas
        r = max(5.0, float(size) * 360 * 1024 / 360.0 * 1.1)
        rx, ry = r * max(1.0, float(aspect)) * s, r * s
        cx, cy = self.flat_xy(lat, lon)
        for dx in (-1024 * s, 0, 1024 * s):
            x = cx + dx
            if ox + 536 * s - rx <= x <= ox + 1560 * s + rx:
                cv.create_oval(x - rx, cy - ry, x + rx, cy + ry, outline=col, width=width, dash=(4, 3))
                cv.create_line(x - 4, cy, x + 5, cy, fill=col, width=width)
                cv.create_line(x, cy - 4, x, cy + 5, fill=col, width=width)
        if globe:
            gx, gy, z = self.globe_xy(lat, lon)
            if z > 0.05:
                gr = max(4.0, 256 * np.sin(np.radians(min(80.0, float(size) * 360 * 1.1)))) * s * max(z, 0.3) ** 0.5
                cv.create_oval(ox + gx * s - gr, oy + gy * s - gr, ox + gx * s + gr, oy + gy * s + gr, outline=col, width=width, dash=(4, 3))

    def draw_map_marks(self):
        s, ox, oy = self.view_geom
        cv = self.canvas
        tool = self.map_tool.get()
        cv.create_rectangle(ox + 536 * s, oy, ox + 1560 * s, oy + 512 * s, outline=ACC, width=1)
        if tool == 'bands':
            act = self.bdrag['i'] if self.bdrag is not None else -1
            x0, x1 = ox + 536 * s, ox + 1560 * s
            for i, b in enumerate(self.P['bands']):
                if i == 0:
                    continue
                y = oy + (90 - float(b[0])) / 180.0 * 512 * s
                col = WARM if i == act else '#ffffff'
                cv.create_line(x0, y, x1, y, fill=col, width=2 if i == act else 1, dash=() if i == act else (6, 4))
                cv.create_rectangle(x0 + 4, y - 9, x0 + 56, y + 8, fill='#101318', outline='')
                cv.create_text(x0 + 8, y, text='%.1f\u00b0' % float(b[0]), fill=col, anchor='w', font=(FONT, 8))
            return
        sact = self.sdrag[0] if self.sdrag is not None else -1
        for i, b in enumerate(self.P.get('big_storms', [])):
            dim = tool != 'storms'
            self.mark_storm(float(b['lat']), float(b['lon']), b.get('size', 0.025), b.get('aspect', 1.0),
                            '#7d8596' if dim else (WARM if i == sact else '#ffffff'), 1 if dim else 2, not dim)
        cact = self.cdrag['ci'] if (self.cdrag is not None and self.cdrag['mode'] == 'move') else -1
        for ci, c in enumerate(self.P.get('storm_chains', [])):
            col = WARM if ci == cact else (ACC if tool == 'chain' else '#7d8596')
            pts = gg.chain_points(c)
            for la, lo in pts:
                self.mark_storm(la, lo, c['size'], c['aspect'], col, 2 if tool == 'chain' else 1, tool == 'chain')
        if self.cdrag is not None and self.cdrag['mode'] == 'new':
            c = self.new_chain_from(self.cdrag['a'], self.cdrag['b'])
            for la, lo in gg.chain_points(c):
                self.mark_storm(la, lo, c['size'], c['aspect'], WARM, 2, True)
            ax, ay = self.flat_xy(*self.cdrag['a'])
            bx, by = self.flat_xy(*self.cdrag['b'])
            if abs(bx - ax) < 512 * s:
                cv.create_line(ax, ay, bx, by, fill=WARM, width=1, dash=(2, 3))

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
        self.stop_live()
        self.update_live_label()
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
            if self.view.get() == 'bands':
                self.update_view()
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
