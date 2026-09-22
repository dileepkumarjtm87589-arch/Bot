#!/usr/bin/env python3
"""
Smart Account Creator Bot
- Reads seed numbers from numbers.txt
- Auto-generates sequential numbers when one works
- Never repeats phone numbers or usernames
- Runs completely autonomous - no manual intervention
"""

import os
import sys
import time
import random
import string
import logging
import json
import traceback
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementNotInteractableException,
    WebDriverException,
    StaleElementReferenceException
)

# ╔══════════════════════════════════════════════════╗
# ║              CONFIGURATION                       ║
# ╚══════════════════════════════════════════════════╝
TARGET_URL      = "https://wa.inwasun.com/login?invite=FAXBSAVDPR"
FIXED_PASSWORD  = "Fisu@2025"
NUMBERS_FILE    = "numbers.txt"
RESULTS_LOG     = "results.log"
STATE_FILE      = "bot_state.json"   # Tracks current number + used usernames
USED_PHONES_FILE = "used_phones.txt" # All used phone numbers
USED_USERS_FILE  = "used_users.txt"  # All used usernames

PAGE_LOAD_WAIT  = 30
ELEMENT_WAIT    = 20
MIN_DELAY       = 3
MAX_DELAY       = 8
MAX_RETRIES     = 3
# How many sequential numbers to try from one seed before moving to next seed
MAX_SEQUENTIAL  = 9999

# ╔══════════════════════════════════════════════════╗
# ║              USER AGENTS                         ║
# ╚══════════════════════════════════════════════════╝
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 OPR/108.0.0.0",
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
]

# ╔══════════════════════════════════════════════════╗
# ║              LOGGING SETUP                       ║
# ╚══════════════════════════════════════════════════╝
def setup_logging():
    fmt = "%(asctime)s | %(levelname)-8s | %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(RESULTS_LOG, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# ╔══════════════════════════════════════════════════╗
# ║         STATE MANAGER CLASS                      ║
# ╚══════════════════════════════════════════════════╝
class StateManager:
    """
    Manages all state:
    - Which phone numbers have been used
    - Which usernames have been used
    - Current seed number being processed
    - Current sequential offset
    """

    def __init__(self):
        self.used_phones    = set()
        self.used_usernames = set()
        self.state          = {}
        self._load_all()

    # ── Load everything from disk ──────────────────
    def _load_all(self):
        # Load used phones
        if os.path.exists(USED_PHONES_FILE):
            with open(USED_PHONES_FILE, "r", encoding="utf-8") as f:
                self.used_phones = set(
                    line.strip() for line in f if line.strip()
                )
            logger.info(f"📱 Loaded {len(self.used_phones)} used phone numbers")

        # Load used usernames
        if os.path.exists(USED_USERS_FILE):
            with open(USED_USERS_FILE, "r", encoding="utf-8") as f:
                self.used_usernames = set(
                    line.strip() for line in f if line.strip()
                )
            logger.info(f"👤 Loaded {len(self.used_usernames)} used usernames")

        # Load bot state
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                self.state = json.load(f)
            logger.info(f"💾 State loaded: {self.state}")
        else:
            self.state = {
                "seed_index":       0,    # which seed number in numbers.txt
                "sequential_offset": 0,   # how far we've gone from seed
                "total_created":    0,    # total accounts created
                "total_attempts":   0,    # total attempts made
            }

    # ── Save state to disk ──────────────────────────
    def save_state(self):
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2)

    def save_phone(self, phone: str):
        self.used_phones.add(phone)
        with open(USED_PHONES_FILE, "a", encoding="utf-8") as f:
            f.write(phone + "\n")

    def save_username(self, username: str):
        self.used_usernames.add(username)
        with open(USED_USERS_FILE, "a", encoding="utf-8") as f:
            f.write(username + "\n")

    # ── Check if phone used ─────────────────────────
    def is_phone_used(self, phone: str) -> bool:
        return phone in self.used_phones

    def is_username_used(self, username: str) -> bool:
        return username in self.used_usernames

    # ── Mark phone as used ──────────────────────────
    def mark_phone_used(self, phone: str):
        self.save_phone(phone)

    def mark_username_used(self, username: str):
        self.save_username(username)

    # ── Increment counters ──────────────────────────
    def increment_created(self):
        self.state["total_created"] += 1
        self.save_state()

    def increment_attempts(self):
        self.state["total_attempts"] += 1
        self.save_state()

    def next_sequential(self):
        self.state["sequential_offset"] += 1
        self.save_state()

    def next_seed(self):
        self.state["seed_index"] += 1
        self.state["sequential_offset"] = 0
        self.save_state()

    def reset_sequential(self):
        self.state["sequential_offset"] = 0
        self.save_state()

    # ── Stats ───────────────────────────────────────
    def stats(self) -> dict:
        return {
            "created":  self.state["total_created"],
            "attempts": self.state["total_attempts"],
            "seed_idx": self.state["seed_index"],
            "offset":   self.state["sequential_offset"],
        }


# ╔══════════════════════════════════════════════════╗
# ║         PHONE NUMBER GENERATOR                   ║
# ╚══════════════════════════════════════════════════╝
class PhoneGenerator:
    """
    Smart phone number generator.
    
    Logic:
    1. Takes seed numbers from numbers.txt
    2. For each seed, generates sequential numbers
       Example: seed=8000000000 → 8000000000, 8000000001, 8000000002...
    3. When sequential exhausted, moves to next seed
    4. Never reuses a number
    5. Handles Indian number format (10 digits, starts with 6-9)
    """

    def __init__(self, state: StateManager):
        self.state        = state
        self.seeds        = self._load_seeds()
        self.current_seed = None
        self.current_base = None
        self._init_current_seed()

    def _load_seeds(self) -> list:
        """Load seed numbers from numbers.txt"""
        if not os.path.exists(NUMBERS_FILE):
            logger.error(f"❌ {NUMBERS_FILE} not found!")
            sys.exit(1)

        seeds = []
        with open(NUMBERS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Clean number - remove spaces, dashes, +91, etc.
                clean = self._clean_number(line)
                if clean:
                    seeds.append(clean)

        if not seeds:
            logger.error("❌ No valid numbers in numbers.txt!")
            sys.exit(1)

        logger.info(f"🌱 Loaded {len(seeds)} seed numbers")
        for s in seeds:
            logger.info(f"   Seed: {s}")
        return seeds

    def _clean_number(self, raw: str) -> str:
        """
        Clean and normalize phone number.
        Returns 10-digit Indian number.
        """
        # Remove all non-digits
        digits = "".join(c for c in raw if c.isdigit())

        # Handle country code
        if digits.startswith("91") and len(digits) == 12:
            digits = digits[2:]
        elif digits.startswith("0") and len(digits) == 11:
            digits = digits[1:]

        # Validate: 10 digits, starts with 6-9
        if len(digits) == 10 and digits[0] in "6789":
            return digits

        logger.warning(f"  ⚠️ Invalid number format: {raw} → skipping")
        return ""

    def _init_current_seed(self):
        """Set current seed based on saved state."""
        idx = self.state.state["seed_index"]
        if idx < len(self.seeds):
            self.current_seed = self.seeds[idx]
            self.current_base = int(self.current_seed)
            logger.info(f"🎯 Current seed: {self.current_seed} (index {idx})")
        else:
            logger.warning("⚠️ All seeds exhausted - will try random generation")
            self.current_seed = None
            self.current_base = None

    def _format_indian(self, number: str) -> str:
        """Format as Indian number with +91 prefix."""
        return f"+91{number}"

    def get_next_number(self) -> str:
        """
        Get the next unused phone number.
        
        Strategy:
        1. Start from current seed + offset
        2. If that's used, increment offset
        3. If offset > MAX_SEQUENTIAL, move to next seed
        4. If all seeds done, generate smart random numbers
        """
        max_attempts = 10000

        for _ in range(max_attempts):
            # Case 1: We have a valid seed
            if self.current_base is not None:
                offset = self.state.state["sequential_offset"]
                candidate_digits = str(self.current_base + offset)

                # Validate still 10 digits
                if len(candidate_digits) == 10 and candidate_digits[0] in "6789":
                    phone_full = self._format_indian(candidate_digits)

                    if not self.state.is_phone_used(phone_full):
                        return phone_full
                    else:
                        logger.debug(f"  Phone {phone_full} already used, next...")
                        self.state.next_sequential()
                        continue

                # Sequential went out of valid range
                # or offset too large - move to next seed
                if offset >= MAX_SEQUENTIAL:
                    logger.info(f"✅ Seed {self.current_seed} exhausted at offset {offset}")
                    self._move_to_next_seed()
                    continue
                else:
                    # Number became invalid (too many digits etc)
                    self._move_to_next_seed()
                    continue

            # Case 2: All seeds exhausted - smart random generation
            else:
                phone = self._generate_smart_random()
                if not self.state.is_phone_used(phone):
                    return phone

        logger.error("❌ Could not generate unique number after 10000 attempts!")
        return None

    def _move_to_next_seed(self):
        """Move to the next seed number."""
        self.state.next_seed()
        new_idx = self.state.state["seed_index"]

        if new_idx < len(self.seeds):
            self.current_seed = self.seeds[new_idx]
            self.current_base = int(self.current_seed)
            logger.info(f"🔄 Moved to seed [{new_idx}]: {self.current_seed}")
        else:
            logger.warning("⚠️ All seeds done! Switching to random generation mode")
            self.current_seed = None
            self.current_base = None

    def advance(self):
        """Called after a number is successfully used - advance to next."""
        self.state.next_sequential()

    def _generate_smart_random(self) -> str:
        """
        Generate smart random Indian mobile number.
        Valid prefixes: 6, 7, 8, 9 (Indian mobile)
        """
        prefixes = [
            "60", "61", "62", "63", "64", "65", "66", "67", "68", "69",
            "70", "71", "72", "73", "74", "75", "76", "77", "78", "79",
            "80", "81", "82", "83", "84", "85", "86", "87", "88", "89",
            "90", "91", "92", "93", "94", "95", "96", "97", "98", "99",
        ]
        prefix = random.choice(prefixes)
        rest   = "".join(random.choices(string.digits, k=8))
        number = prefix + rest
        return self._format_indian(number)

    def stats(self) -> dict:
        return {
            "current_seed":   self.current_seed,
            "current_offset": self.state.state["sequential_offset"],
            "seeds_total":    len(self.seeds),
            "seeds_used":     self.state.state["seed_index"],
        }


# ╔══════════════════════════════════════════════════╗
# ║         USERNAME GENERATOR                       ║
# ╚══════════════════════════════════════════════════╝
class UsernameGenerator:
    """
    Generates unique usernames.
    Never repeats - checks against used_users.txt
    Format: usr_abc1234de
    """

    def __init__(self, state: StateManager):
        self.state = state

    def generate(self) -> str:
        """Generate a guaranteed unique username."""
        max_tries = 10000
        for _ in range(max_tries):
            username = self._make_username()
            if not self.state.is_username_used(username):
                return username

        # Fallback with timestamp
        ts = str(int(time.time()))[-6:]
        return f"usr_{ts}"

    def _make_username(self) -> str:
        l = string.ascii_lowercase
        d = string.digits
        p1 = "".join(random.choices(l, k=3))
        p2 = "".join(random.choices(d, k=4))
        p3 = "".join(random.choices(l, k=2))
        return f"usr_{p1}{p2}{p3}"


# ╔══════════════════════════════════════════════════╗
# ║         BROWSER BUILDER                          ║
# ╚══════════════════════════════════════════════════╝
def build_driver(ua: str) -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-software-rasterizer")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument(f"--user-agent={ua}")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-infobars")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--ignore-certificate-errors")
    opts.add_argument("--allow-running-insecure-content")
    opts.add_argument("--lang=en-US,en;q=0.9")
    opts.add_argument("--disable-popup-blocking")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    chrome = os.environ.get("CHROME_BIN", "/usr/bin/google-chrome")
    if os.path.exists(chrome):
        opts.binary_location = chrome

    cdriver = os.environ.get("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")
    try:
        if os.path.exists(cdriver):
            svc = Service(executable_path=cdriver)
            driver = webdriver.Chrome(service=svc, options=opts)
        else:
            driver = webdriver.Chrome(options=opts)
    except WebDriverException as e:
        logger.error(f"Chrome init failed: {e}")
        raise

    # Hide automation
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = {runtime: {}};
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
        """
    })
    driver.set_page_load_timeout(PAGE_LOAD_WAIT)
    return driver


# ╔══════════════════════════════════════════════════╗
# ║         HELPER FUNCTIONS                         ║
# ╚══════════════════════════════════════════════════╝
def random_delay(mn=MIN_DELAY, mx=MAX_DELAY):
    d = round(random.uniform(mn, mx), 2)
    logger.info(f"  ⏳ {d}s delay...")
    time.sleep(d)

def safe_type(element, text: str):
    """Type text with human-like speed."""
    element.click()
    time.sleep(0.3)
    element.clear()
    time.sleep(0.2)
    element.send_keys(Keys.CONTROL + "a")
    time.sleep(0.1)
    element.send_keys(Keys.DELETE)
    time.sleep(0.2)
    for ch in text:
        element.send_keys(ch)
        time.sleep(random.uniform(0.04, 0.12))

def find_el(driver, selectors: list, timeout=ELEMENT_WAIT):
    """Find first matching element from selector list."""
    end = time.time() + timeout
    while time.time() < end:
        for by, val in selectors:
            try:
                el = driver.find_element(by, val)
                if el.is_displayed():
                    return el
            except Exception:
                continue
        time.sleep(0.5)
    raise TimeoutException(f"No element found from: {selectors[:2]}...")

def check_errors(driver) -> str:
    """Check page for error messages."""
    sels = [
        ".error", ".alert-danger", ".alert-error",
        ".error-message", ".form-error", ".toast-error",
        "[class*='error']", "[class*='Error']",
        ".invalid-feedback", ".help-block",
    ]
    for s in sels:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, s)
            for el in els:
                if el.is_displayed() and el.text.strip():
                    return el.text.strip()
        except Exception:
            pass
    return ""

def log_result(status: str, phone: str, username: str, note: str = ""):
    msg = f"{status} | phone={phone} | user={username} | {note}"
    if status == "SUCCESS":
        logger.info(f"✅ {msg}")
    elif status == "DUPLICATE":
        logger.warning(f"⏭️  {msg}")
    elif status == "SKIP":
        logger.info(f"⏩ {msg}")
    else:
        logger.error(f"❌ {msg}")


# ╔══════════════════════════════════════════════════╗
# ║         FIELD SELECTORS                          ║
# ╚══════════════════════════════════════════════════╝
PHONE_SEL = [
    (By.CSS_SELECTOR, "input[name='phone']"),
    (By.CSS_SELECTOR, "input[type='tel']"),
    (By.CSS_SELECTOR, "input[placeholder*='phone' i]"),
    (By.CSS_SELECTOR, "input[placeholder*='Phone' i]"),
    (By.CSS_SELECTOR, "input[placeholder*='number' i]"),
    (By.CSS_SELECTOR, "input[placeholder*='mobile' i]"),
    (By.CSS_SELECTOR, "input[placeholder*='Mobile' i]"),
    (By.CSS_SELECTOR, "input[id*='phone' i]"),
    (By.CSS_SELECTOR, "input[id*='mobile' i]"),
    (By.XPATH, "//input[contains(@placeholder,'phone') or contains(@placeholder,'Phone')]"),
    (By.XPATH, "//input[contains(@name,'phone') or contains(@name,'mobile')]"),
    (By.XPATH, "//label[contains(text(),'Phone')]/following-sibling::input"),
    (By.XPATH, "//label[contains(text(),'Mobile')]/following-sibling::input"),
]

USER_SEL = [
    (By.CSS_SELECTOR, "input[name='username']"),
    (By.CSS_SELECTOR, "input[name='user']"),
    (By.CSS_SELECTOR, "input[name='name']"),
    (By.CSS_SELECTOR, "input[name='nickname']"),
    (By.CSS_SELECTOR, "input[placeholder*='username' i]"),
    (By.CSS_SELECTOR, "input[placeholder*='Username' i]"),
    (By.CSS_SELECTOR, "input[placeholder*='user name' i]"),
    (By.CSS_SELECTOR, "input[id*='username' i]"),
    (By.XPATH, "//input[contains(@placeholder,'username') or contains(@placeholder,'Username')]"),
    (By.XPATH, "//label[contains(text(),'Username')]/following-sibling::input"),
    (By.XPATH, "//label[contains(text(),'username')]/following-sibling::input"),
]

PASS_SEL = [
    (By.CSS_SELECTOR, "input[name='password']"),
    (By.CSS_SELECTOR, "input[type='password']"),
    (By.CSS_SELECTOR, "input[placeholder*='password' i]"),
    (By.CSS_SELECTOR, "input[placeholder*='Password' i]"),
    (By.CSS_SELECTOR, "input[id*='password' i]"),
    (By.XPATH, "//input[@type='password']"),
]

SUBMIT_SEL = [
    (By.CSS_SELECTOR, "button[type='submit']"),
    (By.CSS_SELECTOR, "input[type='submit']"),
    (By.XPATH, "//button[contains(text(),'Register') or contains(text(),'register')]"),
    (By.XPATH, "//button[contains(text(),'Sign Up') or contains(text(),'Sign up')]"),
    (By.XPATH, "//button[contains(text(),'Create') or contains(text(),'create')]"),
    (By.XPATH, "//button[contains(text(),'Join') or contains(text(),'join')]"),
    (By.XPATH, "//button[contains(text(),'Submit') or contains(text(),'submit')]"),
    (By.XPATH, "//button[@type='submit']"),
    (By.XPATH, "//input[@type='submit']"),
]


# ╔══════════════════════════════════════════════════╗
# ║         REGISTRATION FLOW                        ║
# ╚══════════════════════════════════════════════════╝
def try_register_tab(driver) -> bool:
    sels = [
        (By.XPATH, "//a[contains(text(),'Register') or contains(text(),'register')]"),
        (By.XPATH, "//a[contains(text(),'Sign Up') or contains(text(),'Sign up')]"),
        (By.XPATH, "//span[contains(text(),'Register')]"),
        (By.CSS_SELECTOR, "a[href*='register']"),
        (By.CSS_SELECTOR, "[data-tab='register']"),
        (By.CSS_SELECTOR, ".tab-register"),
    ]
    for by, val in sels:
        try:
            el = driver.find_element(by, val)
            if el.is_displayed():
                el.click()
                time.sleep(1.5)
                logger.info("  ✓ Register tab clicked")
                return True
        except Exception:
            continue
    return False

def create_account(driver, phone: str, username: str) -> dict:
    """Full registration flow. Returns {success, note, is_duplicate}"""
    res = {"success": False, "note": "", "is_duplicate": False}

    logger.info(f"  📄 Page: {driver.title[:50]}")
    logger.info(f"  🔗 URL: {driver.current_url[:80]}")

    # Try to show register form
    try_register_tab(driver)
    random_delay(1, 2)

    # ── PHONE ────────────────────────────────────────
    logger.info(f"  📱 Phone: {phone}")
    try:
        el = find_el(driver, PHONE_SEL, 15)
        random_delay(0.5, 1.5)
        safe_type(el, phone)
        logger.info("  ✓ Phone entered")
    except TimeoutException:
        logger.warning("  ⚠️ Phone field not found - continuing")
        res["note"] = "Phone field missing"

    random_delay(MIN_DELAY, MAX_DELAY)

    # ── USERNAME ─────────────────────────────────────
    logger.info(f"  👤 Username: {username}")
    try:
        el = find_el(driver, USER_SEL, 15)
        random_delay(0.5, 1.5)
        safe_type(el, username)
        logger.info("  ✓ Username entered")
    except TimeoutException:
        logger.warning("  ⚠️ Username field not found - continuing")

    random_delay(MIN_DELAY, MAX_DELAY)

    # ── PASSWORD ─────────────────────────────────────
    logger.info("  🔑 Password: [FIXED]")
    try:
        el = find_el(driver, PASS_SEL, 15)
        random_delay(0.5, 1.5)
        safe_type(el, FIXED_PASSWORD)
        logger.info("  ✓ Password entered")
    except TimeoutException:
        res["note"] = "Password field missing"
        logger.error("  ❌ Password field NOT found")
        return res

    random_delay(MIN_DELAY, MAX_DELAY)

    # ── REFERRAL CHECK ───────────────────────────────
    for s in ["input[name='invite']", "input[name='referral']",
              "input[name='ref']", "input[name='code']",
              "input[name='invite_code']", "input[name='referralCode']"]:
        try:
            el = driver.find_element(By.CSS_SELECTOR, s)
            v  = el.get_attribute("value")
            logger.info(f"  🎫 Referral: '{v}' (auto-filled, not touching)")
            break
        except Exception:
            continue

    random_delay(1, 2)

    # ── SUBMIT ───────────────────────────────────────
    logger.info("  🖱️  Clicking submit...")
    clicked = False
    for by, val in SUBMIT_SEL:
        try:
            btn = driver.find_element(by, val)
            if btn.is_displayed() and btn.is_enabled():
                driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                time.sleep(0.4)
                logger.info(f"  Found btn: '{btn.text[:30]}'")
                try:
                    btn.click()
                except ElementNotInteractableException:
                    driver.execute_script("arguments[0].click();", btn)
                clicked = True
                logger.info("  ✓ Clicked!")
                break
        except Exception:
            continue

    if not clicked:
        # Fallback: Enter key
        try:
            el = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
            el.send_keys(Keys.RETURN)
            clicked = True
            logger.info("  ✓ Enter key (fallback)")
        except Exception:
            res["note"] = "Submit button not found"
            return res

    # ── WAIT FOR RESPONSE ────────────────────────────
    logger.info("  ⌛ Waiting for response...")
    time.sleep(5)
    new_url = driver.current_url
    logger.info(f"  URL now: {new_url[:80]}")

    # Check errors first
    err = check_errors(driver)
    if err:
        err_low = err.lower()
        logger.warning(f"  ⚠️ Page error: {err[:100]}")
        dup_words = ["already","exist","duplicate","taken",
                     "registered","in use","used"]
        if any(w in err_low for w in dup_words):
            res["is_duplicate"] = True
            res["note"] = f"DUPLICATE: {err[:80]}"
        else:
            res["note"] = f"ERROR: {err[:80]}"
        return res

    # Check success keywords
    src = driver.page_source.lower()
    ok_words = ["success","welcome","dashboard","home","created",
                "registered","congratulation","verify","profile"]
    for kw in ok_words:
        if kw in src:
            res["success"] = True
            res["note"]    = f"Keyword={kw}"
            logger.info(f"  ✅ Success keyword: '{kw}'")
            return res

    # URL redirect = success
    if (new_url != TARGET_URL
            and "login" not in new_url.lower()
            and new_url != "about:blank"):
        res["success"] = True
        res["note"]    = f"Redirected={new_url[:60]}"
        return res

    # No error + no clear success
    if "error" in driver.title.lower() or "fail" in driver.title.lower():
        res["note"] = f"Error title: {driver.title}"
    else:
        res["success"] = True
        res["note"]    = "Assumed success (no error detected)"

    return res


# ╔══════════════════════════════════════════════════╗
# ║         SESSION RUNNER                           ║
# ╚══════════════════════════════════════════════════╝
def run_one_session(phone: str, username: str, attempt: int = 1) -> dict:
    """
    Run complete browser session for ONE account.
    Fresh browser every time.
    """
    ua     = random.choice(USER_AGENTS)
    driver = None

    logger.info(f"  🌐 UA: {ua[:55]}...")

    try:
        logger.info("  🚀 Starting Chrome...")
        driver = build_driver(ua)
        logger.info("  ✓ Chrome ready")

        logger.info(f"  🌍 Opening invite URL...")
        driver.get(TARGET_URL)
        random_delay(3, 6)
        logger.info(f"  ✓ Loaded: {driver.title[:50]}")

        result = create_account(driver, phone, username)
        return result

    except TimeoutException as e:
        return {"success": False, "note": f"Timeout: {str(e)[:50]}", "is_duplicate": False}
    except WebDriverException as e:
        return {"success": False, "note": f"WebDriver: {str(e)[:50]}", "is_duplicate": False}
    except Exception as e:
        logger.error(traceback.format_exc())
        return {"success": False, "note": f"Exception: {str(e)[:50]}", "is_duplicate": False}
    finally:
        if driver:
            try:
                driver.quit()
                logger.info("  🔴 Browser closed")
            except Exception:
                pass
        time.sleep(random.uniform(2, 4))


# ╔══════════════════════════════════════════════════╗
# ║         MAIN LOOP                                ║
# ╚══════════════════════════════════════════════════╝
def main():
    logger.info("╔═══════════════════════════════════════════════════╗")
    logger.info("║     SMART ACCOUNT CREATOR BOT - STARTING          ║")
    logger.info(f"║     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}                         ║")
    logger.info("╚═══════════════════════════════════════════════════╝")

    # ── Init state, generators ───────────────────────
    state    = StateManager()
    phone_gen = PhoneGenerator(state)
    user_gen  = UsernameGenerator(state)

    # Print starting stats
    s = state.stats()
    p = phone_gen.stats()
    logger.info(f"📊 Resume Stats:")
    logger.info(f"   Total created  : {s['created']}")
    logger.info(f"   Total attempts : {s['attempts']}")
    logger.info(f"   Current seed   : {p['current_seed']} (#{p['seeds_used']+1}/{p['seeds_total']})")
    logger.info(f"   Sequential at  : +{p['current_offset']}")
    logger.info(f"   Used phones    : {len(state.used_phones)}")
    logger.info(f"   Used usernames : {len(state.used_usernames)}")

    logger.info("\n🔁 Starting infinite loop - Ctrl+C to stop\n")

    account_num = s['created'] + 1

    # ── MAIN INFINITE LOOP ────────────────────────────
    while True:
        try:
            # ─ Get next phone number ─────────────────
            phone = phone_gen.get_next_number()
            if not phone:
                logger.error("❌ Cannot generate phone number! Check numbers.txt")
                time.sleep(60)
                continue

            # ─ Get unique username ───────────────────
            username = user_gen.generate()

            logger.info(f"\n{'═'*55}")
            logger.info(f"  🎯 Account #{account_num}")
            logger.info(f"  📞 Phone    : {phone}")
            logger.info(f"  👤 Username : {username}")
            logger.info(f"{'═'*55}")

            state.increment_attempts()

            # ─ Try to create account ─────────────────
            success    = False
            is_dup     = False
            final_note = ""

            for attempt in range(1, MAX_RETRIES + 1):
                logger.info(f"\n  [Attempt {attempt}/{MAX_RETRIES}]")

                result = run_one_session(phone, username, attempt)

                final_note = result.get("note", "")
                is_dup     = result.get("is_duplicate", False)

                if result["success"]:
                    success = True
                    break

                if is_dup:
                    logger.info("  ⏭️  Duplicate number - moving to next")
                    break

                if attempt < MAX_RETRIES:
                    wait = random.uniform(8, 20)
                    logger.info(f"  ⏳ Retry in {wait:.0f}s...")
                    time.sleep(wait)

            # ─ Process result ─────────────────────────
            if success:
                # Mark both as used
                state.mark_phone_used(phone)
                state.mark_username_used(username)
                state.increment_created()
                phone_gen.advance()

                log_result("SUCCESS", phone, username, final_note)
                account_num += 1

                # Short delay before next
                wait = random.uniform(5, 12)
                logger.info(f"\n  ✅ Done! Next in {wait:.0f}s...\n")
                time.sleep(wait)

            elif is_dup:
                # Phone is duplicate - mark used, move on
                state.mark_phone_used(phone)
                phone_gen.advance()

                log_result("DUPLICATE", phone, username, final_note)

                # No delay needed for duplicates
                time.sleep(2)

            else:
                # Failed - still mark phone to avoid retrying same failed number
                state.mark_phone_used(phone)
                phone_gen.advance()

                log_result("FAILURE", phone, username, final_note)

                # Wait before next on failure
                wait = random.uniform(10, 25)
                logger.info(f"  ⏳ Failed. Next in {wait:.0f}s...")
                time.sleep(wait)

            # ─ Print running total every 10 accounts ──
            if state.state["total_created"] % 10 == 0 and state.state["total_created"] > 0:
                ps = phone_gen.stats()
                logger.info(f"\n{'─'*55}")
                logger.info(f"  📈 RUNNING TOTAL: {state.state['total_created']} accounts created")
                logger.info(f"  📱 Current seed: {ps['current_seed']} +{ps['current_offset']}")
                logger.info(f"{'─'*55}\n")

        except KeyboardInterrupt:
            logger.info("\n\n⛔ Stopped by user (Ctrl+C)")
            break
        except Exception as e:
            logger.error(f"❌ Main loop error: {e}")
            logger.error(traceback.format_exc())
            time.sleep(30)
            continue

    # ── Final summary ─────────────────────────────────
    s = state.stats()
    logger.info("\n╔═══════════════════════════════════════════════════╗")
    logger.info("║                 FINAL SUMMARY                     ║")
    logger.info(f"║  ✅ Accounts Created : {s['created']:<28} ║")
    logger.info(f"║  📊 Total Attempts   : {s['attempts']:<28} ║")
    logger.info(f"║  📱 Phones Used      : {len(state.used_phones):<28} ║")
    logger.info(f"║  👤 Usernames Used   : {len(state.used_usernames):<28} ║")
    logger.info(f"║  🕐 Stopped at       : {datetime.now().strftime('%H:%M:%S'):<28} ║")
    logger.info("╚═══════════════════════════════════════════════════╝")


if __name__ == "__main__":
    main()
