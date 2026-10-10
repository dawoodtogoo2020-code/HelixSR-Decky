# Decky API 1.1.3 corresponding source

`src/index.ts`, `src/types.ts`, `src/types.d.ts` and `package.json` are copied byte-for-byte from the installed `@decky/api` 1.1.3 npm package. They are unmodified. The complete LGPL 2.1 license is in [../decky-api-LGPL-2.1.txt](../decky-api-LGPL-2.1.txt).

Original project: [SteamDeckHomebrew/loader-api](https://github.com/SteamDeckHomebrew/loader-api). Exact published package, including its source and compiled JavaScript: [api-1.1.3.tgz](https://registry.npmjs.org/@decky/api/-/api-1.1.3.tgz).

The HelixSR Decky frontend combines the API with its own TypeScript application using the standard Decky Rollup helper. Complete application source and its build configuration are supplied in the [HelixSR Decky repository](https://github.com/dawoodtogoo2020-code/HelixSR-Decky). The dependency versions are recorded in `package.json` and `pnpm-lock.yaml` in that repository. Its README documents `pnpm install`, `pnpm typecheck` and `pnpm build`.

To rebuild with a changed API, obtain the application source, install the declared dependencies, modify/recompile this library using its TypeScript source and replace the installed `@decky/api` module with that build, then run the application build again. Rollup supplies the virtual `@decky/manifest` import from the plugin manifest. `react`, `react-dom` and `@decky/ui` remain runtime externals. The resulting `dist/index.js` can be repackaged with `python3 scripts/package.py` and installed through Decky's local ZIP picker.

The plugin license permits application modification. Modification of the API and reverse engineering for debugging such library modifications are permitted under the LGPL terms. No generated HelixSR weights, game DLLs or private device data are part of this source directory.
