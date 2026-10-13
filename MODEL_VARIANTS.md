# HelixSR models and future variants

Both interfaces use the same model registry and installation engine. The **HelixSR model** dropdown shows reviewed, supported choices. The selected game's details show the installed model; older installations whose source cannot be proven show **Model unverified**.

1. Update the Decky plugin through **Plugin updates**, or the desktop app through **App updates**.
2. Select your game, then choose a supported **HelixSR model**.
3. Choose **Install HelixSR** or **Update HelixSR**, check the model, release and changed files, then confirm. Wait for completion before launching the game.

Only **HelixSR Model E, sourced from NVIDIA DLSS 310.7.0**, is supported by this release. There is no selectable DLSS 4 network, FSR-derived network, or independently verified legacy “DLSS 3.7” model. Those choices require actual upstream artifacts, licensing, conversion and installation support. Fetching an official release alone does not establish that a new network is compatible.

[HelixSR 1.8.1](https://github.com/lonewolf0622/HelixSR/releases/tag/v1.8.1) adds an experimental native DLSS input loader using the same network as 1.8.0. That is an input route, not a DLSS 4 model. This app continues to use its reviewed native FSR replacement and OptiScaler routes. It does not install the experimental loader.

Game input, model, release version and frame generation are separate. A model selection does not enable frame generation or change its settings. Existing configuration and original game-file ownership are preserved through the transaction engine. **Enable** restores the recorded package; **Update** is an explicit reviewed change. Unknown model recipes stop before building or writing game files, with guidance to check for an app update.

## Adding a new upstream model

Maintainers must review and test the actual upstream release before adding its registry entry. A network name in release notes is insufficient.

* Identify its source network, license, required GPU capabilities, supported input routes and output layout. Do not infer a model from an OptiScaler menu label or release number.
* Review the complete conversion recipe, dependency source identities and build adapter. Model E currently checks 40 conversion/wrapper files, canonical weight identity, the generated manifest, kernel table and x64 FidelityFX DLL interface. A same-version archive replacement remains size/digest-verified; unchanged reviewed recipes can still prepare without a hardcoded download size.
* Add an explicit adapter and model identity, independent of semantic release version. Cache and review identities include the selected model, recipe, release digest and payload hashes. Additional variants use the versioned shared index and a separate settings namespace, and must not be published through the legacy default-model cache pointer.
* Support the union of old and new owned file paths transactionally before changing layouts or routes. Test failure rollback, baseline restoration, cache isolation, consent/review drift and frame-generation/configuration retention.
* Validate both frontends and target hardware. Require users to upgrade both managers before a new model is managed on a shared library. Document hardware/runtime evidence separately from static compatibility and source tests.

Reviewed Model E source recipes cover the official 1.7.0, 1.8.0 and 1.8.1 layouts. Recipe identities are in `py_modules/model_variants.py`; generated NVIDIA-derived assets are never included in app downloads or this repository.

Decky 0.1.22 also recognizes the reviewed replacement of the official 1.8.1 archive. Its converter adds advice and configuration handling in the embedded-output installer branch, which this app skips by requesting `--separate-files`. All 40 recipe files were compared with the prior reviewed archive; only that converter changed. The replacement has its own exact recipe fingerprint. Unknown changes still stop preparation, and downloaded archive and generated model checks remain required.
