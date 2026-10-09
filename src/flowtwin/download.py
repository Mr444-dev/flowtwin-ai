from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

from .config import DATASET_MD5, DATASET_NAME, DATASET_URL, RAW_DIR


MAX_DOWNLOAD_BYTES = 4 * 1024**3


def download_dataset(force: bool = False) -> Path:
    """Download the original compressed XES file and verify its configured MD5."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    target = RAW_DIR / DATASET_NAME
    partial = target.with_suffix(target.suffix + ".part")

    if target.exists() and not force:
        actual = _md5(target)
        if actual == DATASET_MD5:
            print(f"Dataset is already downloaded and its MD5 checksum is valid: {target}")
            return target
        print("The existing file has a different checksum; downloading it again.")

    request = urllib.request.Request(
        DATASET_URL,
        headers={"User-Agent": "FlowTwin-AI-demo/0.1 (research-data download)"},
    )
    print("Downloading the official XES file from 4TU.ResearchData; this may take a while.")
    digest = hashlib.md5()
    try:
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as out:
            total = response.headers.get("Content-Length")
            total_bytes = int(total) if total and total.isdigit() else None
            if total_bytes is not None and total_bytes > MAX_DOWNLOAD_BYTES:
                raise ValueError(f"The server announced a file larger than the {MAX_DOWNLOAD_BYTES // 1024**3} GiB limit.")
            downloaded = 0
            while chunk := response.read(1024 * 1024):
                if downloaded + len(chunk) > MAX_DOWNLOAD_BYTES:
                    raise ValueError(f"The download exceeds the {MAX_DOWNLOAD_BYTES // 1024**3} GiB limit.")
                out.write(chunk)
                digest.update(chunk)
                downloaded += len(chunk)
                if total_bytes:
                    print(f"\rDownloaded {min(1.0, downloaded / total_bytes):.0%}", end="", flush=True)
        print()
        if total_bytes is not None and downloaded != total_bytes:
            raise ValueError(f"Incomplete transfer: expected {total_bytes} bytes, received {downloaded} bytes.")
        if digest.hexdigest().lower() != DATASET_MD5:
            raise ValueError(
                "The downloaded file's MD5 checksum does not match the published value."
            )
        partial.replace(target)
        print(f"Downloaded and verified: {target}")
        return target
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()
