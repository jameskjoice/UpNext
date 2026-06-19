from setuptools import setup

APP      = ["upnext.py"]
APP_NAME = "UpNext"

OPTIONS = {
    "argv_emulation": False,
    "iconfile": "resources/UpNext.icns",
    "plist": {
        "CFBundleName":               APP_NAME,
        "CFBundleDisplayName":        APP_NAME,
        "CFBundleIdentifier":         "com.james.upnext",
        "CFBundleVersion":            "3.0.0",
        "CFBundleShortVersionString": "3.0",
        "NSCalendarsUsageDescription":
            "UpNext reads your calendar to show today's meetings.",
        "NSCalendarsFullAccessUsageDescription":
            "UpNext reads your calendar to show today's meetings.",
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "© 2026 James Joice. All rights reserved.",
    },
    "packages": ["EventKit", "Foundation", "AppKit", "WebKit"],
    "includes": [
        "objc",
        "EventKit",
        "Foundation",
        "AppKit",
        "WebKit",
        "CoreFoundation",
    ],
}

setup(
    app=APP,
    name=APP_NAME,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
