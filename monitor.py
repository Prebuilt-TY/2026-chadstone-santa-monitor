"""Chadstone Standard Santa appointment watcher. Fail-closed until calibrated."""
import argparse
import asyncio
import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DIAG = ROOT / "diagnostics"
STATE = ROOT / "state.json"
TZ = ZoneInfo("Australia/Melbourne")


def parse_datetime(value):
    value = (value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?", value):
        raise ValueError("An explicit ISO date AND time is required")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (dt.replace(tzinfo=TZ) if dt.tzinfo is None else dt).astimezone(TZ)


def filter_slots(raw, cfg, now=None):
    now = now or datetime.now(TZ)
    first, last = date.fromisoformat(cfg["start_date"]), date.fromisoformat(cfg["end_date"])
    if first > last:
        raise ValueError("Invalid date range")
    slots = set()
    for value in raw:
        try:
            dt = parse_datetime(value)
        except (TypeError, ValueError):
            continue
        if first <= dt.date() <= last and dt > now:
            slots.add(dt.isoformat(timespec="minutes"))
    return sorted(slots)


def safe_url(url):
    """Strip URL query strings and fragments from public GitHub diagnostics."""
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def send_push(cfg, values, title):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{24,120}", topic):
        raise RuntimeError("NTFY_TOPIC secret missing/invalid (24+ random characters required)")
    link = cfg["booking_link"]
    body = "Chadstone Standard Santa Photography:\n" + "\n".join(values) + "\nBook: " + link
    body += "\nAvailability may disappear before you book."
    req = urllib.request.Request(
        "https://ntfy.sh/" + topic,
        data=body.encode("utf-8"),
        headers={"Title": title, "Click": link, "Priority": "high", "Tags": "calendar"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as res:
        if not 200 <= res.status < 300:
            raise RuntimeError("ntfy push failed: HTTP " + str(res.status))


def compare_notify(slots, cfg):
    previous = json.loads(STATE.read_text()) if STATE.exists() else {"last_slots": []}
    new = sorted(set(slots) - set(previous.get("last_slots", [])))
    if new:
        send_push(cfg, new, "Chadstone Santa: NEW booking available")
    # Only save a complete, verified snapshot after any required notification succeeds.
    STATE.write_text(json.dumps({"last_slots": slots}, indent=2) + "\n")
    print("Verified available: %d; newly found: %d" % (len(slots), len(new)))


async def diagnostic(context, label):
    DIAG.mkdir(exist_ok=True)
    report = {"note": label, "pages": []}
    for idx, page in enumerate(context.pages[:4]):
        entry = {"url": safe_url(page.url), "frames": []}
        try:
            await page.screenshot(path=str(DIAG / ("page-%d.png" % idx)), timeout=12000, full_page=True)
        except Exception as exc:
            entry["screenshot_error"] = str(exc)[:150]
        for frame in page.frames[:12]:
            f = {"url": safe_url(frame.url), "controls": []}
            try:
                controls = frame.locator("a, button, [role=button], [data-date], [data-time], [data-datetime]")
                for i in range(min(await controls.count(), 140)):
                    node = controls.nth(i)
                    try:
                        info = await node.evaluate("""el => ({
                            tag: el.tagName.toLowerCase(),
                            text: (el.innerText || el.textContent || '').trim().slice(0, 90),
                            aria: el.getAttribute('aria-label'),
                            datetime: el.getAttribute('data-datetime'),
                            date: el.getAttribute('data-date'),
                            time: el.getAttribute('data-time'),
                            href: el.getAttribute('href'),
                            disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true'
                        })""")
                        if info.get("href"):
                            info["href"] = safe_url(info["href"])
                        f["controls"].append(info)
                    except Exception:
                        continue
            except Exception as exc:
                f["error"] = str(exc)[:150]
            entry["frames"].append(f)
        report["pages"].append(entry)
    (DIAG / "probe.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print("DIAGNOSTIC SUMMARY: " + json.dumps({
        "note": label,
        "pages": [{"url": p["url"], "frames": [
            {"url": f["url"], "sample": [
                {"text": n["text"], "tag": n["tag"], "datetime": n["datetime"]}
                for n in f.get("controls", []) if ("book" in (n.get("text") or "").lower()
                    or n.get("datetime"))][:12]}
            for f in p["frames"]]} for p in report["pages"]]
    }, ensure_ascii=False)[:10000])



async def calendar_probe(page):
    """Collect booking calendar day-cell structure without selecting/booking anything."""
    payload = await page.evaluate(r'''() => {
      const text = el => (el?.innerText || el?.textContent || '').trim();
      const info = el => {
        if (!el) return null;
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        const attrs = {};
        for (const name of ['class','role','aria-label','aria-disabled','data-date','data-time','data-datetime','title','tabindex','disabled']) {
          const v = el.getAttribute(name);
          if (v !== null) attrs[name] = v.slice(0,180);
        }
        return {tag:el.tagName.toLowerCase(),text:text(el).slice(0,60),
          attrs, rect:{x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)},
          style:{pointerEvents:s.pointerEvents,cursor:s.cursor,background:s.backgroundImage.slice(0,150),opacity:s.opacity},
          html:el.outerHTML.slice(0,550)};
      };
      const headings = [...document.querySelectorAll('h1,h2,h3,h4,h5,div,span,p')]
        .filter(el => [...el.childNodes].some(n=>n.nodeType === 3 && /Select date\s*&\s*time/i.test(n.textContent||'')))
        .slice(0,8).map(info);
      const digits = [...document.querySelectorAll('body *')]
        .filter(el => el.children.length === 0 && /^\d{1,2}$/.test(text(el)) && el.getBoundingClientRect().width > 0)
        .slice(0,160).map(el => ({day:info(el),parent:info(el.parentElement),grandparent:info(el.parentElement?.parentElement)}));
      const navigation = [...document.querySelectorAll('body *')]
        .filter(el => el.children.length === 0 && /^(November 2026|December 2026|NEXT)$/i.test(text(el)))
        .slice(0,16).map(el=>({item:info(el),parent:info(el.parentElement),grandparent:info(el.parentElement?.parentElement)}));
      const calendar = [...document.querySelectorAll('[role=grid], [role=gridcell], [class*=calendar i], [class*=datepicker i], [class*=date-picker i]')]
        .slice(0,55).map(info);
      const titled = [...document.querySelectorAll('[aria-label], [data-date], [title]')]
        .filter(el=>{const r=el.getBoundingClientRect();return r.width>0&&r.height>0;})
        .slice(0,100).map(info);
      return {calendarHeadings:headings, digitCells:digits, navigation, calendarCandidates:calendar, labelledCandidates:titled};
    }''')
    path = DIAG / "calendar-diagnostics.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print("Calendar diagnostic: %d digit cells, %d candidate controls." %
          (len(payload["digitCells"]), len(payload["calendarCandidates"])))


async def inspect(cfg, probe):
    from playwright.async_api import async_playwright
    DIAG.mkdir(exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(timezone_id=cfg["timezone"], locale="en-AU")
        page = await context.new_page()
        try:
            response = await page.goto(cfg["official_url"], wait_until="domcontentloaded", timeout=40000)
            if response and response.status >= 400:
                raise RuntimeError("Official page HTTP %s" % response.status)
            await page.wait_for_timeout(2200)
            if probe:
                await diagnostic(context, "Official landing page BEFORE booking click")
            # In calibration mode, click first visible Book Now control for investigation only.
            # In real monitoring this must be confirmed specifically as Standard Santa.
            entry_selector = cfg.get("standard_entry_selector") or "a:has-text('Book Now'), button:has-text('Book Now')"
            controls = page.locator(entry_selector)
            visible = []
            for i in range(min(await controls.count(), 20)):
                if await controls.nth(i).is_visible():
                    visible.append(controls.nth(i))
            index = int(cfg.get("standard_entry_index", 0))
            if index >= len(visible):
                raise RuntimeError("No visible booking entry found; check landing-page diagnostic.")
            await visible[index].click(timeout=12000)
            await page.wait_for_timeout(20000 if probe else 5000)
            if probe:
                await diagnostic(context, "After booking entry click. NOT an availability check.")
                await calendar_probe(page)
                print("Probe complete; NO booking notifications were sent.")
                return []
            mandatory = ("standard_scope_selector", "slot_selector", "empty_state_selector",
                         "slot_datetime_attribute", "calendar_frame_url_contains")
            if not cfg.get("enabled") or not cfg.get("full_date_range_verified") or any(not cfg.get(k) for k in mandatory):
                raise RuntimeError("Calendar not calibrated; real monitoring remains disabled")
            matches = []
            for pg in context.pages:
                for frame in pg.frames:
                    if cfg["calendar_frame_url_contains"].lower() not in frame.url.lower():
                        continue
                    scope = frame.locator(cfg["standard_scope_selector"])
                    if await scope.count() == 1:
                        matches.append(scope)
            if len(matches) != 1:
                raise RuntimeError("Expected exactly one Standard Santa calendar; got " + str(len(matches)))
            scope = matches[0]
            controls = scope.locator(cfg["slot_selector"])
            if await controls.count() > 1000:
                raise RuntimeError("Too many candidate slots")
            raw = []
            for i in range(await controls.count()):
                node = controls.nth(i)
                if not await node.is_visible() or not await node.is_enabled():
                    continue
                if (await node.get_attribute("aria-disabled") or "").lower() == "true":
                    continue
                tag = await node.evaluate("el => el.tagName.toLowerCase()")
                role = (await node.get_attribute("role") or "").lower()
                if tag != "button" and role != "button":
                    continue
                label = ((await node.inner_text(timeout=1500)) + " " +
                         (await node.get_attribute("aria-label") or "")).lower()
                if re.search(r"sold out|fully booked|unavailable|sensitive|disabled", label):
                    continue
                raw_date = await node.get_attribute(cfg["slot_datetime_attribute"])
                if raw_date:
                    raw.append(raw_date)
            if not raw:
                # An empty view is NOT evidence of no availability; require explicit marker.
                marker = scope.locator(cfg["empty_state_selector"])
                if await marker.count() == 0 or not await marker.first.is_visible():
                    raise RuntimeError("No slots AND no explicit verified sold-out indicator")
            result = filter_slots(raw, cfg)
            await diagnostic(context, "Calibrated scan found %d matching slots" % len(result))
            return result
        except Exception as exc:
            await diagnostic(context, "PROBE/SCAN ERROR: " + str(exc)[:200])
            raise
        finally:
            await browser.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("probe", "monitor", "test-push"), default="probe")
    mode = parser.parse_args().mode
    cfg = json.loads((ROOT / "config.json").read_text())
    if mode == "test-push":
        send_push(cfg, ["TEST ONLY — NOT A REAL APPOINTMENT"],
                  "TEST ONLY: Chadstone Santa monitor")
        return
    if mode == "monitor":
        today = datetime.now(TZ).date()
        if today > date.fromisoformat(cfg["end_date"]):
            print("Monitoring date range ended; no scan")
            return
        if not cfg.get("enabled"):
            print("Safe-disabled: probe and calibrate the real booking calendar first")
            return
    slots = asyncio.run(inspect(cfg, probe=mode == "probe"))
    if mode == "monitor":
        compare_notify(slots, cfg)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("MONITOR ERROR (no false availability alert): " + str(exc), file=sys.stderr)
        sys.exit(1)
