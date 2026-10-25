import { ButtonItem, DropdownItem, PanelSectionRow } from '@decky/ui';

export type HelixSettingsState = {
  available: boolean; reason?: string; revision?: string; provider?: string; model?: string;
  quick_flow?: string; multiplier?: number; upscaler?: string; int8?: string; wave_size?: string;
};

export function HelixSettings({ settings, disabled, save, advanced = false, toggleAdvanced }: {
  settings: HelixSettingsState; disabled: boolean; save: (changes: Record<string, string | number>) => void;
  advanced?: boolean; toggleAdvanced?: () => void;
}) {
  if (!settings.available) return <PanelSectionRow><div className="helix-muted">{settings.reason}</div></PanelSectionRow>;
  const select = (label: string, key: string, value: string | number | undefined,
    options: [string, string | number][], change?: (value: any) => Record<string, string | number>) =>
    <PanelSectionRow><DropdownItem label={label} disabled={disabled} selectedOption={value}
      rgOptions={options.map(([label, data]) => ({ label, data }))}
      onChange={option => save(change ? change(option.data) : { [key]: option.data })} /></PanelSectionRow>;
  return <>
    {select('Upscaler', 'upscaler', settings.upscaler,
      [...(settings.upscaler === 'unsupported' ? [['Existing custom upscaler', 'unsupported'] as [string, string]] : []),
       ['HelixSR Model E', 'helixsr'], ['AMD FSR', 'fsr']])}
    {select('Frame generation', 'provider', settings.provider,
      [...(settings.provider === 'unsupported' ? [['Existing custom provider', 'unsupported'] as [string, string]] : []),
       ['Off', 'off'], ['HelixSR DLSS FG', 'helixsr'], ['AMD FSR FG', 'fsr'], ['Intel XeSS FG', 'xess']],
      provider => ({ provider, multiplier: 2 }))}
    {settings.provider === 'helixsr' && <>
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
    {toggleAdvanced && <PanelSectionRow><ButtonItem layout="below" onClick={toggleAdvanced}>{advanced ? 'Hide advanced tuning' : 'Advanced tuning'}</ButtonItem></PanelSectionRow>}
    {advanced && <>
      {select('INT8 math', 'int8', settings.int8, [['Automatic', 'auto'], ['On', 'on'], ['Off', 'off']])}
      {select('Wave size', 'wave_size', settings.wave_size, [['Automatic', 'auto'], ['32', '32'], ['64', '64']])}
      <PanelSectionRow><div className="helix-muted">Light and Full are frame generation models. The upscaler remains Model E. XeSS FG supports 3×.</div></PanelSectionRow>
    </>}
  </>;
}
