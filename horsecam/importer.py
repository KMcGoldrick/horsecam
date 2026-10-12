"""Copy photos off an SD card into the library, verified and de-duplicated.

* Every file is hashed (SHA-1) while it is copied; the destination is re-read
  and re-hashed before the original is considered safely imported.
* A file whose content is already in the library is skipped, so re-importing
  a card (or a card that was not formatted between swaps) is harmless.
* Files are renamed  <Cam>_<YYYYMMDD>_<HHMMSS>_<original name>  because trail
  cams restart their IMG_0001 numbering every time a card is formatted.
* Nothing on the card is changed or deleted. Format the card in the camera.
"""
import csv
import datetime as dt
import hashlib
import os
import shutil
import uuid

from PIL import Image

from .library import CAM_OUTPUT_DIRS

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
VIDEO_EXT = {".mp4", ".avi", ".mov", ".mts", ".m4v", ".3gp"}
SKIP_DIRS = {"System Volume Information", "$RECYCLE.BIN", "LOST.DIR"}
BUF = 4 * 1024 * 1024


def scan_card(root, exclude=()):
    """All image/video files under root, sorted by path.

    `exclude` names folders to skip anywhere in the tree (e.g. horses, review)."""
    out = []
    skip = SKIP_DIRS | set(exclude)
    for d, dirs, names in os.walk(root):
        dirs[:] = [x for x in dirs if x not in skip and not x.startswith(".")]
        for n in names:
            if n.startswith("._"):
                continue
            ext = os.path.splitext(n)[1].lower()
            if ext in IMAGE_EXT or ext in VIDEO_EXT:
                out.append(os.path.join(d, n))
    out.sort()
    return out


def exif_time(path):
    """DateTimeOriginal (or DateTime) from EXIF, as a naive local datetime."""
    try:
        with Image.open(path) as im:
            ex = im.getexif()
            s = ex.get_ifd(0x8769).get(36867) or ex.get(306)
        if s:
            s = str(s).strip().rstrip("\x00")[:19]
            return dt.datetime.strptime(s, "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return None


def file_time(path):
    t = exif_time(path) if os.path.splitext(path)[1].lower() in IMAGE_EXT else None
    if t:
        return t, "exif"
    return dt.datetime.fromtimestamp(os.path.getmtime(path)).replace(microsecond=0), "mtime"


def summarize_card(root, files=None, sample=40):
    """Quick preview: counts, size, and approximate date range (sampled)."""
    files = files if files is not None else scan_card(root)
    imgs = [f for f in files if os.path.splitext(f)[1].lower() in IMAGE_EXT]
    total = sum(os.path.getsize(f) for f in files)
    times = []
    if imgs:
        step = max(1, len(imgs) // sample)
        picks = imgs[::step] + [imgs[-1]]
        times = [t for t in (exif_time(p) for p in picks) if t]
    return {
        "files": len(files),
        "images": len(imgs),
        "videos": len(files) - len(imgs),
        "bytes": total,
        "first": min(times) if times else None,
        "last": max(times) if times else None,
    }


def _sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(BUF)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _copy_with_hash(src, dst):
    h = hashlib.sha1()
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        while True:
            chunk = fi.read(BUF)
            if not chunk:
                break
            h.update(chunk)
            fo.write(chunk)
    shutil.copystat(src, dst)
    return h.hexdigest()


def _unique(path):
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    i = 2
    while os.path.exists(f"{stem}_{i}{ext}"):
        i += 1
    return f"{stem}_{i}{ext}"


def import_card(lib, card_root, camera, card_label="", files=None,
                progress=None, stop=None, log=None):
    """Copy everything from card_root into lib/raw/<camera>/.  Returns stats."""
    progress = progress or (lambda done, total, msg="": None)
    log = log or (lambda msg: None)
    files = files if files is not None else scan_card(card_root)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = lib.path("logs", f"import_{stamp}_{camera}.csv")
    stats = {"copied": 0, "duplicate": 0, "failed": 0, "bytes": 0}
    incoming = lib.path("_incoming")

    with open(log_path, "w", newline="", encoding="utf-8") as lf:
        w = csv.writer(lf)
        w.writerow(["source", "result", "library_path", "taken", "time_source", "sha1"])
        for i, src in enumerate(files, 1):
            if stop is not None and stop.is_set():
                log("Import stopped by user.")
                break
            tmp = os.path.join(incoming, uuid.uuid4().hex + ".part")
            try:
                sha = _copy_with_hash(src, tmp)
                if lib.db.scalar("SELECT id FROM photos WHERE sha1=?", (sha,)):
                    os.remove(tmp)
                    stats["duplicate"] += 1
                    w.writerow([src, "duplicate", "", "", "", sha])
                    progress(i, len(files), f"{camera}: {i}/{len(files)}")
                    continue
                if _sha1(tmp) != sha or os.path.getsize(tmp) != os.path.getsize(src):
                    raise IOError("verification failed (copy does not match card)")

                ext = os.path.splitext(src)[1].lower()
                kind = "image" if ext in IMAGE_EXT else "video"
                taken, tsrc = (exif_time(tmp), "exif") if kind == "image" else (None, "")
                if taken is None:
                    taken = dt.datetime.fromtimestamp(os.path.getmtime(src)).replace(microsecond=0)
                    tsrc = "mtime"

                orig = os.path.basename(src)
                fname = f"{camera}_{taken:%Y%m%d_%H%M%S}_{orig}"
                dest_dir = lib.cam_dir(camera, "photos", f"{taken:%Y-%m}")
                os.makedirs(dest_dir, exist_ok=True)
                dest = _unique(os.path.join(dest_dir, fname))
                os.replace(tmp, dest)
                rel = os.path.relpath(dest, lib.root)

                lib.db.execute(
                    "INSERT INTO photos(sha1,camera,kind,taken,time_source,rel_path,fname,"
                    "orig_name,card_label,size,imported) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (sha, camera, kind, taken.isoformat(sep=" "), tsrc, rel,
                     os.path.basename(dest), orig, card_label, os.path.getsize(dest),
                     dt.datetime.now().isoformat(sep=" ", timespec="seconds")))
                stats["copied"] += 1
                stats["bytes"] += os.path.getsize(dest)
                w.writerow([src, "copied", rel, taken.isoformat(sep=" "), tsrc, sha])
            except Exception as e:  # keep going; report at the end
                stats["failed"] += 1
                w.writerow([src, f"FAILED: {e}", "", "", "", ""])
                log(f"FAILED {src}: {e}")
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
            progress(i, len(files), f"{camera}: {i}/{len(files)}")

    stats["log"] = log_path
    lib.ensure_cam_dirs(camera)
    return stats


def index_folder(lib, camera, folder, progress=None, stop=None, log=None,
                 exclude=tuple(CAM_OUTPUT_DIRS)):
    """Catalog photos that are already on the hard drive, WITHOUT copying them.

    Used for camera folders you copied yourself.  Files already in the catalog
    (same path) are skipped quickly; files whose content is already cataloged
    elsewhere (e.g. the same card copied twice) are logged as duplicates and
    left out of the counts.
    """
    progress = progress or (lambda done, total, msg="": None)
    log = log or (lambda msg: None)
    files = scan_card(folder, exclude=exclude)
    known = {r[0] for r in lib.db.query(
        "SELECT rel_path FROM photos WHERE camera=?", (camera,))}
    known_dups = {r[0] for r in lib.db.query("SELECT rel_path FROM dup_paths")}
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = lib.path("logs", f"index_{stamp}_{camera}.csv")
    stats = {"added": 0, "already": 0, "duplicate": 0, "failed": 0, "files": len(files)}
    now = dt.datetime.now().isoformat(sep=" ", timespec="seconds")

    with open(log_path, "w", newline="", encoding="utf-8") as lf:
        w = csv.writer(lf)
        w.writerow(["path", "result", "taken", "time_source", "sha1"])
        for i, path in enumerate(files, 1):
            if stop is not None and stop.is_set():
                log("Indexing stopped by user — run it again to continue.")
                break
            rel = os.path.relpath(path, lib.root)
            if rel in known:
                stats["already"] += 1
            elif rel in known_dups:
                stats["duplicate"] += 1
            else:
                try:
                    sha = _sha1(path)
                    dup = lib.db.query("SELECT rel_path FROM photos WHERE sha1=?", (sha,))
                    if dup:
                        stats["duplicate"] += 1
                        w.writerow([path, f"duplicate of {dup[0][0]}", "", "", sha])
                        lib.db.execute("INSERT OR IGNORE INTO dup_paths VALUES(?,?)", (rel, sha))
                    else:
                        ext = os.path.splitext(path)[1].lower()
                        kind = "image" if ext in IMAGE_EXT else "video"
                        taken, tsrc = file_time(path)
                        lib.db.execute(
                            "INSERT INTO photos(sha1,camera,kind,taken,time_source,rel_path,"
                            "fname,orig_name,card_label,size,imported) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (sha, camera, kind, taken.isoformat(sep=" "), tsrc, rel,
                             _unique_fname(lib, review_name(camera, taken, path)),
                             os.path.basename(path),
                             "indexed", os.path.getsize(path), now))
                        stats["added"] += 1
                        w.writerow([path, "added", taken.isoformat(sep=" "), tsrc, sha])
                except Exception as e:
                    stats["failed"] += 1
                    w.writerow([path, f"FAILED: {e}", "", "", ""])
                    log(f"FAILED {path}: {e}")
            if i % 25 == 0 or i == len(files):
                progress(i, len(files), f"Indexing {camera}: {i:,}/{len(files):,}")

    lib.ensure_cam_dirs(camera)
    stats["log"] = log_path
    return stats


def _unique_fname(lib, name):
    stem, ext = os.path.splitext(name)
    cand, i = name, 2
    while lib.db.scalar("SELECT 1 FROM photos WHERE fname=?", (cand,)):
        cand, i = f"{stem}_{i}{ext}", i + 1
    return cand


def review_name(camera, taken, path):
    """Unique, sortable name used for the copies in horses/ and review/.

    Includes the source sub-folder (e.g. 100MEDIA) because trail cams reuse
    IMG_0001 in every folder and after every format."""
    parent = os.path.basename(os.path.dirname(path))
    return f"{camera}_{taken:%Y%m%d_%H%M%S}_{parent}_{os.path.basename(path)}"


def removable_drives():
    """[(root, label)] for removable drives (SD card readers) on Windows."""
    if os.name != "nt":
        return []
    import ctypes
    import string
    k32 = ctypes.windll.kernel32
    out = []
    mask = k32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if not (mask >> i) & 1:
            continue
        root = f"{letter}:\\"
        if k32.GetDriveTypeW(root) != 2:  # DRIVE_REMOVABLE
            continue
        buf = ctypes.create_unicode_buffer(261)
        ok = k32.GetVolumeInformationW(root, buf, 261, None, None, None, None, 0)
        if ok:  # skips empty card readers
            out.append((root, buf.value))
    return out
