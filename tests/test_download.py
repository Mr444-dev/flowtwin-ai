from __future__ import annotations

import hashlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flowtwin import download


class _Response(io.BytesIO):
    def __init__(self, payload: bytes, headers: dict[str, str] | None = None) -> None:
        super().__init__(payload)
        self.headers = headers or {}

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class DownloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)

    def _configure(self, payload: bytes, headers: dict[str, str] | None = None):
        root = Path(self.temp.name)
        patches = [
            patch.object(download, "RAW_DIR", root),
            patch.object(download, "DATASET_NAME", "sample.xes.gz"),
            patch.object(download, "DATASET_URL", "https://example.invalid/file"),
            patch.object(download, "DATASET_MD5", hashlib.md5(payload).hexdigest()),
            patch.object(download.urllib.request, "urlopen", return_value=_Response(payload, headers)),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        return root

    def test_download_saves_only_checksum_verified_file(self) -> None:
        payload = b"a small test file"
        root = self._configure(payload, {"Content-Length": str(len(payload))})
        target = download.download_dataset()
        self.assertEqual(target.read_bytes(), payload)
        self.assertFalse(target.with_suffix(".gz.part").exists())

    def test_wrong_checksum_removes_partial_file(self) -> None:
        payload = b"not the expected source"
        root = self._configure(payload)
        with patch.object(download, "DATASET_MD5", "0" * 32):
            with self.assertRaisesRegex(ValueError, "MD5"):
                download.download_dataset()
        self.assertEqual(list(root.iterdir()), [])

    def test_download_size_limit_removes_partial_file(self) -> None:
        payload = b"123"
        root = self._configure(payload)
        with patch.object(download, "MAX_DOWNLOAD_BYTES", 2):
            with self.assertRaisesRegex(ValueError, "download exceeds the"):
                download.download_dataset()
        self.assertEqual(list(root.iterdir()), [])

    def test_advertised_length_is_checked(self) -> None:
        payload = b"short"
        root = self._configure(payload, {"Content-Length": "99"})
        with self.assertRaisesRegex(ValueError, "Incomplete transfer"):
            download.download_dataset()
        self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
