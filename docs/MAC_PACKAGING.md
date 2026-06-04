# macOS Packaging

Use a local APFS checkout for signed macOS packaging. SMB, network, or Windows-mounted checkouts are fine for editing, but macOS code signing and Electron Builder are more reliable from a normal local macOS filesystem.

Recommended local shape:

```text
~/code/numquamoblita-clean
```

Run from the local macOS copy:

```bash
npm run desktop:test --prefix app/desktop
npm run desktop:pack:dir:signed --prefix app/desktop
npm run desktop:pack:mac --prefix app/desktop
codesign --verify --deep --strict --verbose=2 app/desktop/dist/mac-arm64/ModelNumquamOblita.app
```

Notes:

- `desktop:pack:dir` is the unsigned local directory build for fast validation.
- `desktop:pack:dir:signed` produces a signed app directory using Electron Builder's local signing path.
- `desktop:pack:mac` builds the distributable macOS DMG and ZIP artifacts.
- Notarization requires Apple signing identities and notarization credentials configured on the packaging machine.
- Generated `app/desktop/dist/` output should not be committed to the public repo.
