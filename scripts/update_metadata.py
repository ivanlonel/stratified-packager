"""Update the version field in metadata.txt with the latest version listed in the changelog."""

from pathlib import Path

from qgispluginci import (  # type: ignore[import-not-found]  # ty: ignore[unresolved-import]
    changelog,
    parameters,
    utils,
)

if __name__ == "__main__":
    try:
        latest = changelog.ChangelogParser().latest_version()
    except AttributeError as e:
        msg = "No version in the major.minor.patch format was found in the changelog."
        raise ValueError(msg) from e

    metadata_path = Path(parameters.Parameters.make_from().plugin_path) / "metadata.txt"
    utils.replace_in_file(str(metadata_path), r"^version=.*$", f"version={latest}")
    # qgis-plugin-ci rewrites the file with host-native line endings; .gitattributes pins the
    # working tree to LF, so normalize here to stop Windows runs from dirtying metadata.txt.
    metadata_path.write_text(
        metadata_path.read_text(encoding="utf-8"), encoding="utf-8", newline="\n"
    )
