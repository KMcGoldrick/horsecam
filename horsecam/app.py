"""HorseCam — trail-cam import, horse detection and attendance histograms."""
import datetime as dt
import os
import queue
import subprocess
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import tkinter.font as tkfont

from . import settings as S
from .library import Library, find_camera_folders, valid_camera_name
from . import importer, detector
from . import tooltip
from . import theme
from .tooltip import tip, NotebookTips

# Tk's built-in fonts; every label, button, tab, list and text box uses one of these
NAMED_FONTS = ("TkDefaultFont", "TkTextFont", "TkFixedFont", "TkMenuFont", "TkHeadingFont",
               "TkCaptionFont", "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont")
CHART_DPI = 100

PAD = dict(padx=6, pady=4)

# Hover help for each chart on the Histograms tab
CHART_HELP = {
    "Hour of day (all cameras)":
        "Bars for each hour of the day (0–23), stacked by camera. Shows what time of "
        "day horses turn up across the whole study.",
    "Hour of day (per camera)":
        "One small hour-of-day histogram per camera, so you can compare when each "
        "location is used.",
    "Daily timeline":
        "Count for every calendar day in the selection. Good for spotting trends, "
        "seasonal changes, or gaps where a camera was down.",
    "Camera × hour heatmap":
        "Grid of camera (rows) by hour of day (columns); darker = more horses. "
        "Compact view of who-comes-when for all cameras at once.",
    "Day of week":
        "Counts for Monday to Sunday, by camera. Useful for spotting weekly patterns "
        "such as people or traffic disturbing the horses.",
}


def open_folder(path):
    if os.name == "nt":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def human(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HorseCam")
        self.s = S.load()
        self._base_font_sizes = {}
        self.fig = None
        self.apply_text_size(self._text_scale())
        k = self._text_scale()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{min(int(1100 * k), sw - 40)}x{min(int(760 * k), sh - 80)}")
        self.minsize(min(int(900 * k), sw - 40), min(int(600 * k), sh - 80))
        self.lib = None
        self.q = queue.Queue()
        self.stop = threading.Event()
        self.worker = None
        self.card_files = None

        self.th = theme.apply(self, self.s.get("theme", theme.DEFAULT))
        self._build_header()
        self._build_status()      # pack the status/log area first so it never gets squeezed
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=6, pady=6)
        self.tab_import = ttk.Frame(nb)
        self.tab_detect = ttk.Frame(nb)
        self.tab_analyze = ttk.Frame(nb)
        self.tab_settings = ttk.Frame(nb)
        nb.add(self.tab_import, text="1. Import photos")
        nb.add(self.tab_detect, text="2. Find horses")
        nb.add(self.tab_analyze, text="3. Histograms")
        nb.add(self.tab_settings, text="Settings")
        self._build_settings()
        self._build_import()
        self._build_detect()
        self._build_analyze()
        nb.bind("<<NotebookTabChanged>>", self._tab_changed)
        self.nb = nb
        NotebookTips(nb, {
            0: "Bring photos into the study: index folders you already copied, or copy "
               "a new SD card into the right camera folder.",
            1: "Run the horse detector on photos that haven't been checked yet, and apply "
               "your manual review decisions.",
            2: "Charts of when horses show up (by hour, day, camera) and saving reports "
               "with CSV files.",
            3: "Study folder, camera names and detection options. Press 'Save settings' "
               "after changing anything here.",
        })

        self.open_library(quiet=True)
        if not self.lib:
            nb.select(self.tab_settings)
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _text_scale(self):
        try:
            return min(3.0, max(0.7, float(self.s.get("text_size", 1.3))))
        except (TypeError, ValueError):
            return 1.3

    def apply_text_size(self, scale):
        """Scale every font in the app (and the on-screen chart) by `scale` × the original."""
        for name in NAMED_FONTS:
            try:
                f = tkfont.nametofont(name)
            except tk.TclError:
                continue
            base = self._base_font_sizes.setdefault(name, f.cget("size"))
            # negative sizes are pixels, positive are points; keep the sign
            size = max(6, round(abs(base) * scale)) if base else round(9 * scale)
            f.configure(size=-size if base < 0 else size)
        d = tkfont.nametofont("TkDefaultFont").actual()
        for fname, mult in (("HCBold", 1.0), ("HCTitle", 1.6)):
            size = max(6, round(abs(d["size"]) * mult))
            if not hasattr(self, "_hc_fonts"):
                self._hc_fonts = {}   # keep references: tkinter deletes unreferenced fonts
            if fname in self._hc_fonts:
                self._hc_fonts[fname].configure(family=d["family"], size=size, weight="bold")
            else:
                self._hc_fonts[fname] = tkfont.Font(root=self, name=fname, family=d["family"],
                                                    size=size, weight="bold")
        tooltip.WRAP_PX = int(380 * scale)
        if self.fig is not None:
            self.fig.set_dpi(CHART_DPI * scale)
            w = self.canvas.get_tk_widget()
            if w.winfo_width() > 1:
                self.fig.set_size_inches(w.winfo_width() / self.fig.dpi,
                                         w.winfo_height() / self.fig.dpi)
            self.canvas.draw_idle()

    def _build_header(self):
        """Colored title strip across the top (hidden in the Classic theme)."""
        self.header = ttk.Frame(self, style="Header.TFrame", padding=(14, 8))
        ttk.Label(self.header, text="HorseCam", style="Header.TLabel").pack(side="left")
        ttk.Label(self.header, text="   trail-cam horse attendance",
                  style="HeaderSub.TLabel").pack(side="left", pady=(6, 0))
        if self.th:
            self.header.pack(fill="x", side="top")

    def apply_theme(self, name):
        self.th = theme.apply(self, name)
        theme.style_text(self.logbox, self.th)
        if self.th and not self.header.winfo_ismapped():
            self.header.pack(fill="x", side="top", before=self.nb)
        elif not self.th and self.header.winfo_ismapped():
            self.header.pack_forget()
        if self.nb.select() == str(self.tab_analyze):
            self.update_chart()

    def _tab_changed(self, _e=None):
        self.refresh_counts()
        if self.nb.select() == str(self.tab_analyze):
            self.update_chart()

    # ------------------------------------------------------------- plumbing
    def _build_status(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", side="bottom", padx=6, pady=(0, 6))
        self.prog = ttk.Progressbar(bar, mode="determinate")
        self.prog.pack(fill="x", side="top")
        row = ttk.Frame(bar)
        row.pack(fill="x")
        tip(self.prog, "Progress of the current job (indexing, importing, detection…).")
        self.status = tk.StringVar(value="Ready.")
        tip(ttk.Label(row, textvariable=self.status), "What the app is doing right now.").pack(side="left")
        self.btn_stop = ttk.Button(row, text="Stop", command=self.stop.set, state="disabled")
        self.btn_stop.pack(side="right")
        tip(self.btn_stop, "Stop the running job safely. Work done so far is kept — indexing, "
                           "import and detection pick up where they left off next time.")
        self.logbox = tk.Text(bar, height=7, wrap="word", state="disabled")
        theme.style_text(self.logbox, self.th)
        self.logbox.pack(fill="x", pady=(4, 0))
        tip(self.logbox, "Activity log for this session. Detailed per-file logs for each "
                         "import or index run are saved in the study folder's logs folder.")

    def log(self, msg):
        self.q.put(("log", msg))

    def progress(self, done, total, msg=""):
        self.q.put(("progress", done, total, msg))

    def _write_log(self, msg):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", f"{dt.datetime.now():%H:%M:%S}  {msg}\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "log":
                    self._write_log(item[1])
                elif kind == "progress":
                    _, done, total, msg = item
                    self.prog["maximum"] = max(1, total)
                    self.prog["value"] = done
                    if msg:
                        self.status.set(msg)
                elif kind == "done":
                    _, cb, res = item
                    self._job_finished()
                    if cb:
                        cb(res)
                elif kind == "error":
                    self._job_finished()
                    self._write_log("ERROR:\n" + item[1])
                    messagebox.showerror("HorseCam", item[1].strip().splitlines()[-1])
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def busy(self):
        return self.worker is not None and self.worker.is_alive()

    def run_bg(self, fn, done=None, label="Working…"):
        if self.busy():
            messagebox.showinfo("HorseCam", "Another job is still running.")
            return
        self.stop.clear()
        self.btn_stop.configure(state="normal")
        self.status.set(label)
        self.prog["value"] = 0

        def target():
            try:
                self.q.put(("done", done, fn()))
            except Exception:
                self.q.put(("error", traceback.format_exc()))

        self.worker = threading.Thread(target=target, daemon=True)
        self.worker.start()

    def _job_finished(self):
        self.btn_stop.configure(state="disabled")
        self.refresh_counts()

    def need_lib(self):
        if not self.lib:
            messagebox.showwarning("HorseCam", "Choose the study folder on the Import tab first.")
            return False
        return True

    def _on_close(self):
        if self.busy() and not messagebox.askyesno(
                "HorseCam", "A job is running. Stop it and quit?"):
            return
        self.stop.set()
        if self.worker:
            self.worker.join(timeout=5)
        if self.lib:
            self.lib.close()
        self.destroy()

    # ------------------------------------------------------------- settings
    def _build_settings(self):
        f = self.tab_settings
        self.v = {}

        def row(r, label, key, width=40, hint="", help_=""):
            lab = ttk.Label(f, text=label)
            lab.grid(row=r, column=0, sticky="e", **PAD)
            var = tk.StringVar(value=str(self.s[key]) if not isinstance(self.s[key], list)
                               else ", ".join(self.s[key]))
            self.v[key] = var
            e = ttk.Entry(f, textvariable=var, width=width)
            e.grid(row=r, column=1, sticky="w", **PAD)
            if help_:
                tip(lab, help_)
                tip(e, help_)
            if hint:
                h = ttk.Label(f, text=hint, style="Hint.TLabel")
                h.grid(row=r, column=2, sticky="w", **PAD)
                if help_:
                    tip(h, help_)
            return e

        row(0, "Study folder:", "library", 55, help_=(
            "The main folder for the study on your hard drive. It holds one sub-folder per "
            "camera, plus the catalog (horsecam.db), reports and logs."))
        tip(ttk.Button(f, text="Browse…", command=self._pick_library),
            "Pick the study folder with a folder browser.").grid(row=0, column=2, sticky="w", **PAD)
        row(1, "Camera names:", "cameras", 55, help_=(
            "Comma-separated list of cameras. Each name must match its folder inside the "
            "study folder. Don't rename a camera after indexing — it would be treated as a "
            "new camera."))
        tip(ttk.Button(f, text="Use the study folder's sub-folder names",
                       command=self._cams_from_folder),
            "Fill in the camera names from the folders found inside the study folder.").grid(
            row=1, column=2, sticky="w", **PAD)
        model_help = ("Which YOLO model finds the horses.\n"
                      "• yolo11n / s — fastest, a bit less accurate\n"
                      "• yolo11m — good balance (default)\n"
                      "• yolo11l / x — most accurate, slow without a GPU\n"
                      "The model downloads the first time it is used (be online).")
        tip(ttk.Label(f, text="Detection model:"), model_help).grid(row=2, column=0, sticky="e", **PAD)
        self.v["model"] = tk.StringVar(value=self.s["model"])
        tip(ttk.Combobox(f, textvariable=self.v["model"], width=20, values=[
            "yolo11n.pt", "yolo11s.pt", "yolo11m.pt", "yolo11l.pt", "yolo11x.pt"]),
            model_help).grid(row=2, column=1, sticky="w", **PAD)
        tip(ttk.Label(f, text="n/s fast · m balanced · l/x most accurate",
                      style="Hint.TLabel"), model_help).grid(row=2, column=2, sticky="w", **PAD)
        row(3, "Image size:", "imgsz", 8, "960 default · 1280 for far horses", help_=(
            "Size (pixels) photos are shrunk to before detection. Bigger finds small or "
            "distant horses better but runs slower. 960 is the default; try 1280 if horses "
            "far from the camera are being missed."))
        row(4, "Device:", "device", 8, "blank = auto · cpu · 0 = GPU", help_=(
            "Where detection runs. Leave blank to pick automatically, type cpu to force the "
            "processor, or 0 for the first NVIDIA graphics card (10–30× faster)."))
        row(5, "Batch size:", "batch", 8, help_=(
            "How many photos are checked at once. Higher can be faster on a GPU; lower it "
            "(e.g. 4 or 2) if you get out-of-memory errors."))
        row(6, "Horse threshold:", "horse_conf", 8, "at/above = horse", help_=(
            "Confidence (0–1) at or above which a photo counts as a horse and is copied to "
            "<camera>\\horses. Lower = more horses found but more false alarms. "
            "Default 0.40. Can also be tried out on the Histograms tab without re-running "
            "detection."))
        row(7, "Review threshold:", "review_conf", 8, "between this and horse = review", help_=(
            "Photos with a confidence between this and the horse threshold go to "
            "<camera>\\review for you to check by eye. Lower = more photos to review but "
            "fewer missed horses. Default 0.15. Must be ≤ the horse threshold."))
        row(8, "Visit gap (minutes):", "visit_gap_min", 8,
            "closer photos = same visit", help_=(
                "Horse photos from the same camera closer together than this are counted "
                "as one visit (trail cams shoot bursts). Default 10 minutes."))
        row(9, "Text size:", "text_size", 8, "1.0 original · 1.3 larger · 1.6 largest", help_=(
            "Makes all the text in HorseCam bigger or smaller, including the chart and these "
            "help boxes. 1.0 is the original size; 1.3 is the default. Applies as soon as "
            "you press Save settings."))
        theme_help = ("Colors for the whole app and the chart:\n"
                      "• Meadow — greens and gold\n• Sunset — warm orange and cream\n"
                      "• Lake — blues and teal\n• Night — dark, easy on the eyes\n"
                      "• Classic — the original plain Windows look\n"
                      "Applies as soon as you press Save settings.")
        tip(ttk.Label(f, text="Color theme:"), theme_help).grid(row=10, column=0, sticky="e", **PAD)
        self.v["theme"] = tk.StringVar(value=self.s.get("theme", theme.DEFAULT))
        tip(ttk.Combobox(f, textvariable=self.v["theme"], values=theme.NAMES,
                         state="readonly", width=12), theme_help).grid(row=10, column=1, sticky="w", **PAD)
        tip(ttk.Button(f, text="Save settings", command=self.save_settings, style="Accent.TButton"),
            "Check and save all the settings above. They are remembered next time the "
            "app starts.").grid(row=11, column=1, sticky="w", pady=12, padx=6)

    def _pick_library(self):
        d = filedialog.askdirectory(title="Choose the study folder (one sub-folder per camera)")
        if d:
            self.v["library"].set(os.path.normpath(d))

    def _cams_from_folder(self):
        root = self.v["library"].get().strip()
        if not root or not os.path.isdir(root):
            messagebox.showwarning("Settings", "Choose the study folder first.")
            return
        cams = find_camera_folders(root)
        if not cams:
            messagebox.showwarning("Settings", f"No sub-folders found in\n{root}")
            return
        self.v["cameras"].set(", ".join(cams))

    def save_settings(self):
        try:
            new = dict(self.s)
            new["library"] = self.v["library"].get().strip()
            new["cameras"] = [c.strip() for c in self.v["cameras"].get().split(",") if c.strip()]
            new["model"] = self.v["model"].get().strip()
            new["imgsz"] = int(self.v["imgsz"].get())
            new["device"] = self.v["device"].get().strip()
            new["batch"] = int(self.v["batch"].get())
            new["horse_conf"] = float(self.v["horse_conf"].get())
            new["review_conf"] = float(self.v["review_conf"].get())
            new["visit_gap_min"] = float(self.v["visit_gap_min"].get())
            new["text_size"] = float(self.v["text_size"].get())
            new["theme"] = self.v["theme"].get()
            if not 0.7 <= new["text_size"] <= 3.0:
                raise ValueError("Text size must be between 0.7 and 3.0")
            if not 0 < new["review_conf"] <= new["horse_conf"] < 1:
                raise ValueError("Need 0 < review threshold ≤ horse threshold < 1")
            bad = [c for c in new["cameras"] if not valid_camera_name(c)]
            if bad:
                raise ValueError(f"Camera names can't contain  < > : \" / \\ | ? * ,  ({bad[0]})")
        except ValueError as e:
            messagebox.showerror("Settings", str(e))
            return
        lib_changed = new["library"] != self.s["library"]
        self.s = new
        S.save(self.s)
        self._cameras_changed()
        self.apply_text_size(self._text_scale())
        self.apply_theme(self.s["theme"])
        self.hc_var.set(str(self.s["horse_conf"]))
        self.gap_var.set(str(self.s["visit_gap_min"]))
        if lib_changed or not self.lib:
            self.open_library()
        self.status.set("Settings saved.")

    def _cameras_changed(self):
        self.cam_combo["values"] = self.s["cameras"]
        self.v["cameras"].set(", ".join(self.s["cameras"]))
        self.v["library"].set(self.s["library"])
        self._rebuild_cam_checks()

    def open_library(self, quiet=False):
        if self.lib:
            self.lib.close()
            self.lib = None
        try:
            self.lib = Library(self.s["library"])
            self.log(f"Study folder: {self.lib.root}")
        except Exception as e:
            if not quiet:
                messagebox.showerror("Library", str(e))
        self.refresh_counts()

    # --------------------------------------------------------------- import
    def _build_import(self):
        f = self.tab_import
        hd = ttk.LabelFrame(f, text="Photos already copied to the hard drive")
        hd.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(hd, text=("Pick the folder that holds one folder per camera. Folder names "
                            "become the camera names; photos stay where they are (no second copy)."),
                  style="Hint.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", **PAD)
        tip(ttk.Button(hd, text="Choose study folder…", command=self.choose_study_folder),
            "Pick the folder that holds one folder per camera (e.g. D:\\HorseStudy). The "
            "sub-folder names become the camera names, and you'll be offered to index "
            "the photos.").grid(row=1, column=0, sticky="w", **PAD)
        self.btn_index = ttk.Button(hd, text="Index photos", command=self.index_folders)
        self.btn_index.grid(row=1, column=1, sticky="w", **PAD)
        tip(self.btn_index, "Catalog the photos already in the camera folders: reads each "
                            "photo's date and fingerprint. Nothing is copied or moved. Photos "
                            "already indexed and duplicate copies are skipped. Can be stopped "
                            "and resumed.")
        tip(ttk.Button(hd, text="Index, then find horses", style="Accent.TButton",
                       command=lambda: self.index_folders(then_detect=True)),
            "Index the camera folders, then go straight on to horse detection for the new "
            "photos.").grid(row=1, column=2, sticky="w", **PAD)
        tip(ttk.Button(hd, text="Open study folder",
                       command=lambda: self.lib and open_folder(self.lib.root)),
            "Open the study folder in File Explorer.").grid(row=1, column=3, sticky="w", **PAD)

        top = ttk.LabelFrame(f, text="SD card")
        top.pack(fill="x", padx=8, pady=8)
        card_help = ("The SD card (or any folder of photos) to import from. Removable drives "
                     "are listed automatically; use Refresh after inserting a card.")
        tip(ttk.Label(top, text="Card:"), card_help).grid(row=0, column=0, sticky="e", **PAD)
        self.card_var = tk.StringVar()
        self.card_combo = ttk.Combobox(top, textvariable=self.card_var, width=40)
        self.card_combo.grid(row=0, column=1, sticky="w", **PAD)
        tip(self.card_combo, card_help)
        tip(ttk.Button(top, text="Refresh", command=self.refresh_cards),
            "Look again for SD cards / removable drives.").grid(row=0, column=2, **PAD)
        tip(ttk.Button(top, text="Browse…", command=self._browse_card),
            "Choose the card or a folder of photos by hand.").grid(row=0, column=3, **PAD)

        cam_help = ("Which camera this card was taken out of. The photos are filed under that "
                    "camera and it drives every chart, so double-check it.")
        tip(ttk.Label(top, text="This card came out of:"), cam_help).grid(
            row=1, column=0, sticky="e", **PAD)
        self.cam_var = tk.StringVar(value=self.s.get("last_camera", ""))
        self.cam_combo = ttk.Combobox(top, textvariable=self.cam_var, width=14,
                                      values=self.s["cameras"], state="readonly")
        self.cam_combo.grid(row=1, column=1, sticky="w", **PAD)
        tip(self.cam_combo, cam_help)

        btns = ttk.Frame(top)
        btns.grid(row=2, column=1, sticky="w", **PAD)
        tip(ttk.Button(btns, text="Scan card", command=self.scan_card, style="Accent.TButton"),
            "Count the photos and videos on the card and show their date range. Must be "
            "done before importing. Nothing on the card is changed.").pack(side="left")
        self.btn_import = ttk.Button(btns, text="Import to library", command=self.import_card,
                                     state="disabled")
        self.btn_import.pack(side="left", padx=8)
        tip(self.btn_import, "Copy the card's photos to <study folder>\\<camera>\\photos\\<YYYY-MM>, "
                             "verifying every file. Photos already in the library are skipped. "
                             "Only format the card if the import reports 0 failed.\n"
                             "(Enabled after Scan card.)")
        self.btn_import_detect = ttk.Button(btns, text="Import, then find horses", style="Accent.TButton",
                                            command=lambda: self.import_card(then_detect=True),
                                            state="disabled")
        self.btn_import_detect.pack(side="left")
        tip(self.btn_import_detect, "Import the card, then go straight on to horse detection "
                                    "for the new photos.\n(Enabled after Scan card.)")

        self.card_info = tk.StringVar(value="Insert a card and press Scan.")
        ttk.Label(f, textvariable=self.card_info, justify="left").pack(anchor="w", padx=14)
        note = ("Card photos are copied to <study folder>\\<camera>\\photos\\ and verified; nothing "
                "on the card is changed. Photos already cataloged are skipped,\nso re-importing "
                "a card (or one you already copied by hand) is safe. After a successful import, "
                "format the card in the camera.")
        ttk.Label(f, text=note, style="Hint.TLabel", justify="left").pack(anchor="w", padx=14, pady=8)
        self.lib_info = tk.StringVar()
        ttk.Label(f, textvariable=self.lib_info, justify="left").pack(anchor="w", padx=14, pady=8)
        self.refresh_cards()

    def choose_study_folder(self):
        if self.busy():
            messagebox.showinfo("HorseCam", "Wait for the current job to finish.")
            return
        d = filedialog.askdirectory(
            title="Choose the folder that contains one folder per camera",
            initialdir=self.s["library"] or None)
        if not d:
            return
        d = os.path.normpath(d)
        cams = find_camera_folders(d)
        if not cams:
            messagebox.showwarning("Study folder", f"No camera folders found in\n{d}")
            return
        bad = [c for c in cams if not valid_camera_name(c)]
        if bad:
            messagebox.showwarning("Study folder", f"Rename this folder first (no commas or "
                                   f"< > : \" | ? *):\n{bad[0]}")
            return
        if not messagebox.askyesno(
                "Study folder",
                f"{d}\n\nFound {len(cams)} camera folders:\n   " + "\n   ".join(cams) +
                "\n\nUse these as the camera names?\n(Remove or rename any folder that "
                "isn't a camera, then choose again.)"):
            return
        self.s["library"] = d
        self.s["cameras"] = cams
        S.save(self.s)
        self._cameras_changed()
        self.open_library()
        if self.lib and messagebox.askyesno(
                "Study folder", "Index the photos in these folders now?\n\n"
                "This reads every photo once (no copying). It can be stopped and resumed."):
            self.index_folders()

    def index_folders(self, then_detect=False):
        if not self.need_lib():
            return
        lib, cams = self.lib, [c for c in self.s["cameras"]
                               if os.path.isdir(self.lib.cam_dir(c))]
        if not cams:
            messagebox.showwarning("Index", "None of the camera folders exist in the study folder.")
            return

        def job():
            total = {"added": 0, "already": 0, "duplicate": 0, "failed": 0}
            for cam in cams:
                if self.stop.is_set():
                    break
                self.log(f"Indexing {cam}…")
                st = importer.index_folder(lib, cam, lib.cam_dir(cam),
                                           self.progress, self.stop, self.log)
                self.log(f"{cam}: {st['added']:,} added, {st['already']:,} already indexed, "
                         f"{st['duplicate']:,} duplicates skipped, {st['failed']} failed")
                for k in total:
                    total[k] += st[k]
            return total

        def done(t):
            self.status.set(f"Indexing done — {t['added']:,} new photos.")
            if t["failed"]:
                messagebox.showwarning("Index", f"{t['failed']} files could not be read. "
                                       "See the logs folder.")
            if then_detect and not self.stop.is_set():
                self.after(200, self.detect)

        self.run_bg(job, done, "Indexing…")

    def refresh_cards(self):
        drives = importer.removable_drives()
        self.card_combo["values"] = [f"{r}  {lbl}".strip() for r, lbl in drives]
        if drives and not self.card_var.get():
            self.card_var.set(self.card_combo["values"][0])

    def _browse_card(self):
        d = filedialog.askdirectory(title="Choose the SD card (or a folder of photos)")
        if d:
            self.card_var.set(d)

    def _card_root(self):
        v = self.card_var.get().strip()
        if len(v) >= 3 and v[1:3] == ":\\":
            return v[:3], v[3:].strip()
        return v, os.path.basename(v.rstrip("\\/"))

    def scan_card(self):
        root, _ = self._card_root()
        if not root or not os.path.isdir(root):
            messagebox.showwarning("Scan", "Choose a card or folder first.")
            return
        self.btn_import.configure(state="disabled")
        self.btn_import_detect.configure(state="disabled")

        def job():
            files = importer.scan_card(root)
            return files, importer.summarize_card(root, files)

        def done(res):
            files, info = res
            self.card_files = (root, files)
            rng = (f"{info['first']:%Y-%m-%d %H:%M}  →  {info['last']:%Y-%m-%d %H:%M}"
                   if info["first"] else "no EXIF dates found")
            self.card_info.set(f"{root}:  {info['images']} photos, {info['videos']} videos, "
                               f"{human(info['bytes'])}\nDates (sampled): {rng}")
            state = "normal" if info["files"] else "disabled"
            self.btn_import.configure(state=state)
            self.btn_import_detect.configure(state=state)
            self.status.set("Scan complete.")

        self.run_bg(job, done, "Scanning card…")

    def import_card(self, then_detect=False):
        if not self.need_lib():
            return
        cam = self.cam_var.get()
        root, label = self._card_root()
        if not cam:
            messagebox.showwarning("Import", "Choose which camera this card came out of.")
            return
        if not self.card_files or self.card_files[0] != root:
            messagebox.showwarning("Import", "Scan the card first.")
            return
        files = self.card_files[1]
        if not messagebox.askyesno(
                "Confirm import",
                f"Import {len(files)} files from {root}\nas camera  {cam}?\n\n"
                "Double-check the camera — this tag drives every chart."):
            return
        self.s["last_camera"] = cam
        S.save(self.s)
        lib = self.lib

        def job():
            return importer.import_card(lib, root, cam, label, files,
                                        self.progress, self.stop, self.log)

        def done(st):
            self.log(f"Import {cam}: {st['copied']} copied ({human(st['bytes'])}), "
                     f"{st['duplicate']} already in library, {st['failed']} failed. "
                     f"Log: {st['log']}")
            if st["failed"]:
                messagebox.showwarning(
                    "Import", f"{st['failed']} files failed to copy. Do NOT format this card "
                    f"yet — see the log:\n{st['log']}")
            else:
                self.status.set(f"Import complete — {st['copied']} new files. Safe to format the card.")
            if then_detect and not self.stop.is_set():
                self.after(200, self.detect)

        self.run_bg(job, done, f"Importing {cam}…")

    # --------------------------------------------------------------- detect
    def _build_detect(self):
        f = self.tab_detect
        self.det_info = tk.StringVar()
        ttk.Label(f, textvariable=self.det_info, justify="left").pack(anchor="w", padx=14, pady=10)
        b = ttk.Frame(f)
        b.pack(anchor="w", padx=10)
        tip(ttk.Button(b, text="Find horses in new photos", command=self.detect, style="Accent.TButton"),
            "Run the detection model on every photo not checked yet. Confident horses are "
            "copied to <camera>\\horses, uncertain ones to <camera>\\review. Can be stopped "
            "and resumed any time.").pack(side="left", **PAD)
        tip(ttk.Button(b, text="Open study folder",
                       command=lambda: self.lib and open_folder(self.lib.root)),
            "Open the study folder in File Explorer to sort the review and horses "
            "folders.").pack(side="left", **PAD)
        tip(ttk.Button(b, text="Apply my review", command=self.apply_review),
            "Read the photos you moved into review\\yes, review\\no and horses\\_not_horse "
            "and record them. Your decisions override the model in every chart.").pack(
            side="left", **PAD)
        help_ = (
            "How review works\n"
            "Each camera folder gets its own horses and review folders:\n"
            "• <camera>\\horses\\  — photos the model is confident about.  Found a wrong one? "
            "Move it into <camera>\\horses\\_not_horse\\.\n"
            "• <camera>\\review\\  — uncertain photos, with the candidate drawn in a yellow box.  "
            "Move each into <camera>\\review\\yes\\ or \\no\\.\n"
            "• Press 'Apply my review'. Your calls override the model in every chart.  "
            "Detection can be stopped and resumed at any time.")
        ttk.Label(f, text=help_, style="Hint.TLabel", justify="left").pack(anchor="w", padx=14, pady=10)

    def detect(self):
        if not self.need_lib():
            return
        lib, s = self.lib, dict(self.s)

        def job():
            return detector.run_detection(lib, s, progress=self.progress,
                                          stop=self.stop, log=self.log)

        def done(st):
            self.log(f"Checked {st['processed']}: {st['horse']} horse, {st['review']} to review, "
                     f"{st['none']} none, {st['error']} unreadable.")
            self.status.set("Detection finished." if not self.stop.is_set() else "Detection paused.")

        self.run_bg(job, done, "Loading model…")

    def apply_review(self):
        if not self.need_lib():
            return
        lib = self.lib
        self.run_bg(lambda: detector.apply_review(lib),
                    lambda c: self.log(f"Review applied: {c['yes']} horse, {c['no']} not horse"
                                       + (f", {c['unknown']} files not recognised" if c["unknown"] else "")),
                    "Applying review…")

    def refresh_counts(self):
        if not self.lib:
            self.lib_info.set("No study folder yet — use 'Choose study folder…' above.")
            self.det_info.set("")
            return
        q = self.lib.db.query
        per_cam = q("SELECT camera, COUNT(*), MIN(taken), MAX(taken) FROM photos "
                    "WHERE kind='image' GROUP BY camera ORDER BY camera")
        lines = [f"Study folder: {self.lib.root}"]
        for cam, n, a, b in per_cam:
            lines.append(f"   {cam}: {n:,} photos   {a[:10]} → {b[:10]}")
        self.lib_info.set("\n".join(lines))
        st = dict(q("SELECT status, COUNT(*) FROM detections GROUP BY status"))
        pending = detector.pending_count(self.lib)
        manual = self.lib.db.scalar("SELECT COUNT(*) FROM manual")
        self.det_info.set(
            f"Waiting to be checked: {pending:,}\n"
            f"Horse: {st.get('horse', 0):,}    Review: {st.get('review', 0):,}    "
            f"No horse: {st.get('none', 0):,}    Unreadable: {st.get('error', 0):,}\n"
            f"Manual decisions recorded: {manual:,}")

    # -------------------------------------------------------------- analyze
    def _build_analyze(self):
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.figure import Figure
        from . import analysis

        f = self.tab_analyze
        ctl = ttk.Frame(f)
        ctl.pack(fill="x", padx=8, pady=6)
        self.chart_var = tk.StringVar(value=analysis.CHARTS[0])
        chart_help = lambda: ("Which chart to show.\n\n" + self.chart_var.get() + ": " +
                              CHART_HELP.get(self.chart_var.get(), ""))
        tip(ttk.Label(ctl, text="Chart:"), chart_help).grid(row=0, column=0, sticky="e")
        tip(ttk.Combobox(ctl, textvariable=self.chart_var, values=analysis.CHARTS,
                         state="readonly", width=26), chart_help).grid(row=0, column=1, sticky="w", **PAD)
        unit_help = ("What to count.\n• visits — bursts of horse photos from one camera less "
                     "than the visit gap apart count as one visit, timed by the first photo. "
                     "Best for attendance.\n• photos — every horse photo counted; closer to "
                     "time spent in view.")
        tip(ttk.Label(ctl, text="Count:"), unit_help).grid(row=0, column=2, sticky="e")
        self.unit_var = tk.StringVar(value="visits")
        tip(ttk.Combobox(ctl, textvariable=self.unit_var, values=["visits", "photos"],
                         state="readonly", width=8), unit_help).grid(row=0, column=3, sticky="w", **PAD)
        from_help = "First day to include (YYYY-MM-DD). Leave blank to start from the earliest photo."
        to_help = "Last day to include (YYYY-MM-DD, inclusive). Leave blank to go to the latest photo."
        tip(ttk.Label(ctl, text="From:"), from_help).grid(row=0, column=4, sticky="e")
        self.from_var = tk.StringVar()
        tip(ttk.Entry(ctl, textvariable=self.from_var, width=11), from_help).grid(row=0, column=5, **PAD)
        tip(ttk.Label(ctl, text="To:"), to_help).grid(row=0, column=6, sticky="e")
        self.to_var = tk.StringVar()
        tip(ttk.Entry(ctl, textvariable=self.to_var, width=11), to_help).grid(row=0, column=7, **PAD)
        ttk.Label(ctl, text="(YYYY-MM-DD, blank = all)", style="Hint.TLabel").grid(row=0, column=8, sticky="w")

        hc_help = ("Confidence (0–1) needed to count a photo as a horse in these charts. Try "
                   "different values here without re-running detection; your review "
                   "decisions always win. Press Update chart to apply.")
        tip(ttk.Label(ctl, text="Horse threshold:"), hc_help).grid(row=1, column=0, sticky="e")
        self.hc_var = tk.StringVar(value=str(self.s["horse_conf"]))
        tip(ttk.Entry(ctl, textvariable=self.hc_var, width=6), hc_help).grid(row=1, column=1, sticky="w", **PAD)
        gap_help = ("Horse photos from one camera closer together than this many minutes are "
                    "one visit. Only affects the 'visits' count. Press Update chart to apply.")
        tip(ttk.Label(ctl, text="Visit gap (min):"), gap_help).grid(row=1, column=2, sticky="e")
        self.gap_var = tk.StringVar(value=str(self.s["visit_gap_min"]))
        tip(ttk.Entry(ctl, textvariable=self.gap_var, width=6), gap_help).grid(row=1, column=3, sticky="w", **PAD)
        self.cam_checks_frame = ttk.Frame(ctl)
        self.cam_checks_frame.grid(row=1, column=4, columnspan=5, sticky="w")
        self.cam_checks = {}
        self._rebuild_cam_checks()

        b = ttk.Frame(f)
        b.pack(fill="x", padx=8)
        tip(ttk.Button(b, text="Update chart", command=self.update_chart, style="Accent.TButton"),
            "Redraw the chart using the dates, threshold, visit gap and cameras chosen "
            "above.").pack(side="left", **PAD)
        tip(ttk.Button(b, text="Save report (all charts + CSV)", command=self.save_report),
            "Save every chart as a PNG plus CSV files (each horse photo, each visit, hourly "
            "counts, per-camera summary) into reports\\<date>, using the current "
            "selection.").pack(side="left", **PAD)
        tip(ttk.Button(b, text="Open reports folder",
                       command=lambda: self.lib and open_folder(self.lib.path("reports"))),
            "Open the folder where saved reports go.").pack(side="left", **PAD)
        self.summary = tk.StringVar()
        tip(ttk.Label(b, textvariable=self.summary),
            "Totals for the current selection: photos checked, photos with horses, and "
            "visits.").pack(side="left", padx=12)

        self.fig = Figure(figsize=(10, 5), dpi=CHART_DPI * self._text_scale())
        self.canvas = FigureCanvasTkAgg(self.fig, master=f)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=6)
        self.chart_var.trace_add("write", lambda *a: self.update_chart())
        self.unit_var.trace_add("write", lambda *a: self.update_chart())

    def _rebuild_cam_checks(self):
        for w in self.cam_checks_frame.winfo_children():
            w.destroy()
        self.cam_checks = {}
        for c in self.s["cameras"]:
            v = tk.BooleanVar(value=True)
            tip(ttk.Checkbutton(self.cam_checks_frame, text=c, variable=v),
                f"Include camera '{c}' in the chart and report. Press Update chart "
                "to apply.").pack(side="left", padx=3)
            self.cam_checks[c] = v

    def _selection(self):
        from . import analysis
        hc = float(self.hc_var.get())
        gap = float(self.gap_var.get())
        start = self.from_var.get().strip() or None
        end = self.to_var.get().strip() or None
        for d in (start, end):
            if d:
                dt.date.fromisoformat(d)
        cams = [c for c, v in self.cam_checks.items() if v.get()]
        df = analysis.load_photos(self.lib, hc)
        df = analysis.filter_df(df, start, end, cams)
        horse = df[df["is_horse"]]
        visits = analysis.make_visits(horse, gap)
        all_cams = list(self.s["cameras"]) + sorted(set(df["camera"]) - set(self.s["cameras"]))
        return df, horse, visits, all_cams

    def update_chart(self):
        if not self.lib:
            return
        from . import analysis
        try:
            df, horse, visits, all_cams = self._selection()
        except ValueError as e:
            messagebox.showerror("Histograms", f"Check the inputs: {e}")
            return
        unit = self.unit_var.get()
        analysis.draw(self.fig, self.chart_var.get(), analysis.events(horse, visits, unit),
                      all_cams, unit)
        self.canvas.draw_idle()
        self.summary.set(f"{len(df):,} photos checked · {len(horse):,} horse photos · "
                         f"{len(visits):,} visits")

    def save_report(self):
        if not self.need_lib():
            return
        from . import analysis
        try:
            df, horse, visits, all_cams = self._selection()
        except ValueError as e:
            messagebox.showerror("Histograms", f"Check the inputs: {e}")
            return
        unit = self.unit_var.get()
        out = analysis.save_report(self.lib, df, horse, visits, all_cams, unit)
        self.log(f"Report saved: {out}")
        open_folder(out)


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
