"""
Phase 1.1: DrissionPage probe of NowGoal league archive page.
Captures XHR endpoints used to load historical season fixtures.
Output: logs/nowgoal_xhr_probe.json

Strategy: launch Chrome manually, wait for it to be ready, then connect DrissionPage.
"""

import json
import os
import subprocess
import sys
import time
from requests import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from DrissionPage import ChromiumPage, ChromiumOptions

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BACKEND_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

DEBUG_PORT = 9335
CHROME_DATA_DIR = "/tmp/chrome_drission_nowgoal"
CHROME_BIN = "/snap/bin/chromium"

# EPL subleague ID on NowGoal
TARGET_URL = "https://football.nowgoal26.com/subleague/36"

KEYWORDS = ["season", "year", "subleague", "league", "match", "fixture", "history", "archive",
            "ajax", "api", "json", "data"]


def start_chrome() -> subprocess.Popen:
    """Launch Chrome headless with remote debug port."""
    args = [
        CHROME_BIN,
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={CHROME_DATA_DIR}",
        "--headless=new",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--window-size=1920,1080",
        "--disable-blink-features=AutomationControlled",
        "--disable-extensions",
    ]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"Chrome launched (pid={proc.pid}, port={DEBUG_PORT})")
    return proc


def wait_for_chrome(timeout=20) -> str:
    """Poll /json/version until Chrome is ready; return ws debugger URL."""
    s = Session()
    s.trust_env = False
    s.keep_alive = False
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = s.get(f"http://localhost:{DEBUG_PORT}/json/version", timeout=2)
            ws_url = resp.json()["webSocketDebuggerUrl"]
            s.close()
            print(f"Chrome ready: {ws_url}")
            return ws_url
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"Chrome did not become ready within {timeout}s")


def connect_drission(ws_url: str) -> ChromiumPage:
    """Connect DrissionPage to the already-running Chrome via ws_address."""
    opt = ChromiumOptions()
    opt.set_address(f"127.0.0.1:{DEBUG_PORT}")
    opt.headless(True)  # must match running Chrome's headless state to avoid restart
    return ChromiumPage(opt)


def is_interesting(url: str) -> bool:
    url_lower = url.lower()
    if "nowgoal" not in url_lower:
        return False
    return any(k in url_lower for k in KEYWORDS)


def probe(page: ChromiumPage) -> dict:
    """Navigate page, capture network packets, look for season-related XHR."""
    result = {"interesting": [], "all_nowgoal": [], "html_snippet": "", "page_title": "", "final_url": ""}

    # Start packet listener before navigation
    try:
        page.listen.start("nowgoal26.com")
        print("Packet listener started")
    except Exception as e:
        print(f"Listener start error: {e}")

    print(f"Navigating to: {TARGET_URL}")
    page.get(TARGET_URL)
    print("Waiting 15s for page to hydrate...")
    time.sleep(15)

    # Scroll to trigger lazy loads
    try:
        page.scroll.to_bottom()
        time.sleep(3)
        page.scroll.to_top()
        time.sleep(2)
    except Exception as e:
        print(f"Scroll error: {e}")

    # Try to find and click season/year selector or navigation
    tried_interactions = 0
    selectors = [
        ("text", "2021/2022"),
        ("text", "2021-2022"),
        ("text", "21/22"),
        ("text", "2022"),
        ("css", "select"),
        ("css", "[class*='season']"),
        ("css", "[class*='year']"),
        ("css", ".tab-item"),
        ("css", "li[class*='season']"),
    ]
    for sel_type, sel_val in selectors:
        try:
            if sel_type == "text":
                el = page.ele(f"text:{sel_val}", timeout=2)
            else:
                el = page.ele(f"css:{sel_val}", timeout=2)
            if el:
                text_preview = (el.text or "")[:60]
                print(f"Found element [{sel_type}:{sel_val}]: '{text_preview}'")
                el.click()
                time.sleep(5)
                tried_interactions += 1
                if tried_interactions >= 2:
                    break
        except Exception:
            continue

    # Collect all captured packets
    time.sleep(3)
    packets = []
    try:
        for pkt in page.listen.steps(count=500, timeout=5):
            if pkt and hasattr(pkt, 'url'):
                packets.append(pkt)
    except Exception as e:
        print(f"Packet collect error: {e}")

    try:
        page.listen.stop()
    except Exception:
        pass

    print(f"Total packets captured: {len(packets)}")

    for pkt in packets:
        url = getattr(pkt, 'url', '')
        if not url:
            continue
        entry = {
            "url": url,
            "method": getattr(pkt, 'method', 'GET'),
            "status": getattr(pkt, 'status', None),
        }
        if is_interesting(url):
            # Try to get response body
            try:
                body = pkt.response.body
                if isinstance(body, (dict, list)):
                    entry["response_sample"] = json.dumps(body)[:1000]
                else:
                    entry["response_sample"] = str(body)[:1000]
            except Exception:
                pass
            result["interesting"].append(entry)
            print(f"  INTERESTING: [{entry['method']}] {url}")

        if "nowgoal" in url.lower():
            result["all_nowgoal"].append(entry)

    # Page state
    try:
        result["page_title"] = page.title
        result["final_url"] = page.url
        result["html_snippet"] = page.html[:8000]
    except Exception as e:
        print(f"Page state error: {e}")

    return result


def main():
    print("=== NowGoal Archive XHR Probe ===")

    chrome_proc = start_chrome()
    try:
        ws_url = wait_for_chrome()
        page = connect_drission(ws_url)
        print("DrissionPage connected to Chrome")

        data = probe(page)

        try:
            page.quit()
        except Exception:
            pass

        # Summary
        print(f"\n=== Results ===")
        print(f"Page title:   {data['page_title']}")
        print(f"Final URL:    {data['final_url']}")
        print(f"NowGoal reqs: {len(data['all_nowgoal'])}")
        print(f"Interesting:  {len(data['interesting'])}")

        if data["interesting"]:
            print("\nInteresting endpoints:")
            for e in data["interesting"]:
                print(f"  [{e.get('method','?')}] {e.get('url','')}")
                if "response_sample" in e:
                    print(f"    Response: {e['response_sample'][:200]}")
        else:
            print("\nNo keyword-matching requests found.")
            print("All NowGoal requests captured:")
            for e in data["all_nowgoal"]:
                print(f"  [{e.get('method','?')}] {e.get('url','')}")

        out_path = os.path.join(LOG_DIR, "nowgoal_xhr_probe.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\nFull output: {out_path}")

    except Exception as e:
        import traceback
        print(f"\nFATAL: {e}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        try:
            chrome_proc.terminate()
            chrome_proc.wait(timeout=5)
        except Exception:
            pass
        # Clean up any stray Chrome processes
        import subprocess as sp
        sp.run(["pkill", "-f", f"chromium.*{DEBUG_PORT}"], capture_output=True)


if __name__ == "__main__":
    main()
