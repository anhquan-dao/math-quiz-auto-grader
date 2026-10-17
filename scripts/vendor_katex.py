"""Provision pinned, integrity-checked KaTeX browser assets for offline reports."""

import argparse
import base64
import hashlib
import io
import json
import logging
import re
import tarfile
import urllib.request
from pathlib import Path

from automarker.io import configure_logging, write_json

LOG = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="0.19.0")
    args = parser.parse_args()
    configure_logging(Path("outputs/logs/vendor_katex.log"))
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        raise ValueError("Use an explicit numeric KaTeX release")
    with urllib.request.urlopen(f"https://registry.npmjs.org/katex/{args.version}",
                                timeout=60) as response:
        metadata = json.load(response)
    distribution = metadata["dist"]
    with urllib.request.urlopen(distribution["tarball"], timeout=60) as response:
        archive = response.read()
    expected = distribution["integrity"]
    actual = "sha512-" + base64.b64encode(hashlib.sha512(archive).digest()).decode("ascii")
    if actual != expected:
        raise ValueError("KaTeX package integrity mismatch")
    root = Path(__file__).resolve().parents[1] / "src/automarker/assets/katex"
    files = []
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as package:
        for member in package.getmembers():
            name = member.name
            if name in {"package/LICENSE", "package/dist/katex.min.js", "package/dist/katex.min.css"}:
                relative = Path(name).name
            elif name.startswith("package/dist/fonts/") and name.endswith(".woff2"):
                relative = "fonts/" + Path(name).name
            else:
                continue
            stream = package.extractfile(member)
            if stream is None:
                raise ValueError(f"Missing package member {name}")
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(stream.read())
            files.append(relative)
            LOG.debug("Provisioned %s", target)
    write_json(root / "provenance.json", {"name": "KaTeX", "version": args.version,
               "source": distribution["tarball"], "integrity": expected,
               "license": metadata["license"], "files": sorted(files)})
    LOG.info("Provisioned KaTeX %s: %d files", args.version, len(files))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        LOG.exception("KaTeX asset provisioning failed")
        raise
