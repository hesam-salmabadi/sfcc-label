"""Move only the first, superseded UQAM iButton imports to a recoverable archive."""

from pathlib import Path


def main() -> None:
    root = Path("/Volumes/Expansion/sfcc-label-data")
    archive = root / "archive/uqam_ibutton_nearest_hour_20260926"
    names = ("bj", "fm", "kj")
    sources = []
    for code in names:
        sources.extend((root / f"standardized/uqam_ibutton_{code}",
                        root / f"metadata/uqam_ibutton_{code}_sensors.csv",
                        root / f"metadata/uqam_ibutton_{code}_context.csv"))
    if archive.exists() or any(not path.exists() for path in sources):
        raise ValueError("archive already exists or an expected first-pass import is absent")
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
    print(f"Archived {len(moved)} superseded first-pass outputs at {archive}")


if __name__ == "__main__":
    main()
