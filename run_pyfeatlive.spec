# -*- mode: python ; coding: utf-8 -*-

import os

site_package_path = (
    "/Users/lukechang/opt/anaconda3/envs/pyfeatlive/lib/python3.11/site-packages"
)
icon_path = "/Users/lukechang/Github/pyfeat-live/logos/pyfeat_logo_green.icns"

block_cipher = None

a = Analysis(
    ["run_pyfeatlive.py"],
    pathex=[],
    binaries=[
        ("/opt/homebrew/Cellar/ffmpeg/6.1.1_1/bin/ffmpeg", "."),
        ("/opt/homebrew/Cellar/opus/1.4/lib/libopus.0.dylib", "."),
        ("/opt/homebrew/Cellar/opus/1.4/lib/libopus.dylib", "."),
        (
            "/System/Volumes/Data/Users/lukechang/opt/anaconda3/envs/pyfeatlive/lib/libblosc2.dylib",
            ".",
        ),
        ("/Users/lukechang/opt/anaconda3/lib/libz.1.dylib", "."),
    ],
    datas=[
        ("pyfeatlive", "./pyfeatlive"),
        (
            os.path.join(
                site_package_path, "altair/vegalite/v5/schema/vega-lite-schema.json"
            ),
            "./altair/vegalite/v4/schema/",
        ),
        ("/Users/lukechang/Github/py-feat/feat", "./feat"),
        (os.path.join(site_package_path, "streamlit/static"), "./streamlit/static"),
        (os.path.join(site_package_path, "streamlit/runtime"), "./streamlit/runtime"),
        (os.path.join(site_package_path, "streamlit_webrtc"), "./streamlit_webrtc"),
        (os.path.join(site_package_path, "aiortc"), "./aiortc"),
        (os.path.join(site_package_path, "aioice"), "./aioice"),
        (os.path.join(site_package_path, "pyee"), "./pyee"),
        (os.path.join(site_package_path, "ifaddr"), "./ifaddr"),
        (os.path.join(site_package_path, "dns"), "./dns"),
        (os.path.join(site_package_path, "google"), "./google"),
        (os.path.join(site_package_path, "google_crc32c"), "./google_crc32c"),
        (os.path.join(site_package_path, "pylibsrtp"), "./pylibsrtp"),
        (os.path.join(site_package_path, "watchdog"), "./watchdog"),
        (os.path.join(site_package_path, "kaleido"), "./kaleido"),
        # (os.path.join(site_package_path, "feat"), "./feat"),
        # (os.path.join(site_package_path, "feat/resources"), "./feat/resources"),
        (os.path.join(site_package_path, "kornia"), "./kornia"),
        (os.path.join(site_package_path, "xgboost"), "./xgboost"),
        (os.path.join(site_package_path, "torch"), "./torch"),
        (os.path.join(site_package_path, "torchvision"), "./torchvision"),
        (os.path.join(site_package_path, "PIL"), "./PIL"),
        (os.path.join(site_package_path, "sklearn"), "./sklearn"),
        (os.path.join(site_package_path, "scipy"), "./scipy"),
        (os.path.join(site_package_path, "matplotlib"), "./matplotlib"),
        (os.path.join(site_package_path, "mpl_toolkits"), "./mpl_toolkits"),
        (os.path.join(site_package_path, "nltools"), "./nltools"),
        (os.path.join(site_package_path, "nilearn"), "./nilearn"),
        (os.path.join(site_package_path, "nisext"), "./nisext"),
        (os.path.join(site_package_path, "nibabel"), "./nibabel"),
        (os.path.join(site_package_path, "seaborn"), "./seaborn"),
        (os.path.join(site_package_path, "pynv"), "./pynv"),
        (os.path.join(site_package_path, "tables"), "./tables"),
        (os.path.join(site_package_path, "deepdish"), "./deepdish"),
        (os.path.join(site_package_path, "h5py"), "./h5py"),
    ],
    hiddenimports=[
        "streamlit",
        "audioop",
        "mpl_toolkits",
        "mpl_toolkits.axes_grid1.anchored_artists",
        "tables",
        "modulefinder",
        "PIL",
        "html.parser",
        "torch",
        "torchvision",
        "kornia",
    ],
    hookspath=["./hooks"],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="run_pyfeatlive",
    icon=icon_path,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity="Developer ID Application: Luke  Chang (S368GH6KF7)",
    entitlements_file=None,
)

# app = BUNDLE(
#     exe,
#     name="PyFeatLive.app",
#     icon=icon_path,
#     bundle_identifier=None,
#     version="0.0.1",
#     info_plist={
#         "NSPrincipalClass": "NSApplication",
#         "NSAppleScriptEnabled": False,
#         "CFBundleDocumentTypes": [
#             {
#                 "CFBundleTypeName": "My File Format",
#                 "CFBundleTypeIconFile": icon_path,
#                 "LSItemContentTypes": ["com.cosanlab.pyfeatlive"],
#                 "LSHandlerRank": "Owner",
#             }
#         ],
#     },
# )
