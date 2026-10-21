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



async def probe_both_months(page, cfg):
    """Inspect Nov and Dec date cells using page style; optionally inspect day selection."""
    DIAG.mkdir(exist_ok=True)
    report = {"kind": "diagnostic_only", "months": [], "time_probe": None}
    async def snapshot(month_name):
        result = await page.evaluate(r'''() => {
          const root=document.querySelector('#booking-modal_wrapper');
          if (!root) return {error:"booking modal missing"};
          const heading=[...root.querySelectorAll('h4')].find(x=>/^(November|December) 2026$/.test(x.textContent.trim()));
          if (!heading) return {error:"month heading missing"};
          const grid=heading.parentElement.parentElement.parentElement;
          const days=[...grid.querySelectorAll('div')].filter(el=> el.childElementCount===0 && el.classList.contains('f1wa5vh2') && /^\d{1,2}$/.test(el.textContent.trim()));
          return {
             heading:heading.textContent.trim(),
             days:days.map(el=> {
               const cs=getComputedStyle(el);
               return {day:Number(el.textContent.trim()),className:el.className,
                 pointerEvents:cs.pointerEvents,cursor:cs.cursor,
                 diagonalMark:cs.backgroundImage.includes('linear-gradient'),
                 rect:{x:Math.round(el.getBoundingClientRect().x),y:Math.round(el.getBoundingClientRect().y)}
               };
             })
          };
        }''')
        if result.get("heading") != month_name or len(result.get("days", [])) < 28:
            raise RuntimeError("Calendar month not reliably loaded: " + json.dumps(result)[:220])
        report["months"].append(result)
        try:
            await page.screenshot(path=str(DIAG / ("calendar-" + month_name.split()[0].lower() + ".png")), full_page=False)
        except Exception as exc:
            print("Screenshot failed: " + str(exc)[:150])
        candidates=[d for d in result["days"] if
           cfg["start_date"] <= ("%04d-%02d-%02d" % (2026, 11 if month_name.startswith("November") else 12, d["day"])) <= cfg["end_date"]
           and d["pointerEvents"] != "none" and not d["diagonalMark"]]
        print("%s: %s target dates not crossed out and pointer-active" % (month_name, len(candidates)))
        return candidates

    november = await snapshot("November 2026")
    header=page.locator("#booking-modal_wrapper h4", has_text="November 2026")
    if await header.count()!=1:
        raise RuntimeError("Month heading not unique")
    right_arrow=header.locator("xpath=../..").locator("xpath=./div[last()]")
    if await right_arrow.count()!=1:
        raise RuntimeError("Next month arrow missing")
    await right_arrow.click(timeout=7000)
    await page.locator("#booking-modal_wrapper h4", has_text="December 2026").wait_for(timeout=12000)
    await page.wait_for_timeout(1400)
    december = await snapshot("December 2026")

    # Inspect one candidate day in EACH month if any are apparently selectable.
    # Only diagnostic UI interactions; never go past date/time exploration.
    report["time_probe"] = []

    async def inspect_candidate(month, day):
        label = f"2026-{month:02d}-{day:02d}"
        try:
            selector = "#booking-modal_wrapper div.f1wa5vh2"
            cells = page.locator(selector).filter(has_text=re.compile(r"^%d$" % day))
            if await cells.count() != 1:
                report["time_probe"].append({"date": label, "error": "Ambiguous date selector"})
                return
            await cells.click(timeout=7000)
            await page.wait_for_timeout(1600)
            try:
                await page.screenshot(
                    path=str(DIAG / f"after-date-selection-{month:02d}.png"),
                    full_page=False)
            except Exception:
                pass
            report["time_probe"].append({
                "selected_date": label,
                "visible_text": (await page.locator("#booking-modal_wrapper").inner_text(timeout=5000))[:2500],
                "buttons": await page.locator("#booking-modal_wrapper button").evaluate_all(
                    "els => els.slice(0,70).map(e=>({text:(e.innerText||'').slice(0,80),disabled:e.disabled}))")
            })
            print("Inspected selected date (no booking): " + label)
        except Exception as exc:
            report["time_probe"].append({"date": label, "error": str(exc)[:250]})
            print("Date diagnostic could not complete for " + label)

    # Calendar currently shows December.
    if december:
        await inspect_candidate(12, december[0]["day"])

    # Reopen a fresh booking calendar so November is independently checked
    # even if selecting December advanced the booking interface.
    if november:
        try:
            await page.goto(cfg["official_url"], wait_until="domcontentloaded", timeout=40000)
            await page.wait_for_timeout(2500)
            entry_selector = cfg.get("standard_entry_selector") or "a:has-text('Book Now'), button:has-text('Book Now')"
            controls = page.locator(entry_selector)
            visible = []
            for i in range(min(await controls.count(), 20)):
                if await controls.nth(i).is_visible():
                    visible.append(controls.nth(i))
            index = int(cfg.get("standard_entry_index", 0))
            if index >= len(visible):
                raise RuntimeError("Booking entry missing when reopening November")
            await visible[index].click(timeout=12000)
            await page.locator("#booking-modal_wrapper h4", has_text="November 2026").wait_for(timeout=25000)
            await page.wait_for_timeout(1000)
            await inspect_candidate(11, november[0]["day"])
        except Exception as exc:
            report["time_probe"].append({"month": "November 2026", "error": str(exc)[:250]})
            print("November time exploration failed; day state was still recorded.")
    (DIAG / "month-status.json").write_text(json.dumps(report,indent=2,ensure_ascii=False))
    print("Both-month calendar diagnostic saved. No booking was made.")



async def scan_confirmed_slots(page, cfg):
    """Fail-closed scan: all target dates in both months, then exact clickable times."""
    import calendar
    from datetime import datetime as dt
    DIAG.mkdir(exist_ok=True)
    root = page.locator("#booking-modal_wrapper")
    if await root.count() != 1 or not await root.is_visible():
        raise RuntimeError("Standard booking modal not open")
    title = await root.inner_text(timeout=5000)
    if "Santa Photography 2026" not in title or "Sensitive Santa" in title:
        raise RuntimeError("Cannot verify Standard Santa event identity")
    report = {"mode": "full-date-scan", "months": [], "time_probes": []}
    month_candidates = {}

    async def snapshot(month, label):
        data = await page.evaluate(r'''() => {
          const root = document.querySelector('#booking-modal_wrapper');
          const head = [...root.querySelectorAll('h4')].find(el => /^(November|December) 2026$/.test(el.textContent.trim()));
          if (!head) return {error:'month heading absent'};
          const grid = head.parentElement.parentElement.parentElement;
          const dayCells = [...grid.querySelectorAll('div')].filter(el =>
             el.childElementCount === 0 && el.classList.contains('f1wa5vh2') &&
             /^\d{1,2}$/.test(el.textContent.trim()));
          return {heading:head.textContent.trim(), days:dayCells.map(el => {
             const style = getComputedStyle(el);
             const rect = el.getBoundingClientRect();
             return {day:Number(el.textContent.trim()),
                pointerEvents:style.pointerEvents,
                cursor:style.cursor,
                crossedOut:style.backgroundImage.includes('linear-gradient'),
                visible:rect.width>0 && rect.height>0 };
          })};
        }''')
        days = data.get("days", [])
        expected = calendar.monthrange(2026, month)[1]
        if data.get("heading") != label or len(days) != expected or set(x["day"] for x in days) != set(range(1,expected+1)):
            raise RuntimeError("Calendar date coverage incomplete for "+ label)
        active = []
        for item in days:
            day = item["day"]
            localdate = f"2026-{month:02d}-{day:02d}"
            if cfg["start_date"] <= localdate <= cfg["end_date"] and \
                item["pointerEvents"] == "auto" and item["cursor"] == "pointer" and \
                not item["crossedOut"] and item["visible"]:
                active.append(day)
        report["months"].append({"month":label, "target_candidates":active,
                                  "inspected_dates":len([d for d in days if cfg["start_date"] <= f"2026-{month:02d}-{d['day']:02d}" <= cfg["end_date"]])})
        month_candidates[month] = active
        print(label + ": %d potential available dates" % len(active))

    try:
        await snapshot(11, "November 2026")
        h = root.locator("h4", has_text="November 2026")
        if await h.count() != 1:
            raise RuntimeError("November heading not unique")
        arrow = h.locator("xpath=../..").locator("xpath=./div[last()]")
        if await arrow.count()!=1:
            raise RuntimeError("December navigation missing")
        await arrow.click(timeout=7000)
        await root.locator("h4", has_text="December 2026").wait_for(timeout=12000)
        await page.wait_for_timeout(1200)
        await snapshot(12, "December 2026")
        if sum(len(v) for v in month_candidates.values()) > 42:
            raise RuntimeError("Implausibly many clickable dates: calibration required")
        if not any(month_candidates.values()):
            print("Complete target date scan: no selectable day, no notification")
            return []

        confirmed = []
        for month in (11,12):
            for day in month_candidates[month]:
                # Reset for each date; avoids selecting a time or booking accidentally.
                await page.goto(cfg["official_url"],wait_until="domcontentloaded",timeout=40000)
                await page.wait_for_timeout(2000)
                selector = cfg.get("standard_entry_selector") or "a:has-text('Book Now'), button:has-text('Book Now')"
                entries = page.locator(selector)
                shown=[]
                for i in range(min(await entries.count(),20)):
                    if await entries.nth(i).is_visible(): shown.append(entries.nth(i))
                idx=int(cfg.get("standard_entry_index",0))
                if idx>=len(shown): raise RuntimeError("Standard booking entry missing")
                await shown[idx].click(timeout=10000)
                modal=page.locator("#booking-modal_wrapper")
                await modal.locator("h4",has_text="November 2026").wait_for(timeout=25000)
                if "Santa Photography 2026" not in (await modal.inner_text(timeout=5000)):
                    raise RuntimeError("Unexpected event after reopening modal")
                if month==12:
                    h=modal.locator("h4",has_text="November 2026")
                    await h.locator("xpath=../..").locator("xpath=./div[last()]").click(timeout=7000)
                    await modal.locator("h4",has_text="December 2026").wait_for(timeout=12000)
                await page.wait_for_timeout(1000)
                cells=modal.locator("div.f1wa5vh2").filter(has_text=re.compile(r"^%d$"%day))
                if await cells.count()!=1: raise RuntimeError("Ambiguous candidate date control")
                status=await cells.first.evaluate("""el=>{
                    const s=getComputedStyle(el);
                    return {pointer:s.pointerEvents, cursor:s.cursor, strike:s.backgroundImage.includes('linear-gradient')};
                }""")
                if status["pointer"]!="auto" or status["cursor"]!="pointer" or status["strike"]:
                    raise RuntimeError("Candidate date changed during scan; rescan next time")
                await cells.click(timeout=6000)
                await page.wait_for_timeout(1500)
                time_controls=await page.evaluate(r'''() => {
                    const root=document.querySelector('#booking-modal_wrapper');
                    if(!root)return [];
                    const match=/^(?:[01]?\d|2[0-3]):[0-5]\d\s*(?:a\.?m\.?|p\.?m\.?)?$/i;
                    return [...root.querySelectorAll('*')].filter(el => el.children.length===0 && match.test((el.innerText||el.textContent||'').trim()))
                      .slice(0,100).map(el => {
                        const element=el.closest('button,[role="button"]')||el.parentElement;
                        const style=element?getComputedStyle(element):null;
                        const rect=element?.getBoundingClientRect();
                        return {text:(el.innerText||el.textContent||'').trim(),
                          visible:!!rect&&rect.width>0&&rect.height>0,
                          clickable:!!style&&style.pointerEvents==='auto' &&
                            (style.cursor==='pointer' || element?.tagName==='BUTTON' || element?.getAttribute('role')==='button') &&
                            !element?.disabled && element?.getAttribute('aria-disabled')!=='true'};
                      });
                }''')
                date_string=f"2026-{month:02d}-{day:02d}"
                valid=[x["text"] for x in time_controls if x["visible"] and x["clickable"]]
                report["time_probes"].append({"date":date_string,"time_strings":valid[:60]})
                if not valid:
                    raise RuntimeError("Date became selectable but no confirmed clickable time: "+date_string)
                for value in valid:
                    raw=value.upper().replace(".","").replace(" ","")
                    m=re.fullmatch(r"(\d{1,2}):(\d{2})(AM|PM)?",raw)
                    if not m: continue
                    hours, minutes=int(m.group(1)), int(m.group(2))
                    if m.group(3):
                        if not 1 <= hours <= 12: continue
                        hours=hours % 12 + (12 if m.group(3)=="PM" else 0)
                    elif hours>23:continue
                    confirmed.append(f"{date_string}T{hours:02d}:{minutes:02d}")
        return filter_slots(confirmed,cfg)
    finally:
        (DIAG/"active-scan.json").write_text(json.dumps(report,indent=2,ensure_ascii=False))

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
                await probe_both_months(page, cfg)
                print("Probe complete; NO booking notifications were sent.")
                return []
            if not cfg.get("enabled"):
                raise RuntimeError("Monitor must be explicitly enabled")
            return await scan_confirmed_slots(page, cfg)
        except Exception as exc:
            await diagnostic(context, "PROBE/SCAN ERROR: " + str(exc)[:200])
            raise
        finally:
            await browser.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("probe", "monitor", "dry-run", "test-push"), default="probe")
    mode = parser.parse_args().mode
    cfg = json.loads((ROOT / "config.json").read_text())
    if mode == "dry-run":
        cfg["enabled"] = True  # Read-only end-to-end test; no notification or state changes
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
    elif mode == "dry-run":
        print("DRY RUN COMPLETE: %d exact candidate time slots; no notification sent" % len(slots))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("MONITOR ERROR (no false availability alert): " + str(exc), file=sys.stderr)
        sys.exit(1)
