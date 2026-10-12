"""SQLite catalog of every photo imported and every detection result.

The database lives in the library folder (horsecam.db) so the library is
self-contained: copy the folder to another drive and everything comes along.
"""
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS photos(
    id          INTEGER PRIMARY KEY,
    sha1        TEXT UNIQUE NOT NULL,   -- content hash, used to skip duplicates
    camera      TEXT NOT NULL,
    kind        TEXT NOT NULL,          -- image | video
    taken       TEXT,                   -- ISO local time (camera clock)
    time_source TEXT,                   -- exif | mtime
    rel_path    TEXT NOT NULL,          -- path relative to library root
    fname       TEXT NOT NULL,          -- library file name (unique)
    orig_name   TEXT,
    card_label  TEXT,
    size        INTEGER,
    imported    TEXT
);
CREATE INDEX IF NOT EXISTS ix_photos_cam_taken ON photos(camera, taken);
CREATE INDEX IF NOT EXISTS ix_photos_fname ON photos(fname);

CREATE TABLE IF NOT EXISTS detections(
    photo_id   INTEGER PRIMARY KEY REFERENCES photos(id),
    model      TEXT,
    horse_conf REAL,      -- best horse confidence in the photo (0 if none)
    n_horses   INTEGER,   -- boxes at or above the horse threshold
    boxes      TEXT,      -- JSON [[x1,y1,x2,y2,conf], ...]
    status     TEXT,      -- horse | review | none | error
    processed  TEXT
);

CREATE TABLE IF NOT EXISTS dup_paths(   -- files skipped as duplicates when indexing
    rel_path TEXT PRIMARY KEY,
    sha1     TEXT
);

CREATE TABLE IF NOT EXISTS manual(
    photo_id INTEGER PRIMARY KEY REFERENCES photos(id),
    horse    INTEGER NOT NULL,   -- 1 = horse, 0 = not horse (overrides model)
    set_at   TEXT
);
"""


class DB:
    def __init__(self, path):
        self.con = sqlite3.connect(path, check_same_thread=False)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA synchronous=NORMAL")
        self.con.executescript(SCHEMA)
        self.lock = threading.Lock()

    def execute(self, sql, args=()):
        with self.lock:
            cur = self.con.execute(sql, args)
            self.con.commit()
            return cur

    def query(self, sql, args=()):
        with self.lock:
            return self.con.execute(sql, args).fetchall()

    def scalar(self, sql, args=()):
        rows = self.query(sql, args)
        return rows[0][0] if rows else None

    def close(self):
        with self.lock:
            self.con.close()
