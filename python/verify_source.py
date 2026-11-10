"""Compare the supplied workbook with the official UCI archive."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request
from zipfile import ZipFile

from source import PROJECT, load_config, sha256


def compare_archive(local_path, archive_path):
    with ZipFile(archive_path) as archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
        if [item.filename for item in members] != ["online_retail_II.xlsx"]:
            raise ValueError("Unexpected official archive members")
        with archive.open(members[0]) as stream:
            official_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        local_hash = sha256(local_path)
        if local_hash != official_hash:
            raise ValueError("Local workbook differs from the official UCI workbook")
        return {
            "status": "Passed", "local_workbook_sha256": local_hash,
            "official_workbook_sha256": official_hash,
            "workbook_bytes": Path(local_path).stat().st_size,
            "official_member_bytes": members[0].file_size,
            "official_archive_sha256": sha256(archive_path),
            "archive_member": members[0].filename,
        }


def main():
    config = load_config()
    raw_dir = PROJECT / "data/raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    archive_path = raw_dir / "online_retail_ii_official.zip"
    request = urllib.request.Request(config["official_archive_url"], headers={"User-Agent": "R2-portfolio-source-verification/1.0"})
    with urllib.request.urlopen(request) as response, archive_path.open("wb") as target:
        status = response.status
        while chunk := response.read(1024 * 1024):
            target.write(chunk)
    result = compare_archive(PROJECT / config["source_path"], archive_path)
    result.update({
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "official_url": config["official_url"],
        "download_url": config["official_archive_url"], "http_status": status,
        "citation": "Chen, D. (2012). Online Retail II [Dataset]. UCI Machine Learning Repository.",
        "doi": "https://doi.org/10.24432/C5CG6D",
        "license": "CC BY 4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "terms_review": "Dataset page and attribution reviewed separately; this command verifies workbook identity.",
    })
    output_dir = PROJECT / "outputs"
    output_dir.mkdir(exist_ok=True)
    (output_dir / "source_verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
