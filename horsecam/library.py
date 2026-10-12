"""Study-folder layout.  One sub-folder per camera; the folder name is the camera name.

<study folder>/
    horsecam.db                  catalog of every photo + detection results
    reports/<timestamp>/         saved charts (PNG) and data (CSV)
    logs/                        one CSV per import / folder scan
    <Cam>/                       e.g. your existing copied DCIM folders live here
        DCIM/...                 photos you copied yourself (indexed in place)
        photos/<YYYY-MM>/        photos imported from cards by the app
        horses/                  copies of photos the model is confident show horses
        horses/_not_horse/       move false positives here, then "Apply my review"
        review/                  uncertain photos, with the candidate box drawn
        review/yes/  review/no/  sort uncertain photos here, then "Apply my review"
"""
import os

from .db import DB

ROOT_SUBDIRS = ["reports", "logs", "_incoming"]
# Folders inside a camera folder that are the app's output, never source photos.
CAM_OUTPUT_DIRS = {"horses", "review"}
# Top-level folders in the study folder that are not cameras.
NOT_CAMERAS = set(ROOT_SUBDIRS) | {"System Volume Information", "$RECYCLE.BIN"}

BAD_NAME_CHARS = set('<>:"/\\|?*,')


def valid_camera_name(name):
    return bool(name) and not (set(name) & BAD_NAME_CHARS) and name == name.strip()


def find_camera_folders(root):
    """Sub-folder names of `root` that look like camera folders, sorted."""
    out = []
    for n in sorted(os.listdir(root), key=str.lower):
        p = os.path.join(root, n)
        if (os.path.isdir(p) and n not in NOT_CAMERAS
                and not n.startswith((".", "_", "$"))):
            out.append(n)
    return out


class Library:
    def __init__(self, root):
        if not root:
            raise ValueError("No study folder set. Choose one on the Import tab or in Settings.")
        self.root = os.path.abspath(root)
        for d in ROOT_SUBDIRS:
            os.makedirs(os.path.join(self.root, d), exist_ok=True)
        self.db = DB(os.path.join(self.root, "horsecam.db"))

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def abs(self, rel_path):
        return os.path.join(self.root, rel_path)

    # per-camera output folders
    def cam_dir(self, cam, *parts):
        return os.path.join(self.root, cam, *parts)

    def horses_dir(self, cam):
        return self.cam_dir(cam, "horses")

    def not_horse_dir(self, cam):
        return self.cam_dir(cam, "horses", "_not_horse")

    def review_dir(self, cam):
        return self.cam_dir(cam, "review")

    def ensure_cam_dirs(self, cam):
        for d in (self.not_horse_dir(cam), self.cam_dir(cam, "review", "yes"),
                  self.cam_dir(cam, "review", "no")):
            os.makedirs(d, exist_ok=True)

    def cameras_in_db(self):
        return [r[0] for r in self.db.query("SELECT DISTINCT camera FROM photos ORDER BY camera")]

    def close(self):
        self.db.close()
