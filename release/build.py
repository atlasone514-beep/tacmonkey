"""Build a TACMonkey release: build/dist/TACMonkey-Setup-<version>.exe (+ SHA256SUMS.txt).

    set TAC_GAME=<game folder, with BepInEx be.793 and the patched loader installed>
    python release/build.py

Needs PyInstaller (pip install pyinstaller) and the .NET 8 SDK ("dotnet" on PATH, or set DOTNET
to dotnet.exe). Steps: build the mod, package the app (PyInstaller, one folder), zip it, add the
mod + patched loader + a manifest with the checksums the setup verifies, then package the setup
as one exe.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BUILD = REPO / "build"
PAYLOAD = BUILD / "payload"

# BepInEx build the loader fix is made for (the setup downloads exactly this file)
BEPINEX = {
    "url": "https://builds.bepinex.dev/projects/bepinex_be/793/"
           "BepInEx-Unity.IL2CPP-win-x64-6.0.0-be.793%2Bdbc82f0.zip",
    "file": "BepInEx-Unity.IL2CPP-win-x64-6.0.0-be.793+dbc82f0.zip",
    "size": 34339235,
    "sha256": "5b63d7d0e92a2448ccd13b738ff95ff1cc1026c6d718555d4df8e6c824953ac4",
}
# Il2CppInterop.Generator.dll 1.5.3 (dbda1cb) as shipped in be.793, and after tools/patcher
GENERATOR = {
    "original_sha256": "95364bf2686f50d114784e482a0e78c472f6a649d07ea31a075328b2b756899d",
    "patched_sha256": "bed22f0d8a2a1ca49a2cd06f5c1bb21bda832b027d041a11f04feabdeda65e63",
}

NOTICE = """TACMonkey setup - third-party parts

TACMonkey app (TACMonkey.exe): built with PyInstaller; includes Python (PSF License),
OpenCV (Apache 2.0) and NumPy (BSD).

Il2CppInterop.Generator.dll: a modified copy of Il2CppInterop 1.5.3 (commit dbda1cb),
https://github.com/BepInEx/Il2CppInterop, licensed LGPL-3.0. The only change: in
CustomAttributeEx.Extract, SingleOrDefault is replaced by LastOrDefault, so the duplicated
dumper attributes in this game's code don't stop the generator. The patching program is in
tools/patcher of https://github.com/atlasone514-beep/tacmonkey; the original file is kept next
to it as Il2CppInterop.Generator.dll.original.

BepInEx (LGPL-2.1, https://github.com/BepInEx/BepInEx) is not included: the setup downloads
the official build from builds.bepinex.dev and checks its SHA-256.
"""


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(cmd, **kw):
    print(">", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def read_version(path, pattern):
    m = re.search(pattern, Path(path).read_text(encoding="utf-8"))
    if not m:
        sys.exit(f"version not found in {path}")
    return m.group(1)


def main():
    game = os.environ.get("TAC_GAME")
    if not game or not (Path(game) / "BepInEx" / "core").is_dir():
        sys.exit("Set TAC_GAME to the game folder (with BepInEx be.793 installed).")
    version = read_version(REPO / "app" / "farm.py", r'(?m)^VERSION = "([^"]+)"')
    mod_version = read_version(REPO / "mod" / "TACAutoTap" / "Plugin.cs",
                               r'Version = "([^"]+)"')
    app_mod = read_version(REPO / "app" / "farm.py", r'MOD_VERSION = "([^"]+)"')
    if app_mod != mod_version:
        sys.exit(f"app/farm.py MOD_VERSION is {app_mod} but the mod is {mod_version} - set them "
                 "the same, so the app's mod check matches what this setup installs.")
    dotnet = os.environ.get("DOTNET") or shutil.which("dotnet")
    if not dotnet and not os.environ.get("TAC_MOD_DLL"):
        sys.exit("dotnet not found - install the .NET 8 SDK or set DOTNET to dotnet.exe")
    print(f"TACMonkey {version}, mod {mod_version}")

    shutil.rmtree(BUILD, ignore_errors=True)
    PAYLOAD.mkdir(parents=True)

    # 1. the mod: built from source, or (TAC_MOD_DLL) an already built TACAutoTap.dll of the
    # same version, e.g. when BepInEx\interop isn't there to compile against yet
    prebuilt = os.environ.get("TAC_MOD_DLL")
    if prebuilt:
        if mod_version.encode() not in Path(prebuilt).read_bytes():
            sys.exit(f"{prebuilt} isn't TAC Auto Tap {mod_version}")
        print(f"Using the built mod {prebuilt} (SHA-256 {sha256(prebuilt)})")
        shutil.copy2(prebuilt, PAYLOAD / "TACAutoTap.dll")
    else:
        if not (Path(game) / "BepInEx" / "interop").is_dir():
            sys.exit("BepInEx\\interop is missing in TAC_GAME - start the game once so BepInEx "
                     "makes it, or set TAC_MOD_DLL to a built TACAutoTap.dll of this version.")
        run([dotnet, "build", REPO / "mod" / "TACAutoTap", "-c", "Release", "-nologo", "-v", "q",
             f"-p:Game={game}"])
        shutil.copy2(REPO / "mod" / "TACAutoTap" / "bin" / "TACAutoTap.dll", PAYLOAD)

    # 2. the patched loader, checked against the known hash
    patched = Path(game) / "BepInEx" / "core" / "Il2CppInterop.Generator.dll"
    if sha256(patched) != GENERATOR["patched_sha256"]:
        sys.exit(f"{patched} isn't the patched generator (run tools/patcher first)")
    shutil.copy2(patched, PAYLOAD)

    # 3. the app, as one folder (TACMonkey.exe + _internal), zipped. The icon: app/icon.png
    # as a multi-size .ico for the exes (shortcuts take theirs), the png for the windows
    from PIL import Image
    png = REPO / "app" / "icon.png"
    ico = BUILD / "TACMonkey.ico"
    BUILD.mkdir(exist_ok=True)
    Image.open(png).convert("RGBA").resize((256, 256), Image.LANCZOS).save(
        ico, sizes=[(n, n) for n in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
    pyi = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
           "--workpath", BUILD / "work", "--specpath", BUILD, "--icon", ico,
           "--add-data", f"{png};."]
    run(pyi + ["--windowed", "--name", "TACMonkey", "--distpath", BUILD / "app",
               "--add-data", f"{REPO / 'app' / 'genesis_shards.json'};.",
               "--add-data", f"{REPO / 'app' / 'genesis_extra.json'};.",
               REPO / "app" / "farm_ui.pyw"])
    app = BUILD / "app" / "TACMonkey"
    with zipfile.ZipFile(PAYLOAD / "app.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(app.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(app).as_posix())

    # 4. manifest + notice, then the setup as one exe
    (PAYLOAD / "manifest.json").write_text(json.dumps({
        "version": version, "mod_version": mod_version, "bepinex": BEPINEX,
        "generator": GENERATOR}, indent=2), encoding="utf-8")
    (PAYLOAD / "NOTICE.txt").write_text(NOTICE, encoding="utf-8")
    name = f"TACMonkey-Setup-{version}"
    run(pyi + ["--onefile", "--windowed", "--name", name, "--distpath", BUILD / "dist",
               "--add-data", f"{PAYLOAD};payload", REPO / "installer" / "setup.pyw"])
    exe = BUILD / "dist" / f"{name}.exe"
    shutil.copy2(PAYLOAD / "NOTICE.txt", BUILD / "dist" / "NOTICE.txt")
    (BUILD / "dist" / "SHA256SUMS.txt").write_text(f"{sha256(exe)}  {exe.name}\n", encoding="utf-8")
    print(f"\nBuilt {exe} ({exe.stat().st_size / 1e6:.1f} MB)\nSHA-256 {sha256(exe)}")


if __name__ == "__main__":
    main()
