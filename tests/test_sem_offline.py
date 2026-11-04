"""Offline SEM geometry/pixel invariants; no Adobe session or user images."""
import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from plotting_core.sem.plan import center_crop, prepare_sem
from plotting_core.sem.contract import SKILL_ROOT
from plotting_core.instruments.service import detect_vendor

try:
    from PIL import Image
    import pypdf
    from plotting_core.sem.image_worker import source_rgb
    PIXEL_RUNTIME = True
except ImportError:
    PIXEL_RUNTIME = False


def png_gray(width, height, value=64):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    samples = (b"\0" + bytes([value]) * width) * height
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) +
            chunk(b"IDAT", zlib.compress(samples)) + chunk(b"IEND", b""))


class SemOfflineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="battery-sem-fixture-")
        self.directory = Path(self.temporary.name)
        source_directory = self.directory / "source"
        source_directory.mkdir()
        self.image = source_directory / "synthetic.png"
        self.image.write_bytes(png_gray(200, 120))
        profile = json.loads((SKILL_ROOT / "templates" / "sem_visual_profile.json").read_text(encoding="utf-8"))
        self.document = {
            "schema_version": 1, "task_name": "synthetic_sem",
            "output_root": str(self.directory / "outputs"),
            "source": {"file": str(self.image)},
            "calibration": {"length": 10., "unit": "um", "start_px": [20, 110],
                            "end_px": [120, 110], "source": "synthetic explicit pixel scale"},
            "image_region_px": [0, 0, 200, 100], "crop_px": [50, 0, 150, 100],
            "panel": {"width_pt": 200., "height_pt": 200.},
            "scale_bar": {"length": 2., "unit": "um"},
            "style": profile["style"]}

    def tearDown(self):
        self.temporary.cleanup()

    def test_scale_uses_calibration_and_isotropic_crop_without_source_changes(self):
        before = self.image.read_bytes()
        plan = prepare_sem(self.document)
        self.assertAlmostEqual(plan["calibration"]["um_per_px"], .1)
        self.assertAlmostEqual(plan["scale_bar"]["width_pt"], 40.)
        self.assertEqual(plan["placed_full_image"]["width_pt"], 400.)
        self.assertEqual(plan["placed_full_image"]["height_pt"], 240.)
        self.assertEqual(self.image.read_bytes(), before)

    def test_crop_cannot_include_unverified_footer(self):
        document = copy.deepcopy(self.document)
        document["crop_px"] = [50, 0, 150, 110]
        with self.assertRaises(ValueError):
            prepare_sem(document)

    def test_nonisotropic_display_and_missing_scale_are_rejected(self):
        for field in ("stretch", "zero_scale"):
            document = copy.deepcopy(self.document)
            if field == "stretch":
                document["panel"]["width_pt"] = 300.
            else:
                document["calibration"]["end_px"] = document["calibration"]["start_px"]
            with self.subTest(case=field), self.assertRaises(ValueError):
                prepare_sem(document)

    def test_center_crop_is_geometric_and_unknown_processing_is_rejected(self):
        self.assertEqual(center_crop([0, 0, 200, 100], 1.), [50., 0, 150., 100])
        document = copy.deepcopy(self.document)
        document["contrast"] = "enhance"
        with self.assertRaises(ValueError):
            prepare_sem(document)

    def test_unsupported_instrument_format_is_not_routed_by_guess(self):
        with self.assertRaises(ValueError):
            detect_vendor("synthetic.res")
        self.assertEqual(detect_vendor("synthetic.cex"), "land")
        self.assertEqual(detect_vendor("synthetic.ndax"), "neware")

    @unittest.skipUnless(PIXEL_RUNTIME, "Optional Pillow/pypdf worker is unavailable")
    def test_grayscale_transport_preserves_all_samples_without_alpha(self):
        before = self.image.read_bytes()
        original, rgb, _ = source_rgb(self.image)
        try:
            self.assertEqual(rgb.mode, "RGB")
            self.assertEqual(rgb.size, (200, 120))
            self.assertEqual(rgb.tobytes(), bytes([64, 64, 64]) * 200 * 120)
            self.assertEqual(self.image.read_bytes(), before)
        finally:
            original.close()
            rgb.close()

    @unittest.skipUnless(PIXEL_RUNTIME, "Optional Pillow/pypdf worker is unavailable")
    def test_transparent_and_sixteen_bit_inputs_are_rejected(self):
        transparent = self.image.parent / "transparent.png"
        image = Image.new("RGBA", (10, 10), (64, 64, 64, 0))
        image.save(str(transparent))
        image.close()
        sixteen = self.image.parent / "sixteen.tif"
        image = Image.new("I;16", (10, 10))
        image.save(str(sixteen))
        image.close()
        for path in (transparent, sixteen):
            with self.subTest(path=path.name), self.assertRaises(ValueError):
                source_rgb(path)


if __name__ == "__main__":
    unittest.main()
