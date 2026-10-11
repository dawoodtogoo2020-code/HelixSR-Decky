# Desktop third-party notices

HelixSR Desktop application source and its original icon are MIT-licensed. See LICENSE. This AppImage contains no HelixSR game DLLs, DLSS DLLs or generated HelixSR network assets. Those are obtained or generated separately on the user's device under their own terms.

The AppImage includes dynamically linked Qt for Python (PySide6-Essentials and shiboken6 6.12.0), Qt libraries and platform plugins. PySide6 is available under LGPLv3, GPLv2/GPLv3 or a commercial license. This distribution uses the open-source LGPL option for the modules it imports (QtCore, QtGui and QtWidgets). Qt and third-party notices and license texts distributed with the wheels are included under `usr/share/helixsr-desktop/licenses` in the extracted AppImage.

Corresponding upstream sources:

- [PySide/shiboken 6.12.0 sources](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/)
- [Qt 6.12 sources](https://download.qt.io/official_releases/qt/6.12/)
- [Qt open-source licensing](https://doc.qt.io/qt-6/licensing.html)
- [LGPLv3](https://www.gnu.org/licenses/lgpl-3.0.html) and [GPLv3](https://www.gnu.org/licenses/gpl-3.0.html)

You may inspect, modify and replace these libraries, including for debugging your modifications. Extract the AppImage with `./HelixSR-Desktop-0.1.0-x86_64.AppImage --appimage-extract`, replace compatible libraries in `squashfs-root/usr/bin/helixsr-desktop/_internal/PySide6/Qt/lib` and related bindings/plugins, then run `squashfs-root/AppRun`. Use matching Qt/binding ABI versions. The application does not block reverse engineering for debugging modifications to LGPL components.

Other bundled runtime components include Python under the Python Software Foundation license, PyInstaller under GPLv2 with its bootloader exception, altgraph under MIT, packaging under Apache-2.0/BSD-2-Clause, setuptools under MIT, and dependency hook notices. License texts are included with the runtime. [Python source](https://www.python.org/downloads/source/), [PyInstaller 6.22.3 source and exception](https://github.com/pyinstaller/pyinstaller/tree/v6.22.3), and [PyInstaller hooks](https://github.com/pyinstaller/pyinstaller-hooks-contrib) are publicly available.

The AppImage runtime source and license are available from [AppImage type2-runtime](https://github.com/AppImage/type2-runtime). The build tool is [appimagetool](https://github.com/AppImage/appimagetool), pinned in the build script by SHA-256. It is used during packaging, not installed as a game dependency.

Complete application source, modifications, dependency versions and build scripts are in the [desktop-v0.1.0 source release](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/tree/desktop-v0.1.0). See THIRD_PARTY_NOTICES.md for notices that apply to the separate Decky plugin.
