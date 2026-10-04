import os
import tempfile
import unittest

from helpers import small_photos, copy_photos
from photodrift import ordering


class OrderingTests(unittest.TestCase):
    def test_natural_sort(self):
        names = ["IMG_10.jpg", "IMG_2.jpg", "img_1.jpg"]
        self.assertEqual(sorted(names, key=ordering.natural_key), ["img_1.jpg", "IMG_2.jpg", "IMG_10.jpg"])

    def test_order_file_edit_cycle(self):
        photos = copy_photos(small_photos())
        with tempfile.TemporaryDirectory() as out:
            path = os.path.join(out, "order.txt")
            order, excluded, added, dropped = ordering.resolve_order(photos, path)
            self.assertEqual(order, ["IMG_%04d.jpg" % i for i in range(1, 7)])
            self.assertEqual(added, order)

            # User moves 5 to the top and leaves 2 out.
            with open(path, "w") as f:
                f.write("# my order\nIMG_0005.jpg\nIMG_0001.jpg\n# IMG_0002.jpg\nIMG_0003.jpg\n")
            order, excluded, added, dropped = ordering.resolve_order(photos, path)
            self.assertEqual(order, ["IMG_0005.jpg", "IMG_0001.jpg", "IMG_0003.jpg", "IMG_0004.jpg",
                                     "IMG_0006.jpg"])
            self.assertEqual(excluded, ["IMG_0002.jpg"])
            self.assertEqual(added, ["IMG_0004.jpg", "IMG_0006.jpg"])

            # A photo disappears, a new one appears.
            os.remove(os.path.join(photos, "IMG_0001.jpg"))
            os.rename(os.path.join(photos, "IMG_0006.jpg"), os.path.join(photos, "IMG_0099.jpg"))
            order, excluded, added, dropped = ordering.resolve_order(photos, path)
            self.assertEqual(order, ["IMG_0005.jpg", "IMG_0003.jpg", "IMG_0004.jpg", "IMG_0099.jpg"])
            self.assertEqual(sorted(dropped), ["IMG_0001.jpg", "IMG_0006.jpg"])
            with open(path) as f:
                text = f.read()
            self.assertIn("# IMG_0002.jpg", text)

            # Reset sorts everything again.
            order, excluded, _, _ = ordering.resolve_order(photos, path, reset=True)
            self.assertEqual(order[0], "IMG_0002.jpg")
            self.assertEqual(excluded, [])

    def test_sort_by_date(self):
        photos = small_photos(count=8)
        names = ordering.sort_photos(ordering.find_photos(photos), photos, "date")
        # make_test_photos puts photo 7 five days back, so it comes before photo 5.
        self.assertLess(names.index("IMG_0007.jpg"), names.index("IMG_0005.jpg"))


if __name__ == "__main__":
    unittest.main()
