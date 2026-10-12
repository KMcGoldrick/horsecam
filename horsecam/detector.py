"""Find horses with a YOLO object detector (COCO classes include "horse").

Every image gets one row in `detections` with the best horse confidence, so
thresholds can be changed later in the Analyze tab without re-running the model.

    conf >= horse_conf              -> status "horse"  -> copied to <Cam>/horses/
    review_conf <= conf < horse_conf-> status "review" -> copied (with box) to <Cam>/review/
    conf <  review_conf             -> status "none"
"""
import datetime as dt
import json
import os
import shutil

from PIL import Image, ImageDraw

from .settings import MODELS_DIR


MODEL_URLS = [  # official Ultralytics release assets, newest first
    "https://github.com/ultralytics/assets/releases/download/v8.4.0/{}",
    "https://github.com/ultralytics/assets/releases/download/v8.3.0/{}",
]
MIN_MODEL_BYTES = 1_000_000   # real weights are 5–110 MB; anything smaller is a broken download


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _download(base, dest, log):
    """Plain, non-resuming download to a temp file, renamed only when complete."""
    import requests
    tmp = dest + ".download"
    last = None
    for url in MODEL_URLS:
        url = url.format(base)
        _remove(tmp)
        try:
            log(f"Downloading {base}…")
            with requests.get(url, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            if os.path.getsize(tmp) < MIN_MODEL_BYTES:
                raise IOError("downloaded file is too small")
            os.replace(tmp, dest)
            log(f"Model saved to {dest}")
            return True
        except Exception as e:
            last = e
            _remove(tmp)
    log(f"Download failed: {last}")
    return False


def load_model(name, log=lambda m: None):
    from ultralytics import YOLO  # heavy import, only when detecting
    if os.path.isfile(name):      # a full path to a .pt file you downloaded yourself
        return YOLO(name)
    os.makedirs(MODELS_DIR, exist_ok=True)
    base = os.path.basename(name)
    local = os.path.join(MODELS_DIR, base)

    # Clear out half-finished downloads from earlier attempts (they cause
    # "416 Range Not Satisfiable" when Ultralytics tries to resume them).
    for stale in (local, os.path.join(os.getcwd(), base)):
        if os.path.isfile(stale) and os.path.getsize(stale) < MIN_MODEL_BYTES:
            _remove(stale)

    if os.path.isfile(local):
        try:
            return YOLO(local)
        except Exception:
            log(f"{local} is damaged — downloading it again.")
            _remove(local)

    if _download(base, local, log):
        return YOLO(local)
    try:
        return YOLO(local)        # last resort: Ultralytics' own downloader
    except Exception:
        _remove(local)
        raise RuntimeError(
            f"Couldn't download the model {base}.\n\n"
            f"Download it in your web browser from\n{MODEL_URLS[0].format(base)}\n"
            f"and save it as\n{local}\nthen press Find horses again.")


def make_yolo_predict(settings, log=lambda m: None):
    """Returns predict(paths) -> list of [[x1,y1,x2,y2,conf], ...] (or None on error)."""
    model = load_model(settings["model"], log)
    horse_ids = [k for k, v in model.names.items() if v == "horse"]
    if not horse_ids:
        raise RuntimeError(f"Model {settings['model']} has no 'horse' class.")
    kw = dict(conf=float(settings["review_conf"]), classes=horse_ids,
              imgsz=int(settings["imgsz"]), verbose=False)
    if settings.get("device"):
        kw["device"] = settings["device"]

    def boxes_of(r):
        if r.boxes is None or len(r.boxes) == 0:
            return []
        xyxy = r.boxes.xyxy.tolist()
        conf = r.boxes.conf.tolist()
        return [[*map(float, b), float(c)] for b, c in zip(xyxy, conf)]

    def predict(paths):
        try:
            return [boxes_of(r) for r in model.predict(paths, **kw)]
        except Exception:
            out = []                      # one bad file shouldn't sink the batch
            for p in paths:
                try:
                    out.append(boxes_of(model.predict(p, **kw)[0]))
                except Exception:
                    out.append(None)
            return out

    return predict


def _copy_horse(lib, rel, fname, camera):
    d = lib.horses_dir(camera)
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, fname)
    if not os.path.exists(dst):
        shutil.copy2(lib.abs(rel), dst)


def _write_review(lib, rel, fname, camera, boxes):
    d = lib.review_dir(camera)
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, fname)
    if os.path.exists(dst):
        return
    try:
        with Image.open(lib.abs(rel)) as im:
            im = im.convert("RGB")
            dr = ImageDraw.Draw(im)
            width = max(3, im.width // 400)
            for x1, y1, x2, y2, c in boxes:
                dr.rectangle([x1, y1, x2, y2], outline=(255, 200, 0), width=width)
                dr.text((x1 + 4, max(0, y1 - 14)), f"horse? {c:.2f}", fill=(255, 200, 0))
            im.save(dst, quality=90)
    except Exception:
        shutil.copy2(lib.abs(rel), dst)


def pending_count(lib):
    return lib.db.scalar(
        "SELECT COUNT(*) FROM photos p LEFT JOIN detections d ON d.photo_id=p.id "
        "WHERE p.kind='image' AND d.photo_id IS NULL")


def run_detection(lib, settings, predict=None, progress=None, stop=None, log=None):
    """Process every image that has no detection row yet. Resumable."""
    progress = progress or (lambda done, total, msg="": None)
    log = log or (lambda msg: None)
    if predict is None:
        log(f"Loading model {settings['model']} (first run downloads it)…")
        predict = make_yolo_predict(settings, log)

    rows = lib.db.query(
        "SELECT p.id, p.rel_path, p.fname, p.camera FROM photos p "
        "LEFT JOIN detections d ON d.photo_id=p.id "
        "WHERE p.kind='image' AND d.photo_id IS NULL ORDER BY p.camera, p.taken")
    hc, rc = float(settings["horse_conf"]), float(settings["review_conf"])
    batch = max(1, int(settings.get("batch", 8)))
    stats = {"processed": 0, "horse": 0, "review": 0, "none": 0, "error": 0}
    total = len(rows)
    log(f"{total} photos to check.")

    for i in range(0, total, batch):
        if stop is not None and stop.is_set():
            log("Detection paused — run again to continue where it left off.")
            break
        chunk = rows[i:i + batch]
        results = predict([lib.abs(r[1]) for r in chunk])
        now = dt.datetime.now().isoformat(sep=" ", timespec="seconds")
        for (pid, rel, fname, cam), boxes in zip(chunk, results):
            if boxes is None:
                status, best, n = "error", 0.0, 0
                boxes = []
            else:
                best = max((b[4] for b in boxes), default=0.0)
                n = sum(1 for b in boxes if b[4] >= hc)
                status = "horse" if best >= hc else "review" if best >= rc else "none"
            try:
                if status == "horse":
                    _copy_horse(lib, rel, fname, cam)
                elif status == "review":
                    _write_review(lib, rel, fname, cam, boxes)
            except Exception as e:
                log(f"Could not copy {fname}: {e}")
            lib.db.execute(
                "INSERT OR REPLACE INTO detections(photo_id,model,horse_conf,n_horses,"
                "boxes,status,processed) VALUES(?,?,?,?,?,?,?)",
                (pid, settings.get("model", "custom"), best, n,
                 json.dumps([[round(v, 3) for v in b] for b in boxes]), status, now))
            stats[status] += 1
            stats["processed"] += 1
        progress(min(i + batch, total), total,
                 f"Checked {min(i + batch, total)}/{total} — horses {stats['horse']}, "
                 f"review {stats['review']}")
    return stats


def apply_review(lib):
    """Read the user's manual sorting and record it as overrides.

    <Cam>/review/yes/          -> horse   (original also copied into <Cam>/horses/)
    <Cam>/review/no/           -> not horse
    <Cam>/horses/_not_horse/   -> not horse
    """
    now = dt.datetime.now().isoformat(sep=" ", timespec="seconds")
    counts = {"yes": 0, "no": 0, "unknown": 0}
    for cam in lib.cameras_in_db():
        lib.ensure_cam_dirs(cam)
        sources = [(lib.cam_dir(cam, "review", "yes"), 1),
                   (lib.cam_dir(cam, "review", "no"), 0),
                   (lib.not_horse_dir(cam), 0)]
        for folder, verdict in sources:
            for d, _, names in os.walk(folder):
                for n in names:
                    row = lib.db.query(
                        "SELECT id, rel_path, camera FROM photos WHERE fname=?", (n,))
                    if not row:
                        counts["unknown"] += 1
                        continue
                    pid, rel, pcam = row[0]
                    lib.db.execute(
                        "INSERT OR REPLACE INTO manual(photo_id,horse,set_at) VALUES(?,?,?)",
                        (pid, verdict, now))
                    if verdict == 1:
                        _copy_horse(lib, rel, n, pcam)
                    counts["yes" if verdict else "no"] += 1
    return counts
