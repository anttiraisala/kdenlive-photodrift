# PhotoDrift

Photos drift up over a video in [Kdenlive](https://kdenlive.org/).

PhotoDrift turns a folder of photos into instant-print style cards (white
frame, wide bottom border, slight curl, gloss, a faint uneven surface and
a soft shadow) and writes a Kdenlive **title clip** in which the cards rise
from the bottom of the frame and leave through the top. The video under the
title clip shows between the cards.

It is a plain Python script. It does not need Natron or any Kdenlive plugin:
the result is an ordinary `.kdenlivetitle` file that Kdenlive (and MLT)
render natively.

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
python3 photodrift.py --photos ~/Pictures/summer --out ~/Videos/myproject/photodrift \
    --start 1:10 --end 2:05
```

`--start` and `--end` are the points in your video where the cards should
start and stop; they set the clip duration, and the scroll speed follows
from it. Without them the duration is chosen so that each card is visible
for about 8 seconds (`--card-time`).

Output:

```
~/Videos/myproject/photodrift/
  photodrift.kdenlivetitle   the title clip: cards + scrolling
  cards/*.png                one card image per photo
  order.txt                  card order (editable)
  photodrift.json            settings and per-card state
  backups/                   earlier versions of the title clip
```

## Using it in Kdenlive

1. **Project > Add Clip...** and pick `photodrift.kdenlivetitle`.
2. Drag the clip from the Project Bin to a video track **above** your video,
   so that it starts at the `--start` point.
3. Play. The cards rise over the video.

### Duration and speed

The scroll runs over the **title clip's own duration** (the one PhotoDrift
writes, or the one set in the title editor). Making the clip longer or
shorter on the timeline does *not* change the speed: a longer clip shows an
empty frame after the last card has left, a shorter one cuts the scroll.

To change the speed, either run PhotoDrift again with new `--start`/`--end`
(or `--duration`), or open the title editor and change its duration field.

### Moving cards by hand

1. Double-click the clip in the Project Bin to open the title editor.
2. Zoom out to see the cards below the frame, and drag cards where you
   want them. You can also rotate and scale them.
3. Press **OK**. Kdenlive asks whether to save the changes *to the title
   file* or *in the project only*. Choose **Save to title file**.

When you later run PhotoDrift again (more photos, another order, another
style...), your moves are kept: each moved card keeps its offset from its
automatic position, and its rotation and scale. Use `--reset-positions` to
forget the manual moves.

Other things you add in the title editor (text, for example) are kept too.

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
| `--start T --end T` | | duration = end - start (`75`, `1:15`, `0:01:15.5`, `00:01:15:12`) |
| `--duration T` | | duration directly |
| `--card-time S` | 8 | automatic duration: seconds each card is visible |
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

The crop of each photo is centred. To keep another part of a photo, edit its
`"focus"` value in `photodrift.json` (`[0.5, 0.2]` keeps the upper part)
and run again.

## Preview without Kdenlive

```bash
python3 tools/melt_preview.py ~/Videos/myproject/photodrift/photodrift.kdenlivetitle preview.mp4
python3 tools/melt_preview.py title.kdenlivetitle preview.mp4 --background myvideo.mp4 --scale 1
```

This renders the title with MLT's own `kdenlivetitle` producer, the same
code Kdenlive uses. It needs an X11 desktop (MLT's Qt module requires one).

## Development

```bash
python3 tools/make_test_photos.py --out test-photos --count 20   # synthetic test photos
python3 -m unittest discover -s tests                             # tests
```

The render test (`tests/test_melt.py`) runs when `melt` and an X11 display
are available, and is skipped otherwise; on a server use `xvfb-run`.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
