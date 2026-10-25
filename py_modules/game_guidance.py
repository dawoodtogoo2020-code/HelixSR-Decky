"""Read-only installation next steps, separate from runtime verification."""
from pathlib import PurePosixPath

DD2_GUIDE = 'https://github.com/optiscaler/OptiScaler/wiki/Dragons-Dogma-2'
PRAGMATA_GUIDE = 'https://github.com/optiscaler/OptiScaler/wiki/PRAGMATA'


def setup_guidance(game):
    report = game.get('installation_status') or {}
    ready = game.get('compatibility') == 'candidate' and report.get('can_modify', True)
    route = game.get('route')
    managed = bool(game.get('managed'))
    notes, links = [], []
    # Only an identified title gets its special instructions. A DLL named
    # dinput8.dll is not proof of REFramework, its version or a working loader.
    exe = PurePosixPath(str(game.get('selected_executable') or game.get('main_exe') or '').replace('\\', '/')).name.lower()
    dd2 = (game.get('source') == 'Steam' and str(game.get('appid')) == '2054970') or (
        exe == 'dd2.exe' and str(game.get('name', '')).casefold().replace("'", '').replace('’', '') == 'dragons dogma 2')
    if dd2 and route == 'optiscaler':
        notes.append("Dragon's Dogma 2 needs extra setup: OptiScaler's guide requires the DD2 build of REFramework (dinput8.dll). This app does not install or verify REFramework. Follow the linked game guide, including its Linux loader instructions, before launching. Do not replace an existing mod blindly. This is not a verified Steam Deck gameplay result.")
        links.append(dict(label="Dragon's Dogma 2 setup guide", url=DD2_GUIDE))
    pragmata = (game.get('source') == 'Steam' and str(game.get('appid')) == '3357650') or (
        exe == 'pragmata.exe' and str(game.get('name', '')).casefold() == 'pragmata')
    if pragmata and route == 'optiscaler':
        notes.append('PRAGMATA requires a compatible REFramework build for Scaler. Without it the game can exit during startup. This app does not install or verify that dependency. Follow the linked game guide and enable its dinput8 loader alongside dxgi on Proton. Keep existing mods and launch options. Game updates can require a newer REFramework build.')
        links.append(dict(label='PRAGMATA setup guide', url=PRAGMATA_GUIDE))
    if game.get('awareness_deferred'):
        action, headline, steps = 'inspect', 'Checking this game before installation', ['Wait for the selected game details to finish loading.']
    elif report.get('can_repair'):
        action, headline = 'repair', 'HelixSR files are missing'
        steps = ['Use Repair HelixSR files, review the missing-file list, then confirm the repair. The app will use only the exact recorded package and will not overwrite changed files.']
    elif not ready or game.get('recovery_available'):
        action, headline = 'review', report.get('label') or 'Review required'
        steps = ['Resolve the reasons shown below, then refresh this game. Selecting it does not install HelixSR.']
    elif not managed and not game.get('legacy'):
        action, headline = 'install', 'HelixSR is not installed for this game'
        steps = ['Choose Install HelixSR for this game, then confirm the file changes. Wait for installation to finish.']
        if game.get('dx12_confirmation_needed'):
            steps.insert(0, "Confirm the game actually runs in DirectX 12 for this plugin's current installation route. The checkbox and launch options cannot add DX12 to a DX11-only game.")
    elif game.get('legacy') and not managed:
        action, headline = 'adopt', 'Existing HelixSR installation needs importing'
        steps = ['Review the existing installation before managing or updating its files.']
    elif not game.get('enabled'):
        action, headline = 'enable', 'HelixSR files are installed but disabled'
        steps = ['Use Enable HelixSR to restore the installed files. This does not prove the game is using them.']
    elif route == 'optiscaler':
        override = ((game.get('optiscaler') or {}).get('setup') or {}).get('override', 'unknown')
        if override != 'correct':
            action, headline = 'launch', 'Files installed. Finish Proton launch setup'
            steps = ['Review the Proton proxy launch option below. Keep other launch options and any extra game-specific loader requirements.',
                     "For this plugin's current Scaler route, launch in DirectX 12 and select a supported DLSS, FSR or XeSS input. The input name is not the output backend."]
        else:
            action, headline = 'play', 'Files installed. Check the in-game settings next'
            steps = ["For this plugin's current Scaler route, launch in DirectX 12 and select a supported DLSS, FSR or XeSS input. Check OptiScaler is using FFX: FSR HelixSR (3.1.5)."]
    else:
        action, headline = 'play', 'Files installed. Select AMD FSR in the game'
        steps = ['This native FSR replacement does not need an OptiScaler proxy launch option.']
    if managed and game.get('enabled'):
        steps.append('Installed files are not runtime proof. The optional status overlay needs fresh HelixSR log evidence to report neural output.')
    return dict(action=action, headline=headline, steps=steps, notes=notes, links=links)
