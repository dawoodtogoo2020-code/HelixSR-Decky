"""Reviewed release choices, independent of upstream latest discovery."""

import re
from collections.abc import Mapping

LATEST_CHOICE = "latest"
COMPATIBLE_CHOICE = "compatible-1.8.1"
COMPATIBLE_VERSION = "1.8.1"
COMPATIBLE_METADATA_SOURCE = "reviewed-compatibility-release"
REVIEWED_CHOICES = ('reviewed-2.0.0', 'reviewed-1.9.3', COMPATIBLE_CHOICE)
RECOMMENDED_CHOICE = 'reviewed-2.0.0'

_UNSUPPORTED_FROM = (1, 9, 0)
_COMPATIBLE_TUPLE = (1, 8, 1)

# Immutable pinned identity of the official v1.8.1 asset.
_IDENTITY = (
    ("version", COMPATIBLE_VERSION),
    ("url", "https://github.com/lonewolf0622/HelixSR/releases/download/v1.8.1/HelixSR-1.8.1.zip"),
    ("page", "https://github.com/lonewolf0622/HelixSR/releases/tag/v1.8.1"),
    ("sha256", "abab32b16acf2536b39663763c355f3cfd35c4876c90297d6b5481bd9ad03a19"),
    ("size", 55766339),
)
_DESCRIPTIVE = (
    ("metadata_source", COMPATIBLE_METADATA_SOURCE),
    ("license_url", "https://github.com/lonewolf0622/HelixSR/blob/v1.8.1/LICENSE"),
)

_VERSION_RE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


def selection(value=None):
    """Normalize an explicit, known release selection."""
    if value is None:
        return LATEST_CHOICE
    if isinstance(value, str) and value in (LATEST_CHOICE,) + REVIEWED_CHOICES:
        return value
    raise ValueError(
        f"Unsupported HelixSR release selection {value!r}; "
        "choose Latest or one of the reviewed releases."
    )


def compatible_release():
    """Return a new, independent dict describing the pinned 1.8.1 release."""
    return dict(_IDENTITY + _DESCRIPTIVE)


def reviewed_release(choice):
    """Return the immutable identity of an explicitly selected reviewed release."""
    choice = selection(choice)
    if choice == COMPATIBLE_CHOICE:
        return compatible_release()
    if choice == 'reviewed-2.0.0':
        import helix20_release as adapter
    elif choice == 'reviewed-1.9.3':
        import modern_release as adapter
    else:
        raise ValueError('Latest requires current upstream metadata')
    return dict(version=adapter.MODERN_VERSION, url=adapter.RELEASE_URL,
                page=adapter.RELEASE_PAGE, sha256=adapter.RELEASE_SHA256,
                size=adapter.RELEASE_SIZE, metadata_source='reviewed-release',
                license_url=f'https://github.com/lonewolf0622/HelixSR/blob/v{adapter.MODERN_VERSION}/LICENSE')


def release_choices():
    """Display choices without downloading or changing an installation."""
    choices = []
    for choice in REVIEWED_CHOICES:
        release = reviewed_release(choice)
        recommended = choice == RECOMMENDED_CHOICE
        suffix = 'recommended' if recommended else 'older release'
        choices.append(dict(id=choice, label=f"HelixSR {release['version']} ({suffix})",
                            version=release['version'], page=release['page'],
                            recommended=recommended))
    choices.append(dict(id=LATEST_CHOICE, label='Latest upstream (check for newer)', version=None,
                        page='https://github.com/lonewolf0622/HelixSR/releases', recommended=False))
    return choices


def release_status(release):
    """Expose compatibility without confusing discovery with install eligibility."""
    result = dict(release) if isinstance(release, Mapping) else {}
    try:
        if result.get('error') or not result.get('version'):
            raise ValueError(result.get('error') or 'Check the release before installing.')
        require_supported_latest(result)
    except (ValueError, TypeError) as error:
        result.update(supported=False, support_reason=str(error))
    else:
        result.update(supported=True, support_reason='')
    return result


def validate_compatible_release(value):
    """Verify a release mapping carries the exact pinned 1.8.1 identity."""
    if not isinstance(value, Mapping):
        raise ValueError("Compatible HelixSR release metadata must be a mapping.")
    for key, expected in _IDENTITY:
        actual = value.get(key)
        if type(actual) is not type(expected) or actual != expected:
            raise ValueError(
                f"Compatible HelixSR release {key} {actual!r} does not match the "
                f"reviewed 1.8.1 asset; refusing to accept a replaced or different archive."
            )
    for key, expected in _DESCRIPTIVE:
        if key in value and value[key] != expected:
            raise ValueError(
                f"Compatible HelixSR release {key} {value[key]!r} does not match "
                f"the reviewed value {expected!r}."
            )
    return dict(value)


def parse_version(value):
    """Parse a strict MAJOR.MINOR.PATCH version into an int tuple."""
    match = _VERSION_RE.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise ValueError(
            f"Malformed HelixSR release version {value!r}; expected MAJOR.MINOR.PATCH."
        )
    return tuple(int(part) for part in match.groups())


def require_supported_latest(release):
    """Reject releases whose package identity and preparation are unsupported.

    Supported releases are returned unchanged; existing recipe and output
    guards in the manager still apply afterwards.
    """
    if not isinstance(release, Mapping):
        raise ValueError("Latest HelixSR release metadata must be a mapping.")
    version = release.get("version")
    if version == "2.0.0":
        from helix20_release import validate_release
        validate_release(release)
        return release
    if version == "1.9.3":
        from modern_release import validate_release
        validate_release(release)
        return release
    if parse_version(version) > _COMPATIBLE_TUPLE:
        raise ValueError(
            f"Latest HelixSR {version} was detected but its package format is not yet reviewed. "
            "Check for a plugin update before installing it. Your installed files are unchanged. "
            "Select 'HelixSR 2.0.0 (recommended)' to use the supported package."
        )
    return release
