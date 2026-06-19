# UpNext — Project Notes

## What it is
macOS menu bar app that shows today's calendar events in a clean popover.
Built with Python + pyobjc (AppKit, EventKit, WebKit). No Google API — reads directly from macOS Calendar app (synced Google Calendar).

## Location
- **Source:** `/Users/james.joice/Claude/Claude Projects/UpNext/upnext.py`
- **Built app:** `/Users/james.joice/Claude/Claude Projects/UpNext/dist/UpNext.app`
- **Python venv:** `~/Claude/calendar_bar_env/`

## How to rebuild
```bash
cd "/Users/james.joice/Claude/Claude Projects/UpNext"
rm -rf build dist
/Users/james.joice/Claude/calendar_bar_env/bin/python setup.py py2app
pkill -f UpNext
open dist/UpNext.app
```

## How to share
Right-click `UpNext.app` in Finder → Compress → send the `.zip`.  
Recipient: unzip, if macOS blocks it go to **System Settings → Privacy & Security → Open Anyway**.  
They must also add Google Calendar via **System Settings → Internet Accounts** for events to appear.

## Features
- Menu bar calendar icon with today's date (updates automatically at midnight)
- **Left-click** opens popover: greeting (Good morning/afternoon/evening, **Name**), date, calendar card, events
- **Right-click** opens context menu: Preferences / Get Info / Quit UpNext
- **Get Info** shows version + copyright (© 2026 James Joice)
- Calendar: click any date to see that day's events; `‹` / `›` to navigate months (fetches prev + current + next month on open)
- Year progress bar: "49.3% of 2026 · 186 days left" — always reflects today regardless of browsed month
- Calendar dates shown as rounded squares (today = filled blue square)
- Calendar floats as an elevated card (white bg + shadow) over the popover background
- Today's events grouped: Earlier / Now / Starting soon / Later today
- Active (Now) events rendered as elevated cards with shadow
- **TODAY** label shown as a blue pill badge
- Other days: flat chronological list
- Clicking an event with a Meet/Zoom link opens it directly (↗ arrow indicates clickable)
- Light/Dark/System appearance via Preferences (right-click → Preferences)
- Light mode uses `#F2F2F7` (Apple system off-white), not plain white
- Popover is 240px wide, max 520px tall; events pane scrolls when content overflows
- Refreshes every 60 seconds

## Copyright
`setup.py` plist includes `NSHumanReadableCopyright: © 2026 James Joice. All rights reserved.`  
Visible in Finder → Get Info on the `.app` file, and via right-click → Get Info in the app itself.

## Key technical details
- **NSDate timezone fix:** `_NS_EPOCH_UNIX = 978307200`, use `datetime.fromtimestamp(ns + epoch)`
- **Theming:** CSS class `html.dark` injected at render time — NOT `@media (prefers-color-scheme)` which doesn't react to pyobjc NSAppearance changes
- **Calendar rendering:** fully JS-driven (`renderCalendar()`, `init()`) — Python only embeds events JSON
- **WKWebView background:** `setValue_forKey_(NSColor.clearColor(), "backgroundColor")` + `setUnderPageBackgroundColor_(clearColor)`
- **pyobjc rules:** methods called as ObjC selectors need trailing `_` and a `sender` param; pure Python helpers inside NSObject subclasses need `@objc.python_method` decorator
- **Right-click detection:** `btn.sendActionOn_(NSEventMaskLeftMouseUp | NSEventMaskRightMouseUp)` then check `NSApp.currentEvent().type() == NSEventTypeRightMouseUp`
- **Context menu:** `NSMenu.popUpContextMenu_withEvent_forView_()` — menu items need `setEnabled_(True)` explicitly
- **Calendar card:** `.cal-wrap` uses `background: var(--card-bg)`, `border-radius: 12px`, `box-shadow`
- **Active event card:** `.ev.active-card` elevated with shadow, applied to "now" status events only

## Known quirks
- First launch asks for Calendar permission — expected macOS behaviour
- App is not notarized; recipients need to allow via Privacy & Security on first open
- If multiple icons appear in menu bar, run `pkill -f UpNext` in Terminal to kill all instances
