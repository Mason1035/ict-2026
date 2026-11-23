"""Download the small CC BY 4.0 subsets used by public_multimodal_v1.

Data ownership remains with the original authors; no remote source code is run.
"""

import argparse
import json
from pathlib import Path
import urllib.request


def sources():
    lisa = {"Experiments.csv": 11033408, "TDR_centre_slope_measurements.csv": 11033418,
            "TDR_downslope_measurements.csv": 11033420, "TDR_upslope_measurements.csv": 11033433,
            "Tab_Note.csv": 11033427}
    for name, number in lisa.items():
        yield f"lisa/{name}", f"https://dataverse.harvard.edu/api/access/datafile/{number}?format=original"
    for number in range(1, 5):
        name = f"ProbeData_{number}.mat"
        yield f"smartstone/{name}", f"https://zenodo.org/api/records/4316597/files/{name}/content"


def fetch(destination):
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError("choose a new download directory; existing data will not be overwritten")
    destination.mkdir(parents=True)
    records = []
    for name, url in sources():
        request = urllib.request.Request(url, headers={"User-Agent": "zhifang-public-sensor-research/0.1"})
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read(5_000_001)
        if not body or len(body) > 5_000_000:
            raise ValueError(f"empty or unexpectedly large data file: {name}")
        if body.lstrip().lower().startswith((b"<!doctype html", b"<html")):
            raise ValueError(f"server returned HTML instead of sensor data: {name}")
        if name.endswith(".mat") and not body.startswith(b"MATLAB 5.0 MAT-file"):
            raise ValueError(f"not a MATLAB v5 numeric file: {name}")
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(body)
        records.append({"file": name, "url": url, "bytes": len(body), "license": "CC BY 4.0"})
    (destination / "SOURCES.json").write_text(json.dumps({"license_url": "https://creativecommons.org/licenses/by/4.0/",
        "lisa": {"authors": "Longoni, Scaioli, Panzeri, Arosio, Corti, Hojat and Papini", "doi": "10.7910/DVN/0H4AVF"},
        "smartstone": {"authors": "Dost, Gronz, Casper and Krein", "doi": "10.5281/zenodo.4316597"},
        "changes": "Selected original files downloaded without content changes.", "files": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        records = fetch(args.destination)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Download incomplete: {exc}\n")
    print(json.dumps({"status": "DOWNLOADED", "files": len(records), "destination": str(args.destination)}))
