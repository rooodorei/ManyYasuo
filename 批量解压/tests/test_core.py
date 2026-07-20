import tempfile
import unittest
from pathlib import Path

from extraction_core import find_blocking_file, finalize_extraction, parse_block_terms


class ExtractionRulesTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_protection_requires_all_terms_in_the_same_filename(self):
        (self.root / "路径说明.txt").touch()
        (self.root / "中文说明.txt").touch()
        terms = parse_block_terms("路径, 中文")
        self.assertIsNone(find_blocking_file(self.root, terms))

        expected = self.root / "路径不要有中文.txt"
        expected.touch()
        self.assertEqual(find_blocking_file(self.root, terms), expected)

    def test_protection_only_checks_the_first_two_levels(self):
        second = self.root / "资料"
        second.mkdir()
        expected = second / "中文路径提示.md"
        expected.touch()
        terms = parse_block_terms("路径，中文")
        self.assertEqual(find_blocking_file(self.root, terms), expected)

        expected.unlink()
        third = second / "更深层"
        third.mkdir()
        (third / "路径不能有中文.txt").touch()
        self.assertIsNone(find_blocking_file(self.root, terms))

    def test_tag_renames_outer_folder_and_removes_empty_marker(self):
        output = self.root / "output"
        output.mkdir()
        staging = output / ".staging"
        payload = staging / "原文件夹"
        marker = payload / "AAA_客户标签"
        marker.mkdir(parents=True)
        (payload / "内容.txt").touch()

        destination, message = finalize_extraction(
            staging,
            output,
            Path("示例.7z"),
            {"tag_prefix": "AAA_", "block_terms": "路径, 中文"},
        )

        self.assertEqual(destination, output / "客户标签")
        self.assertTrue(destination.is_dir())
        self.assertFalse((destination / marker.name).exists())
        self.assertIn("已按标签改名", message)

    def test_protected_file_keeps_original_outer_folder_name(self):
        output = self.root / "output"
        output.mkdir()
        staging = output / ".staging"
        payload = staging / "英文目录"
        (payload / "AAA_中文标签").mkdir(parents=True)
        notice_dir = payload / "说明"
        notice_dir.mkdir()
        (notice_dir / "请注意路径不要有中文.txt").touch()

        destination, message = finalize_extraction(
            staging,
            output,
            Path("示例.7z"),
            {"tag_prefix": "AAA_", "block_terms": "路径, 中文"},
        )

        self.assertEqual(destination, output / "英文目录")
        self.assertTrue((destination / "AAA_中文标签").is_dir())
        self.assertIn("保留原名", message)


if __name__ == "__main__":
    unittest.main()
