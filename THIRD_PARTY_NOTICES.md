# Third-party notices

Plugin code: MIT, see LICENSE.

## Bundled HTML parser

The backend includes CPython 3.11.17's pure-Python HTML parser, entity table, HTML helpers and markup base under the private `_helix_html` and `_helix_markupbase` module names. Decky's frozen Python omits these standard-library modules. Only internal import names were changed to avoid modifying or shadowing the host's libraries. Upstream copyright and license terms remain separate from this project's MIT license. The full [CPython license](licenses/cpython-3.11.17-LICENSE.txt), source URLs, original and modified hashes, and change summary are included in [the provenance record](licenses/cpython-3.11.17-PROVENANCE.json). Both distributions include these notices.

## Components included in the frontend

The distributable includes the following code and icon data in `dist/index.js`. Their licenses remain separate from the plugin's MIT license.

### Decky API 1.1.3

The bundled connection glue originates from `@decky/api` 1.1.3 by the SteamDeckHomebrew Team, licensed under GNU LGPL version 2.1. The exact license shipped with that dependency is included as [licenses/decky-api-LGPL-2.1.txt](licenses/decky-api-LGPL-2.1.txt).

Unmodified corresponding library source from the installed package is included in [licenses/decky-api-1.1.3-source](licenses/decky-api-1.1.3-source). The library was bundled and tree-shaken by Rollup; its source files were not modified. Source and rebuild information is in [the source README](licenses/decky-api-1.1.3-source/README.md). Upstream: [SteamDeckHomebrew/loader-api](https://github.com/SteamDeckHomebrew/loader-api). The exact published package is available from [the npm 1.1.3 package archive](https://registry.npmjs.org/@decky/api/-/api-1.1.3.tgz).

Users may modify the library and rebuild the combined frontend for their own use. Reverse engineering for debugging modifications to the LGPL-covered library is permitted. This notice does not place third-party library code under the plugin's MIT license.

### React Icons 5.3.0

The bundled React icon rendering helpers are from `react-icons` 5.3.0. Copyright 2018 kamijin_fanta. They are MIT licensed. The package's exact copyright, permission and icon-license notices are included as [licenses/react-icons-LICENSE.txt](licenses/react-icons-LICENSE.txt). Upstream: [react-icons/react-icons](https://github.com/react-icons/react-icons), [published 5.3.0 package](https://registry.npmjs.org/react-icons/-/react-icons-5.3.0.tgz).

### Font Awesome Free 5: adjust icon

The plugin's `FaAdjust` icon comes from the **adjust** SVG in Font Awesome Free 5, by Fonticons, Inc. React Icons identifies its Font Awesome 5 source version as `5.15.4-3-gafecf2a`. The SVG icon is licensed under [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/). Source: [Font Awesome adjust SVG](https://github.com/FortAwesome/Font-Awesome/blob/5.15.4/svgs/solid/adjust.svg), [Font Awesome project](https://github.com/FortAwesome/Font-Awesome).

The SVG path is represented as a React component by React Icons and displayed with the plugin's size/color styling. No endorsement by Fonticons is implied. The Font Awesome license notice is included as [licenses/font-awesome-free-5-LICENSE.txt](licenses/font-awesome-free-5-LICENSE.txt); the full CC BY 4.0 legal text is included as [licenses/CC-BY-4.0.txt](licenses/CC-BY-4.0.txt). This release includes SVG icon data, not Font Awesome font files.

## Host-provided and build-only dependencies

React, React DOM and `@decky/ui` are provided by the Steam/Decky runtime as external globals and are not copied into this plugin ZIP. `@decky/rollup` is the build configuration helper, not bundled application code. Their upstream licenses still govern their own distributions. The ZIP contains only the selected bundled frontend, backend source, documentation and explicitly listed license/source files.

## Downloaded game components and local preparation

HelixSR is downloaded from [lonewolf0622/HelixSR](https://github.com/lonewolf0622/HelixSR). It is not bundled. Downloaded packages retain their HelixSR freeware license, Apache 2.0 setup-script license, OptiScaler GPL 3.0 notices, fakenvapi MIT notices and AMD FidelityFX notices. The build-only adapter truncates only the Apache-licensed shell setup before its interactive game-install stage; all upstream release files remain available alongside the generated network. The modified adapter is temporary and not distributed.

NVIDIA DLSS and generated network files remain subject to NVIDIA's license. Generated weights/kernels are private local installation assets and are excluded from the plugin ZIP and diagnostic exports. No compiled HelixSR binary is reverse engineered or patched by this plugin.
