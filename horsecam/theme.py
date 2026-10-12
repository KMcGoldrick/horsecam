"""Color themes for HorseCam.  Pick one on the Settings tab ("Color theme")."""
import tkinter as tk
from tkinter import ttk

# Each theme:
#   bg      window background          panel  tabs / plain buttons
#   accent  main buttons, selected tab accent2 progress bar, highlights
#   dark    accent when pressed / frame titles
#   text    normal text                hint   grey help text
#   field   entry boxes                border lines
#   header  title strip (None = no strip)
#   chart   (surface, ink, ink2, grid) for the Histograms chart
THEMES = {
    "Meadow": dict(
        bg="#eef4e6", panel="#dce9cd", accent="#3f7d3a", accent2="#e0a030",
        dark="#2c5a28", text="#1f2a1c", hint="#5b6b52", field="#ffffff",
        border="#b7c9a3", header="#3f7d3a",
        chart=("#fbfdf8", "#1f2a1c", "#5b6b52", "#dfe8d4")),
    "Sunset": dict(
        bg="#fcf3e9", panel="#f4dcc3", accent="#d0602a", accent2="#7a4fa0",
        dark="#9e4416", text="#3a2416", hint="#7a5a45", field="#ffffff",
        border="#e3c2a3", header="#b84e1f",
        chart=("#fffaf4", "#3a2416", "#7a5a45", "#f0dfcd")),
    "Lake": dict(
        bg="#eaf2f8", panel="#d2e3f0", accent="#1f6fa8", accent2="#27a99a",
        dark="#14507c", text="#14283a", hint="#4f6578", field="#ffffff",
        border="#b2cadf", header="#1f6fa8",
        chart=("#f8fbfd", "#14283a", "#4f6578", "#dbe6ef")),
    "Night": dict(
        bg="#1f242b", panel="#2c333c", accent="#e9a23b", accent2="#4fb3a9",
        dark="#c4841f", text="#ecebe8", hint="#a3abb5", field="#2a3139",
        border="#3d4651", header="#151a20",
        chart=("#1f242b", "#ecebe8", "#a3abb5", "#3a424c")),
    "Classic": None,   # the original plain Windows look
}
NAMES = list(THEMES)
DEFAULT = "Meadow"

_classic_theme = None


def get(name):
    return THEMES.get(name) or None


def apply(root, name):
    """Style every ttk widget for theme `name`. Returns the theme dict (None for Classic)."""
    global _classic_theme
    st = ttk.Style(root)
    if _classic_theme is None:
        _classic_theme = st.theme_use()
    t = THEMES.get(name, THEMES[DEFAULT]) if name in THEMES else THEMES[DEFAULT]

    if t is None:                                   # Classic
        st.theme_use(_classic_theme)
        st.configure("Accent.TButton")
        st.configure("Hint.TLabel", foreground="#52514e")
        st.configure("Header.TFrame")
        root.configure(bg=st.lookup("TFrame", "background") or "SystemButtonFace")
        _chart(("#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1"))
        return None

    st.theme_use("clam")
    bg, panel, acc, acc2, dark = t["bg"], t["panel"], t["accent"], t["accent2"], t["dark"]
    text, hint, field, border = t["text"], t["hint"], t["field"], t["border"]
    on_acc = "#1a1a1a" if name == "Night" else "#ffffff"

    st.configure(".", background=bg, foreground=text, fieldbackground=field,
                 bordercolor=border, lightcolor=bg, darkcolor=border,
                 troughcolor=panel, selectbackground=acc, selectforeground=on_acc,
                 insertcolor=text, focuscolor=acc)
    st.configure("TFrame", background=bg)
    st.configure("TLabel", background=bg, foreground=text)
    st.configure("Hint.TLabel", background=bg, foreground=hint)

    st.configure("TNotebook", background=bg, bordercolor=border, tabmargins=(6, 6, 6, 0))
    st.configure("TNotebook.Tab", background=panel, foreground=text, padding=(14, 6),
                 bordercolor=border, lightcolor=panel)
    st.map("TNotebook.Tab",
           background=[("selected", acc), ("active", border)],
           foreground=[("selected", on_acc)],
           lightcolor=[("selected", acc)],
           expand=[("selected", (1, 1, 1, 0))])

    st.configure("TButton", background=panel, foreground=text, bordercolor=border,
                 lightcolor=panel, darkcolor=panel, padding=(10, 4))
    st.map("TButton",
           background=[("disabled", bg), ("pressed", border), ("active", border)],
           foreground=[("disabled", hint)],
           lightcolor=[("active", border)], darkcolor=[("active", border)])
    st.configure("Accent.TButton", background=acc, foreground=on_acc, bordercolor=dark,
                 lightcolor=acc, darkcolor=acc, padding=(12, 4))
    st.map("Accent.TButton",
           background=[("disabled", panel), ("pressed", dark), ("active", dark)],
           foreground=[("disabled", hint)],
           lightcolor=[("active", dark), ("disabled", panel)],
           darkcolor=[("active", dark), ("disabled", panel)])

    st.configure("TLabelframe", background=bg, bordercolor=border, lightcolor=bg, darkcolor=bg)
    st.configure("TLabelframe.Label", background=bg, foreground=dark if name != "Night" else acc,
                 font="HCBold")

    st.configure("TEntry", fieldbackground=field, foreground=text, bordercolor=border,
                 lightcolor=field)
    st.map("TEntry", bordercolor=[("focus", acc)], lightcolor=[("focus", acc)])
    st.configure("TCombobox", fieldbackground=field, foreground=text, background=panel,
                 arrowcolor=text, bordercolor=border, lightcolor=field, darkcolor=field)
    st.map("TCombobox",
           fieldbackground=[("readonly", field)],
           selectbackground=[("readonly", field)],
           selectforeground=[("readonly", text)],
           bordercolor=[("focus", acc)], background=[("active", border)])
    root.option_add("*TCombobox*Listbox.background", field)
    root.option_add("*TCombobox*Listbox.foreground", text)
    root.option_add("*TCombobox*Listbox.selectBackground", acc)
    root.option_add("*TCombobox*Listbox.selectForeground", on_acc)

    st.configure("TCheckbutton", background=bg, foreground=text, indicatorbackground=field,
                 indicatorforeground=acc)
    st.map("TCheckbutton", background=[("active", bg)],
           indicatorbackground=[("selected", acc)], indicatorforeground=[("selected", on_acc)])
    st.configure("Horizontal.TProgressbar", background=acc2, troughcolor=panel,
                 bordercolor=border, lightcolor=acc2, darkcolor=acc2)
    st.configure("Header.TFrame", background=t["header"])
    st.configure("Header.TLabel", background=t["header"], foreground="#ffffff",
                 font="HCTitle")
    st.configure("HeaderSub.TLabel", background=t["header"],
                 foreground="#ffffff" if name != "Night" else t["hint"])
    root.configure(bg=bg)
    _chart(t["chart"])
    return t


def _chart(c):
    """Point the Histograms chart colors at the theme."""
    from . import analysis
    analysis.SURFACE, analysis.INK, analysis.INK2, analysis.GRID = c


def style_text(widget, t):
    """Color a plain tk.Text box (the log) to match."""
    if t is None:
        widget.configure(background="white", foreground="black", insertbackground="black")
    else:
        widget.configure(background=t["field"], foreground=t["text"],
                         insertbackground=t["text"], highlightthickness=1,
                         highlightbackground=t["border"], highlightcolor=t["accent"],
                         relief="flat")
