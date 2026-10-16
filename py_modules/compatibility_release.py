"""Explicit HelixSR 1.8.1 compatibility release policy.

The managers support the reviewed HelixSR 1.8.1 recipe only. Upstream 1.9.x
changed the converter manifest, the Scaler tree and the licensing terms, so a
newer "latest" release is rejected instead of silently falling back. The pinned
1.8.1 identity applies only after the user explicitly selects compatibility.

This module is pure: no network, cache, filesystem or clock access.
"""

import re
from collections.abc import Mapping

LATEST_CHOICE = "latest"
COMPATIBLE_CHOICE = "compatible-1.8.1"
COMPATIBLE_VERSION = "1.8.1"
COMPATIBLE_METADATA_SOURCE = "reviewed-compatibility-release"

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
    """Normalize a release selection; only 'latest' or the compatibility choice."""
    if value is None:
        return LATEST_CHOICE
    if isinstance(value, str) and value in (LATEST_CHOICE, COMPATIBLE_CHOICE):
        return value
    raise ValueError(
        f"Unsupported HelixSR release selection {value!r}; "
        f"use {LATEST_CHOICE!r} or {COMPATIBLE_CHOICE!r}."
    )


def compatible_release():
    """Return a new, independent dict describing the pinned 1.8.1 release."""
    return dict(_IDENTITY + _DESCRIPTIVE)


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
    """Reject latest releases newer than the reviewed 1.8.1 recipe.

    Supported releases are returned unchanged; existing recipe and output
    guards in the manager still apply afterwards.
    """
    if not isinstance(release, Mapping):
        raise ValueError("Latest HelixSR release metadata must be a mapping.")
    version = release.get("version")
    if parse_version(version) > _COMPATIBLE_TUPLE:
        raise ValueError(
            f"Latest HelixSR {version} is not supported: HelixSR 1.9 and later "
            "changed the installer, converter manifest and Scaler layout, which "
            "this manager has not reviewed. Select 'Compatible HelixSR "
            f"{COMPATIBLE_VERSION}' explicitly to install the reviewed release."
        )
    return release
