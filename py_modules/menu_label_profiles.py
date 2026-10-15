"""Conservative native-menu candidates; manager owns files and restoration.

Synthetic validation of this transform does not prove an installed game build
uses this resource. No filesystem, network, or game-state operations occur here.
"""
import re
import xml.etree.ElementTree as ET
from xml.parsers import expat

LABEL = 'Helix SR'
WITCHER_XML = 'bin/config/r4game/user_config_matrix/pc/graphics.xml'
MAX_XML_BYTES = 128 * 1024
_FSR_LABELS = frozenset(('AMD FSR Upscaling', 'AMD FSR 2', 'AMD FSR 3',
                         'AMD FSR 3.1', 'FSR 2', 'FSR 3', 'FSR 3.1'))
_ATTR = re.compile(rb'''\s+([A-Za-z_:][A-Za-z0-9_.:-]*)\s*=\s*(["'])(.*?)\2''', re.DOTALL)


def profile_for(game: dict, route: str) -> dict:
    """Return profile availability, never a claim of runtime compatibility."""
    result = dict(id=None, supported=False,
                  reason='Verified native menu label profile unavailable for this game.',
                  path=None, label=LABEL)
    if not isinstance(game, dict):
        return result
    if game.get('source') != 'Steam' or str(game.get('appid', '')) != '292030':
        return result
    result.update(id='witcher3-fsr-native-menu-v1', path=WITCHER_XML)
    if route != 'direct':
        result['reason'] = 'The Witcher 3 menu label profile requires the direct HelixSR route.'
        return result
    result.update(supported=True,
                  reason='Checked XML transform available; exact resource layout and live game safety must still verify.')
    return result


def _tag_end(raw, start):
    """Find a real start tag's closing bracket, accounting for quoted values."""
    quote = None
    for index in range(start, len(raw)):
        byte = raw[index]
        if quote is not None:
            if byte == quote:
                quote = None
        elif byte in (34, 39):
            quote = byte
        elif byte == 62:
            return index + 1
    raise ValueError('Unterminated XML element')


def patch_witcher3(raw: bytes) -> bytes:
    """Replace only the validated FSR Option displayName's literal UTF-8 bytes."""
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_XML_BYTES:
        raise ValueError('Menu XML must be nonempty bytes no larger than 128 KiB')
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('DTD and entity declarations are forbidden')
    try:
        decoded = raw.decode('utf-8-sig', errors='strict')
        root = ET.fromstring(decoded)
    except (UnicodeError, ET.ParseError, ValueError) as exc:
        raise ValueError('Menu resource must be valid UTF-8 XML') from exc
    variables = [node for node in root.iter('Var') if node.get('id') == 'AAMode']
    if len(variables) != 1:
        raise ValueError('Expected exactly one AAMode Var')
    variable = variables[0]
    if 'nonLocalizedExceptFirst' not in {tag.strip() for tag in variable.get('tags', '').split(';')}:
        raise ValueError('AAMode Var lacks the required literal-label tag')
    arrays = list(variable.iter('OptionsArray'))
    if len(arrays) != 1 or arrays[0] not in list(variable):
        raise ValueError('Expected one direct AAMode OptionsArray')
    array = arrays[0]
    options = list(array)
    if not options or any(node.tag != 'Option' for node in options):
        raise ValueError('Unexpected OptionsArray layout')
    ids = [node.get('id') for node in options]
    if any(value is None or not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError('Missing or duplicate Option IDs')
    targets = [node for node in options if node.get('id') == '2']
    if len(targets) != 1:
        raise ValueError('Expected exactly one FSR Option id 2')
    target = targets[0]
    original = target.get('displayName')
    if original not in _FSR_LABELS:
        raise ValueError('FSR displayName is unknown or already changed without ownership')
    entries = list(target.iter('Entry'))
    if len(entries) != 1 or any(entries[0].get(key) != value for key, value in
                                (('overrideGroup', 'PostProcess'), ('varId', 'AAMode'), ('value', '5'))):
        raise ValueError('FSR Option must uniquely select PostProcess AAMode value 5')
    # Reject a target carrying nested options/variables rather than a scalar
    # choice. Entry may have a conventional Entries wrapper.
    if any(node.tag not in ('Option', 'Entries', 'Entry') for node in target.iter()):
        raise ValueError('Unexpected FSR Option child layout')
    if any(node is not target and node.tag == 'Option' for node in target.iter()):
        raise ValueError('Nested FSR Options are forbidden')

    nodes = list(root.iter())
    target_ordinal = next(index for index, node in enumerate(nodes) if node is target)
    starts = []
    parser = expat.ParserCreate()
    def declaration(version, encoding, standalone):
        if encoding and encoding.lower().replace('_', '-') not in ('utf-8', 'utf8'):
            raise ValueError('Menu XML declaration must specify UTF-8')
    parser.XmlDeclHandler = declaration
    parser.StartElementHandler = lambda name, attrs: starts.append((name, parser.CurrentByteIndex))
    try:
        parser.Parse(raw, True)
    except (expat.ExpatError, ValueError) as exc:
        raise ValueError('Menu resource must be valid UTF-8 XML without alternate encodings') from exc
    if len(starts) != len(nodes) or starts[target_ordinal][0] != 'Option':
        raise ValueError('XML element identity is ambiguous')
    start = starts[target_ordinal][1]
    end = _tag_end(raw, start)
    tag = raw[start:end]
    matches = [match for match in _ATTR.finditer(tag) if match.group(1) == b'displayName']
    if len(matches) != 1:
        raise ValueError('Expected one literal displayName attribute')
    match = matches[0]
    if match.group(3) != original.encode('utf-8'):
        raise ValueError('Encoded or normalized displayName values are forbidden')
    lower, upper = start + match.start(3), start + match.end(3)
    output = raw[:lower] + LABEL.encode('utf-8') + raw[upper:]
    try:
        parsed = ET.fromstring(output.decode('utf-8-sig'))
    except (UnicodeError, ET.ParseError) as exc:
        raise ValueError('Generated menu XML failed validation') from exc
    if list(parsed.iter())[target_ordinal].get('displayName') != LABEL:
        raise ValueError('Generated menu label did not verify')
    return output
