# HorseCam

Windows app for the trail-cam horse study: copy photos off the SD cards,
find the photos with horses, sort them into folders, and plot when horses show up.

## Install (once)

1. Install **Python 3.12** from python.org — tick **"Add python.exe to PATH"**.
2. Unzip this folder somewhere permanent (e.g. `C:\HorseCam`).
3. Double-click **setup.bat**. Answer **Y** if the PC has an NVIDIA graphics card.
4. Double-click **HorseCam.bat** to start the app.
5. On the **Import photos** tab press **Choose study folder…** and pick the folder
   that holds one folder per camera. The folder names become the camera names.

The first detection run downloads the model (~40 MB), so be online for that.

## First pass: photos you already copied

Your existing layout works as-is:

```
D:\HorseStudy\              <- choose this folder
  North Gate\DCIM\...
  Creek\DCIM\...
```

After choosing the folder, press **Index, then find horses**. Indexing reads each
photo once to record its date and a fingerprint (hash); nothing is copied or moved.
If the same card was copied twice, the second copy is detected and skipped.

## Every card swap (~2 months)

1. **Import photos → SD card** — put a card in the reader, *Refresh*, choose which camera it
   came out of, *Scan card*, then *Import, then find horses*. Photos go to
   `<camera>\photos\<YYYY-MM>\`. (Or keep copying DCIM folders by hand into the
   camera folder and press *Index, then find horses* — either works.)
   Every file is hashed, copied, and re-verified. Files already in the library are
   skipped, so importing the same card twice — or a card you already copied by hand — is harmless. Nothing on the card is
   changed. Only format the card (in the camera) after the import says
   **0 failed**.
2. **Find horses** — runs automatically after import, or press the button.
   It can be stopped and resumed; it picks up where it left off.
3. **Review** — in each camera folder, open `review\`. Uncertain photos have the
   candidate outlined in yellow. Move each into `review\yes` or `review\no`. If
   something in `horses\` isn't a horse, move it to `horses\_not_horse`.
   Press **Apply my review**.
   Your decisions override the model everywhere.
4. **Histograms** — pick a chart, date range and cameras. *Save report* writes every
   chart as PNG plus CSVs (each horse photo, each visit, hourly counts, per-camera
   summary) into `reports\<date>\`.

## Study folder layout

```
<study folder>\
  horsecam.db              catalog of every photo and detection (keep this!)
  reports\                 saved charts and CSVs
  logs\                    one CSV per import / index run
  North Gate\
    DCIM\...               your own copies (indexed in place, never changed)
    photos\2026-12\        cards imported by the app
    horses\                photos with horses (copies)
    horses\_not_horse\     your false-positive corrections
    review\                uncertain photos with yellow boxes
    review\yes  review\no  your review decisions
  Creek\
    ...
```

The copies in `horses` and `review` are named
`<camera>_<date>_<time>_<source folder>_<file>` so they sort by time and never
collide (trail cams reuse IMG_0001 in every folder).

Don't rename a camera folder after indexing: the catalog stores paths, so a
renamed folder would be indexed again as a new camera.

## Visits vs photos

Trail cams shoot bursts — one horse grazing for 20 minutes can be 100 photos.
**Visits** groups a camera's horse photos into one event when they are less than
the *visit gap* (default 10 min) apart, timed by the first photo. Use visits for
attendance; photos is closer to time-in-view.

## Settings worth knowing

| Setting | Default | Notes |
|---|---|---|
| Model | yolo11m | `yolo11s` ≈ 2–3× faster, a little less accurate; `yolo11l` if you have a GPU |
| Image size | 960 | 1280 helps with horses far from the camera, but is slower |
| Horse threshold | 0.40 | Can be changed on the Histograms tab without re-running detection |
| Review threshold | 0.15 | Lower = more photos to review, fewer missed horses |

**Speed:** on a typical laptop CPU expect roughly 2–5 photos/second with
`yolo11m`; an NVIDIA GPU is 10–30× faster. A big batch can run overnight;
press Stop any time and resume later.

## Tips for clean data

- **Camera clocks.** The charts use each camera's clock. Set all six to the same
  time when you redeploy, and note that trail cams don't change for daylight
  saving (it ends **Nov 1, 2026**) — either keep cameras on standard time all
  year or reset them at each swap.
- **Night (IR) photos** are harder for the model. Check the review folder for
  dawn/dusk/night hours before trusting a low count at night.
- **Camera downtime.** `camera_summary.csv` shows how many days each camera
  produced any photo — a camera with a dead battery shows as a gap, not as
  "no horses". If your cameras support a time-lapse photo (e.g. one per hour),
  turning it on gives you a definite uptime record.
- Back up the whole study folder (including `horsecam.db`) to a second drive.
