"""Validate imported-game records without reading or changing game files."""
import os
from pathlib import Path


def normalize_imports(records):
    """Return independent valid records and bounded, non-sensitive warnings."""
    if records is None:
        return [], []
    if not isinstance(records, (list, tuple)):
        return [], ['Imported: saved game list has an invalid format']
    valid, warnings, invalid = [], [], 0
    for position, record in enumerate(records, 1):
        reason = None
        if not isinstance(record, dict):
            reason = 'entry must be an object'
        else:
            try:
                folder = os.fspath(record.get('folder'))
                if not isinstance(folder, str) or not folder or '\x00' in folder:
                    reason = 'folder must be a nonempty text path'
            except (TypeError, ValueError, OSError):
                reason = 'folder must be a valid text path'
        if reason:
            invalid += 1
            if len(warnings) < 20:
                warnings.append(f'Imported: entry {position}: {reason}')
            continue
        item = dict(record, folder=folder)
        if not isinstance(item.get('name'), str) or not item['name'].strip():
            item['name'] = Path(folder).name or 'Imported game'
        valid.append(item)
    if invalid > len(warnings):
        warnings.append(f'Imported: {invalid - len(warnings)} additional invalid entries skipped')
    return valid, warnings
