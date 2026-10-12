"""Cameras tab: statistics per camera plus the first and last horse photo."""
import datetime as dt
import os
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, ttk

from . import analysis
from .tooltip import tip

THUMB_W, THUMB_H = 400, 300          # at text size 1.0; grows with the text size

COLUMN_HELP = (
    "One row per camera. Click a row to see its first and last horse photo.\n\n"
    "• Photos / Photo dates / Days w/ photos — every photo in the catalog, its date range, "
    "and how many days the camera took at least one photo (a gap = camera down).\n"
    "• Checked / Waiting — photos the horse detector has / hasn't looked at yet.\n"
    "• Horse photos / Horse % — photos counted as horses (your review decisions win), and "
    "the share of checked photos.\n"
    "• Horse days — days with at least one horse photo.\n"
    "• Visits, Visits/day — bursts of horse photos grouped by the visit gap; per day the "
    "camera was taking photos.\n"
    "• Avg / Longest (min) — length of a visit from first to last photo.\n"
    "• Busiest hour — hour of day with the most visits.\n"
    "• To review — photos in the review folder you haven't decided on yet.\n"
    "• First / Last horse — date and time of the earliest and latest horse photo.")


def show_in_folder(path):
    if os.name == "nt":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


def open_file(path):
    if os.name == "nt":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class CamerasTab:
    def __init__(self, app, frame):
        self.app = app
        self.f = frame
        self.stats = []
        self.by_cam = {}
        self._imgs = {}            # keep PhotoImage references alive
        self._build()

    # ------------------------------------------------------------------ layout
    def _build(self):
        app, f = self.app, self.f
        ctl = ttk.Frame(f)
        ctl.pack(fill="x", padx=8, pady=(8, 2))
        hc_help = ("Confidence (0–1) needed to count a photo as a horse. Shared with the "
                   "Histograms tab. Your review decisions always win.")
        gap_help = ("Horse photos from one camera closer together than this many minutes "
                    "count as one visit. Shared with the Histograms tab.")
        date_help = ("Only count photos between these days (YYYY-MM-DD). Blank = all. "
                     "Shared with the Histograms tab.")
        for col, (label, var, width, h) in enumerate((
                ("Horse threshold:", app.hc_var, 6, hc_help),
                ("Visit gap (min):", app.gap_var, 6, gap_help),
                ("From:", app.from_var, 11, date_help),
                ("To:", app.to_var, 11, date_help))):
            tip(ttk.Label(ctl, text=label), h).grid(row=0, column=2 * col, sticky="e", padx=(8, 2))
            tip(ttk.Entry(ctl, textvariable=var, width=width), h).grid(
                row=0, column=2 * col + 1, sticky="w", padx=(0, 6), pady=4)

        b = ttk.Frame(f)
        b.pack(fill="x", padx=8)
        tip(ttk.Button(b, text="Refresh", command=self.refresh, style="Accent.TButton"),
            "Recalculate the statistics with the threshold, visit gap and dates above.").pack(
            side="left", padx=6, pady=4)
        tip(ttk.Button(b, text="Save table (CSV)", command=self.save_csv),
            "Save this table, including the first/last horse photo file names, to the "
            "study folder's reports folder and open it.").pack(side="left", padx=6, pady=4)
        tip(ttk.Button(b, text="Open camera folder", command=self.open_cam_folder),
            "Open the selected camera's folder in File Explorer.").pack(side="left", padx=6, pady=4)
        self.note = tk.StringVar()
        ttk.Label(b, textvariable=self.note, style="Hint.TLabel").pack(side="left", padx=12)

        # table
        tf = ttk.Frame(f)
        tf.pack(fill="x", padx=8, pady=4)
        cols = [c[0] for c in analysis.STAT_COLUMNS]
        self.tree = ttk.Treeview(tf, columns=cols, show="headings", height=6,
                                 selectmode="browse")
        from tkinter import font as tkfont
        bold = tkfont.nametofont("HCBold")
        for key, heading, width in analysis.STAT_COLUMNS:
            self.tree.heading(key, text=heading)
            px = max(self._px(width), bold.measure(heading) + 24)
            self.tree.column(key, width=px, minwidth=40, stretch=False,
                             anchor="w" if key in ("camera", "range") else "e")
        xs = ttk.Scrollbar(tf, orient="horizontal", command=self.tree.xview)
        self.tree.configure(xscrollcommand=xs.set)
        self.tree.pack(fill="x")
        xs.pack(fill="x")
        tip(self.tree, COLUMN_HELP)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.show_detail())

        # first / last horse photo
        self.detail = ttk.LabelFrame(f, text="First and last horse photo")
        self.detail.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        self.cards = {}
        self._resize_job = None
        self.detail.bind("<Configure>", self._on_resize, add="+")
        for i, key in enumerate(("first", "last")):
            c = ttk.Frame(self.detail)
            c.grid(row=0, column=i, sticky="nsew", padx=10, pady=6)
            self.detail.columnconfigure(i, weight=1, uniform="cards")
            title = ttk.Label(c, text="First horse" if key == "first" else "Last horse",
                              style="CardTitle.TLabel")
            title.pack(anchor="w")
            when = tk.StringVar(value="–")
            ttk.Label(c, textvariable=when, style="CardWhen.TLabel").pack(anchor="w")
            info = tk.StringVar()
            ttk.Label(c, textvariable=info, style="Hint.TLabel", justify="left").pack(anchor="w")
            row = ttk.Frame(c)
            row.pack(anchor="w", pady=(4, 0))
            img = ttk.Label(c, anchor="center")
            img.pack(anchor="w", pady=4)
            bo = ttk.Button(row, text="Open photo", command=lambda k=key: self._open(k))
            bo.pack(side="left")
            bs = ttk.Button(row, text="Show in folder", command=lambda k=key: self._reveal(k))
            bs.pack(side="left", padx=6)
            word = "earliest" if key == "first" else "latest"
            tip(title, f"The {word} photo from this camera that counts as a horse "
                       "(model or your review), within the dates above.")
            tip(img, "Yellow boxes show where the model found the horse(s). Click 'Open "
                     "photo' to see it full size.")
            tip(bo, "Open the full-size photo in your picture viewer.")
            tip(bs, "Open File Explorer with this photo selected.")
            self.cards[key] = dict(when=when, info=info, img=img, path=None)

    def _px(self, chars):
        from tkinter import font as tkfont
        return int(chars * tkfont.nametofont("TkDefaultFont").measure("0") + 16)

    # ------------------------------------------------------------------ data
    def refresh(self):
        app = self.app
        if not app.lib:
            self.note.set("No study folder yet — choose one on the Import tab.")
            self.tree.delete(*self.tree.get_children())
            return
        try:
            hc = float(app.hc_var.get())
            gap = float(app.gap_var.get())
            start = app.from_var.get().strip() or None
            end = app.to_var.get().strip() or None
            for d in (start, end):
                if d:
                    dt.date.fromisoformat(d)
        except ValueError as e:
            messagebox.showerror("Cameras", f"Check the inputs: {e}")
            return
        keep = self.tree.selection()
        self.stats = analysis.camera_stats(app.lib, hc, gap, app.s["cameras"], start, end)
        self.by_cam = {r["camera"]: r for r in self.stats}
        self.tree.delete(*self.tree.get_children())
        for r in self.stats:
            cells = analysis.stat_cells(r)
            self.tree.insert("", "end", iid=r["camera"],
                             values=[cells[c[0]] for c in analysis.STAT_COLUMNS])
        self.tree.configure(height=max(3, min(8, len(self.stats))))
        tot_h = sum(r["horse_photos"] for r in self.stats)
        tot_v = sum(r["visits"] for r in self.stats)
        self.note.set(f"{len(self.stats)} cameras · {tot_h:,} horse photos · {tot_v:,} visits")
        sel = keep[0] if keep and keep[0] in self.by_cam else (
            self.stats[0]["camera"] if self.stats else None)
        if sel:
            self.tree.selection_set(sel)
            self.tree.see(sel)
        self.show_detail()

    def _on_resize(self, _e=None):
        if self._resize_job:
            self.f.after_cancel(self._resize_job)
        self._resize_job = self.f.after(250, self._redraw_thumbs)

    def _redraw_thumbs(self):
        self._resize_job = None
        if self.stats and str(self.f) == self.app.nb.select():
            self.show_detail()

    def selected(self):
        s = self.tree.selection()
        return s[0] if s else None

    def show_detail(self):
        cam = self.selected()
        r = self.by_cam.get(cam)
        self.detail.configure(text=f"{cam} — first and last horse photo" if cam
                              else "First and last horse photo")
        for key, card in self.cards.items():
            p = r and r[key]
            card["path"] = None
            card["img"].configure(image="", text="")
            if not p:
                card["when"].set("–")
                card["info"].set("No horse photos for this camera yet." if r else "")
                continue
            t = p["taken"]
            card["when"].set(t.strftime("%a %d %b %Y   %H:%M:%S"))
            how = ("your review" if p["manual"] == 1 else
                   f"model {p['conf']:.0%} sure" if p["conf"] is not None else "")
            path = self._find_file(cam, p)
            card["info"].set(f"{p['fname']}   ·   {how}" + ("" if path else "\n(file not found on disk)"))
            card["path"] = path
            if path:
                self._thumb(key, path, p["id"])

    def _find_file(self, cam, p):
        lib = self.app.lib
        for path in (lib.abs(p["rel_path"]), os.path.join(lib.horses_dir(cam), p["fname"])):
            if os.path.isfile(path):
                return path
        return None

    def _thumb(self, key, path, photo_id):
        try:
            import json
            from PIL import Image, ImageDraw, ImageOps, ImageTk
            k = self.app._text_scale()
            w, h = int(THUMB_W * k), int(THUMB_H * k)
            # shrink to the space left in the window
            self.f.update_idletasks()
            lbl = self.cards[key]["img"]
            card = lbl.master
            avail_h = (self.detail.winfo_rooty() + self.detail.winfo_height()
                       - lbl.winfo_rooty() - 12)
            avail_w = card.winfo_width() - 4
            if avail_h > 60:
                h = min(h, avail_h)
            if avail_w > 60:
                w = min(w, avail_w)
            im = Image.open(path)
            full = im.size                        # boxes are in full-size pixels
            im.draft("RGB", (w * 2, h * 2))       # fast reduced JPEG decode
            im.load()
            sx, sy = im.size[0] / full[0], im.size[1] / full[1]
            if im.mode != "RGB":
                im = im.convert("RGB")
            row = self.app.lib.db.query("SELECT boxes FROM detections WHERE photo_id=?",
                                        (photo_id,))
            boxes = json.loads(row[0][0]) if row and row[0][0] else []
            dr = ImageDraw.Draw(im)
            lw = max(2, im.size[0] // 300)
            for x1, y1, x2, y2, *_ in boxes:
                dr.rectangle([x1 * sx, y1 * sy, x2 * sx, y2 * sy], outline="#ffd400", width=lw)
            im = ImageOps.exif_transpose(im)
            im.thumbnail((w, h))
            ph = ImageTk.PhotoImage(im)
            self._imgs[key] = ph
            self.cards[key]["img"].configure(image=ph)
        except Exception as e:                       # unreadable file, PIL missing, …
            self.cards[key]["img"].configure(image="", text=f"(can't show preview: {e})")

    # ------------------------------------------------------------------ buttons
    def _open(self, key):
        p = self.cards[key]["path"]
        if p:
            open_file(p)

    def _reveal(self, key):
        p = self.cards[key]["path"]
        if p:
            show_in_folder(p)

    def open_cam_folder(self):
        cam = self.selected()
        if cam and self.app.lib:
            d = self.app.lib.cam_dir(cam)
            if os.path.isdir(d):
                open_file(d)

    def save_csv(self):
        if not self.app.need_lib():
            return
        if not self.stats:
            self.refresh()
        out = analysis.save_camera_stats(self.app.lib, self.stats)
        self.app.log(f"Camera table saved: {out}")
        open_file(out)
