import { DropdownItem, PanelSectionRow } from '@decky/ui';

export type HelixSettingsState = {
  available: boolean; reason?: string; revision?: string; provider?: string; model?: string;
  quick_flow?: string; multiplier?: number; upscaler?: string; int8?: string; wave_size?: string;
};

export function HelixSettings({ settings, disabled, save }: {
  settings: HelixSettingsState; disabled: boolean; save: (changes: Record<string, string | number>) => void;
}) {
  if (!settings.available) return <PanelSectionRow><div>{settings.reason}</div></PanelSectionRow>;
  const select = (label: string, key: string, value: string | number | undefined,
    options: [string, string | number][], change?: (value: any) => Record<string, string | number>) =>
    <PanelSectionRow><DropdownItem label={label} disabled={disabled} selectedOption={value}
      rgOptions={options.map(([label, data]) => ({ label, data }))}
      onChange={option => save(change ? change(option.data) : { [key]: option.data })} /></PanelSectionRow>;
  return <>
    {select('Upscaler', 'upscaler', settings.upscaler,
      [...(settings.upscaler === 'unsupported' ? [['Existing custom upscaler', 'unsupported'] as [string, string]] : []),
       ['HelixSR Model E', 'helixsr'], ['AMD FSR 3.1', 'fsr']])}
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
    {settings.provider !== 'off' && select('Frame multiplier', 'multiplier', settings.multiplier,
      settings.provider === 'xess' ? [['2×', 2], ['3×', 3]] : [['2×', 2]])}
    {select('INT8 math', 'int8', settings.int8, [['Automatic', 'auto'], ['On', 'on'], ['Off', 'off']])}
    {select('Wave size', 'wave_size', settings.wave_size, [['Automatic', 'auto'], ['32', '32'], ['64', '64']])}
    <PanelSectionRow><div className="helix-muted">Close the game to save settings, then restart it.
      HelixSR frame generation requires a DirectX 12 game with DLSS frame generation enabled in the game.
      Light and Full are frame generation models; the upscaling network remains Model E.
      3× is available through XeSS FG. Configured settings do not prove active frame generation.
      FSR 3/4 choices are also available in Scaler’s in-game menu when supported.</div></PanelSectionRow>
  </>;
}
