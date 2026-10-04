# PhotoDrift

Photos drift up over a video in [Kdenlive](https://kdenlive.org/).

PhotoDrift turns a folder of photos into instant-print style cards (white
frame, wide bottom border, slight curl, gloss, a faint uneven surface and
a soft shadow) that rise from the bottom of the frame and leave through the
top. The video under them shows between the cards.

It writes two things:

- **`photodrift-strip.png`** with a **Transform preset**: all cards in one
  tall image, moved by Kdenlive's Transform effect. The scroll speed
  follows the clip length: make the clip longer on the timeline and the
  cards move slower.
- **`photodrift.kdenlivetitle`**, a Kdenlive title clip with the same
  cards. Open it in Kdenlive's title editor to move, rotate and scale cards
  by hand; the next run puts your changes into the strip. It can also be
  used directly on the timeline, but then the speed is fixed by its own
  duration.

It is a plain Python script. It does not need Natron or any Kdenlive plugin:
Kdenlive (and MLT) render the results natively.

## Requirements

- Python 3 with Pillow and numpy. On Ubuntu / Linux Mint:

  ```bash
  sudo apt install python3-pil python3-numpy
  ```

- Kdenlive (tested format: Kdenlive 26.08 / MLT 7).
- Optional, for previews without Kdenlive and for the render test: `melt`
  (`sudo apt install melt`).

## Quick start

```bash
python3 photodrift.py --photos ~/Pictures/summer --out ~/Videos/myproject/photodrift
```

Output:

```
~/Videos/myproject/photodrift/
  photodrift-strip.png       all cards in one tall image (for the timeline)
  photodrift.kdenlivetitle   title clip: the card layout (edit cards here)
  cards/*.png                one card image per photo
  order.txt                  card order (editable)
  photodrift.json            settings and per-card state
  photodrift-transform-preset.json   copy of the Transform preset
  backups/                   earlier versions of the title clip
```

The Transform preset is also added to Kdenlive's own preset file,
`~/.local/share/kdenlive/effects/presets/qtblend.json`, under the name
**PhotoDrift *folder name*** (here: "PhotoDrift photodrift"). Other presets
in that file are kept; the previous file is saved as `qtblend.json.bak`.

## Using it in Kdenlive

### On the timeline: the strip (speed follows the clip length)

1. **Project > Add Clip...** and pick `photodrift-strip.png`.
2. Drag it to a video track **above** your video, at the point where the
   cards should start. Drag its end to where they should stop.
3. Open the **Effects** tab, search for **Transform** and drag it onto the
   strip clip.
4. In the Effect Stack, open the Transform effect's menu (the hamburger
   button on the effect's title bar) and choose the preset **PhotoDrift
   *folder name***.
5. Play. The cards rise over the video.

The preset has two keyframes, at the first and the last frame of the clip.
When you drag the clip end, Kdenlive moves the last keyframe with it, so
the cards slow down or speed up to fit. If the speed ever does not follow,
choose the preset again: it always uses the current clip length.

Do not change the Transform values by hand; move cards in the title editor
instead (below).

### Moving cards by hand

1. Add `photodrift.kdenlivetitle` to the Project Bin as well (**Project >
   Add Clip...**). It does not need to be on the timeline.
2. Double-click it in the Project Bin to open the title editor.
3. Zoom out to see the cards below the frame, and drag cards where you
   want them. You can also rotate and scale them.
4. Press **OK**. Kdenlive asks whether to save the changes *to the title
   file* or *in the project only*. Choose **Save to title file**.
5. Run PhotoDrift again (only `--out` is needed). The strip is rendered
   again with your changes. If the strip clip in Kdenlive does not update
   by itself, right-click it in the Project Bin and choose **Reload Clip**.
   If PhotoDrift says "choose the preset again", the strip changed size:
   select the strip clip and choose the preset again (step 4 above).

Your moves are kept in later runs too (more photos, another order, another
style...): each moved card keeps its offset from its automatic position,
and its rotation and scale. Use `--reset-positions` to forget them.

Text or other items added in the title editor are kept in the title clip
but are not drawn into the strip.

### The title clip on the timeline (fixed speed)

The title clip can also go on the timeline directly. Its scroll runs over
the title's **own duration**: making the clip longer on the timeline does
not slow it down (the frame stays empty after the last card), a shorter
clip cuts the scroll. Set the duration with `--start`/`--end` or
`--duration`, or in the title editor's duration field.

### Strip size

The strip is as tall as all the cards together (about 1920 x 8500 pixels
for 15 photos with the defaults). Qt cannot load images over 256 MB
(1920 x ~34000 pixels); PhotoDrift warns if the strip gets that big. Use
fewer photos per strip, a smaller `--card-width` or a smaller `--spacing`.

## Card order

The first run writes `order.txt`, sorted by file name (`--sort date` uses
the EXIF date instead). Edit it and run again:

- move lines to change the order,
- put `#` in front of a photo to leave it out.

New photos in the folder are added to the end; deleted photos are removed
together with their cards. `--reset-order` sorts everything again.

## Running again

Settings are stored in `photodrift.json`, so later runs only need `--out`
and the options you want to change:

```bash
python3 photodrift.py --out ~/Videos/myproject/photodrift --layout center --tilt 3
```

Card images are re-rendered only when the photo or the card settings
change. Before the title file is overwritten, the previous version is
copied to `backups/`.

## Options

| Option | Default | Meaning |
|---|---|---|
| `--photos DIR` | | photo folder (needed on the first run) |
| `--out DIR` | | output folder |
| `--recursive` | off | also use photos in subfolders |
| `--sort name\|date\|mtime` | name | order of new photos |
| `--size WxH` | 1920x1080 | project frame size, e.g. 3840x2160 or 1080x1920 |
| `--fps N` | 25 | project frame rate |
| `--start T --end T` | | title clip duration = end - start (`75`, `1:15`, `0:01:15.5`, `00:01:15:12`) |
| `--duration T` | | title clip duration directly |
| `--card-time S` | 8 | automatic title clip duration: seconds each card is visible |
| `--card-width F` | 0.30 | card width as a fraction of the frame width |
| `--layout` | alternate | `alternate` (left/right), `center` or `random` |
| `--spacing F` | 0.5 | vertical distance between cards, fraction of frame height |
| `--side-offset F` | 0.2 | alternate layout: distance from the centre, fraction of width |
| `--jitter-x F`, `--jitter-y F` | 0.03, 0.08 | random displacement |
| `--tilt DEG` | 5 | maximum random tilt (set in the title, editable in Kdenlive) |
| `--seed N` | 1 | same seed = same cards and layout |
| `--aperture` | 4:5 | photo opening: `4:5`, `1:1`, any `W:H`, or `native` |
| `--film` | 0.6 | faded warm film look, 0..1 |
| `--vignette` | 0.35 | darker photo corners, 0..1 |
| `--curl` | 0.5 | card curl, 0..1 |
| `--gloss`, `--gloss-angle` | 0.5, 30 | gloss reflection strength and angle |
| `--bump` | 0.5 | uneven surface, 0..1 |
| `--shadow` | 0.45 | drop shadow opacity, 0..1 |
| `--supersample 1\|2` | 1 | card image resolution (2 = double size, shown at 50 %) |
| `--no-strip` | | only write the title clip |
| `--no-kdenlive-preset` | | do not touch Kdenlive's preset file |
| `--kdenlive-dir DIR` | ~/.local/share/kdenlive | Kdenlive data folder |

The crop of each photo is centred. To keep another part of a photo, edit its
`"focus"` value in `photodrift.json` (`[0.5, 0.2]` keeps the upper part)
and run again.

## Preview without Kdenlive

```bash
python3 tools/melt_preview.py ~/Videos/myproject/photodrift/photodrift.kdenlivetitle preview.mp4
python3 tools/melt_preview.py title.kdenlivetitle preview.mp4 --background myvideo.mp4 --scale 1
python3 tools/melt_preview.py ~/Videos/myproject/photodrift/photodrift-strip.png preview.mp4 --frames 1500
```

This renders with MLT, the same engine Kdenlive uses: the title with the
`kdenlivetitle` producer, the strip with the Transform effect (`qtblend`)
and the preset's keyframes (`--frames` = clip length). It needs an X11
desktop (MLT's Qt module requires one).

## Development

```bash
python3 tools/make_test_photos.py --out test-photos --count 20   # synthetic test photos
python3 -m unittest discover -s tests                             # tests
```

The render tests (`tests/test_melt.py`) run when `melt` and an X11 display
are available, and are skipped otherwise; on a server use `xvfb-run`.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
