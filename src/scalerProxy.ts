import type { OverrideDll } from "./launchOptions";

// The file name a Scaler install gives OptiScaler (py_modules/scaler_proxy.py).
export type ScalerProxy = {
  file: string; dll: string; needed: string; mismatch: boolean;
  game?: string | null; env?: string[]; warnings?: string[]; evidence?: string | null; tested?: boolean;
};

export function proxyDll(proxy?: ScalerProxy | null): OverrideDll {
  return proxy?.dll === "winmm" ? "winmm" : "dxgi";
}

// Extra NAME=value launch assignments, only for the proxy the game actually installed.
export function proxyEnv(proxy?: ScalerProxy | null): string[] {
  if (!proxy || proxyDll(proxy) !== proxy.dll || proxy.mismatch) return [];
  return (proxy.env || []).filter(a => /^[A-Za-z_][A-Za-z0-9_]*=[A-Za-z0-9_.-]*$/.test(a));
}

export function proxyTitle(proxy?: ScalerProxy | null): string {
  const dll = proxyDll(proxy);
  return dll === "dxgi" ? "Enable Proton OptiScaler proxy" : `Enable Proton OptiScaler proxy (${dll}.dll)`;
}

// The note under the launch-option button, with the tester's warnings.
export function proxyNote(proxy?: ScalerProxy | null): string | null {
  if (!proxy?.game || proxyDll(proxy) === "dxgi") return null;
  const option = [`WINEDLLOVERRIDES="${proxy.dll}=n,b"`, ...proxyEnv(proxy)].join(" ");
  return [`${proxy.game} loads Scaler as ${proxy.file}. The launch option sets ${option}.`, ...(proxy.warnings || [])].join("\n");
}
