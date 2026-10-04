import io
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import make_test_photos  # noqa: E402

_PHOTO_CACHE = {}


def small_photos(count=6, seed=3):
    """Folder with ``count`` small generated photos (cached per test run)."""
    key = (count, seed)
    if key not in _PHOTO_CACHE:
        d = tempfile.mkdtemp(prefix="pd-photos-")
        with redirect_stdout(io.StringIO()):
            make_test_photos.main(["--out", d, "--count", str(count), "--seed", str(seed), "--scale", "0.08"])
        _PHOTO_CACHE[key] = d
    return _PHOTO_CACHE[key]


def copy_photos(src, names=None):
    d = tempfile.mkdtemp(prefix="pd-photos-copy-")
    for n in sorted(os.listdir(src)):
        if names is None or n in names:
            shutil.copy2(os.path.join(src, n), d)
    return d
