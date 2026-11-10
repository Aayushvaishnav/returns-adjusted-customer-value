"""Check that README previews use the dashboard area instead of a print page."""

from pathlib import Path
import re
import shutil
import subprocess
import unittest


PREVIEWS = Path(__file__).resolve().parents[1] / 'reports/excel/preview'
VIEWS = ('Value_Overview', 'Segment_Migration', 'Cohorts', 'Review_Actions')


@unittest.skipUnless(shutil.which('magick'), 'ImageMagick is required for preview checks')
class ExcelPreviewTests(unittest.TestCase):
    def test_dashboard_fills_each_readme_image(self):
        for view in VIEWS:
            with self.subTest(view=view):
                result = subprocess.run(
                    ['magick', f'png:{PREVIEWS / (view + ".png")}',
                     '-format', '%w %h %@', 'info:'],
                    check=True, capture_output=True, text=True)
                match = re.fullmatch(r'(\d+) (\d+) (\d+)x(\d+)\+(\d+)\+(\d+)',
                                     result.stdout)
                self.assertIsNotNone(match, result.stdout)
                width, height, content_width, content_height, left, top = map(int, match.groups())
                margins = (left, top, width - left - content_width,
                           height - top - content_height)
                self.assertTrue(all(0 <= margin <= 12 for margin in margins),
                                f'{view} has excess outer whitespace: {margins}')


if __name__ == '__main__':
    unittest.main()
