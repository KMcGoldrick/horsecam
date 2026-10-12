"""Turn detections into horse-attendance tables and histograms.

Counting unit
-------------
Trail cams fire bursts, so one horse standing in front of a camera for 20
minutes can produce 100+ photos.  "Visits" groups a camera's horse photos into
one event whenever consecutive photos are less than `gap_min` minutes apart;
the visit is timed by its first photo.  "Photos" counts every horse photo.
Visits is usually the better attendance measure; photos is closer to
"time spent in view".
"""
import os

import pandas as pd
from matplotlib.figure import Figure

# Fixed categorical order (camera keeps its color in every chart).
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4",
          "#008300", "#6250d6", "#e34948"]
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"

CHARTS = [
    "Hour of day (all cameras)",
    "Hour of day (per camera)",
    "Daily timeline",
    "Camera × hour heatmap",
    "Day of week",
]


def load_photos(lib, horse_conf):
    """One row per analysed image with an is_horse flag (manual review wins)."""
    rows = lib.db.query(
        "SELECT p.id, p.camera, p.taken, p.fname, p.rel_path, d.horse_conf, d.n_horses, "
        "d.status, m.horse FROM photos p "
        "JOIN detections d ON d.photo_id=p.id "
        "LEFT JOIN manual m ON m.photo_id=p.id WHERE p.kind='image'")
    df = pd.DataFrame(rows, columns=["id", "camera", "taken", "fname", "rel_path",
                                     "horse_conf", "n_horses", "status", "manual"])
    df["taken"] = pd.to_datetime(df["taken"])
    model_says = df["horse_conf"].fillna(0) >= float(horse_conf)
    df["is_horse"] = df["manual"].map({1: True, 0: False}).where(
        df["manual"].notna(), model_says).astype(bool)
    df["n_horses"] = df["n_horses"].fillna(0).astype(int)
    df.loc[df["is_horse"] & (df["n_horses"] < 1), "n_horses"] = 1
    return df


def filter_df(df, start=None, end=None, cameras=None):
    if start:
        df = df[df["taken"] >= pd.Timestamp(start)]
    if end:
        df = df[df["taken"] < pd.Timestamp(end) + pd.Timedelta(days=1)]
    if cameras:
        df = df[df["camera"].isin(cameras)]
    return df


def make_visits(horse_df, gap_min):
    cols = ["camera", "visit", "start", "end", "minutes", "photos", "max_horses"]
    if horse_df.empty:
        return pd.DataFrame(columns=cols)
    out = []
    gap = pd.Timedelta(minutes=float(gap_min))
    for cam, g in horse_df.sort_values("taken").groupby("camera"):
        vid = (g["taken"].diff() > gap).cumsum()
        for v, gv in g.groupby(vid):
            s, e = gv["taken"].min(), gv["taken"].max()
            out.append([cam, int(v) + 1, s, e, round((e - s).total_seconds() / 60, 1),
                        len(gv), int(gv["n_horses"].max())])
    return pd.DataFrame(out, columns=cols)


def events(horse_df, visits, unit):
    """(camera, time) table for whatever we are counting."""
    if unit == "visits":
        return visits.rename(columns={"start": "t"})[["camera", "t"]]
    return horse_df.rename(columns={"taken": "t"})[["camera", "t"]]


def _style(ax, title, ylabel):
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", color=INK, fontsize=11, fontweight="bold")
    ax.set_ylabel(ylabel, color=INK2)
    ax.tick_params(colors=INK2, labelsize=8.5)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _cam_colors(all_cams):
    return {c: SERIES[i % len(SERIES)] for i, c in enumerate(all_cams)}


def _stacked(ax, table, colors, x, width=0.85):
    bottom = None
    for cam in table.columns:
        vals = table[cam].values
        ax.bar(x, vals, width, bottom=bottom, color=colors[cam], label=cam,
               edgecolor=SURFACE, linewidth=1)
        bottom = vals if bottom is None else bottom + vals


def draw(fig, chart, ev, all_cams, unit, subtitle=""):
    """Draw one chart onto a matplotlib Figure."""
    fig.clear()
    fig.patch.set_facecolor(SURFACE)
    colors = _cam_colors(all_cams)
    ylabel = "Horse visits" if unit == "visits" else "Horse photos"
    cams = [c for c in all_cams if c in set(ev["camera"])]

    if ev.empty:
        ax = fig.add_subplot(111)
        ax.axis("off")
        ax.text(0.5, 0.5, "No horse detections in this selection",
                ha="center", va="center", color=INK2, fontsize=12)
        return

    if chart == "Hour of day (all cameras)":
        ax = fig.add_subplot(111)
        t = (ev.assign(h=ev["t"].dt.hour).pivot_table(index="h", columns="camera",
             aggfunc="size", fill_value=0).reindex(range(24), fill_value=0))
        t = t[[c for c in cams if c in t.columns]]
        _stacked(ax, t, colors, range(24))
        ax.set_xticks(range(24))
        ax.set_xticklabels([f"{h:02d}" for h in range(24)])
        ax.set_xlabel("Hour of day (camera clock)", color=INK2)
        _style(ax, f"Horse attendance by hour of day{subtitle}", ylabel)
        if len(cams) > 1:
            ax.legend(frameon=False, fontsize=8.5, ncol=min(6, len(cams)),
                      loc="upper left", labelcolor=INK2)

    elif chart == "Hour of day (per camera)":
        n = len(cams)
        cols = 3 if n > 4 else 2 if n > 1 else 1
        rows = -(-n // cols)
        axes = fig.subplots(rows, cols, sharex=True, sharey=True, squeeze=False)
        for i, cam in enumerate(cams):
            ax = axes[i // cols][i % cols]
            h = ev[ev["camera"] == cam]["t"].dt.hour.value_counts().reindex(range(24), fill_value=0)
            ax.bar(range(24), h.values, 0.85, color=colors[cam])
            _style(ax, f"{cam}  (n={int(h.sum())})", ylabel if i % cols == 0 else "")
            ax.set_xticks(range(0, 24, 3))
        for j in range(n, rows * cols):
            axes[j // cols][j % cols].axis("off")
        fig.suptitle(f"Hour of day by camera{subtitle}", x=0.01, ha="left",
                     color=INK, fontsize=11, fontweight="bold")

    elif chart == "Daily timeline":
        ax = fig.add_subplot(111)
        d = ev.assign(day=ev["t"].dt.normalize())
        days = pd.date_range(d["day"].min(), d["day"].max(), freq="D")
        t = d.pivot_table(index="day", columns="camera", aggfunc="size",
                          fill_value=0).reindex(days, fill_value=0)
        t = t[[c for c in cams if c in t.columns]]
        _stacked(ax, t, colors, t.index, width=0.85)
        ax.set_xlabel("Date", color=INK2)
        _style(ax, f"Horse attendance per day{subtitle}", ylabel)
        fig.autofmt_xdate()
        if len(cams) > 1:
            ax.legend(frameon=False, fontsize=8.5, ncol=min(6, len(cams)),
                      loc="upper left", labelcolor=INK2)

    elif chart == "Camera × hour heatmap":
        ax = fig.add_subplot(111)
        t = (ev.assign(h=ev["t"].dt.hour).pivot_table(index="camera", columns="h",
             aggfunc="size", fill_value=0).reindex(columns=range(24), fill_value=0))
        t = t.reindex(cams)
        im = ax.imshow(t.values, aspect="auto", cmap="Blues", vmin=0)
        ax.set_yticks(range(len(cams)))
        ax.set_yticklabels(cams)
        ax.set_xticks(range(24))
        ax.set_xticklabels([f"{h:02d}" for h in range(24)])
        vmax = t.values.max() or 1
        for r in range(t.shape[0]):
            for c in range(24):
                v = int(t.values[r, c])
                if v:
                    ax.text(c, r, v, ha="center", va="center", fontsize=7,
                            color="white" if v > vmax * 0.55 else INK)
        _style(ax, f"Camera × hour of day{subtitle}", "")
        ax.grid(False)
        ax.set_xlabel("Hour of day (camera clock)", color=INK2)
        fig.colorbar(im, ax=ax, label=ylabel, shrink=0.8)

    elif chart == "Day of week":
        ax = fig.add_subplot(111)
        names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        t = (ev.assign(w=ev["t"].dt.dayofweek).pivot_table(index="w", columns="camera",
             aggfunc="size", fill_value=0).reindex(range(7), fill_value=0))
        t = t[[c for c in cams if c in t.columns]]
        _stacked(ax, t, colors, range(7), width=0.7)
        ax.set_xticks(range(7))
        ax.set_xticklabels(names)
        _style(ax, f"Horse attendance by day of week{subtitle}", ylabel)
        if len(cams) > 1:
            ax.legend(frameon=False, fontsize=8.5, ncol=min(6, len(cams)),
                      loc="upper left", labelcolor=INK2)

    fig.tight_layout()


def save_report(lib, df_sel, horse_df, visits, all_cams, unit, label=""):
    """Write every chart (PNG) plus the underlying CSVs to reports/<timestamp>/."""
    stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    out = lib.path("reports", stamp + (f"_{label}" if label else ""))
    os.makedirs(out, exist_ok=True)
    ev = events(horse_df, visits, unit)
    for chart in CHARTS:
        fig = Figure(figsize=(11, 6), dpi=150)
        draw(fig, chart, ev, all_cams, unit)
        safe = "".join(ch if ch.isalnum() else "_" for ch in chart).strip("_")
        fig.savefig(os.path.join(out, f"{safe}.png"), facecolor=SURFACE)

    horse_df[["camera", "taken", "fname", "rel_path", "horse_conf", "n_horses",
              "manual"]].sort_values(["camera", "taken"]).to_csv(
        os.path.join(out, "horse_photos.csv"), index=False)
    visits.to_csv(os.path.join(out, "horse_visits.csv"), index=False)
    hourly = (ev.assign(hour=ev["t"].dt.hour).pivot_table(index="hour", columns="camera",
              aggfunc="size", fill_value=0).reindex(range(24), fill_value=0))
    hourly.to_csv(os.path.join(out, f"hourly_{unit}.csv"))
    # effort: days each camera produced any photo at all (rough uptime check)
    eff = (df_sel.assign(day=df_sel["taken"].dt.date).groupby("camera")
           .agg(photos=("id", "size"), days_with_photos=("day", "nunique"),
                first=("taken", "min"), last=("taken", "max")))
    eff["horse_photos"] = horse_df.groupby("camera").size()
    eff["horse_visits"] = visits.groupby("camera").size() if not visits.empty else 0
    eff.fillna(0).to_csv(os.path.join(out, "camera_summary.csv"))
    return out
