"""Archive only our KJ first-floor pass before rebuilding collision averages."""

from pathlib import Path


root = Path("/Volumes/Expansion/sfcc-label-data")
archive = root / "archive/uqam_ibutton_kj_first_floor_20260926"
sources = (root / "standardized/uqam_ibutton_kj",
           root / "metadata/uqam_ibutton_kj_sensors.csv",
           root / "metadata/uqam_ibutton_kj_context.csv")
if archive.exists() or any(not path.exists() for path in sources):
    raise ValueError("archive exists or a KJ first-floor output is missing")
archive.mkdir(parents=True)
moved = []
try:
    for source in sources:
        destination = archive / source.name
        source.replace(destination)
        moved.append((destination, source))
except Exception:
    for destination, source in reversed(moved):
        destination.replace(source)
    raise
print(f"Archived {len(moved)} KJ first-floor output paths")
