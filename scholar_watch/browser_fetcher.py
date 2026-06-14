"""Fetch Google Scholar "Cited by" results through a real Chrome (Selenium).

Google blocks scripted HTTP access to the ``/scholar?cites=`` endpoint — plain
requests, cookie-warmed sessions, ``scholarly``, and even Chrome-TLS impersonation
all get a "not a robot" interstitial. A real, logged-in Chrome session is trusted,
so we drive the user's *installed* Chrome with a dedicated profile they sign into
once. Selenium Manager resolves chromedriver automatically; the system Chrome is
used as-is (nothing extra to bundle).

Most parsing logic here is split into pure functions so it can be unit-tested
against saved HTML without launching a browser.
"""

import logging
import os
import re
import time

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

SCHOLAR_HOST = "https://scholar.google.com"


def default_profile_dir() -> str:
    """The dedicated Chrome profile dir (lives beside the DB, under the app data root)."""
    from .config import PROJECT_ROOT
    return str(PROJECT_ROOT / "chrome_profile")


def resolve_profile_dir(override: str = "") -> str:
    return override or default_profile_dir()


def profile_is_setup(profile_dir: str) -> bool:
    """True if the profile dir exists and looks initialized (one-time login done)."""
    return os.path.isdir(profile_dir) and bool(os.listdir(profile_dir))

# Markers that mean Google served a robot-check / interstitial instead of results.
_CAPTCHA_MARKERS = (
    "id=\"gs_captcha_ccl\"",
    "id=\"gs_captcha_f\"",
    "class=\"g-recaptcha\"",
    "not a robot",
    "unusual traffic",
    "/sorry/",
    "enablejs",
)


class CitingCaptcha(Exception):
    """Raised when the cited-by page is a CAPTCHA / robot-check instead of results."""


def looks_like_captcha(html: str) -> bool:
    """True if the page looks like a robot-check rather than search results."""
    low = (html or "").lower()
    # If there are actual result blocks, it's not a captcha page.
    if "gs_ri" in low or 'class="gs_r' in low:
        return False
    return any(m in low for m in _CAPTCHA_MARKERS)


def parse_gs_a(text: str) -> tuple[str | None, str | None, int | None]:
    """Parse a Scholar ``gs_a`` byline into (authors, venue, year).

    Format is roughly: ``A Author, B Author - Journal Name, 2025 - publisher.com``.
    Every field is optional/fuzzy, so be defensive.
    """
    text = (text or "").strip()
    if not text:
        return None, None, None
    parts = [p.strip() for p in text.split(" - ")]
    authors = parts[0] or None
    middle = parts[1] if len(parts) >= 2 else ""

    year = None
    m = re.search(r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b", middle) or re.search(
        r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b", text
    )
    if m:
        year = int(m.group(1))

    venue = middle
    if year:
        venue = re.sub(r",?\s*" + str(year) + r"\b", "", venue).strip(" ,")
    venue = venue or None
    return authors, venue, year


def parse_citing_html(html: str, limit: int | None = None) -> list[dict]:
    """Parse cited-by result blocks into normalized dicts.

    Returns up to ``limit`` items, each ``{title, authors, year, venue, url}`` —
    the same shape the rest of the pipeline already stores.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    results: list[dict] = []
    for block in soup.select("div.gs_ri"):
        rt = block.select_one("h3.gs_rt")
        if not rt:
            continue
        title = rt.get_text(" ", strip=True)
        # Strip Scholar's bracket tags like "[HTML]", "[PDF]", "[CITATION]".
        title = re.sub(r"^\s*\[[^\]]+\]\s*", "", title).strip()
        if not title:
            continue
        link = rt.find("a")
        url = link.get("href") if link else None
        authors, venue, year = parse_gs_a(
            block.select_one("div.gs_a").get_text(" ", strip=True)
            if block.select_one("div.gs_a") else ""
        )
        results.append({
            "title": title,
            "authors": authors,
            "year": year,
            "venue": venue,
            "url": url,
        })
        if limit and len(results) >= limit:
            break
    return results


class BrowserCitingFetcher:
    """Reusable Selenium Chrome driver for fetching cited-by pages."""

    def __init__(self, profile_dir: str, headless: bool = True, page_timeout: int = 25):
        self.profile_dir = profile_dir
        self.headless = headless
        self.page_timeout = page_timeout
        self.driver = None

    def _build_driver(self):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        opts = Options()
        opts.add_argument(f"--user-data-dir={self.profile_dir}")
        opts.add_argument("--profile-directory=Default")
        if self.headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--window-size=1280,900")
        opts.add_argument("--no-first-run")
        opts.add_argument("--no-default-browser-check")
        # Reduce "I'm automated" tells.
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)

        driver = webdriver.Chrome(options=opts)
        driver.set_page_load_timeout(self.page_timeout + 20)
        return driver

    def start(self) -> None:
        if self.driver is None:
            logger.info("Launching Chrome (headless=%s) for cited-by fetches", self.headless)
            self.driver = self._build_driver()
            if not self.headless:
                # A real window passes Google's checks where headless gets CAPTCHA'd;
                # minimize it so it stays out of the user's way during a scrape.
                try:
                    self.driver.minimize_window()
                except Exception:
                    pass

    def surface_window(self) -> None:
        """Restore and bring the window to the foreground.

        The window is normally minimized to stay out of the way, but a CAPTCHA is
        useless if the user can't see it — so un-minimize and surface it when a
        robot-check needs a human.

        ``maximize_window()`` alone does NOT reliably restore a *minimized* Chrome
        window on Windows, so drive it through the DevTools Protocol: set the window
        state back to "normal" (un-minimize) and then "maximized". Chrome rejects a
        state change and a bounds change in the same call, so it's done in two steps.
        """
        if self.driver is None:
            return
        restored = False
        try:
            window_id = self.driver.execute_cdp_cmd("Browser.getWindowForTarget", {})["windowId"]
            self.driver.execute_cdp_cmd(
                "Browser.setWindowBounds",
                {"windowId": window_id, "bounds": {"windowState": "normal"}},
            )
            self.driver.execute_cdp_cmd(
                "Browser.setWindowBounds",
                {"windowId": window_id, "bounds": {"windowState": "maximized"}},
            )
            restored = True
        except Exception as e:
            logger.warning("CDP window restore failed (%s); falling back to maximize_window", e)
        if not restored:
            try:
                self.driver.maximize_window()
            except Exception as e:
                logger.warning("maximize_window fallback also failed: %s", e)
        # Bring the tab to the front within the window and nudge OS focus.
        try:
            self.driver.execute_cdp_cmd("Page.bringToFront", {})
        except Exception:
            pass
        try:
            self.driver.switch_to.window(self.driver.current_window_handle)
        except Exception:
            pass

    def stop(self) -> None:
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    def restart(self, headless: bool) -> None:
        """Relaunch the driver, e.g. to switch from headless to visible on a CAPTCHA."""
        self.stop()
        self.headless = headless
        self.start()

    def fetch(self, citedby_path: str, limit: int, solve_timeout: int = 0) -> list[dict]:
        """Load a cited-by page and return up to ``limit`` citing papers.

        ``citedby_path`` is a site-relative path (already including ``scisbd=1``).
        Raises :class:`CitingCaptcha` if Google served a robot-check. When
        ``solve_timeout`` > 0 (visible fallback), wait that many seconds for the
        user to solve a CAPTCHA before giving up.
        """
        self.start()
        url = SCHOLAR_HOST + citedby_path
        self.driver.get(url)

        deadline = time.time() + max(self.page_timeout, solve_timeout)
        while True:
            if self.driver.find_elements("css selector", "div.gs_ri"):
                break
            if looks_like_captcha(self.driver.page_source):
                if solve_timeout and time.time() < deadline:
                    time.sleep(2)
                    continue
                raise CitingCaptcha(url)
            if time.time() > deadline:
                break
            time.sleep(0.5)

        html = self.driver.page_source
        if looks_like_captcha(html):
            raise CitingCaptcha(url)
        return parse_citing_html(html, limit)
