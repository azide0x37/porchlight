import shutil
import subprocess
import unittest
from pathlib import Path


class GuestQrImageTest(unittest.TestCase):
    def run_check(self, name):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        result = subprocess.run(
            [node, str(Path(__file__).with_name("qr_image_checks.cjs")), name],
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_native_pixels_and_quiet_zone_are_preserved(self):
        self.run_check("exactPixels")

    def test_non_monochrome_and_excessive_images_are_refused(self):
        self.run_check("limits")

    def test_decoder_bounds_and_resource_cleanup(self):
        self.run_check("resources")
