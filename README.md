# UpNext

A clean macOS menu bar app that shows your calendar events at a glance.

![macOS](https://img.shields.io/badge/macOS-12%2B-black) ![Version](https://img.shields.io/badge/version-3.3-blue)

---

## What it does

Click the calendar icon in your menu bar to see today's meetings — greeting, date, a monthly calendar, and your events grouped by what's happening now vs. later.

## Features

- **Menu bar icon** with today's date, updates at midnight
- **Countdown pill** — shows meeting name + time remaining when a meeting is active or starting within 30 min
- **Left-click** — opens popover with greeting, calendar, and events
- **Right-click** — Preferences / Refresh / Get Info / Quit
- **Events grouped:** Now → Starting Soon → Later Today → Earlier
- **Next Up card** — highlights the next upcoming event with countdown
- **Pending events** shown with a subtle stripe pattern (not yet accepted)
- **Declined events** hidden automatically
- **Zoom links** open directly in the Zoom app
- **Google Meet links** open in Chrome
- **Microsoft Teams links** open in the Teams app
- **Right-click event** — copy join link, or open in Google Calendar
- **Year progress** — shows % of year gone and days remaining
- **Calendar card** — browse any month, click dates to see events
- **TODAY pill** badge on today's date
- **Light / Dark / System** appearance (right-click → Preferences)
- **Accent color** picker — blue, red, green, yellow
- **Show/hide all-day events** toggle in Preferences
- **Pill font** — Rounded or Mono (Preferences)
- **Pill style** — Light or Dark pill (Preferences)
- Refreshes every 30 seconds

## Installation

1. Download `UpNext-v3.3.zip` from [Releases](../../releases/latest)
2. Unzip and move `UpNext.app` to your Applications folder
3. Double-click to open
4. If macOS blocks it: **System Settings → Privacy & Security → Open Anyway**
5. Grant Calendar access when prompted

> **Google Calendar users:** Make sure Google Calendar is linked in **System Settings → Internet Accounts** — UpNext reads from macOS Calendar, not Google directly.

## Usage

| Action | Result |
|--------|--------|
| Left-click icon | Open / close popover |
| Right-click icon | Context menu |
| Click event with ↗ | Join Zoom, Meet, or Teams |
| Right-click event | Copy join link / open in Google Calendar |
| Click calendar date | See that day's events |
| `‹` / `›` arrows | Navigate months |

## Requirements

- macOS 12 or later
- Google Calendar synced via macOS Internet Accounts (or any macOS Calendar)

---

© 2026 James Joice. All rights reserved.
