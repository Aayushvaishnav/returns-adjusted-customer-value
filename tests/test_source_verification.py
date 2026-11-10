from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from verify_source import compare_archive


class ArchiveVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.local = self.root / "local.xlsx"
        self.local.write_bytes(b"synthetic comparison bytes")
        self.archive = self.root / "official.zip"
        with ZipFile(self.archive, "w") as target:
            target.write(self.local, "online_retail_II.xlsx")

    def test_identical_archive_member_passes(self):
        result = compare_archive(self.local, self.archive)
        self.assertEqual(result["status"], "Passed")
        self.assertEqual(result["workbook_bytes"], result["official_member_bytes"])
        self.assertEqual(result["local_workbook_sha256"], result["official_workbook_sha256"])

    def test_changed_local_file_fails(self):
        self.local.write_bytes(b"different workbook")
        with self.assertRaisesRegex(ValueError, "differs"):
            compare_archive(self.local, self.archive)

    def test_ambiguous_archive_member_fails(self):
        with ZipFile(self.archive, "a") as target:
            target.writestr("unexpected.xlsx", b"extra")
        with self.assertRaisesRegex(ValueError, "members"):
            compare_archive(self.local, self.archive)


if __name__ == "__main__":
    unittest.main()
