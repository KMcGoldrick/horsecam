"""Hover help: small yellow pop-ups that appear when the mouse rests on a control."""
import tkinter as tk

DELAY_MS = 500      # how long the mouse must rest before the tip appears
WRAP_PX = 380       # tip width before text wraps


class _TipWindow:
    """One borderless pop-up, shared by every tip on a widget."""

    def __init__(self, owner):
        self.owner = owner
        self.win = None

    def show(self, text, x, y):
        self.hide()
        if not text:
            return
        w = tk.Toplevel(self.owner)
        w.wm_overrideredirect(True)
        try:
            w.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        tk.Label(w, text=text, justify="left", wraplength=WRAP_PX,
                 background="#ffffe1", foreground="#1f1f1f", relief="solid",
                 borderwidth=1, padx=6, pady=4, font="TkTooltipFont").pack()
        w.update_idletasks()
        # keep the tip on screen
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        tw, th = w.winfo_reqwidth(), w.winfo_reqheight()
        x = min(x, sw - tw - 4)
        if y + th > sh - 4:
            y = y - th - 32
        w.wm_geometry(f"+{max(0, x)}+{max(0, y)}")
        self.win = w

    def hide(self):
        if self.win is not None:
            self.win.destroy()
            self.win = None


class ToolTip:
    """Attach hover help to a widget.

    text may be a string or a function returning a string (for tips that
    change, e.g. describing the currently selected item).
    """

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = _TipWindow(widget)
        self._after = None
        widget.bind("<Enter>", self._enter, add="+")
        widget.bind("<Leave>", self._leave, add="+")
        widget.bind("<ButtonPress>", self._leave, add="+")
        widget.bind("<Destroy>", self._leave, add="+")

    def _enter(self, _e=None):
        self._cancel()
        self._after = self.widget.after(DELAY_MS, self._show)

    def _leave(self, _e=None):
        self._cancel()
        self.tip.hide()

    def _cancel(self):
        if self._after:
            try:
                self.widget.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    def _show(self):
        self._after = None
        text = self.text() if callable(self.text) else self.text
        x = self.widget.winfo_pointerx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip.show(text, x, y)


def tip(widget, text):
    """Add hover help to widget and return the widget (so it can be chained)."""
    ToolTip(widget, text)
    return widget


class NotebookTips:
    """Hover help on the tab headers of a ttk.Notebook: {tab_index: text}."""

    def __init__(self, nb, texts):
        self.nb = nb
        self.texts = texts
        self.tip = _TipWindow(nb)
        self._after = None
        self._tab = None
        nb.bind("<Motion>", self._motion, add="+")
        nb.bind("<Leave>", self._leave, add="+")
        nb.bind("<ButtonPress>", self._leave, add="+")

    def _tab_at(self, x, y):
        try:
            return self.nb.index(f"@{x},{y}")
        except tk.TclError:
            return None

    def _motion(self, e):
        tab = self._tab_at(e.x, e.y)
        # only react over the tab headers, not the page body
        if tab is not None and e.y > 30:
            tab = None
        if tab == self._tab:
            return
        self._leave()
        self._tab = tab
        if tab is not None and tab in self.texts:
            self._after = self.nb.after(DELAY_MS, self._show)

    def _show(self):
        self._after = None
        if self._tab is None:
            return
        x = self.nb.winfo_pointerx() + 12
        y = self.nb.winfo_pointery() + 20
        self.tip.show(self.texts[self._tab], x, y)

    def _leave(self, _e=None):
        if self._after:
            try:
                self.nb.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None
        self._tab = None
        self.tip.hide()
