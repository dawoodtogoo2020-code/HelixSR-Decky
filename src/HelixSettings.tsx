import { ButtonItem, DropdownItem, PanelSectionRow, ToggleField } from '@decky/ui';

export type HelixSettingsState = {
  available: boolean; reason?: string; revision?: string; provider?: string; model?: string; family?: string;
  quick_flow?: string; multiplier?: number; upscaler?: string; int8?: string; wave_size?: string; overlay?: string;
};

export function overlayDescription(overlay: string | undefined, hlx: boolean): string {
  const name = hlx ? 'HLX answers through the FSR 4 path, so it may read FSR 4.' :
    'Model E answers through the FSR 3.1 path, so it may read FSR rather than HelixSR.';
  return (overlay === 'custom' ? 'Scaler\'s FPS overlay is on without the upscaler row. ' : '') +
    `Scaler's in-game FPS overlay shows the active upscaler path. ${name} Page Up hides it in game. Close the game to save.`;
}

export function HelixSettings({ settings, disabled, save, advanced = false, toggleAdvanced }: {
  settings: HelixSettingsState; disabled: boolean; save: (changes: Record<string, string | number>) => void;
  advanced?: boolean; toggleAdvanced?: () => void;
}) {
  if (!settings.available) return <PanelSectionRow><div className="helix-muted">{settings.reason}</div></PanelSectionRow>;
  const hlx = settings.family === 'hlx-fsr';
  const select = (label: string, key: string, value: string | number | undefined,
    options: [string, string | number][], change?: (value: any) => Record<string, string | number>) =>
    <PanelSectionRow><DropdownItem label={label} disabled={disabled} selectedOption={value}
      rgOptions={options.map(([label, data]) => ({ label, data }))}
      onChange={option => save(change ? change(option.data) : { [key]: option.data })} /></PanelSectionRow>;
  return <>
    {select('Upscaler', 'upscaler', settings.upscaler,
      [...(settings.upscaler === 'unsupported' ? [['Existing custom upscaler', 'unsupported'] as [string, string]] : []),
       hlx ? ['HLX FSR 4 (FSR 4.1.2 Lite)', 'hlx-fsr'] : ['HelixSR Model E', 'helixsr'], ['AMD FSR (native)', 'fsr']])}
    {select('Frame generation', 'provider', settings.provider,
      [...(settings.provider === 'unsupported' ? [['Existing custom provider', 'unsupported'] as [string, string]] : []),
       ['Off', 'off'], ...(hlx ? [] : [['HelixSR DLSS FG', 'helixsr'] as [string, string]]), ['AMD FSR FG', 'fsr'], ['Intel XeSS FG', 'xess']],
      provider => ({ provider, multiplier: 2 }))}
    {!hlx && settings.provider === 'helixsr' && <>
      {select('Frame generation model', 'model', settings.model, [['Light (faster)', 'light'], ['Full', 'full']],
        (model): Record<string, string | number> => model === 'light' ? { model, quick_flow: 'off' } : { model })}
      {settings.model === 'full' && select('QuickFlow', 'quick_flow', settings.quick_flow,
        [['Off', 'off'], ['Fast', 'fast'], ['Fastest', 'fastest']])}
    </>}
    {['helixsr', 'fsr', 'xess'].includes(settings.provider || '') && select('Frame multiplier', 'multiplier', settings.multiplier,
      settings.provider === 'xess' ? [['2×', 2], ['3×', 3]] : [['2×', 2]])}
    <PanelSectionRow><div className="helix-muted">
      {settings.provider === 'off' ? 'Plugin frame generation is off. In-game and external frame generation are separate.' :
       settings.provider === 'helixsr' ? 'Requires DX12 and DLSS frame generation enabled in the game. If that option is missing, this route cannot generate frames.' :
       settings.provider === 'fsr' || settings.provider === 'xess' ? 'Uses the active upscaler for frame generation. Keep the game\'s own frame generation off. HUD artifacts and compatibility depend on the game.' :
       'A custom frame-generation route is configured. Select a provider to replace it.'}
      {' '}Close the game to save. Restart to apply. Saved settings do not confirm generated frames.
    </div></PanelSectionRow>
    <PanelSectionRow><ToggleField label="Show upscaler overlay in game" disabled={disabled}
      description={overlayDescription(settings.overlay, hlx)} checked={settings.overlay === 'upscaler'}
      onChange={checked => save({ overlay: checked ? 'upscaler' : 'off' })} /></PanelSectionRow>
    {!hlx && toggleAdvanced && <PanelSectionRow><ButtonItem layout="below" onClick={toggleAdvanced}>{advanced ? 'Hide advanced tuning' : 'Advanced tuning'}</ButtonItem></PanelSectionRow>}
    {!hlx && advanced && <>
      {select('INT8 math', 'int8', settings.int8, [['Automatic', 'auto'], ['On', 'on'], ['Off', 'off']])}
      {select('Wave size', 'wave_size', settings.wave_size, [['Automatic', 'auto'], ['32', '32'], ['64', '64']])}
      <PanelSectionRow><div className="helix-muted">Light and Full select the frame generation model. XeSS FG supports 3×.</div></PanelSectionRow>
    </>}
  </>;
}
