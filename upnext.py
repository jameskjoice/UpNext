#!/usr/bin/env python3
"""
UpNext — macOS menu bar app, dot-style popover.
NSStatusItem + NSPopover + WKWebView. Reads macOS Calendar via EventKit.
"""

import re, datetime, calendar, json
import objc
import AppKit
import WebKit
import EventKit
import Foundation

MEET_RE = re.compile(r'https://meet\.google\.com/[a-z0-9\-]+', re.IGNORECASE)
ZOOM_RE = re.compile(r'https://[a-z0-9.]*zoom\.us/j/[^\s<>"\']+', re.IGNORECASE)

def extract_join_link(text):
    if not text: return None
    m = MEET_RE.search(text)
    if m: return m.group(0)
    m = ZOOM_RE.search(text)
    if m: return m.group(0).rstrip(')')
    return None

# ── NSDate helpers ─────────────────────────────────────────────────────────────

_NS_EPOCH_UNIX = 978307200

def from_ns(ns):
    return datetime.datetime.fromtimestamp(
        ns.timeIntervalSinceReferenceDate() + _NS_EPOCH_UNIX)

def to_ns(dt):
    return Foundation.NSDate.dateWithTimeIntervalSinceReferenceDate_(
        dt.timestamp() - _NS_EPOCH_UNIX)

# ── EventKit ───────────────────────────────────────────────────────────────────

def _fetch_single_month(store, year, month):
    last_day = calendar.monthrange(year, month)[1]
    sod = datetime.datetime(year, month, 1, 0, 0, 0)
    eod = datetime.datetime(year, month, last_day, 23, 59, 59)
    cals = store.calendarsForEntityType_(EventKit.EKEntityTypeEvent)
    pred = store.predicateForEventsWithStartDate_endDate_calendars_(
        to_ns(sod), to_ns(eod), cals)
    raw = store.eventsMatchingPredicate_(pred) or []
    events = []
    for ev in raw:
        if ev.isAllDay(): continue
        title    = ev.title() or "Untitled"
        start    = from_ns(ev.startDate())
        end      = from_ns(ev.endDate())
        notes    = ev.notes()    or ""
        location = ev.location() or ""
        url_prop = ev.URL()
        url_str  = str(url_prop) if url_prop else ""
        cal_obj  = ev.calendar()
        color    = "#007AFF"
        if cal_obj:
            c = cal_obj.color()
            if c:
                r = int(c.redComponent()   * 255)
                g = int(c.greenComponent() * 255)
                b = int(c.blueComponent()  * 255)
                color = f"rgb({r},{g},{b})"
        join_link = extract_join_link(notes + " " + location + " " + url_str)
        events.append({
            "date":      start.strftime("%Y-%m-%d"),
            "title":     title,
            "start":     start.strftime("%-I:%M %p"),
            "end":       end.strftime("%-I:%M %p"),
            "start_dt":  start.isoformat(),
            "end_dt":    end.isoformat(),
            "color":     color,
            "join_link": join_link or "",
        })
    return events

def fetch_month_events(store):
    """Fetch prev, current, and next month events for navigation."""
    now  = datetime.datetime.now()
    y, m = now.year, now.month
    months = []
    # prev month
    pm, py = (m - 1, y) if m > 1 else (12, y - 1)
    months.append((py, pm))
    months.append((y, m))
    # next month
    nm, ny = (m + 1, y) if m < 12 else (1, y + 1)
    months.append((ny, nm))

    seen = set()
    all_events = []
    for yr, mo in months:
        for ev in _fetch_single_month(store, yr, mo):
            key = (ev["start_dt"], ev["title"])
            if key not in seen:
                seen.add(key)
                all_events.append(ev)
    all_events.sort(key=lambda e: e["start_dt"])
    return all_events

def event_status_str(ev_dict, now):
    start = datetime.datetime.fromisoformat(ev_dict["start_dt"])
    end   = datetime.datetime.fromisoformat(ev_dict["end_dt"])
    if end   < now:                              return "past"
    if start <= now:                             return "now"
    if (start - now).total_seconds() <= 900:    return "soon"
    return "later"

# ── menu bar icon ──────────────────────────────────────────────────────────────

def make_menubar_icon(day):
    W, H = 16.0, 16.0
    img  = AppKit.NSImage.alloc().initWithSize_(Foundation.NSMakeSize(W, H))
    img.lockFocus()
    black = AppKit.NSColor.blackColor()
    black.set()

    body = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        Foundation.NSMakeRect(0.5, 0.5, W - 1, H - 1), 2.5, 2.5)
    body.setLineWidth_(1.0)
    body.stroke()

    header_h = 4.5
    header = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        Foundation.NSMakeRect(0.5, H - header_h - 0.5, W - 1, header_h), 2.5, 2.5)
    sq = AppKit.NSBezierPath.bezierPathWithRect_(
        Foundation.NSMakeRect(0.5, H - header_h - 0.5, W - 1, header_h / 2))
    header.appendBezierPath_(sq)
    header.fill()

    for rx in (3.5, W - 3.5):
        ring = Foundation.NSMakeRect(rx - 0.8, H - header_h - 1.0, 1.6, 2.5)
        AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            ring, 0.8, 0.8).fill()

    label = str(day)
    font_size = 8.5 if len(label) == 1 else 7.5
    font  = AppKit.NSFont.systemFontOfSize_weight_(font_size, AppKit.NSFontWeightMedium)
    attrs = {
        AppKit.NSFontAttributeName:            font,
        AppKit.NSForegroundColorAttributeName: black,
    }
    ns_label = Foundation.NSString.stringWithString_(label)
    size     = ns_label.sizeWithAttributes_(attrs)
    body_top = 0.5
    body_h   = H - header_h - 1.5
    x = (W - size.width)  / 2
    y = body_top + (body_h - size.height) / 2 + 0.5
    ns_label.drawAtPoint_withAttributes_(Foundation.NSMakePoint(x, y), attrs)

    img.unlockFocus()
    img.setTemplate_(True)
    return img

# ── appearance ─────────────────────────────────────────────────────────────────

APPEARANCE_KEY = "UpNextAppearance"
ACCENT_KEY     = "UpNextAccent"

ACCENT_COLORS = {
    "blue":   "#007AFF",
    "red":    "#FF3B30",
    "green":  "#34C759",
    "yellow": "#FFD60A",
}

def load_accent_color():
    v = Foundation.NSUserDefaults.standardUserDefaults().stringForKey_(ACCENT_KEY)
    return v if v in ACCENT_COLORS else "blue"

def save_accent_color(name):
    Foundation.NSUserDefaults.standardUserDefaults().setObject_forKey_(name, ACCENT_KEY)

def is_system_dark():
    eff = AppKit.NSApp.effectiveAppearance()
    return eff is not None and "Dark" in str(eff.name())

def body_class(mode):
    if mode == "dark":  return "dark"
    if mode == "light": return ""
    return "dark" if is_system_dark() else ""

def load_appearance_mode():
    return (Foundation.NSUserDefaults.standardUserDefaults()
            .stringForKey_(APPEARANCE_KEY)) or "system"

def save_appearance_mode(mode):
    Foundation.NSUserDefaults.standardUserDefaults().setObject_forKey_(
        mode, APPEARANCE_KEY)

# ── helpers ────────────────────────────────────────────────────────────────────

def get_first_name():
    try:
        full = str(Foundation.NSProcessInfo.processInfo().fullUserName())
        return full.split()[0] if full.strip() else "there"
    except Exception:
        return "there"

def greeting():
    h = datetime.datetime.now().hour
    if h < 12:  return "Good morning"
    if h < 17:  return "Good afternoon"
    return "Good evening"

def _esc(s):
    return (s.replace("&","&amp;").replace("<","&lt;")
             .replace(">","&gt;").replace('"',"&quot;"))

# ── HTML ───────────────────────────────────────────────────────────────────────

CSS = """
@font-face { font-family: 'Inter'; font-weight: 400 600; src: url('data:font/woff2;base64,d09GMgABAAAAAFR4AA8AAAAA9GQAAFQWAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAGoEIG/xcHNReBmA/U1RBVEgAhTQRCAqByDyBp3ULh2YAATYCJAOPSAQgBYQWB6g+GzDfV9Bt+/UlBunNKj3AB++tqGG73kBvpmBpce1jRwaCjQNgW36b7P///xOTjSHrQHcA6Jr7an1VAwmD0zwMjkREDVSIMM0spuIeKOG7djMPKgf1BRfHPAP5V/coYojD5KPmGTC6SeOkwgp3roCnssP7u0ZQr11hlGtPqwxczEx4jkji8cCszOmTtD12mTbhSopKUA6KU5o+uJ27+jrPgdchanuXOv/He33Widn+7MeGIUzsX3w061fd7toTb9MWm19s/qVpIQg7TBzq3K43vTXi0rgZazuoLjYRiyEpf8q367qupqvft2Ppv62dgW0jf5KT1/9/mvN/n3vvTIbJRDukNNhEsAAheJCari5qpOUZNTUqbrTPrGJPjD4XnhifnwcUxdo/9ty9DzaRzJpIxUZIZkfsANjGcfkIEw0EOzzk7d8YWzNZtT7FLyKpyHXmOJdjhmHumZlhbBhmrs32EZIc57BsmCN3FyohVH586bRKpfLLL0nl//qZuN97E1sbjtKyOXHAw6Q1Rb2q/IW78Qjp91aqpfdnZ0M6Ao5wR8KdMXFxY2icfPbvW3pkX8uaGW1WBGdiEifrFJE1xSQmVcHZmEb7Voshhu7DZE2rUpeqYRjUrCn6MEU0buoPN4jBbU0xRQGzFe2AlR111mnMRLDe4o88THGJCgqY4N11UycVyxDUrbvrm6+uwCMRjuLK3h1rsNZx/xyu6aVzyQgUsAJg16lQEYaYE8b+s2nZN8d4HW0flNslL9RIaKvMCNR4eri3d+4vpaZhDJfS6AEu4AcMYVADtpT0OffZfJ0RnKSZ3UND3RxIMojIBLs7tnP3fyd9d6EKsAp34ZZI8JKqSQjAU+0H+hZub28vYRdWglwmLuxQR6NMW2UqKysBbY1DoQj+HdyALYVaWwnvQQtmHpnNpi1fu3C3337oFSSdLO9kZeSXJ2SeH0TIDJ7PxjKqapDnx3AjvvFXfTduOQPfwXWF2q8JfGIugACLrh2QZX71PpDOg2Nknu0QkKeXz5riVIMO23Y/L6K1p9PBeaX2t4mndxHs+wNDzSTz3xK0WjA/sMtr1lTov19+s/9Ob5wlDWS5tYpCIdwIv5THyEmE909NDfWHNISoZkNUf5esZkP5JCQK4XIyAqG2sBqH16C5Wjqbp7eULiMUurQyvjSdtv+0p5SqUWAv/3v39OrAKIRD4bAOp3HEIRNcHJb5/KnV/tF4nr7k+K1+0Fm0FqHoEh2RD6gp76r5M/O/NBqN/f1lZyV9e23FS4oX5Hj9Tgq86EvarKLYd/ECOwtIjo/kRSfL3B1gB9xhxVjdu/rKK69sCUoqmvqKEiHCG4fZzk50bn30aZalYQBWOCsI4oDi4f+nNfvvUi3C7XOMI979mWx7m6V3FTkHFdygetPVIhTBtcLz2YU8u/l5eFggv96tNJvhAhccK4DFwn+5SqnH6jc+hbIDjfguZXak7lzzlbNzXcUDYMrDsgCGAB7AYKy6krd65/J+vDSmY5hnbum6Un4VoFcgvwWDB4qB//CX+j53QMoCrenUnRAsywpR6Vu3rweVVmmILF/H3nyMCZnbIrgUTbe4PYVC63jq792waqNHvceB7lvKUkS8ICGIBBERkaH3vD3Cs4rk+HmodeIVZhWdngQCOP32N2RaYFxInMvIVR8gj3yKfK4RadIcSiIJlI1soKZLDTUHO9QSeaGW+yPUVpWhjhCFOqM/1FVDoZ4xGt6LboT3pTaEAKpU7bCzf4wKsF7+09cLWAkAmmEAwi777eMF9J8vbudoSWycbe5GrvwRoqBN7YkLbU5HE90QPl32PZ7pJOYa2B8rKwiCJ732noTjmh5itv2oQvCmrAbYqNbWs3w5q5/Om2H6K1QzY5iJ7dL61hlp71i3dvSc0KOZHdz+1a58vqiKvhzi65bvOKlmj7nEOcJReZibhzBSrkMXMJwiGadyn7MiZGu1xfKWpSB1hrlNTxS4Z92lcDbAoofOof4zc73v22kRJ4iK7qjOLrtQjUAoFVmNdKg9+aTcS+3u3N3KVROUtShprIp2ouI3x6IpYDU5I1q7aXMvpcQGe4DvisNKmLkipE+bcrMdapNnmzXUQP1xubIHbrq47HZbckmbZ6ykSCanb6oCgO57xu5BRdwBUFFxQD3DwaQJlCt5YUk6f1Pu0azviXLD+h5qUMoG636kWkbOVCkrmlKkDD2S9Q5ZXHwyDqituZsqjh6Vnt5QTrSGSp2ZdvIqZSRtKotkT57upUTaNrtj/BC5oUSVBHFBAh1jIvWGrIuaDI2njYFYOTaS2bD2QCVJyISInkON5lQykW7qXry64qspCWcQnRH8iXlTNMd3p2eWpLH6bHFq/80F1Taq1CBIaiMjDV+e6IiSzSuVpFRLztvy44UynjI8Op3BANYpUYEZFrv4gYve8IG7/ZJ3eDT/r3r155/+p//1PBrlXpXRv8V5E/VcYijYYX9CRValfGb7/w0BvreNYXRSbi3rN4Xi1bpmzwKQkMivSBKrWgoEQmmcaZEW6rxG8QqwhHff5jwNzNosCGfP9xnjc4V3edZzekgNU5pgRdGjcYpFtnRkBsTyzXUhhGhYodbQW9JiKl8bN/iPzLuS1yFyJWvmQS1NcPZb3eAo0GHvbyGuVjPiWD2WRq6af8f3wQU7+5G10p4/KgtceJVWj1rpa5m9kl/p5aV49G9FTov9K+zIInr64FmqOey7bqMaCQ7XcaJagqieZ78OLq97r7301Ij5xt4GWnSF6IwXqS47DuyLuY4JvmdYah0Crj4gcu25Wh5bDYNrRsJw1cNrafsq8OWYfYjcnfdTOlEPiskbR6ELlP2SgZpiX2T2WqhuBSTvuWfkuAjlUuJQkWsAd1Ag28MVcxTftjI5x0myaHjUEhYFQq46PKfuI0YkfoIQFgaLT/KaOt/HHut9K93Zir2Il3d7nPrVSzR7zvOdn3uPKcs8TrfDrCGghpyKx4+2uvsuAA10uE07HvZzerRb4+wWZ4/aCL5ffji6VSH2L3cpP14aEJiF91in7XOo88fQwnwEQjFozp6H2hDh22hQb532FFYXR4ohN5Bj43aoNkY/Dq1IMweMvQrGXoaELC3wyhfoKss11YsZswF8VJRXBeXDc/kzpVUQDYWeJft5Ch6v38BjrzAy92y690XRz0FdRZIzklVOwiEMHLuHYZXdKpo4VFf6eLKmYBgIU4f4akCFFn4ny3/epHuFipQg0ao8SFSP8WswyoH+odzLo7g1+9HMXDZ0l9ZQ3kceZ3VRasfLyT0jy/NM754KLVzKhGbPmakXXdl/UT+uDXX26++5ygMAe+RRyrtUCDQSJXXPdRPjyYiNHOflTPH8nsfNQWWg9D2qfvdJynwmGY+9OMx8C/VZn1EKBC1NiA0SWP8963/2g+fh0rpywij/7oq4K5OYSYngGJxMqNwR/nGR3NFfiWONC1PFDdd16ShL7uOVWivYtdh3P9Vka93pObCOBeGQ9OVjqMnD0h6BmZJaDDB69xqINvPgN9Yh0NWAT/oOsT56O/iZXyAt7eJW8Pw8AXf//asg/BqYdKJ4DkEaESXwEORbuh+VUjBTGhpl1xbKkctKhfccSpRyKtceWidu9ut+ah9QwddBEYG0PCbk4NtqRMcMQaZnJCoDYyQzMl06a3PA1jzsLGzZy1PCQbkGnjpOrQBTZAseiKx4dXq+EbSRkU2GEjkou0Dshga19yfLOs1aizaoI461jtO1h54TIPQZFrthxHgy0XaQKUdqJ3hQ/gIIFAhB8P9DhNktXASkRAz7JEmlJk26XVhyKeDI8xues2DKnANRrpkMISEN54nIEGsD0U4CpUOnA7pcgNLDAL363w4YpGLIMIgR42RNuEfGnHmy/mKABYv7Bx5R8pivIJ5YgiD1Btxbq3b42z9UffTJfuv+FWPrqKcfQH7C/A/5hdN2abKCQ0EFJ5ITWCcvMAomUMpjdwgOVVPK35X6QBgHH0S9Oho1Ugul1Y4LOnVSl1nYPz060teqQUOWJkhvGhsWLdIS5bY6ldHmSb62bSvs2l2x7yDUuav0bk8xYpGltzLjlNUnDN++6c+OdcDA/SQgfZAsg6NFyJAMJ4yIRCJHQkoialQhjx4du/KPlfRxyhkvkabECbGzJE7aMlnKzlTxNJVOV+EMFc00a0eJzxcoyOtOlER2uJ+W8eVdd2mx9IARa4+k266P5YnbB5Nvc00bt7AxeR47sSZqLxPfokznK1lKdLsSfW5qd7F4YaU8WD9XaZjCXuJoNd9skPFU55NCKm4sZrh1jK+3keJ/Y4u3ctrhACUEpIdbopGBZhkRpu2plWRkD9xDUGC0xEYL7MTAseLHh9W5sP8S59MKJ/mU0J7AxcLU5SDaZo5tRCMN+QQJESREsB06Q/3k+Mkpk2NIbQetJG6nnAKyKKeAslZelM8kN8eZXBwUE6aYMLochgMdB7ocPsdh+h5yHMp2eLiUNLKV9oJcdfQ2Ce02J7ifDn5ae1mblyIj4d0J3STF0R1y9N4TbkGdKKEQL0oTZY8Hft6z8ndKjZ/Cy0qzo6ZV255n7nXccCRuDGsZPQ6iqeBitP+0v2armS0Ftj+8i0Dw3kIKDI36juxtYt4dAVop51td2trb+besNyuG/y0Ld9l6f62tUcKkX++8QkzteZVs8LLxsug1QnlAqkW82L8ceNFfZPNfz0+f5tcbfJzwqHv/4z56z/9CJWD6m+DqA/LQR1I0B9KWvv3fNoh6btq33X+bmn1qT1Eu5uXeF75w3GwmmtH1ZdTd+LDVs3QcHX4OtkdYMtWl60uDa4UptMUawMnFfGbJ/lgtx6P0vyE2+5MRP8r8BbIULo+NIkUiValGIiRC1m4Y1Q03ZJl0S7a/LMr12BKeF14o8NY/Cq37v5oABNibLEQWNAaDIEBTSAgStKQ8yhG1b1QjTnf00p7+GKYjnta90CoXshm79D7PKTMYQC7rSvR0NXSHD4cffEYuB2U0aBqLGDc1Ea75k1EmObeCM38h1rByPyzzF+PG9SAm3Q8TJ7achIsv61lKryOjFendiztHKcP34FhjMhxbpizZcuSOQbOEreS2UexGyZQ33dY5DpLH+yCDbdNygB6Shz3SfHSOrwHocU940lN/+wYAJZZfMn2X5eRsm3LKfXNzKM4s4R4KJF21GJmupXqARLunZY9B03KYNifOXLhyg3GKOw+evGB5w/Hhyw++BH4FbFsqsxR5/JQQGyoUmTGyAiVHHgzcDggKkBTtpCRcxC2yXRvC7R61J9HQcpg2J85cuHKDcYo7D568YHnD8eHLD15ghA+JSOIkEkkUsmgUMahixYlHk9AnTkIHI9oRSXTpdkGvPv0xECqDMYJj1DXX3TDmpnFz5i24bzHeTvLOqnWfbfhi01ffyvfPlN2W0F915KN1RcLJHUYBMvX3e0valoiRUzN+k7CRrJN2LkQiOkaympnh2DJlyZbT5XYcqqNkAHAIEpmJIobKTGNhZYvqSSIicQAdQ5JkKZhSI21IerAmZLY55ppnvgUWxqJB3JI3EbEN9Zct69kexqoj3IUPRt2vF01G5l1YkDTpPWtYhmPLlCVbTsm9GrFdlvUapIhTZC58u4dQKuz+D3J7jUoA7WV43/9CNwOCfgYrz3TEi8M9/Mv7UqvTuaqPH0KP1Ui3nF87Q/ZnDt4PbalOte6ccTTB5WgIp4vwMa6OEUlDkqVgSo23w95Zte6zDV9s+upb+T53P6wfTUvHWqG27HrnMHKB6/VY1i+ALlnrCJNBiQAmYpLJpphqWkwH6Pg4m3Yprs9MsXr1VN5hQ7OTzCBZgZIjDwZuBwQFSIp2UppECZ8sIhLH0DGCNVkGtkxZsuWU3In6rGWxfZhFrGAFI5JGJUvB7FKjBgAAAIBKvB3zzqq/vffBmn+s+2zDF5u++la+j9SHLQUnb93JycaCSxU0OlHoGJKifGSFSlWq1ahVp15D6Wggkfm/RhaUHHkwcDsgKEBStJNS0+R/t3QE3x/yFSh0WpFiJc4odbaym1VUqlKtRq069RoINGrS7LwWougIgNPOx6vDJt0yZdqM2+64a9af7vkrHox66NHyz1nb/ouy2x/Jb1ew7e3h2z/sKJsIYJHCdg85rkweQ+3LORDONXLhutsNjFPhDfsM/QQXNseLvBN3uds97nWf+z1QHmxEzp50CGfWhesGxQ6DZperuH4Ux4tO1HjDbXfsnqHujRlo88eIPFSijoihxTHWrNvAOuIRR28SRu9i30nq5oBb8lb7x1lqKxFjmnaxRWZy2IK8zm6jYC5g6MFJ98herqCfjWgGKRK9dAsGaehMwxK3TeyUfggQKEiICEQk5C5awkrwBvP9IV+BQqcVKVYS5ThVqFSlWo1adeo16Ig79F2znnhalr4Akp/zZLKcLyvXgOIBWWz5JXPELmcO3zLwzqz66JN1n234YtNX38r3BYJWTFz1Y6jjluniRAmxVyFOZ9MucZih0BExJHWtRnTcrrNWbtNTL4cD1lPCgDyAUdGle7Vk004MjCoDZTDQCwgBAUDlM3gEg9pAhGm9O8PJuOlDEQEREruFrpQZ49wm2ek1WaIQaYyR7FD04gHoBDLjjQyQNiZzbvecd2coDDqEXS2Ju8io1toQePQWjW2aomjc9YLrXLahCEYvkgLWCyzFVeuDjUAjjQxAye/mt5ILETlIuMsPiqWkqA8AFdg8w1KMLh0BtXiJV9Z2V9C9dMwzPPfCspdeeW3Fm+b7YR8HfZqNNFv+Lf+tCNMyf5wagNTXu2ibh3Q2pUj0ZoNOJp95Pq+9v5vP5J/uKsZQsg6KWJhPOlmnTeQt6px3kW1P2sOt2CV23gwRb7NTOtkUhimvF/sj0tCZwgoQKChDyIhIopCQRd+AbNZ1MMYYv5YhWLjInRKnhpmOhFagzDVJhoimi47CZDtJB9nSdMUUBNAuBZlTwX7XbLg0BIAKxy+Pt3+vHAXvqB+d9Y2YgQrNKADC8L+HoRLU6zWx5WFSzvvp6QtmnFd8foMJ57+8PsOoCz/yRehx+WvxCTpd+f38AW2u/pKC8PUfRF6s6ASwIzQAf2sWMoVKYz0jXtwljluCpDDwSPZ89wUvn1RpOh+ZmmH3Vo8TPFGPP5gaXEkuTeYk4x2YKb/5kjbBPOgEeYAAdL+Y4In/JHq9Oz1Wr8j813POM/nZ8VHSgGo5vDwj3EsdoMXx9kmyBtCjz3hZs5CVbGTn4NSCLpZLDx48eYURcdIAOptL1FNSqFWzEKwLJ0ESyWQihWJIJTNpeD3xUwqyLOQKnMOrIOpy13lhDRZLc1MuSj5+KVKlSQ98akoJEiVJZvCoQkW/9tbX8V5/hkJFioV1EypM+CmRTySPSp/5BwKhSCyRyuQKpUrNb/WU3vSD6TKMSf2yc9A+vKFCS0UpT0FiZAz0E3KhusmJSwAwmDG2dAOf+u2G5MnXFcj/XrbdSXiA/PlNu33ePG8WN+9NlV67Xq7Ki3PFXcEX5jK5vJdV1B3pAEdyak/+0T76Af960bi9rnpZo853VjMmWH2DYhU2r47Vrl2DVxTvauUgwTDiJvCztz3joGU4vlV0FT0KkLr32kAIx7bc9+9DnsOTAbsEcnC0+5AfbjmQQAoIEm1j8/0Z3AFnDWaJ9WTP3jy838pJQCzMAst4VUPUKgfIpAgePMJ7otMBbQ4QsNqqe4ATQOAAGRa0kzoEgXQk6imCVYdw166se3eADjSd5Xc1M7waGsvTfsrOb+SvUWBRBdttoQrVVMcsxtN2/fW3h+sMKHjaTNk5Hl/rAONpTc5/2x8uoH6nxlO+4Xr6gYWDgqfMvzOEgQGCVY/ebUvy7rEJB1ZhtzKf9ACMVJbsgE7QJazpk/ZGHAk6umIwlwNoGRaTs0WdRdwNElkaSHSJbESr2x+3249KEoFI0qU0xeV4UThhj5DVrxW366srzqohfLlP3LRFRYkvIztTiQIESBb6EzcjGdG9vbbfiwoSZyOE1VsO4EP5ia3h6iw1lSrzPAMXhC198/aCchNjIhlbYimXDHk7e0f033iOWpTjhMO/HyvXVTvzJL1hLmZYlL2/FWRIheMDwTdZ6d0dBcBoz6RUfuuCAAakyrctyOjP2lp8yPV1megARvtpBbnku9fvPYs0pZrFacrIgfRk53imwjkRBiZnCkXO2ZIl51pdelLbA22ewQFkEG6QQT0OnDeswFQ0teyyDao2AG8KCXXSJwQQZJLajpKS1IoErQ4j904IaIIKNENNxM4A+bc7g0MLuQRP5mo2qipUtQhAdYkwLLuP6XIjJU5u6Ldg7IoYkBEy73jTLHv+QtnD9dbbuJS1Rp/iSx9Tqr/rkLvFSHKpi+ygQC1/u0NzCipsj17Gx+O23B0UThiSUhZaEHFAfnhQO9QrcKxLNudx8CSVyKRMHckQSFYpNzP/pNBTokOVtHYQqSksyFkvKNgd5+NyEXDZp4I+1+gJUf+ZgaESeAIwJomqXcrriiG9Li277HfFik9/Dyz9+mw50/YVOlErFodKlAd001nVMC/MR8E5e4A86vEtmytDXU3rCiMAp2cS6P7Bifwhyghlw9UZgEhW0fVvEd3rFkSpnIb+KnRSKp0Lo5H7LKynXmWlAz+Fz/cnojd3+Mat4T71vruczjpspw2WlcgZoZp6/C7aKBKUGsM/ArVVPbNtGt5jFC78fTISQhEUARHnZQR2zQ7bg29/N/4dwYiIUPZEbiCSdIY4TlofZ+n5s8OzFMkGIvDeDeNjEhaSziuBi10k8aEc4h6IR7euu+zU4W2cWxfYMkSp37pwqHBTxOmqoCgKPQzRwXui0FaGgnKJdkQ3vUC+P0JveQxWHMCUKwAQIMWZ0VsP5O+KY2+EKFEspTCEejKgGdzATpTDyYVRiC4V/VLJ2eMrFFk88odT6aXx5Pik+jfl6bIpMJvzt7M1fzG1uT2r89VZmudmYb4wM/PpmZjrG1C/qmV9Vl59VKP6a9l1rbq1U836edXqtZLrUhXrVOXrueLrieKKvojG//1tqSIvJSqg7lqqrTR+7BhRCs03TLZdWzcsxkPzbzfsmGgpiDmgxCYrLZJjmjRJEsTqrJVH53a1Ul///5VXD66dOfSei1//suc/68mnPvz4u9/+Zt9+/HzdPf6d79eyOZNGbGidE656Jcsba4kjL3i4uc5m5y3Xn58KMNZoiDDgQOijDQHlFJIDkziIBOCJIxbsmdJGKPx/m52Ns3qK4x3lUAc43afl1J7Swz/swziUE3p8D+bYnoITOMZxHU0w3rCP6yyZNWHYBiZZ0ypXNM7SRhtphGHnPKvlLTDv3HNO5SPHXyrUtWpUWVivjx46tGhQo0K5/3tXUgic1+O21xrhS2G6VygcKLGPS/kGHLKSwAIAAMdxHMchIiIyxhhjRES0V1Wff+dTa4ejpSYOAOCcc86RJGlmZiZJSo3EAAAAAAAAAAAAAAAAAHKXgqMtBQCAc845R5KkmZmZJGkpkiRJkiRJkiRJkiRJkswuBUdbCgAA55xzjiRJMzMzSdJSkiRJkiRJkiRJkiRJkkZfaW6FjhMoVygHUxyiAJ4cWQjyc7OTEfWH733qXXe9pNZZh+222RpLzDHFGEM8rlJF02Fx6mv1nNbuLc62vhhTqvpvvN770dQGSCm1pCRJkpIkSaMfR4+SuR5e7fhjj7LQ+Q4z2xUsMGMaZ6y+nVoVinWgkja1skVNK62EYmvVUFObUGcVarJpRUbD+dbtUDLXHrOf7ryzcsEau963zepU6nc7W92SsppYcoOLq2ttmtek6gX97pWIgYPoq6N3CX76x2hC4WESXqLd6GqLelVKFWh3W1rb0vLLLqOUhta3mNq2oIEadVVjjBp81JGwCDADJJpUKsKRhoaEAMuZjQJZ/BLoNBKImmVKT8N6yt2wKhNeFpTZuBIbUM861qLB+uuuvTJFbVhV8CgogG4tapXiY2OgCOULw1aBAIOLRgwN6n3tQ2+66QW1zjtuv+02WGEB84TZXuv5QXm9cyvmdvlyMWap2jHd798OR0tN3GTvsL/uIihWgKa0j/Tc4Wjp4XcndJQkSTMzM0mSpFHYi5/HHflDi4R+N+zx8bO1FN8f8hUodFqRYiXKnHPWGaVh+PcptX0kBiICC6MfznSOJklSrkKlKtVq1KpTr0EzoSYCjWEkJxYNeEEQGWRQ81oHEy9OPuBVox5yPUBNE5CMVull7Gt1NtNVzt72B4uWiGmzlITDRF/o5kSt/FFMi6gWjzuzisRkV6KbDdWK+9cVvlXxJjEhWp6vKJMXQPxjQ8Xu/z7ZThBv2lAt9r1MMg3EWRvK0VdD6AtijQ1ly0zC5SHG2FCWgX0xup5LnxnDftr//EEv6IxasKNLtT8qFleG2YAYjVrCil6BmE0WV/p/f7NFoQbrtsIAdrG94kEhGl8WDAr+8LHbrjqsxiKTDFGpm3JZ6LEVP6VAngEgOQB8gDMDeBEDhGmAKGqQxAyQShgkmwbIJY3XZBpkKmGQ4jJIKWm8MS7jjSlpgFrSALVsg8wljNdc0nRRWUfBakJHz4ARb6vIudV55gy+EhV2peHQem7Muk7uUzGpCM6OiOsoBJwArShcGK6QyO/jdrvkb0Wv91d1BZd2nV+0K/j67RLij7N8iFNP+t8R+mS+e4Wz0Q0fmr3vlyvSvraV1uApY2mNGq0KfA/5G8dzZJB/fB0G467IQTt79/lPG8u/5zcMxsSJM3+f79oNX7RR37TrNp0RX/Hgs3PNRlQfBNSno9fn0NtlhA84/uE9q7+Wceodra0uPwY85zVvWGaFZ82XNHrqYylzeNR8GGaxuJ9oMb+v/Gfe3OIOs0xzl0lmHshWN/C6iWG8OaZ0zQmPMhy+yiUujstDF2h/f2IcDXaik1Y9qdBLl3VEU9GdifXlY0S0NtskMdHmo6AlW5oR0EQdjdQW9RxUJ3tR6TbP8Vrp5qPgLAslFHGaQgrIb/IFIW9lLg25ZJJDFtmwi4zklkuvT5JJhRlOgQ7jy8cXEtmTKvXUSRtheYXRcIQo7CQQCQ0ypDoOfyMsfng0FjNyLRK7B6JmSTYjZFSYboYmpWDHgjJkEbDjt1ZR4vcl17ZTKpg6p4o7vrjhgzMYPAMEazdyr9TxjjCcjeYeOTwgqezo5UCJY9Ne6aQTtsEqbIk5Zg7e96EiIQF+SeI4hahlmD5G6GHMcU6YbnGNEJ3m0WZAm8Mb7eBa1ss6r+F3NNiHOmrszw8IgmtMzjSuZDedZ5qOospKuRpbhghi0JAww5FR/6SjIfkYCzunWHH80gQUCivTRkddRFR5QrVBJphshlkWWWq9Gptts8MhR51w0lXXPesFr7rpDW97zyMf+9YP6v2mYSZ3o+b7T7rkcuuRPa/uq0KedBLA9ZjTiEsh3Y9kqGfckJjZK+GiAubKLmpSkuNtAIWqi65UHxc7QTWRwHTYbXeAd7Zh/kleWrcAI60AGHFrMBIwFgAA6HvuLYeXGP8308n/y6C+XklAzwWATAHAoKH0LwO6bfmfdtMfd19ECZh6+YuORoXoBP4+VssAaP4B4HAcUDPI3r0KMI90XKIDsRy83Em7gb8Vc5RYoHly9etop5o02xAXPIb7lhH7d0z9UP1Y/cZwG0mG10g18o1So9M75rvu0SHPplHFeHfTFgkMBqwIMxzfrRGC44HsKgsfuTbijITR84wSvZODPZ2Ppu/6aev23+I7TSeayvebL0fwDJIZ+OIgOGHADhfagC9/aO7NsXFXfXbYRkgnwCDfA72sLQAAepE467HS4/np9JFhrQXSVA9l5RIkGiWAMwOd6erqFD/+8PbzhlV57jPNAjNKxIAvdECOZCNR9GVpzecHTfjKKG9465dJXTaPJ4wbSfMQZQIdZ6p+8RL5iGZojEsSBEuVpjefdQTrKiY6X926XKD6087/AZzCooVW3OIlyBaUI7Mv01ZX3XTXWacI6UIgkUiikGX4oU4hvj+UyFfsjAp16jWo1aXbBR1+etG0GbfdMllQpix76ZVnNvznd5XutTLWM9JwNxrNcqzGIRCQ2co7AGojAOCfBtDjQOx5Ab6PAbQrA5SbAwBIABjorA/u3mPuoMHqlvlvS6kOwtJhWLOGDfPUO6VXQ3uM0Fj6XFqXZpBU9YU9LSJAg4WhZFYjNZmhNO/uGiyf3A2+apXVnf2BzDW8uKHNFlB57QLIGkPiklkYGlnJcNtx3KAFN8FVBcaCangYbUlhDVYp6SocGoYVuDGVV5IVza1klg2UW0WuZxdT+bVX7eIDqHLv4dUUM7zBHcNxpCuqDawyo7Cyr/OJMkNzGi1mTdxkgVdqXlURYLXiU3/2dSEsSjCDRldlqpVxpUiilWJWc2P4GYtL6pkmGQ1ti0UfbjiSEL2sMVwCmCcCnpZsv9nBpjYB9v5GGBEdKZ3gihHWGl1gKJqGV1XMxiYskZT4hV7AtL8xRCFgtP/lK4/sDex8QVUpm2vQuL6foRRwSYhdQAVY3EZ4GXpfRu8tMYlmglDjz9jbq4KZOl9ubDKoqa95oEH7CQEXsNqSPHFOPOQcKWE5KILPnQXgdv7pDymtix/sHotX+3QA4wGwleOMnwdBO/1GUxrujzSHD0sr0VY5MgnElw9dtiRVZ7sGJfo2JdpJTvIeS+362Ei6xWKNiUDYiP7g5ywyA4ygdoJdFo6AQ/feGh3rRzy2KVwpakIJlXrO2z5e5Mzq7F7G1bxH55NzUUHPeTT7dmnbQ74EL9OPnKn2oncjJJU3qIoUXs3zsbHPWBLDvDURKHwZ6QktgnjAzMcIShVWFaOH1ZAs7CUtttSKPblE5WEouYlSyHZw1rYcwuUxokCUoGLP08Yq123wrhVB0WZZ/UnIkKOI2Yzzvf3kTLVeeS/oZfqxc2/weKDahmL4Oif5XDKL1jlycae+wIaK09/0QUl/CN84Ycj08ZqyonvZTPVzoQpRm/sYLLDKydF9SI7P2k12kKBFTemD0bNH5ccKBko/KSjg/26ENW4H5GwUttgdHqzAJcEZ5wLD6qgjdypxIBzPeNQ6lWW8sRhKjAImgdsNfSTeqXuMuL4j8lNA6GOfR0ifR4X+hvUmzvHtvVwHxZCyRDkocClYXvAu/L8tNTiN3WAfIMaogkSCThM625+rGnxDl0IkpaH39GPCDf7s1oRf719olWBQGlYStwTB9v5taIIbp2NZQDsbCypq3/GUv8JNtoT08S/AQDf7Gl0OlBzLYzskE+v7QIhWNDl/Mf1oNWDEDn10VPHJUJvUOVuRiqugU6K2r6hcPoUeGYdkSnM8ahmQ6KzSMqa3Rrm80YdQy0zqbp5WQu4Ke+Y99vmpfkTmHQuCJ4WV8QfnGAgg5P99vkibOr4hvUIfqaChIaxLw8KlACm/rezENRyDxtM/mhLO9Xw9t/IWGNWeEPIwBuk8eF1iO/0SKurtMpvGdt+WKkDm1X9MZlQlkklQ/7WhnPOEZR2EY1jBiToL8SB5bdRasExkH4Bvm8h8Y9dJTIW9LfZKX7TTcqJ5lLTW4cKKPDHkEhgb7SB76DauNnq5Uuul2qxXWy4Vh+7qwj1E9ueS5SHi+PfRxxATMBCBsKV0fr6+mFyMcce94KN3VHH42n4EtKJun2av2/vTVAK4VgGDWfBU/xe20wQPjgwrH1UmRps6K9pgmzq3IUbr44tDWYcYze0BQuTOOXdUJ2Jfx05C5GDqCpvGRVT5e/HSxrOHuq3CWv/PbJdQu7gmqpHOUTvuLpemuGB8etJNK3n7IvDEFCKwUs7BhiOFex+doJPXJVRLKp9rZCCBe/XXFoseNtP8I6L5qqj7Ov9jfPX/SER1Get4b4xP8LggpLnTJzg7EiXb9PFDEo8MNthY/GGxQbjFthhcV8VbvYfoh9rUEDL6D4NwzEoJPhGe5oSej1Ricmt6xxmlVe44160ipkjjhoRLWcevWh5P5FRaL09Y32oWN88xutq1f3F2G8IfesYj3/sIuI5sI5Tlr6wMF6PyUCEJoRE4IL4Int9J3svzyVxf0n8Xnh2xj3aEaWldA8X/nmUJQFkNYn3UolBwfolWFomCvPFaOaGRLW44pLgKiNZoZxwyyD7LOD1i5C1mP4/BDmugBUJ7UUvBaHclF22DTUcZPNIlBY7wfI+/NjXJOCKZY2zUWfNFWwrY7foiMbGX/dhddLKLDKVBxhWSmgNxSAIr0yelRZ1EuEt6YwGaj/kiM/NiZgK4djGL8cSGvecBHrXuO06l2KErutCh9XhmU3oKQMpklXK+BKVBzevKoHbrA339YbrXBdH7PdTFCF731VxmaNWdC9Nc8sgjrZE3S8JNsWFYOl4BbVBq5ipcsTUxdbmEl13dCiZgMAFZBDgooOTCrrAml+xS6MOEaUEui1oZcK/D7cHxQUi37FR8mEIoNL8yUihGcRzN1FQ9gXE+Ay3f9tzuNS/l2jCfjItRn7uTbDhKxz1paog6qcL59OKg1Fj0qO8YI0eYGTONkdiNiKMZsKzg361OIDu66Ntq+/KgFr5x1NG9dW0sT+zNruOabwx4qZrcCBzEJ7rGANyo+AwWq0/lsVzlSI1BG/QWk/C2mPTsyPZR3s6EiGpAyu2/ZLOxbj4BdrjtLXtigzpLkQhssWaHXVV7BWMHZlKsoDHPORh9tSXjET2w9YRgBkTgrsPx18HbrfFvlWJ/tRQ9Igd85+1ii4Y44bbg4rRYESQSI9w+BKMYU0l4YWO8AUC0K5RcxNABxoMIhnVscfv2NsHgd5Bk73ofIvvoAnZnLAOpvK1Oie0zAk3j08AUAj8WBs/hAcsu54MA/C7/IBtpjjouhwfTpQ4J+G2TZc3aUkzQxwjMW7KD0TjlrAgeY2SVSVXbcbeMUSyTJ2NdR0mw2Y5m6akjey0My/IzwDBRYYlKZKTJjfkLS5jJAO65I1UEUxzKIOt1LGXhOKlw7mqorulwUzSwYjimLfon1cV1TU9lrnsL0PLqlux3CRc8A4k/JqHIplYKW3l1R4EQMZb99tgpclpRR68u5WY0dxDi25ZOQwi2KK5XFab+yow4yR4JuMfH6a/Ai+TjB/mcXwhI/tSh/O8svFNe6XyBr5T0S9qgpHerZDcMJ/mhf02Vx3vj1aQB0pVm5UQij9Zcmz6xYp9mZtrtsQinBQLhflYUTKsXU80t9HRqjj161O9eEQtUvl7KMqGThXB+JiT5yIi5h9RHd+Z61k7YlwO3NJdwuqatQ/ogVrpnNCnODbSp8z8VHQPASJHDIat72x9Ffz4B/2iLZ28PUcb+AHISqEhVKsbYOTVqRyTauRCDuXDBwS52wcQf+9JDaqhPYVgdHSycF4/nhcMJh8Bdsr3P2vrgT56UtN19oAGMLRxE2AOpdEggFVxZk64AGF9pOq0lcpLOSMEWFMw+3Fte8K2aH9pVHRWojA6Tu5ae+6Klvvir3tmND0trX2ZHC6ixfRNx+VuPZxlDgXHNtIKR0dlFkPYHZ2tvHO18feKIOWVYd6QvAYEAYw1TSlxPjtayN3ZLVVDxfakbFdQgX7P9A2dnw2bJpWH7xqn4BiaxAByVx9o3X87Y2r+eHfx2eYnxy2tCFPvf1nmKw9h6CWCsSaUPR4ZK0V37jhcCABd+wJ5JmyuMK+fWRSmZWu8+0sUhlpRVCWLkOOrkOGF50lVr+qWjI70JCER/gv7I9T5kdTV61EOJKkVK/3+YyprdRNVvf835Sx7/0y63c7daVIjSvopN1UpcvVs1zmWHpq3OleCgwbrwx2ESbdvyPtsXgi1Ig8mzu+TODEjk2FWvGzcDAzg1bpHxVUHYnlwqt6VBxZK35Ww6ITCdJOvq8q5sJ9dWTgATf0UKlJpA53i+WMW5TiNrFcgn0DqAZRUNnFWQKkx6vfMUprSlrYvWRd5znyLI5AMrmBYJ79o/OVnPtGR4t9z7j8o6H6GH7F6/mpgguM3n1QvjrfKTY7CzGryaNTLx41f/2knw7hpYeymQl/qmjk23xW6s4xy7PaW3n8YOfTbqrjh88WL5EcOeT+vS1dbppODxzMzgm7cT24cAjAe2MhzU6+PW3n4TqBfHzT2OTGA4oiya1o1bKlTHrlA2bPposKwjnokI7jttGnL5Nrntg053ovYgr1b9oGwt8M8Hu2q2TwwX3glk1JF8scxMzwKD0jlzb/TkqaGc1Ftlbd0K7o1rUvszl/5XaAc7rhZWL2DYpS9DeW0MSlLuVe/433+4fXJW3p57GNiUTk4Zlwx9gdYD+K+0pEQApHwA47csDqIcLqe4MImJHv38GRx84Vq/Xbt8NW91k9/V9ZWft1oN0DNAW35UxczxZgJA04SDn+4pPlrVla8CR2/8Z50Baq5ElHYBlOFAQxaPSmvpOIMho6Uh64wirXXUGZAPoE2gpskbVeGiqZ1wHvLc8rwfFcJlyFPewtCQizwjVEqwB8d/WQkaNMv/SSxeqObHiC+ELZyIUyze1bMbp2cJrxSKRB03KrT9XnhbF88IPtoy3ccODcWnP7m8uTaPTKInXfWOvF8ylkC6QHz8kqyWh2bvxIcoNJkQqcGZl7JIjgbyDSffLyTTXNTenxRxELGOeM5tFkdQKC0R4c3UCK9rCYquwcenYDziWfhIsDww249/IBmob/v80Z45/sP9gtqtWdbf3jcGkg4/Igtn+/Iod0dTOWdmixKe5xT2ZKw/yioNqzZJiPvd+7WdZkpHz79E77F5Djqo99XaBVXcHX7/RCxS2fM6LOAV58UtkrFbY9vwW6MT9w+NRLmJbvTv/uKz7/2j6v841jbRNaFZPaTq8SM3W6M2NlvJh8fHKvtJETl1amuy25do+ERlaeWUgIwQt5CgU7XVZRNlUTLAhKP+2Pxue/Tb990UszvzLbLprY/2nF3bT73SIii6V5os0zPAgN07VxJaZReTvtdvbU+B4DHIAYZj6mOHx1vJmxutUUdujlf3kEKzatCbawCOlTW1uoicflLK/dKJymh4T3eUzERZWfVULQnaIiYjpgTAdEz9uf1kN2ltrZtqdmdeh+qzXMAKdfYgRBzVAZi6j/2+tXAFMzYzSvkAyE/5mb23AhMDE1S7nO7ufWmcSklNBvJdYOJI7Poa0FKi7z3C+zeS1okrHv48OGaBrgtn94VXD2v3dnqvr7WGHxkbr+4jhWfVqGyuAPns1MCWLhMp61k6wY3+0tkW9f/E2bLqqRrStkBI3pwqAmpOAsEagGNtHW2a9rjkYuOHrDwwNb82dnl0pp15KZI6Ah4DeawBecDOAxdSmKMjKczlEK4Ov45qnxuQ01Z8s9cXMLWUODeeVIlUQUqRaCQtKie18mhhbgyWNzyoL6tp0Nyldfc++sCELoAD/rcW+L1dpDchAGoYcE9FetxX1tH67AeF1bV3Ci3YKKu0DyWt9+SAElmDdl49l9PSP161uq7G6xDmhzZFEruTxsxBB63JlLlU2iP4O4cLJln04sgdcVJfZPSI9+bOW9zqifq43hMd0flLInr9Y4mpNXe/6e75SFh9feSOu6KmJsehKwKrl3v/UcG1PXWZnelXE+Mkb/J59Wq7An6upkd2AC6ubKoF8NlC6wIX+7zPW8ZeFx1xK6kMyYDa5sqxEpu/hCK1yl8tq6ijSUtnivZ7QQzXB/BIfUZPKLmFOgt8+JL71iaeZJ5DzJlhThQhN7pA47X5n4a3Z8/zq+cU0wc/GN/VmXhhfjBzIPNc63hJFI5OS9m/bb1gOLnQnFc+/SupZQU6DbYgHXZVf0fwezoVcxs+iHsHP541RI/v3kI8bKn4pVA+tCxdSWgKDGwgNz3489LQMie6nOItDi27Pt3aMHulAsgdgmJXMKM2846+BuQGZCtSqLrJEZVX+vdZ/rsdydf9s3rzgbsMs2QNyGMNijJlvm7pKXuRk+soS0pGpysIl4Kyrhp4rLWSbOro9VgO53pcxLK6r+UK8iTrWQ6HI82xZSG1QKg80MwH6x4E+/kzqNrA5HdXsKVP1qLQ/NqfaOdKJScrt+rM6l6oQEVZQCUf0FNSAPVpOyB0vwDq3TbWnbKzCdutYj3nv5enQKEeYx5P18yHE7y26EwtH0/jCjo9+owKEmTvg7ele8iMT0R5SrNGTaEEFE0KdjbXxpbJ9Tr7qV5TA6KlxXHcjacoKap0Ah/dwmRGt00QSlHADyYwdihxqngYQ3UGd0/vmsjj4VP9LGnv1U7mBe/0dFX08cxeTUONfzJi2tsDMIqKFOEobKs9XO/K7fvltwqi3pTmBW1P1FR+syria1lh0McblUCxCdZo1jzrT8Q1+LQn07WPzzzpiPbmym4vzwPGEAAQENuvoIrbejCzCuAQc7g7vZkIJ9gzA9QnmTe8taGTR/nMV44erC2TJe+y+RBryI1bcskDRHuAHwPS9I7SaydeEX+qkJEly2VbLOIsvpvb2KXvbVaFTJBhT3oOqp0RnP2b0nzB7rFa0js7xZjgMqF7MLE/OGkUhNzSDZn24QC3aQykzCK0mEQkrzti7t8zfg16AZ1KI40JCIQwk+skCPQKvc9FzVFJ+8h139jbDzk7g5nctxadAMyB2quT39ofYj0lD223lpfBWJ7YEtd/d325tPy9twzBSF2YqHz+79BZBD1l4SawwgAAxxbkFfKLx89tvywOiV6ncevG3DvDaZTGfn96Wg8x/ELq2lCr0oGawaG9NY2QpiTcwyn53tG7H1BXpMCCozZlUjC0ARP+hJHSS296pfHvhqSIaEn07keRArFUzL4SSG2mUUPq2vyT4oY9U8ug0etywosb2gX915Vqz/177sLQl/oTqJsHn8An2ofg5jVAJJq1cCmrtCEf45ugRqWyolcRQO79NQAHMLVX69tX3PEF1rCuWLQ81Jgzmcq4x8tnLtzNyANh4JbV/+9UYRPrOlKCWwjy5TWHmFHtAYnp9GSPkWEfMB9Ty4b8CJl7mp2mhooW31TfXXWhG1nY8UWlaVPj9MTFlo+oRpCKMsfXs0YcYvs0e3qNpq53WBldufcsZyabeT8vlzE/mZkTIXJnc13aQtnJ92e4AG3phkapS30BWLWEqQAze7V7VuW9MqAVcGOkQ5X0Pcjywxd+gcOgofmrypmhAeUzwq9gD2jp+XX2MDJxT39lrBRwQWufjEX57FLx7aAEEUgAKan9d6LzeLPRzH6QAhJoortB8InZxM7AyEYQC2Ii6jvwSSld+LB6EANiiY1dgcAMrpYNfjw19zg7df8uStuYhlo1OjeVz2+ql0xeavlndyN7CPjVZTTF9Wn19Gx9VGJhdHXueTCLucDhQLaSNzuElfzXB6HhmNodzYpGSBuHNjXWme1/ZCnAgsqNxRaeo2PTsI4sewy2nF3r4G01maVmwJPEc3vvx/zJKmLPP2dW1z9LSx9Prjj3KDu0Rv90dOSNY8So1ovRbOYSaWCECmtdmQ2DpJ4zvn7yOilRjwY04ABydmzVdwwvRLnHxrovamjggzMASnFU04gU7+pGIwOcz48YhZeRkOseL4uLI61EYSQzrjcp5GydV7hvjVP0OVjqT1iH8DM8t6UPWlz6RZDo2J9VHGgaaBbL0m+FZCLp3nTuhAVvFAmueb4qLoq0Lg+PMuPgsAUo5+SbyXech/SQJm7uvnh2TxDZk+xLiHk3UpZ6GMGEPvgx5O8GUQRv/hJikg30ZJuelzHw6Xk0AwRwkwwA1xiT4DiceP2QyL8RmtXOLxbbF5ncTudN21VMMvluZtWpZVid3ISQO4ZHtX5WNMZM55ncLrIX84vbs1oSnnH7cxhblmpWxccwjZ0m19fWQYkTGccrjzGrmlnNd/u1N8BRzehBm52T6IH+4bY/bR1nOjT2tV1SMyvl3TunejRoa7im2bX9ODdawR+ZQYppOpkky4XeiuNfcdwsLfB+Udo+RqYrRO0QacVilpCMxUJ8WG4whVaso7mSj4GWv35xQZd040NymQw6v+jHdn4xXKmgBCQ+OCoytDa//GTKeFlDUaSW3xrv8aRN4jci8mAlC9Pwk0yO03JdEVjcCwcznuM6bnFwOoIDxi5fR4vyjN0uYLLAzl6t40je8odsy8uXsy2W/z7C7ejU4YaVa1FauZatp0Enr2Mp8yH5fH/IKn+gSRN5QSzeeUGoOdAn1NrZc4Jv0dy+R1XUjnDV2aPaLFJWJo5J5m0oi0QIp/U1tSurAqsZ4tFTlY89ADQRmmJm5uYA7LhUIlW8zRFLxeC+cWOuM08q5UgBQfZjggBABn2evjENuayM6bS06Qx22lTgZE2lYbEzSgzu9/MTP1/gv+QM+VpdYXR72+XG2AaFjtOvgP2FoHyWGDAmHauuvtzvmzD8lrrbC2T7C2CurBSPSnKWPfVG2Wlo7uhfx2QU8xXogKcUSCX3xySrxezzjORCI8uh+3Jgsp41jIB0viIQvZIbkRu/gl47wchS5ihCZysnAKpzQlxeGTh5U5qrk3s5EwBIjvMlcpO/hyd9PP/YSwanPGAMSoBcZjndDQNHrWVfDlgGJNmyZRwAy4DAEbryqTU1o+PKqT1gwk1j6MjqeFCpHhhqjH+qMTEYjxgqlI808tHX9zEqJ4BqRKfCcXA8ncNd/VKDWkaBdxEyrUm3L4VQKBICLfyUHcHYNCAqC5L2+J7GuH156+2EhHCMXdCV96EyIHlg10SZXC/Iqey5+aPPH0JtgDJeIJfxYoMy7rYfH7+WteY2RltBr4CfH+MAkIIjMByGjNku3jdBRPkk1pwGVewGgbYsR+lyyoeI9oK7Cc94xUXVseenABzlVb5K04s1cqfifLwYiZaGO1lSDU8HR2dP/d/r41RDLocMDIYAHrpNI3NpKVOjrc1x4K1a221u6w3JHpFoj0Ri2Col+7sIdKFA3Kyo2CwuXc9oXNjN39hDuZjHJIsiI0VksrCyyUxhHpqy0cyqWHibUSruwp01tHhZT3NEhw6Js8FT8PSSpXEoW/R0qZqmfkgEREpujXddx3Nfvsw9BjpAZ+7xde+juV2dR1FfcRKdQNIa+9XLYxyAeaPu8oL/WnWJ8CPTssxZBj6pZSFHGEFn2DOADpSVO5+ZOZ+b61iVuZfcnGlMqotLKgYjrErM7h0OGEGFi4FYgk9wtIvjhz1FqxcnhpauX+tz3JnhsfkJlWB9SzjDig+xsfSwxVskG3q6HVJu/t1ByD3TOtB5pu592z9gxy0BrTRl6UF2+fP/dz8YGpOe3M+sDdn5yZ6WmS5kpSYLM2msFFGqnSYC8AawX7SX588aY9wMDDxhbOAWD7GxmzPYmy+RLNrP9sE1A0RkmmDids/iYh+NlRkVxeGAYJjWui7zqV5bw6HhK+yvJ3lKVvqy4x0EeOerrXDzOs8EJzuYRRnZOFGjfH/wXkdHnQqJszkb5u5ZkZPkoQx1s3USEyvPXn8Xym/6mlX8Vrha0ScooEtodE+n6CiXbt8Lyp80NJuyMIxbVXaqjzL8o6eAmJU9tpRYWv8iL+OtnNOGlSnR3/NHweuryYb4TDyRyXbXTXlUw9YPTwWqZLChWv+16PJofhbAR0Bwv9nlZFikfohJ8OlYCo2XHDbf9f/8FH86nC6m+joUF1clRMi+hpP7wOGJ9aLHITnnIbFSGVwViZ5aHY/HC+MLyEIyvTIKj82OplDKo2T85iGx7OZ7QZy8W4H0OhKt4nT8Lng5WtBMp2QLn4UC+caqRItnU7ke2mwHV+9Of6eGoc7PAmPlpZ+6CvCfR5aWZMEVtrGedqUWzUxcK5pKTcW6NsE/VUAaBaHQv7j38rw94NR2xUTgAul22Iyw4OAMks9M3Zvrw8PPrp/BWGTm/BHjvzQI15IATSXOjH9yFXHRhR8cFcUJd8GcCUwmVBKi+AEujklBwcHZwS6zkLCEcyN+LNZlbEwhIYyXGb8Tnr+rrCgqNKnsti8ImRArPCpbIcR/gM5LIia2ZN3ApD1QVmKP+MVXQSJnZbzYYcGUP9LCiKdTKJZUwycTR6ytJyXoI9ZQu3xrH2p3AEVATaR33YoEx5XC2k5yuafunGmL3/FXQ33Xs2s7T88rOMdhffi8B8Nwda++MEpca1BEAymO1j4eyWuO4rMCAwuYRMd4C+vwQHgQOwkI1CfK4ESJjUR9ohYcUeLP+aQXBxDr65i74PHo9FK8bwJ3xCONOexB4/ri00vj0XA2urIuLCC9+E8fboVznL6NtwGmMCbKkaZn722EyY+hfgpkRTo6ssICg1PDHB1TI4EGFM/l6yGOR/wlqO95urmmV2dYLKBNJiK32Z5ibhNmheenR2Hi7MwiIrKSk+kjwMGKHQ8ok4HdjttDTusWWd0avHXTH2XHCGiu5/fJPumy6Aflbp1uYJPP/A8U0pvdX0LS5AHiTZXLCb5JVbPWPhGPzL9ymEafw184BM1W2Qn+4MCUypD0N2qc9ItYMv3KZplshEvtAk+Tqk3wBFguh8YIHR5gcPJ6GUHDjCsteLivVj8jZPjuEi0ssJwWG1Ae9gL8zrXgck/e3a67weWfmXQMTfn5L3No8zmgL8Ucb6MCh2Cfq+K3XyT46t6m8lfmlJe9l1FOzY/H76hRQGXqymVYXc841zJQ29sQr21miSXYDSoJei5zXYK0XQy9tC0t3QkAjZntcuWdZ8CMZAbshX1MvHpU87u/7nhMlGGTSt5eCty4VO5iyxysIYxt5eISbZgEB2Zwe1jNanwNUKYyTJfPmr84dfO7Jx9T5QL0DMyyDYNhNXOLZ1kUbpiXAjCB/BQwXW0hy/mUV1eTkUERAqmPyEivAJ0hOzP74gCQPruKmnXv3rx7d7R4aWmQCKSDkdIXtVVogXC5yeIeHQu0vOKEZxNzJONtUuOovAd5GLdRMAyRdxJvELM550OldCKY+0Wel0ojhS8jQUsjmPQMglbYWsh5R5U9SXJHaJGtW7aqz1rhsyIUjvacE0fpaBs7pRY/20XLryu+7/wMnng+epbhQvYCkN9Kz2h4iGo+pWvqMjJuThoEr4K6YzxF5FjuGMOFHGMfYjvHol+hELc8fxKsJhmXvJ0aYhxILvMsAI4gGJr66Bj9gjkve8jM4WO95n0/zBvyHXBBHlifIEc7HN7LGxvIs7L3IWA9cAQ7G68QLHYbFXDe4bN24rZv3/BvcKLBvAE46o47rq/mpx9fEFl3081+XjKvoGqDDfH2whHs7HzwWA8cnmft4OOPxXrd4CvLA3unB2i/x/VH1A4JlydTisOcezmKJ3MINpR+kMKtorgHGXsb2+jZYozLOxqVLaDYhhoGG1rpOTq9U7XzImCxPv6O1BWb53cZN3fb3l43MHQ8DJYcQdQ/7OdK57vngXIBzvOnJ4ME/SwRAHHqLyJya5naVBW2Lym7J3m7L6LeDQ9YN8J0EAvlcUT3vaeY9V0n14IBHj2+q/YO8DnQ5mNV6DA5cWCz2T6j1R6zK01dvxZXXO2zWKPLpoDW5z5IWr6XYGRmDib5CdEivx7YON5we4ksXccnha/rbasDtVe6sP3ljffWYUccr1ajv7e98bu/VtID7ylfu+6I35wykCy6R/eZH8Z8GUZ8qadSfKmXPL41caSazfalubKZbNeAKk/7DwM5DV9Ooy2nYctpDOJpX21p+p9e1rx+ESnw+WXZLiO//xyfUdTdKntd/jw3VXWRHjOWM/F9efDjlZq5UpYno+3ze0zGgPIS4IoMTeT3NnqdKcmDIxfMF4SuyEHI8PZKnPpOL+DYLwLh32g5kwt7LjLOcDsMCD+3zwH8tGHLXDPb165el5BkclODQ0Kxn0XWc0dqKwCsqeb7kptlc4EILpAGPaTBRZ3ewRTWAi35Rrmyo1l7OKTKq/TSlP3DG2OQWsWk+T5Dv/MK/vp4+9oim9ZXRRqd4aHYofm74k7r05O/qYJvxX43g/zlQmtA1/zcfI/BrH1c0o40NjtQzG5+5x16G7rybcE56lXWs629s7hC+K3rjrM+MGgd2T5WNO8vp/nemszaXx45z/w66I/SKLvU4vSTCp1KKSsE3uh3Q7r/e4FRBW15owN8q+69VTWraW4ylQcLQQeV3WK9/Yt7pfBml0PTaI383ajJXdghwTG6CSfoptFuALWKv31GZAPs8Ib8uCyWgL9H6EJ+8obuF7Zi/yjKJ6JjYC72z88Nrc6O1tYE4Ct0xe9vZjmvUG//4I6R1zdkxiNMMzdq4SDF7nT23JN3DJbgv478juStuS18877409w+iH05t+czGMC+DOYBHbPYYH9FW50P9hA2GxTnDCrDNXrDnYHQVDQNcQiFzI4V/vbTnD8OPyP419L+9S3/RnZNbBo6TqUAzIyeQk+jYyiNnlG+lqCycdCfA7wAduQ3AMKCidPUCcf4pYCnuCKDL4IXSZPycuC/IMkTexV4B55yTikjcDZzXM4apMRjsa/GM7+Dts/ySZzH/vbffTJnQcQ/IF6plK+MgiVUUl6NUil4BWAaVMCDBD4dsMDrKAOxUSbKQtkoB+UiDuIqAk8jagRN4G3QDN5FwiArQEBslIVyEAdxg6wA/iHKQGyUibJQNspBuYjj4dbaOTJ5q0EAUqswRmfO3t0MKMzI2iWCVaz2rL3nvJGqHWWj9f7TsJyhvw8tNzgdgEVyBnQbzaI/0T00h+bRX3DhyPJA+fnjXb28ZP37v4FBVv9lfQelzC+5b+e+jP9s++/tW/6/M3D8hzLHzO7mL29+7SkaHse2xMD+D8kfdlz4u42IyukBybPyF0WDB+DP/ZgB8P6RQDxTkoUykVIHcEJdRKbsybLReraQMAn3fHQz2zo6XckU6p6zki8uLgiBmJ+7hRQk1mHW1FEfELO1YbJC6A3qTAIj6rKYG60z2wHRM9PcHqCCUVaUw7dHN86XQgOQSgnbBFFpZFZkd7K4rymRVDs9nx2bQczKsRhTmAnGGNlVKgFksr2DEpmxa1CSQplIqQM60TAlZCJ1Dl1dpCNTOWdRdtnoDrqKdPYAnJS5/RKWesz0I7J5ZJHQ1J4rZkhBIhLqgE60TKsS5uTorP8vaEhI1lOtgpeUAi4OrsykiOrSdWWKgB6VpIUzYqkCpi6CGKM3YDIWoPN7iuWj84ON7bdKmqYo6iIHE4lSx2AlgUfYY3QTxlYIzvQZh9V6rZGZCMyjNAdeEUOKQM10LxINg1WE9GE2v5fJATyPOWg2PCdEj6a0FDwdpEZpYkWWQUsLoCi7rniCVHOwe96dClNMItQbm5bZU0xrcC9q84Up16ZQXznMIIUjHomWrk4KIJNuYdgerIAMhTKRQvc8hUZ9oGW3xq7KiN0PN/jevuhM6W0t6kWSttUE4VAX0eHlVrbR1R3upRqHiDeztRIJoUyksJV2tgLKGSwGgZhLGzLAHSwDxkgxeU19D6OjaP6Y1ni4zTWoghxFx2C1dYFdEJOx1EV08sZ7HuVMSWsC0ksQB+hUppidlKJKz0dvcbYkZ1pmuj8LSeBQSaj4hEpMU88xyW4LaAMYddJGRQNdICv2elAwoL2uzc01yhljg5DMB9Gdpvt2UifGF1kln7QB2XZBzrrMuInWgzc7xiZMluyqNEuADD7prWurpW2RwGQHmZcy9mIjWUnmQBnp9gFOK3IBjKofZLnAEP/QvGbprklK5OA7cFtXcaUBXXF9HiKVZThjhcjL0nO6oEabTcuMsjo2J1Ih7qSE4RMDlYyvK6Qe2ZAIWrHxWSvb3OWNVUBFnZSkGOyR7coHWEvoBashhs9yzRVbOMuUqDn4NJRKoyCMuB0LzM8LPDAuI2Y5t3o5x96unkscUc3VyShm2zywHNdJCRufGKhk/Ewg9ciGRNCKjc9aQRmsjQmgqijWempvnZf9NiGZ5n/lGOycgmyin5S7jnrJCOdAjo0BjY6TfzKDwpxzLmCbewgesz9mJaLDQz5a2/iU38rZF9J2LuDIznuZUx+Xo/mib7u5203V79mp7w4I5WG7NRqb/XLr7rceNh67q8s+XPzI6sXp998DCkCUfPpy4daJiKOFP5QnJwDA//W9iwDw6WNko3/Il8awAECDAQAoYN06yuCp9//5q3RpDCj8Zkvdq4AQLxJXkf5U1xxdzxCaGMAy9AVhl9nDaBOqamYmi5XGE0ZFFrHbET1ZRz6jEWLu4IMWUuvZjZeazqFeG1MUI9WpjBVRdV2sCJ0a6owEqQkOJnE0e/K3jTrkUdjJtKDvHMVql5DMMcOqsYChriz6mBKqeYzQaQ6VdBYihYORouPZbEO7WCrPvi0bt83QIunkRHX1dqw//dvfuK3wyJZtWqLa8tow8F5QqK8SAyNe81mlxxaGJ/G27DWXtt7eJyRAmZ00h1HFA94zU52ZRn4BGSjNoxnb5bFxO2T3ABGwCHlm4j96TEkG6a0W2wdtLdVzTyymHZh0jl7YeOHjhEQzxvz50tPTjN0nuwrnY8Z7ABZMlcN6PlmYQY1xTJnd2qhNLVtJto1GgKIi+1FOdhVpltcpAnL9kJ4tEa0jii6Fsd7GMbYmHWzgROmcyPmb0RxNZZClKv6x67WOJ6vo1jO6Rctru7QEQ2Pw5kBm8FwXTVxNqYChUNuoi5ICecB607R0mLm9TfqM6+FetQxq0+naGrqMURx3w67TgOOm6+dLujJDc5VGdOgEh2Gvo7pJw4do/gGKK1RsE9kL1FxC8TIVz1DzAhXzkbxIxQvIRh7cq9N7hKltVhloG+uXXmzrVznkMYixVJQMWDZNc9qWDEIXPbcBk6Yz9TZvsfY9NbFMpagBAfCAC/53Adz3LcgCqwooL0guCSB+AREOtrauy+YpV142pYDsky+bF1Kyzrcz03TxA73R3Tb6OKnkxo0E7IJVPrgfzhihSmDwIYKncenWscqEAGmpj/l+1D2+D+0niIHwUUSPqQ2s2ZciawAMVmYLgoo/tmCw4ustOEI4Wwi4+f0WEoqocrmFvrO5FQVsDqKOQoMKnDMJEI9Tr8132eIHbFPjMj/iJ/wYBfKMU1DlBM9nrvJDXm8nVWqmPcdVvhUceXqDx+wN9ObK0ykCHl0n9fiGEyOV1kkW4CERnL6/ZnXGTjBgyJJ15rH6TOoxEMmUIQNmohkgUYVQd8dmfPnx8qFac7sPhZhlndAxZEjOuU+dEYPnpDp8BaJdKXDcJUl3fGMKMRTptDddKDExt25DumhyqmEqM8p0Q8SHdjnj5SBx8Km5dTRxdwZ2yWDvS4XaRz8fI8UuoFL6aitX3FKcVtzir5RS9AopNxSQKUu2oBwhuf+WThYYEf5T99GySwXqKdr2KoFpjpyy5sKVYzAu0IKlazwcH7784PlfHdCHcEzBQi6S4kSjXOQSxC4ejyZBIvo/retLloL57wA+39OxZGDLlCVbjlwcXHn/HE87o/SYy5z7p3eaQOOj1UzovBYiYq3atJPo0KlLtwt69OrTb+BaD+Aiv5xOHP+KVw1+AEIwgmIACMEIiuEESdEMyxcIRWLJRVn+m3Mms8VqszucLrfH6/NDhAllXEiljXVeRElWVE03TMt2XM9Y50NMudXudHv9wXA0nkxn88Vytd5sd/vD8XS+XB+fnl9e394/Pr++fyDChDIupNLGOh9iyqW2Puba9uP8qLmQShvrfIgpl9r6ME7zsm77cV73837084IoyYqq6YZp2Y7r+UEYxUma5UVZ1U3b9cM4zcu67Yfj6Xy53u6P5+v9+f7+ACJMKAMQYUIZF1JpY/0gjOIkzfKirOqm7fphdNO8rNt+nNf9vN+v2DUX3/9+EilvdRSBYFBsx0SX+9zwKQqM+fVB3gls1ApEzLoGlRxdh1xZktVqJZJaG/GIiZvMay8qZoqRilm9JUFyBkp4jNbFTp3RTp0vjIWPzlmoCNZmkoZQ8lVM0sC1cz+KobU+y5vNqipaNTjX87qNBZCiYvsCVNL0DNzSCEOd0cGRjXhUK83FJtRItyhJyao6pDkTeyIp2iZ9Jau6jfCjyVhY1aPyUfItjXRKFrkIgGrVsGJ2suw3HOwgGNdQPHqpWtw71wn5asdJwHuMKolyX/UgyRIS0Udsz26Gz0ehIFqiN+3iTKdF3iQ7Ex095ETEMePZMYvJW+Rir+UujNQYW8dosuXPTlTbkUVvVYrIwyZ4Ks2g2iIi+lwTfL4oaYFzuVwud77ae4qk29uR1Y6IshkxB6YmoOPM0d2KSPvIzCjFzBFhP5rRpkyUusZH5DFFr4guO0YHGIxYzqFtIa62EAQjQgEVK9GRKHl+Dc0C2KmcwD2bQsAAQTGcYJ3ms3O0DYCgGE6wSNUe5BhTKdecimVZrWP1nhNflF5aHv7qYP0L2Zs3sHufDZvilZL/GCbXpRVX88lclic2Ld2AWEwTmJDdb7H5Zl+vAG/XSv2+eYsep5AAE+M5pfzaOMNAD68ZUNZLun9vSM6/TBGKubLjDpRS3SvqLVeV4dh+Br4C/LzFQlejzx+dH7CMvRydb/Z3Rfe+Hf/P78P1u9lcJ+X4TxIP6rrJzoJ62dxSh76MHQPZVFLlzR4fZMQyO7dGKAF+nUVARwvDCRZJ0YxfQ0N7cezmkGCAoBhOsEiKZtgcu3UTDBAUwwkWSdEMm2P3NjswQFDZEWnDxBUTW6bDPfFqvV9Bf3/5+fUXkvrp0+d/eoPRT+x54df/n3++fH23UF1liivr2WIRYghlkSaGHYFKPcGNQ5Z+wEm/x7WHb77LPmn9GzBf8b15K2+DKrZQSpyu5UUU0n63jfXj6M13y/LbH2Df/0TF4T7K1gM9ivptcXMKjP0c0P+HPGxfGJxMk9chdz4J0vw53l1PET8P78pSC/Mp5s/1ft5zLwAA') format('woff2'); }
:root {
  --bg:         #F2F2F7;
  --text:       #1c1c1e;
  --sub:        #6c6c70;
  --sep:        rgba(0,0,0,0.07);
  --hover:      rgba(0,0,0,0.05);
  --accent:     #007AFF;
  --today-bg:   #007AFF;
  --today-text: #ffffff;
  --cal-past:   #c7c7cc;
  --prog-bg:    rgba(0,0,0,0.07);
  --sel-bg:     rgba(0,122,255,0.10);
  --card-bg:    #ffffff;
  --card-shadow: rgba(0,0,0,0.10);
}
html, body { background: var(--bg); }
html.dark {
  --bg:         #1c1c1e;
  --text:       #f2f2f7;
  --sub:        #8e8e93;
  --sep:        rgba(255,255,255,0.09);
  --hover:      rgba(255,255,255,0.07);
  --accent:     #0A84FF;
  --today-bg:   #0A84FF;
  --cal-past:   #48484a;
  --prog-bg:    rgba(255,255,255,0.1);
  --sel-bg:     rgba(10,132,255,0.15);
  --card-bg:    rgba(255,255,255,0.08);
  --card-shadow: rgba(0,0,0,0.25);
}
* { margin:0; padding:0; box-sizing:border-box; }
html {
  font-family: -apple-system, system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
  -webkit-font-smoothing: antialiased;
  user-select: none;
  width: 240px;
  height: 100%;
}
body {
  background: var(--bg);
  width: 240px;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ── header ── */
.hdr {
  flex-shrink: 0;
  padding: 14px 16px 11px;
}
.hdr-greeting {
  font-family: 'Inter', -apple-system, sans-serif;
  font-size: 18px;
  font-weight: 400;
  letter-spacing: -0.3px;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.hdr-greeting strong {
  font-weight: 600;
}
.hdr-meta {
  margin-top: 4px;
  font-size: 11px;
  color: var(--sub);
  display: flex;
  align-items: center;
  gap: 5px;
}
.hdr-dot { width: 3px; height: 3px; border-radius: 50%; background: var(--sub); opacity: 0.5; }
.hdr-count { color: var(--accent); font-weight: 500; }

/* ── calendar ── */
.cal-wrap {
  flex-shrink: 0;
  margin: 0 10px 10px;
  padding: 10px 8px 8px;
  background: var(--card-bg);
  border-radius: 12px;
  box-shadow: 0 2px 10px var(--card-shadow);
}
.cal-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.cal-nav {
  background: none; border: none; cursor: pointer;
  color: var(--sub); font-size: 14px; line-height: 1;
  padding: 0 2px; flex-shrink: 0;
}
.cal-nav:hover { color: var(--text); }
.cal-month-lbl { font-size: 10px; font-weight: 700; letter-spacing: 0.5px; color: var(--sub); flex: 1; }
.cal-year-row {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 5px;
}
.cal-year-pct { font-size: 10px; color: var(--sub); }
.cal-year-pct strong { color: var(--text); font-weight: 600; }
.cal-days-left { font-size: 10px; color: var(--sub); flex-shrink: 0; }
.cal-progress-bar {
  height: 2px; border-radius: 1px;
  background: var(--prog-bg); margin-bottom: 8px; overflow: hidden;
}
.cal-progress-fill { height: 100%; border-radius: 1px; background: var(--accent); transition: width 0.2s; }
.cal-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  justify-items: center;
  align-items: center;
  gap: 2px 0;
}
.cal-dow {
  font-size: 9px; font-weight: 600; letter-spacing: 0.3px;
  color: var(--sub); padding-bottom: 3px;
  width: 28px; text-align: center;
}
.cal-cell {
  font-size: 11px; font-variant-numeric: tabular-nums;
  width: 28px; height: 28px;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  border-radius: 6px;
  cursor: pointer; background: transparent;
  flex-shrink: 0; gap: 1px;
}
.cal-spacer { display: block; width: 28px; height: 28px; flex-shrink: 0; }
.cal-cell:hover { background: var(--hover); }
.cal-cell.past { color: var(--cal-past); }
.cal-cell.today {
  background: var(--today-bg) !important;
  color: var(--today-text); font-weight: 700;
}
.cal-cell.selected:not(.today) {
  background: var(--sel-bg) !important;
  color: var(--accent); font-weight: 600;
}
.cal-num { line-height: 1; }
.cal-ev-dot { width: 3px; height: 3px; border-radius: 50%; background: var(--accent); flex-shrink: 0; }
.cal-cell.today .cal-ev-dot { background: var(--today-text); }
.cal-cell.past .cal-ev-dot { background: var(--cal-past); }

/* ── events pane: scrollable ── */
.events-pane {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
}
.events-pane::-webkit-scrollbar { width: 4px; }
.events-pane::-webkit-scrollbar-thumb { background: var(--sep); border-radius: 2px; }

.events-day-lbl {
  padding: 8px 16px 3px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  color: var(--sub);
}
.events-day-lbl.today-lbl {
  display: flex; align-items: center;
}
.today-pill {
  background: var(--accent);
  color: #fff;
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.5px;
}
.sec {
  padding: 6px 16px 1px;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  color: var(--sub);
  display: flex;
  align-items: center;
  gap: 5px;
}
.sec-pip { width: 5px; height: 5px; border-radius: 50%; flex-shrink: 0; }

.ev {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 5px 14px;
  min-height: 38px;
  border-radius: 6px;
  margin: 0 4px;
  cursor: default;
}
.ev.clickable { cursor: pointer; }
.ev.clickable:hover { background: var(--hover); }
.ev.active-card {
  background: var(--card-bg);
  border-radius: 10px;
  margin: 2px 8px;
  padding: 8px 10px;
  box-shadow: 0 2px 8px var(--card-shadow);
}
.ev-dot { width: 3px; border-radius: 2px; align-self: stretch; flex-shrink: 0; min-height: 28px; }
.ev-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.ev-time {
  font-size: 10px;
  color: var(--sub);
  font-variant-numeric: tabular-nums;
}
.ev-title {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 12px;
  font-weight: 500;
}
.ev-title.bold { font-weight: 700; }
.ev-arrow { font-size: 10px; color: var(--sub); flex-shrink: 0; opacity: 0.6; margin-top: 4px; }

.sep { height: 1px; background: var(--sep); margin: 3px 10px; }
.empty-msg {
  padding: 16px;
  text-align: center;
  color: var(--sub);
  font-size: 12px;
}

/* ── footer ── */
.footer {
  flex-shrink: 0;
  border-top: 1px solid var(--sep);
}
.foot-row {
  padding: 7px 16px;
  font-size: 12px;
  color: var(--sub);
  cursor: pointer;
}
.foot-row:hover { color: var(--text); background: var(--hover); }

/* ── prefs ── */
.prefs-title {
  padding: 10px 14px 5px;
  font-size: 10px; font-weight: 700; letter-spacing: 0.4px;
  text-transform: uppercase; color: var(--sub);
}
.mode-row {
  display: flex; align-items: center;
  padding: 7px 14px; font-size: 13px;
  color: var(--text); cursor: pointer; gap: 9px;
}
.mode-row:last-child { border-radius: 0 0 10px 10px; }
.mode-row:hover { background: var(--hover); }
.mode-check {
  width: 15px; height: 15px; border-radius: 50%;
  border: 1.5px solid var(--sub); flex-shrink: 0;
}
.mode-check.on {
  border-color: var(--accent); background: var(--accent);
  box-shadow: inset 0 0 0 3px var(--bg);
}
"""

JS = r"""
var ALL_EVENTS = [];
var TODAY_STR = '';
var todayY = 0, todayM = 0, todayD = 0;
var curY = 0, curM = 0;
var selectedDate = null;
var MONTH_NAMES = ['January','February','March','April','May','June',
                   'July','August','September','October','November','December'];

function init(eventsJson, todayStr) {
  ALL_EVENTS = eventsJson;
  TODAY_STR  = todayStr;
  var p = todayStr.split('-');
  todayY = +p[0]; todayM = +p[1]; todayD = +p[2];
  curY = todayY; curM = todayM;
  renderCalendar();
  selectDateStr(todayStr);
}

function prevMonth() {
  curM--; if (curM < 1) { curM = 12; curY--; }
  renderCalendar();
  showFirstEventOfMonth();
}

function nextMonth() {
  curM++; if (curM > 12) { curM = 1; curY++; }
  renderCalendar();
  showFirstEventOfMonth();
}

function showFirstEventOfMonth() {
  var pfx = curY + '-' + String(curM).padStart(2,'0');
  var dates = ALL_EVENTS
    .filter(function(e){ return e.date.startsWith(pfx); })
    .map(function(e){ return e.date; })
    .filter(function(d,i,a){ return a.indexOf(d)===i; });
  dates.sort();
  if (dates.length) selectDateStr(dates[0]);
  else {
    selectedDate = pfx + '-01';
    renderEvents(selectedDate);
  }
}

function renderCalendar() {
  var daysInMonth = new Date(curY, curM, 0).getDate();
  var firstDow    = new Date(curY, curM - 1, 1).getDay(); // 0=Sun

  document.getElementById('cal-month-lbl').textContent =
    MONTH_NAMES[curM-1].toUpperCase() + ' ' + curY;

  // year progress (always based on today, not the browsed month)
  var isLeap   = (todayY % 4 === 0 && (todayY % 100 !== 0 || todayY % 400 === 0));
  var daysInYear = isLeap ? 366 : 365;
  var dayOfYear = 0;
  var daysPerMonth = [31,isLeap?29:28,31,30,31,30,31,31,30,31,30,31];
  for (var i = 0; i < todayM - 1; i++) dayOfYear += daysPerMonth[i];
  dayOfYear += todayD;
  var daysLeftYear = daysInYear - dayOfYear;
  var pct = (dayOfYear / daysInYear * 100).toFixed(1);

  var pctEl  = document.getElementById('cal-year-pct');
  var dLeftEl = document.getElementById('cal-days-left');
  var fillEl  = document.getElementById('cal-prog-fill');
  if (pctEl)  pctEl.innerHTML  = '<strong>' + pct + '%</strong> of ' + todayY;
  if (dLeftEl) dLeftEl.textContent = daysLeftYear + ' days left';
  fillEl.style.width = pct + '%';

  // grid
  var DOW = ['S','M','T','W','T','F','S'];
  var html = DOW.map(function(d){ return '<span class="cal-dow">'+d+'</span>'; }).join('');
  for (var i = 0; i < firstDow; i++) html += '<span class="cal-spacer"></span>';

  for (var d = 1; d <= daysInMonth; d++) {
    var ds = curY + '-' + String(curM).padStart(2,'0') + '-' + String(d).padStart(2,'0');
    var isToday   = (ds === TODAY_STR);
    var isCellPast = !isToday && (
      curY < todayY || (curY === todayY && curM < todayM) ||
      (curY === todayY && curM === todayM && d < todayD));
    var isSel = (ds === selectedDate && !isToday);
    var cls = 'cal-cell'
      + (isToday ? ' today' : '')
      + (isCellPast ? ' past' : '')
      + (isSel ? ' selected' : '');
    html += '<span class="'+cls+'" onclick="selectDateStr(\''+ds+'\')">'+d+'</span>';
  }
  document.getElementById('cal-grid').innerHTML = html;
}

function selectDateStr(dateStr) {
  selectedDate = dateStr;
  // update selected highlight without full re-render
  document.querySelectorAll('.cal-cell').forEach(function(c) {
    c.classList.remove('selected');
    var ds = c.getAttribute('onclick');
    if (ds && ds.indexOf("'"+dateStr+"'") !== -1 && !c.classList.contains('today')) {
      c.classList.add('selected');
    }
  });
  renderEvents(dateStr);
}

function renderEvents(dateStr) {
  var pane = document.getElementById('events-pane');
  if (!pane) return;

  var evs = ALL_EVENTS.filter(function(e){ return e.date === dateStr; });

  var lbl = (dateStr === TODAY_STR) ? 'Today' : (function(){
    var p = dateStr.split('-');
    var d = new Date(+p[0], +p[1]-1, +p[2]);
    return d.toLocaleDateString('en-US', {weekday:'long', month:'long', day:'numeric'});
  })();

  if (evs.length === 0) {
    pane.innerHTML = '<div class="empty-msg">No events on ' + lbl + '</div>';
    pane.scrollTop = 0;
    return;
  }

  var isToday = (dateStr === TODAY_STR);
  var html = isToday
    ? '<div class="events-day-lbl today-lbl"><span class="today-pill">TODAY</span></div>'
    : '<div class="events-day-lbl">' + lbl + '</div>';

  if (isToday) {
    // group by live status
    var SEC_META = {
      past:  ['#c7c7cc', 'Earlier'],
      now:   ['#34C759', 'Now'],
      soon:  ['#FF9500', 'Starting soon'],
      later: ['#8e8e93', 'Later today']
    };
    var ORDER = ['now','soon','later','past'];
    var groups = {};
    evs.forEach(function(ev){ (groups[ev.status] = groups[ev.status]||[]).push(ev); });
    var first = true;
    var anchorSet = false;
    ORDER.forEach(function(sec){
      if (!groups[sec] || !groups[sec].length) return;
      if (!first) html += '<div class="sep"></div>';
      first = false;
      var sm = SEC_META[sec];
      // mark the first non-past section as the scroll anchor
      var anchorId = (!anchorSet && sec !== 'past') ? ' id="upcoming-anchor"' : '';
      if (anchorId) anchorSet = true;
      html += '<div class="sec"'+anchorId+'><span class="sec-pip" style="background:'+sm[0]+'"></span>'+sm[1]+'</div>';
      groups[sec].forEach(function(ev){ html += evRow(ev, sec === 'now'); });
    });
  } else {
    // other days: flat list, no status groups
    evs.forEach(function(ev){ html += evRow(ev, false); });
  }

  pane.innerHTML = html;
}

function evRow(ev, bold) {
  var boldCls   = bold ? ' bold' : '';
  var cardCls   = bold ? ' active-card' : '';
  var clickable = ev.join_link ? ' clickable' : '';
  var onclick   = ev.join_link
    ? ' onclick="window.webkit.messageHandlers.join.postMessage(\''+ev.join_link+'\')"' : '';
  var arrow = ev.join_link ? '<span class="ev-arrow">↗</span>' : '';
  return '<div class="ev'+cardCls+clickable+'"'+onclick+'>'
    + '<span class="ev-dot" style="background:'+ev.color+'"></span>'
    + '<div class="ev-body">'
    + '<span class="ev-time">'+ev.start+' – '+ev.end+'</span>'
    + '<span class="ev-title'+boldCls+'">'+ev.title+'</span>'
    + '</div>'
    + arrow + '</div>';
}
"""

def generate_html(events, mode=None):
    if mode is None: mode = load_appearance_mode()
    bc       = body_class(mode)
    accent       = ACCENT_COLORS[load_accent_color()]
    accent_style = f'style="--accent:{accent};--today-bg:{accent}"'
    now      = datetime.datetime.now()
    today    = now.date()
    today_str = today.strftime("%Y-%m-%d")
    date_str = now.strftime("%A, %B %-d")
    name     = get_first_name()
    greet    = greeting()


    # annotate status for today's events
    for ev in events:
        if ev["date"] == today_str:
            ev["status"] = event_status_str(ev, now)
        else:
            ev["status"] = "later"

    events_json = json.dumps(events, ensure_ascii=False)

    cal_html = """<div class="cal-wrap">
  <div class="cal-head">
    <button class="cal-nav" onclick="prevMonth()">&#8249;</button>
    <span class="cal-month-lbl" id="cal-month-lbl"></span>
    <button class="cal-nav" onclick="nextMonth()">&#8250;</button>
  </div>
  <div class="cal-year-row">
    <span class="cal-year-pct" id="cal-year-pct"></span>
    <span class="cal-days-left" id="cal-days-left"></span>
  </div>
  <div class="cal-progress-bar"><div class="cal-progress-fill" id="cal-prog-fill" style="width:0%"></div></div>
  <div class="cal-grid" id="cal-grid"></div>
</div>"""

    return f"""<!DOCTYPE html>
<html class="{bc}" {accent_style}><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>{CSS}</style>
</head><body>
<div class="hdr">
  <div class="hdr-greeting">{_esc(greet)}, <strong>{_esc(name)}!</strong></div>
  <div class="hdr-meta">{date_str}</div>
</div>
{cal_html}
<div class="events-pane" id="events-pane"></div>
<script>{JS}</script>
<script>init({events_json}, '{today_str}');</script>
</body></html>"""


def generate_prefs_html(current_mode):
    bc = body_class(current_mode)
    cur_accent = load_accent_color()
    def chk(m): return ' on' if current_mode == m else ''
    def row(m, label):
        return (f'<div class="mode-row" '
                f'onclick="window.webkit.messageHandlers.action.postMessage(\'mode:{m}\')">'
                f'<span class="mode-check{chk(m)}"></span>{label}</div>')
    def swatch(name, color):
        border = '3px solid var(--text)' if cur_accent == name else '3px solid transparent'
        return (f'<span class="accent-swatch" style="background:{color};outline:{border}" '
                f'onclick="window.webkit.messageHandlers.action.postMessage(\'accent:{name}\')"></span>')
    swatches = (swatch('blue','#007AFF') + swatch('red','#FF3B30') +
                swatch('green','#34C759') + swatch('yellow','#FFD60A'))
    pa = ACCENT_COLORS[cur_accent]
    p_accent_style = f'style="--accent:{pa};--today-bg:{pa}"'
    return f"""<!DOCTYPE html>
<html class="{bc}" {p_accent_style}><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>{CSS}
.accent-row {{ display:flex; align-items:center; gap:10px; padding:8px 14px; }}
.accent-swatch {{ width:22px; height:22px; border-radius:50%; cursor:pointer;
  outline-offset:2px; flex-shrink:0; }}
</style>
</head><body>
<div class="prefs-title">Appearance</div>
{row('system','System')}
{row('light','Light')}
{row('dark','Dark')}
<div class="prefs-title" style="margin-top:4px">Accent Color</div>
<div class="accent-row">{swatches}</div>
</body></html>"""


PREFS_W   = 180
PREFS_H   = 28 + 3 * 34 + 28 + 46  # appearance rows + accent section
POPOVER_W = 240
MAX_POP_H = 500   # fixed height — events pane always scrolls

# Fixed-height sections (px)
_HDR_H  = 61   # padding + greeting + meta
_CAL_H  = 185  # cal-head + progress + grid + padding

def _popover_height(events):
    return MAX_POP_H

# ── ObjC ───────────────────────────────────────────────────────────────────────

def _zoom_native_url(https_url):
    """Convert zoom.us/j/ID?pwd=X to zoommtg://zoom.us/join?action=join&confno=ID&pwd=X"""
    m = re.search(r'zoom\.us/j/(\d+)', https_url)
    if not m:
        return None
    conf = m.group(1)
    pwd_m = re.search(r'[?&]pwd=([^&]+)', https_url)
    native = f'zoommtg://zoom.us/join?action=join&confno={conf}'
    if pwd_m:
        native += f'&pwd={pwd_m.group(1)}'
    return native


class JoinHandler(AppKit.NSObject):
    def userContentController_didReceiveScriptMessage_(self, uc, msg):
        url_str = str(msg.body())
        if not url_str.startswith("http"):
            return
        if 'zoom.us/j/' in url_str:
            native = _zoom_native_url(url_str)
            if native:
                AppKit.NSWorkspace.sharedWorkspace().openURL_(
                    Foundation.NSURL.URLWithString_(native))
                return
        AppKit.NSWorkspace.sharedWorkspace().openURL_(
            Foundation.NSURL.URLWithString_(url_str))


class ActionHandler(AppKit.NSObject):
    def initWithDelegate_(self, delegate):
        self = objc.super(ActionHandler, self).init()
        if self is not None:
            self._delegate = delegate
        return self

    def userContentController_didReceiveScriptMessage_(self, uc, msg):
        payload = str(msg.body())
        if payload == "quit":
            AppKit.NSApplication.sharedApplication().terminate_(None)
        elif payload == "prefs":
            self._delegate.showPrefsPanel()
        elif payload.startswith("mode:"):
            mode = payload[5:]
            save_appearance_mode(mode)
            self._delegate.applyAppearance_(mode)
            self._delegate.refreshPrefsPanel()



class PopoverVC(AppKit.NSViewController):
    def loadView(self):
        cfg = WebKit.WKWebViewConfiguration.alloc().init()
        uc  = cfg.userContentController()
        self._join_handler = JoinHandler.alloc().init()
        uc.addScriptMessageHandler_name_(self._join_handler, "join")
        self._action_handler = None

        frame = Foundation.NSMakeRect(0, 0, POPOVER_W, MAX_POP_H)
        wv = WebKit.WKWebView.alloc().initWithFrame_configuration_(frame, cfg)
        try:
            wv.setValue_forKey_(AppKit.NSColor.clearColor(), "backgroundColor")
            wv.setUnderPageBackgroundColor_(AppKit.NSColor.clearColor())
        except Exception:
            pass
        wv.setWantsLayer_(True)
        wv.layer().setCornerRadius_(12.0)
        wv.layer().setMasksToBounds_(True)
        self._wv = wv
        self._uc = uc
        self.setView_(wv)

    def setActionHandler_(self, handler):
        self._action_handler = handler
        self._uc.addScriptMessageHandler_name_(handler, "action")

    def show_events(self, events):
        html = generate_html(events)
        h    = _popover_height(events)
        def update():
            self.view().setFrameSize_(Foundation.NSMakeSize(POPOVER_W, h))
            self._wv.loadHTMLString_baseURL_(html, None)
        AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(update)
        return h


class PrefsActionHandler(AppKit.NSObject):
    def initWithDelegate_(self, delegate):
        self = objc.super(PrefsActionHandler, self).init()
        if self is not None:
            self._delegate = delegate
        return self

    def userContentController_didReceiveScriptMessage_(self, uc, msg):
        payload = str(msg.body())
        if payload.startswith("mode:"):
            mode = payload[5:]
            save_appearance_mode(mode)
            self._delegate.applyAppearance_(mode)
            self._delegate.refreshPrefsPanel()
        elif payload.startswith("accent:"):
            name = payload[7:]
            if name in ACCENT_COLORS:
                save_accent_color(name)
                self._delegate.applyAppearance_(load_appearance_mode())
                self._delegate.refreshPrefsPanel()


class HuddleDelegate(AppKit.NSObject):

    def applicationDidFinishLaunching_(self, _notif):
        self._store        = None
        self._icon_day     = None
        self._events       = []
        self._prefs_pop    = None
        self._prefs_wv     = None
        self._prefs_action = None

        self._si = AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(-1)
        self._update_icon()
        btn = self._si.button()
        btn.setTarget_(self)
        btn.setAction_(objc.selector(self.togglePopover_, signature=b'v@:@'))
        btn.sendActionOn_(AppKit.NSEventMaskLeftMouseUp | AppKit.NSEventMaskRightMouseUp)

        self._vc = PopoverVC.alloc().init()
        self._vc.loadView()
        action_handler = ActionHandler.alloc().initWithDelegate_(self)
        self._vc.setActionHandler_(action_handler)

        self._pop = AppKit.NSPopover.alloc().init()
        self._pop.setBehavior_(AppKit.NSPopoverBehaviorTransient)
        self._pop.setContentViewController_(self._vc)
        self._pop.setContentSize_(Foundation.NSMakeSize(POPOVER_W, MAX_POP_H))

        store = EventKit.EKEventStore.alloc().init()
        def handler(granted, error):
            if granted:
                self._store = store
        store.requestFullAccessToEventsWithCompletion_(handler)

        AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            60.0, self, objc.selector(self.timerFired_, signature=b'v@:@'), None, True)

    def applyAppearance_(self, mode):
        self._vc.show_events(self._events)

    @objc.python_method
    def _countdown_label(self):
        now = datetime.datetime.now()
        today_str = now.date().isoformat()
        upcoming = [e for e in self._events if e['date'] == today_str]
        if not upcoming:
            return ""
        upcoming.sort(key=lambda e: e['start_dt'])
        for e in upcoming:
            start = datetime.datetime.fromisoformat(e['start_dt'])
            end   = datetime.datetime.fromisoformat(e['end_dt'])
            if start <= now <= end:
                return "now"
            if start > now:
                delta = int((start - now).total_seconds() / 60)
                if delta <= 15:
                    return f"{delta}m"
                return ""
        return ""

    def _update_icon(self):
        today = datetime.date.today()
        if today.day != self._icon_day:
            self._icon_day = today.day
            self._si.button().setImage_(make_menubar_icon(today.day))
        self._si.button().setTitle_("")

    def showEvents(self):
        h = self._vc.show_events(self._events)
        self._pop.setContentSize_(Foundation.NSMakeSize(POPOVER_W, h))

    def showPrefsPanel(self):
        if self._prefs_pop is None:
            cfg = WebKit.WKWebViewConfiguration.alloc().init()
            self._prefs_action = PrefsActionHandler.alloc().initWithDelegate_(self)
            cfg.userContentController().addScriptMessageHandler_name_(
                self._prefs_action, "action")

            wv = WebKit.WKWebView.alloc().initWithFrame_configuration_(
                Foundation.NSMakeRect(0, 0, PREFS_W, PREFS_H), cfg)
            try:
                wv.setValue_forKey_(AppKit.NSColor.clearColor(), "backgroundColor")
                wv.setUnderPageBackgroundColor_(AppKit.NSColor.clearColor())
            except Exception:
                pass
            self._prefs_wv = wv

            vc = AppKit.NSViewController.alloc().init()
            vc.setView_(wv)

            pop = AppKit.NSPopover.alloc().init()
            pop.setContentViewController_(vc)
            pop.setContentSize_(Foundation.NSMakeSize(PREFS_W, PREFS_H))
            pop.setBehavior_(AppKit.NSPopoverBehaviorTransient)
            self._prefs_pop = pop

        self.refreshPrefsPanel()

        btn = self._si.button()
        self._prefs_pop.showRelativeToRect_ofView_preferredEdge_(
            btn.bounds(), btn, 1)

    def closePrefsPanel(self):
        if self._prefs_pop and self._prefs_pop.isShown():
            self._prefs_pop.performClose_(None)

    def refreshPrefsPanel(self):
        if self._prefs_wv is None:
            return
        html = generate_prefs_html(load_appearance_mode())
        self._prefs_wv.loadHTMLString_baseURL_(html, None)

    def togglePopover_(self, sender):
        event = AppKit.NSApp.currentEvent()
        if event and event.type() == AppKit.NSEventTypeRightMouseUp:
            self._showContextMenu()
            return
        if self._pop.isShown():
            self._pop.performClose_(sender)
        else:
            self._events = fetch_month_events(self._store) if self._store else []
            self.showEvents()
            btn = self._si.button()
            self._pop.showRelativeToRect_ofView_preferredEdge_(
                btn.bounds(), btn, 1)

    @objc.python_method
    def _showContextMenu(self):
        menu = AppKit.NSMenu.alloc().init()
        prefsItem = menu.addItemWithTitle_action_keyEquivalent_(
            "Preferences", objc.selector(self.menuPrefs_, signature=b'v@:@'), "")
        infoItem  = menu.addItemWithTitle_action_keyEquivalent_(
            "Get Info",    objc.selector(self.menuGetInfo_, signature=b'v@:@'), "")
        menu.addItem_(AppKit.NSMenuItem.separatorItem())
        quitItem  = menu.addItemWithTitle_action_keyEquivalent_(
            "Quit UpNext", objc.selector(self.menuQuit_, signature=b'v@:@'), "")
        for item in [prefsItem, infoItem, quitItem]:
            item.setTarget_(self)
            item.setEnabled_(True)
        event = AppKit.NSApp.currentEvent()
        AppKit.NSMenu.popUpContextMenu_withEvent_forView_(
            menu, event, self._si.button())

    def menuPrefs_(self, sender):
        self.showPrefsPanel()

    def menuGetInfo_(self, sender):
        AppKit.NSApp.activateIgnoringOtherApps_(True)
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_("UpNext")
        alert.setInformativeText_("Version 3.0\n© 2026 James Joice. All rights reserved.")
        alert.addButtonWithTitle_("OK")
        alert.runModal()

    def menuQuit_(self, sender):
        AppKit.NSApplication.sharedApplication().terminate_(None)

    def timerFired_(self, _timer):
        if self._store:
            self._events = fetch_month_events(self._store)
        self._update_icon()
        if self._pop.isShown():
            self.showEvents()


if __name__ == "__main__":
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(1)
    delegate = HuddleDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.run()
