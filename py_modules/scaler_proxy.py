"""The file name Scaler installs give OptiScaler, per game.

Scaler loads OptiScaler as dxgi.dll by default, with WINEDLLOVERRIDES="dxgi=n,b".
OptiScaler also loads under other proxy names, and some games need one of them.
Deck Wizard ran Red Dead Redemption 2 on a Steam Deck (2026-11-13) with OptiScaler
as winmm.dll, WINEDLLOVERRIDES="winmm=n,b" and SteamDeck=0, DX12 selected in the
game. For that game the plugin installs the same reviewed OptiScaler.dll from the
HelixSR release under the name winmm.dll. Nothing else changes.

An install keeps the name it was installed with. Records written before this
module existed have no proxy field and used dxgi.dll.
"""

DEFAULT = 'dxgi.dll'
NAMES = ('dxgi.dll', 'winmm.dll')

# Steam app ID -> proxy name, the extra launch environment and the evidence for it.
GAMES = {
    '1174180': dict(
        game='Red Dead Redemption 2', file='winmm.dll', env=('SteamDeck=0',), tested=False,
        evidence=('A Steam Deck tester ran Red Dead Redemption 2 with OptiScaler as winmm.dll, '
                  'WINEDLLOVERRIDES="winmm=n,b" and SteamDeck=0, with DirectX 12 selected in the game. '
                  "This plugin's own winmm.dll install has not been checked on a Steam Deck yet."),
        warnings=('Select DirectX 12 in the game before applying this launch option.',
                  'Only apply this override if you know what you are doing.')),
}


def entry(game):
    if not isinstance(game, dict) or game.get('source') != 'Steam':
        return None
    return GAMES.get(str(game.get('appid') or ''))


def for_game(game):
    """The proxy name a new Scaler install uses for this game."""
    found = entry(game)
    return found['file'] if found else DEFAULT


def recorded(rec):
    """The proxy name an existing install used."""
    name = rec.get('proxy', DEFAULT) if isinstance(rec, dict) else DEFAULT
    if name not in NAMES:
        raise ValueError('The installation record names an unknown Scaler proxy file; review it before changing files')
    return name


def chosen(game, rec):
    return recorded(rec) if rec else for_game(game)


def remap(pairs, proxy):
    """Give OptiScaler's dxgi.dll destination the chosen proxy name."""
    if proxy not in NAMES:
        raise ValueError('Unknown Scaler proxy file: ' + str(proxy))
    return tuple((source, proxy if dest == DEFAULT else dest) for source, dest in pairs)


def status(game, rec):
    """What the panel needs: the installed name, the launch option and the warnings."""
    found = entry(game)
    name = chosen(game, rec)
    needed = found['file'] if found else DEFAULT
    matches = name == needed
    return dict(file=name, dll=name[:-len('.dll')], needed=needed, mismatch=not matches,
                game=found['game'] if found else None,
                env=list(found['env']) if found and matches else [],
                warnings=list(found['warnings']) if found and matches else [],
                evidence=found['evidence'] if found else None,
                tested=bool(found and found['tested']))
