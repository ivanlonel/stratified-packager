"""Update the version field in metadata.txt with the latest version listed in the changelog."""

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

    utils.replace_in_file(
        f"{parameters.Parameters.make_from().plugin_path}/metadata.txt",
        r"^version=.*$",
        f"version={latest}",
    )
