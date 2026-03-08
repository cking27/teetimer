#!/usr/bin/env python3
"""
TeeTimer - Automated tee time booking for The Hills Country Club (Invited Clubs)
"""

import json
import time
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementClickInterceptedException,
    StaleElementReferenceException
)
from webdriver_manager.chrome import ChromeDriverManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TeeTimer:
    def __init__(self, config_path: str = "config.json"):
        self.config = self._load_config(config_path)
        self.driver = None
        self.wait = None

    def _load_config(self, config_path: str) -> dict:
        """Load configuration from JSON file."""
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(path) as f:
            config = json.load(f)

        logger.info(f"Loaded config for date: {config['booking']['target_date']}")
        return config

    def _init_driver(self):
        """Initialize Chrome WebDriver."""
        options = Options()
        # Run in non-headless mode so you can see what's happening
        # Uncomment the next line to run headless:
        # options.add_argument("--headless=new")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=options)
        self.wait = WebDriverWait(self.driver, 20)
        logger.info("WebDriver initialized")

    def _calculate_booking_open_time(self) -> datetime:
        """
        Calculate when booking opens for the target date.
        Tee times open at first_tee_time, booking_opens_days_ahead days before the target date.
        """
        target_date = datetime.strptime(self.config['booking']['target_date'], '%Y-%m-%d')
        days_ahead = self.config['timing']['booking_opens_days_ahead']
        first_tee = self.config['timing']['first_tee_time']

        # Booking opens X days before, at first tee time
        open_date = target_date - timedelta(days=days_ahead)
        hour, minute = map(int, first_tee.split(':'))
        booking_opens = open_date.replace(hour=hour, minute=minute, second=0, microsecond=0)

        return booking_opens

    def _wait_until_start_time(self):
        """Wait until it's time to start trying to book."""
        booking_opens = self._calculate_booking_open_time()
        start_before = self.config['timing']['start_trying_minutes_before']
        start_time = booking_opens - timedelta(minutes=start_before)

        now = datetime.now()

        logger.info(f"Target date: {self.config['booking']['target_date']}")
        logger.info(f"Booking opens at: {booking_opens}")
        logger.info(f"Will start trying at: {start_time}")

        if now < start_time:
            wait_seconds = (start_time - now).total_seconds()
            logger.info(f"Waiting {wait_seconds:.0f} seconds until start time...")

            # Show countdown
            while datetime.now() < start_time:
                remaining = (start_time - datetime.now()).total_seconds()
                if remaining > 60:
                    logger.info(f"Starting in {remaining/60:.1f} minutes...")
                    time.sleep(min(60, remaining - 30))
                elif remaining > 10:
                    logger.info(f"Starting in {remaining:.0f} seconds...")
                    time.sleep(10)
                else:
                    time.sleep(1)

            logger.info("Start time reached!")
        else:
            logger.info("Start time already passed, beginning immediately")

    def login(self) -> bool:
        """Log in to the Invited Clubs member portal."""
        logger.info("Navigating to login page...")
        self.driver.get(self.config['urls']['login'])

        try:
            # Wait for login form to load
            time.sleep(3)

            # The page has two sections: "New User" and "Returning Users"
            # We need to find the password field first (unique to returning users section)
            # then find the username field near it

            # Find password field - this is unique to the returning users section
            password_field = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password']"))
            )
            logger.info("Found password field")

            # Find the username field - it's the text input right before the password field
            # Look for text input in the same form/section as the password field
            try:
                # Try to find parent form or container
                parent_form = password_field.find_element(By.XPATH, "./ancestor::form")
                username_field = parent_form.find_element(By.CSS_SELECTOR, "input[type='text']")
            except NoSuchElementException:
                # Try finding text input near password field
                try:
                    username_field = password_field.find_element(
                        By.XPATH,
                        "./preceding::input[@type='text'][1]"
                    )
                except NoSuchElementException:
                    # Try label-based approach
                    try:
                        username_field = self.driver.find_element(
                            By.XPATH,
                            "//label[contains(text(), 'Username')]/following::input[1]"
                        )
                    except NoSuchElementException:
                        # Last resort - find all text inputs, the one near password is likely correct
                        text_inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='text']")
                        # Get the one that's in the same section (near password)
                        username_field = None
                        for inp in text_inputs:
                            # Check if this input is near the password field
                            try:
                                parent = inp.find_element(By.XPATH, "./ancestor::*[.//input[@type='password']]")
                                username_field = inp
                                break
                            except NoSuchElementException:
                                continue

                        if not username_field and text_inputs:
                            # Just use the last text input (likely to be in returning users section)
                            username_field = text_inputs[-1]

            if not username_field:
                logger.error("Could not find username field")
                return False

            logger.info("Found username field")

            # Clear and enter credentials
            username_field.clear()
            time.sleep(0.2)
            username_field.send_keys(self.config['credentials']['username'])
            logger.info(f"Entered username: {self.config['credentials']['username']}")

            password_field.clear()
            time.sleep(0.2)
            password_field.send_keys(self.config['credentials']['password'])
            logger.info("Entered password")

            # Find and click login button - look for the one in the returning users section
            try:
                # Find login button near password field
                login_button = password_field.find_element(
                    By.XPATH,
                    "./following::input[@type='submit'][1] | ./following::button[1]"
                )
            except NoSuchElementException:
                try:
                    login_button = self.driver.find_element(
                        By.XPATH,
                        "//input[@type='submit'][@value='Log In']"
                    )
                except NoSuchElementException:
                    login_button = self.driver.find_element(
                        By.XPATH,
                        "//input[@type='submit'] | //button[@type='submit']"
                    )

            logger.info("Clicking login button...")
            login_button.click()

            # Wait for redirect/login to complete
            time.sleep(4)

            # Check if login succeeded
            current_url = self.driver.current_url.lower()
            page_source = self.driver.page_source.upper()

            if "WELCOME" in page_source or "member" in current_url or "portal" in current_url:
                logger.info("Login successful!")
                return True
            elif "invalid" in page_source.lower() or "error" in page_source.lower() or "must enter" in page_source.lower():
                logger.error("Login failed - check credentials")
                return False
            else:
                logger.info("Login appears successful (redirected)")
                return True

        except TimeoutException:
            logger.error("Timeout waiting for login page elements")
            return False
        except Exception as e:
            logger.error(f"Error during login: {e}")
            return False

    def navigate_to_tee_times(self) -> bool:
        """Navigate to the tee times booking modal via Quick Links."""
        logger.info("Navigating to tee times...")

        try:
            # Wait for page to fully load
            time.sleep(2)

            # Look for tee times link in Quick Links or elsewhere
            tee_time_selectors = [
                "//a[contains(text(), 'Tee Time')]",
                "//a[contains(text(), 'TEE TIME')]",
                "//a[contains(text(), 'tee time')]",
                "//a[contains(text(), 'Book Tee Time')]",
                "//a[contains(@href, 'CCTTWEB')]",
                "//a[contains(@href, 'teetime')]",
                "//*[contains(text(), 'Quick Links')]/following::a[contains(text(), 'Tee')]",
            ]

            tee_time_link = None
            for selector in tee_time_selectors:
                try:
                    elements = self.driver.find_elements(By.XPATH, selector)
                    for elem in elements:
                        if elem.is_displayed():
                            tee_time_link = elem
                            break
                    if tee_time_link:
                        break
                except NoSuchElementException:
                    continue

            if tee_time_link:
                logger.info("Found tee time link, clicking...")
                tee_time_link.click()
            else:
                # Try navigating directly
                logger.info("Tee time link not found, trying direct navigation...")
                self.driver.get(self.config['urls']['tee_times_modal'])

            # Wait for modal/page to load
            time.sleep(3)

            # Check for "My Tee Times" header or similar
            try:
                self.wait.until(
                    EC.presence_of_element_located((
                        By.XPATH,
                        "//*[contains(text(), 'My Tee Times') or contains(text(), 'Available Tee Times') or contains(text(), 'Select Course')]"
                    ))
                )
                logger.info("Tee times interface loaded")
                # Dismiss any info modal that appears
                self.dismiss_info_modal()
                return True
            except TimeoutException:
                # Check if we're in an iframe
                iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
                for iframe in iframes:
                    try:
                        self.driver.switch_to.frame(iframe)
                        if "tee" in self.driver.page_source.lower():
                            logger.info("Switched to tee times iframe")
                            # Dismiss any info modal that appears
                            self.dismiss_info_modal()
                            return True
                        self.driver.switch_to.default_content()
                    except:
                        self.driver.switch_to.default_content()

                logger.warning("Tee times page loaded but expected elements not found")
                return True  # Continue anyway

        except Exception as e:
            logger.error(f"Error navigating to tee times: {e}")
            return False

    def dismiss_info_modal(self):
        """Dismiss any informational modal that appears."""
        logger.info("Checking for info modal to dismiss...")

        # Wait a moment for modal to appear
        time.sleep(2)

        try:
            # Look for Dismiss button - try multiple selectors
            dismiss_selectors = [
                # Based on screenshot - button with "Dismiss" text
                "//input[@value='Dismiss']",
                "//button[text()='Dismiss']",
                "//button[contains(text(), 'Dismiss')]",
                "//a[text()='Dismiss']",
                "//a[contains(text(), 'Dismiss')]",
                # The modal might have Messages header
                "//*[contains(text(), 'Messages')]/following::*[contains(text(), 'Dismiss')]",
                "//*[contains(text(), 'Messages')]/following::input[@value='Dismiss']",
                "//*[contains(text(), 'Messages')]/following::button[1]",
                # Generic modal close buttons
                "//*[contains(@class, 'modal')]//*[contains(text(), 'Dismiss')]",
                "//button[contains(text(), 'Close')]",
                "//button[contains(text(), 'OK')]",
            ]

            for selector in dismiss_selectors:
                try:
                    elements = self.driver.find_elements(By.XPATH, selector)
                    for elem in elements:
                        if elem.is_displayed():
                            logger.info(f"Found dismiss button, clicking...")
                            try:
                                elem.click()
                            except ElementClickInterceptedException:
                                # Try JavaScript click
                                self.driver.execute_script("arguments[0].click();", elem)
                            logger.info("Dismissed info modal")
                            time.sleep(1)
                            return True
                except Exception:
                    continue

            # Also try finding any visible button in a modal-like container
            try:
                # Look for elements that look like modal overlays
                modal_buttons = self.driver.find_elements(
                    By.XPATH,
                    "//*[contains(@style, 'z-index') or contains(@class, 'modal') or contains(@class, 'overlay')]//button | " +
                    "//*[contains(@style, 'z-index') or contains(@class, 'modal') or contains(@class, 'overlay')]//input[@type='button']"
                )
                for btn in modal_buttons:
                    if btn.is_displayed() and ('dismiss' in btn.text.lower() or 'close' in btn.text.lower() or 'ok' in btn.text.lower()):
                        btn.click()
                        logger.info("Dismissed modal via fallback method")
                        time.sleep(1)
                        return True
            except Exception:
                pass

            logger.info("No info modal found to dismiss")
            return False

        except Exception as e:
            logger.debug(f"No modal to dismiss: {e}")

    def ensure_in_tee_times_frame(self):
        """Make sure we're in the tee times iframe."""
        try:
            # Check if we can see tee times content
            if "My Tee Times" in self.driver.page_source or "March" in self.driver.page_source:
                return True

            # Try to find and switch to the iframe
            self.driver.switch_to.default_content()
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes:
                try:
                    self.driver.switch_to.frame(iframe)
                    if "tee" in self.driver.page_source.lower() or "March" in self.driver.page_source:
                        logger.info("Switched to tee times iframe")
                        return True
                    self.driver.switch_to.default_content()
                except:
                    self.driver.switch_to.default_content()

            # Try fancybox iframe specifically
            try:
                fancybox_iframe = self.driver.find_element(By.ID, "fancybox-frame")
                self.driver.switch_to.frame(fancybox_iframe)
                logger.info("Switched to fancybox iframe")
                return True
            except:
                pass

            return False
        except Exception as e:
            logger.error(f"Error ensuring frame: {e}")
            return False

    def debug_page_elements(self):
        """Print debug info about visible elements on the page."""
        logger.info("=== DEBUG: Page Elements ===")

        # Find the date header area and all elements in it
        try:
            # Find the first March element and get its parent container
            march_elem = self.driver.find_element(By.XPATH, "//*[contains(text(), 'March')]")
            # Get parent elements to find the date header row
            parent = march_elem.find_element(By.XPATH, "./..")
            grandparent = parent.find_element(By.XPATH, "./..")
            great_grandparent = grandparent.find_element(By.XPATH, "./..")

            logger.info(f"March element parent chain:")
            logger.info(f"  Parent: {parent.tag_name}, class='{parent.get_attribute('class')}'")
            logger.info(f"  Grandparent: {grandparent.tag_name}, class='{grandparent.get_attribute('class')}'")
            logger.info(f"  Great-grandparent: {great_grandparent.tag_name}, class='{great_grandparent.get_attribute('class')}'")

            # The arrow is likely a sibling of the date tabs container, not inside it
            # Let's find the container that holds both date tabs and the arrow
            # Go up more levels and look for siblings

            # Find cc-float-left's siblings
            float_left = great_grandparent
            parent_of_float = float_left.find_element(By.XPATH, "./..")
            siblings = parent_of_float.find_elements(By.XPATH, "./*")
            logger.info(f"Parent of cc-float-left has {len(siblings)} children:")

            for i, sib in enumerate(siblings):
                tag = sib.tag_name
                cls = sib.get_attribute('class') or ''
                html = (sib.get_attribute('outerHTML') or '')[:120]
                logger.info(f"  Sibling {i}: {tag} class='{cls}' : {html}")

            # Also look for span elements with ui-icon class (common jQuery UI pattern)
            ui_icons = self.driver.find_elements(By.XPATH, "//span[contains(@class, 'ui-icon')]")
            logger.info(f"Found {len(ui_icons)} ui-icon spans:")
            for icon in ui_icons:
                if icon.is_displayed():
                    logger.info(f"  ui-icon: {icon.get_attribute('outerHTML')[:100]}")

        except Exception as e:
            logger.info(f"Error exploring date header: {e}")

        logger.info("=== END DEBUG ===")

    def navigate_to_date(self, target_date: str) -> bool:
        """
        Navigate to the target date in the tee times calendar.
        target_date format: YYYY-MM-DD
        """
        target = datetime.strptime(target_date, '%Y-%m-%d')
        target_day = target.day
        target_month_abbr = target.strftime('%b')  # "Mar"
        target_month_full = target.strftime('%B')  # "March"
        target_weekday = target.strftime('%a')  # "Sun", "Mon", etc.

        logger.info(f"Navigating to date: {target_weekday} {target_month_full} {target_day} ({target_date})")

        # Debug: show what's on the page
        self.debug_page_elements()

        # First, let's see what's currently visible on the page
        time.sleep(1)

        max_clicks = 15
        clicks = 0

        while clicks < max_clicks:
            # Try to find the date tab
            # Screenshot shows format like: "Sun\nMarch 8" or "Tue\nMarch 17"
            # The day number might be on its own line or with the month

            # First check if the date is already visible and selected
            page_text = self.driver.page_source

            # Look for date tabs - they show weekday + month + day
            # Try to find an element that contains both month and day number
            date_patterns = [
                # Exact format from screenshot: weekday on top, "Month Day" below
                f"//*[contains(text(), '{target_month_full} {target_day}')]",
                f"//*[contains(text(), '{target_month_full}') and contains(text(), ' {target_day}')]",
                # Just month and day
                f"//*[contains(text(), '{target_month_abbr} {target_day}')]",
                # Day number with month nearby
                f"//*[text()='{target_day}'][..//*[contains(text(), '{target_month_full}')]]",
                f"//*[text()=' {target_day}'][..//*[contains(text(), '{target_month_full}')]]",
            ]

            for pattern in date_patterns:
                try:
                    date_elements = self.driver.find_elements(By.XPATH, pattern)
                    for date_elem in date_elements:
                        if date_elem.is_displayed():
                            elem_text = date_elem.text.strip()
                            # Make sure this looks like a date tab (not table data)
                            # Date tabs should contain month name
                            if target_month_full in elem_text or target_month_abbr in elem_text:
                                logger.info(f"Found date element: '{elem_text}'")
                                try:
                                    date_elem.click()
                                    logger.info(f"Selected date: {target_date}")
                                    time.sleep(1.5)
                                    return True
                                except ElementClickInterceptedException:
                                    self.driver.execute_script("arguments[0].click();", date_elem)
                                    logger.info(f"Selected date via JS: {target_date}")
                                    time.sleep(1.5)
                                    return True
                except (NoSuchElementException, StaleElementReferenceException):
                    continue

            # Date not found, we need to click the forward arrow
            # The arrow should be near the date tabs, not elsewhere on the page
            logger.info(f"Date not visible yet, looking for navigation arrow...")

            # Look specifically for the date navigation arrow
            # Based on screenshot it's a circular play button style after the date tabs
            arrow_found = False

            # Try to find arrow by looking near the "My Tee Times" header area
            try:
                # The arrow is likely an <a> or <img> element after the last date tab
                # Look for elements in the header/nav area that could be arrows
                header_area = self.driver.find_elements(
                    By.XPATH,
                    "//*[contains(text(), 'My Tee Times')]/ancestor::*[position()<=3]"
                )

                for area in header_area:
                    # Find clickable elements that might be arrows within this area
                    potential_arrows = area.find_elements(
                        By.XPATH,
                        ".//a | .//button | .//img | .//span[contains(@class, 'icon')]"
                    )
                    for arrow in potential_arrows:
                        if arrow.is_displayed():
                            # Check if this looks like a forward arrow
                            arrow_html = arrow.get_attribute('outerHTML') or ''
                            arrow_class = arrow.get_attribute('class') or ''
                            arrow_src = arrow.get_attribute('src') or ''

                            if any(x in arrow_html.lower() + arrow_class.lower() + arrow_src.lower()
                                   for x in ['next', 'forward', 'right', 'arrow', 'play', '>']):
                                logger.info(f"Found potential arrow: {arrow_html[:100]}")
                                try:
                                    arrow.click()
                                    arrow_found = True
                                    clicks += 1
                                    time.sleep(1)
                                    break
                                except:
                                    pass
                    if arrow_found:
                        break
            except Exception as e:
                logger.debug(f"Error finding arrow in header: {e}")

            # If we already found and clicked an arrow above, continue to next iteration
            if arrow_found:
                logger.info(f"Navigated forward (click {clicks})")
                continue

            # The forward arrow is id="cc_tab_next" with title="Show Next Date"
            try:
                # Get dates before clicking for comparison
                dates_before = [e.text for e in self.driver.find_elements(By.XPATH, "//*[contains(text(), 'March')]")[:6]]
                logger.info(f"Current dates visible: {dates_before}")

                # Find the next arrow by ID
                next_arrow = self.driver.find_element(By.ID, "cc_tab_next")

                # Check if it's visible (not hidden)
                visibility = next_arrow.get_attribute("style") or ""
                if "hidden" in visibility:
                    logger.info("Next arrow is hidden (already at end of dates)")
                    # Can't navigate further, break out
                    break

                logger.info("Found cc_tab_next arrow, clicking...")

                # Click the arrow
                try:
                    ActionChains(self.driver).move_to_element(next_arrow).click().perform()
                except:
                    self.driver.execute_script("arguments[0].click();", next_arrow)

                time.sleep(1.5)

                # Check if dates changed
                dates_after = [e.text for e in self.driver.find_elements(By.XPATH, "//*[contains(text(), 'March')]")[:6]]
                logger.info(f"Dates after click: {dates_after}")

                if dates_before != dates_after and len(dates_after) > 0:
                    logger.info("Navigation successful!")
                    clicks += 1
                    continue
                else:
                    logger.warning("Dates didn't change after clicking arrow")

            except NoSuchElementException:
                logger.error("Could not find cc_tab_next element")
            except Exception as e:
                logger.error(f"Error in date navigation: {e}")

            # If we still haven't navigated, log an error
            if not clicked:
                logger.error("Could not find working date navigation arrow")
                # Try finding any clickable element that might navigate
                try:
                    # Look for the >> or > button visible in screenshot
                    arrow = self.driver.find_element(By.XPATH, "//*[contains(text(), '»') or contains(text(), '›')]")
                    arrow.click()
                    time.sleep(0.7)
                    clicks += 1
                except:
                    break

        logger.error(f"Could not find date {target_date} after {clicks} attempts")
        return False

    def select_course(self, course_name: str) -> bool:
        """Select a course from the dropdown."""
        logger.info(f"Selecting course: {course_name}")

        try:
            # Find the course dropdown - based on screenshot it says "Select Course for Play:"
            dropdown_selectors = [
                "//select[contains(@id, 'course') or contains(@name, 'course')]",
                "//select[contains(@id, 'Course') or contains(@name, 'Course')]",
                "//label[contains(text(), 'Course')]/following::select[1]",
                "//label[contains(text(), 'Select Course')]/following::select[1]",
                "//*[contains(text(), 'Select Course')]/following::select[1]",
                "//select",
            ]

            for selector in dropdown_selectors:
                try:
                    dropdowns = self.driver.find_elements(By.XPATH, selector)
                    for dropdown in dropdowns:
                        if dropdown.is_displayed():
                            select = Select(dropdown)
                            # Try to select by visible text
                            try:
                                select.select_by_visible_text(course_name)
                                logger.info(f"Selected course: {course_name}")
                                time.sleep(1.5)
                                return True
                            except NoSuchElementException:
                                # Try partial match
                                for option in select.options:
                                    if course_name.lower() in option.text.lower():
                                        select.select_by_visible_text(option.text)
                                        logger.info(f"Selected course: {option.text}")
                                        time.sleep(1.5)
                                        return True
                except (NoSuchElementException, StaleElementReferenceException):
                    continue

            logger.error(f"Could not find or select course: {course_name}")
            return False

        except Exception as e:
            logger.error(f"Error selecting course: {e}")
            return False

    def _parse_time_to_minutes(self, time_str: str) -> int:
        """Parse time string like '07:30 AM' to minutes since midnight."""
        time_str = time_str.strip().upper()
        match = re.match(r'(\d{1,2}):(\d{2})\s*(AM|PM)?', time_str)
        if not match:
            return -1

        hour = int(match.group(1))
        minute = int(match.group(2))
        ampm = match.group(3)

        if ampm == 'PM' and hour != 12:
            hour += 12
        elif ampm == 'AM' and hour == 12:
            hour = 0

        return hour * 60 + minute

    def find_and_book_tee_time(self) -> bool:
        """
        Find an available tee time and book it.
        Returns True if booking successful, False otherwise.
        """
        target_time = self.config['booking']['target_time']
        leeway_hours = self.config['booking']['leeway_hours']
        num_players = self.config['booking']['num_players']

        target_minutes = self._parse_time_to_minutes(target_time)
        max_minutes = target_minutes + (leeway_hours * 60)

        target_time_str = f"{target_minutes // 60:02d}:{target_minutes % 60:02d}"
        max_time_str = f"{max_minutes // 60:02d}:{max_minutes % 60:02d}"

        logger.info(f"Looking for tee time between {target_time_str} and {max_time_str}")
        logger.info(f"Need {num_players} player slots")

        time.sleep(1)

        # Find all rows in the tee times table
        # Based on screenshot: rows have Reserve button, Course Name, Play Date, Tee Time, Player Slots Available
        try:
            # Look for tee time entries - the green buttons show times like "+ 07:30 AM"
            # Find all elements that look like reserve buttons with times

            # Method 1: Find by the reserve button pattern
            reserve_buttons = self.driver.find_elements(
                By.XPATH,
                "//*[contains(@class, 'reserve') or contains(@class, 'btn')]"
                "[contains(text(), 'AM') or contains(text(), 'PM') or contains(text(), ':')]"
            )

            # Method 2: Find table rows
            rows = self.driver.find_elements(
                By.XPATH,
                "//tr[.//td[contains(text(), ':') and (contains(text(), 'AM') or contains(text(), 'PM'))]]"
            )

            available_slots = []

            for row in rows:
                try:
                    row_text = row.text
                    # Skip header rows
                    if 'Reserve' in row_text and 'Course' in row_text:
                        continue

                    # Extract tee time from the row
                    time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM))', row_text, re.IGNORECASE)
                    if not time_match:
                        continue

                    tee_time = time_match.group(1).strip()
                    tee_minutes = self._parse_time_to_minutes(tee_time)

                    # Check if within acceptable window
                    if tee_minutes < target_minutes or tee_minutes > max_minutes:
                        continue

                    # Extract slots available (last number in the row)
                    numbers = re.findall(r'\b(\d+)\b', row_text)
                    if not numbers:
                        continue

                    # The slots available should be the last number
                    slots_available = int(numbers[-1])

                    # Check if enough slots
                    if slots_available < num_players:
                        logger.info(f"  {tee_time}: only {slots_available} slots (need {num_players})")
                        continue

                    # Check if reserve button is enabled (green vs grey)
                    # Green buttons are clickable, grey are not
                    try:
                        # Look for the reserve button in this row
                        reserve_btn = row.find_element(
                            By.XPATH,
                            ".//button | .//input[@type='button'] | .//a[contains(text(), ':')]"
                        )

                        # Check if it's not disabled/greyed
                        if reserve_btn.is_enabled():
                            available_slots.append({
                                'time': tee_time,
                                'minutes': tee_minutes,
                                'slots': slots_available,
                                'row': row,
                                'button': reserve_btn
                            })
                            logger.info(f"  Found: {tee_time} with {slots_available} slots")
                    except NoSuchElementException:
                        pass

                except (StaleElementReferenceException, Exception) as e:
                    continue

            if not available_slots:
                # Try alternative method - look for the green + buttons directly
                logger.info("Trying alternative method to find tee times...")

                time_buttons = self.driver.find_elements(
                    By.XPATH,
                    "//*[contains(text(), 'AM') or contains(text(), 'PM')]"
                    "[contains(text(), ':')]"
                    "[not(contains(@class, 'disabled'))]"
                )

                for btn in time_buttons:
                    try:
                        btn_text = btn.text.strip()
                        time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM))', btn_text, re.IGNORECASE)
                        if not time_match:
                            continue

                        tee_time = time_match.group(1).strip()
                        tee_minutes = self._parse_time_to_minutes(tee_time)

                        if tee_minutes < target_minutes or tee_minutes > max_minutes:
                            continue

                        # Try to find slots for this time in parent row
                        try:
                            parent_row = btn.find_element(By.XPATH, "./ancestor::tr")
                            row_text = parent_row.text
                            numbers = re.findall(r'\b(\d+)\b', row_text)
                            slots_available = int(numbers[-1]) if numbers else 4
                        except:
                            slots_available = 4  # Assume available if button is green

                        if slots_available >= num_players and btn.is_enabled():
                            available_slots.append({
                                'time': tee_time,
                                'minutes': tee_minutes,
                                'slots': slots_available,
                                'button': btn
                            })
                            logger.info(f"  Found: {tee_time}")

                    except (StaleElementReferenceException, Exception):
                        continue

            if not available_slots:
                logger.warning("No available tee times found in the acceptable window")
                return False

            # Sort by time (earliest first)
            available_slots.sort(key=lambda x: x['minutes'])

            # Try to book the earliest available slot
            for slot in available_slots:
                logger.info(f"Attempting to book {slot['time']}...")

                try:
                    slot['button'].click()
                    time.sleep(2)

                    # Now fill in the player information
                    if self.fill_player_info():
                        if self.save_reservation():
                            logger.info(f"Successfully booked {slot['time']}!")
                            return True
                        else:
                            logger.warning(f"Failed to save reservation for {slot['time']}")
                    else:
                        logger.warning(f"Failed to fill player info for {slot['time']}")

                    # If this slot failed, try next one
                    # Click cancel if there's a cancel button
                    try:
                        cancel_btn = self.driver.find_element(
                            By.XPATH,
                            "//button[contains(text(), 'Cancel')] | //input[@value='Cancel']"
                        )
                        cancel_btn.click()
                        time.sleep(1)
                    except:
                        pass

                except Exception as e:
                    logger.error(f"Error booking {slot['time']}: {e}")
                    continue

            return False

        except Exception as e:
            logger.error(f"Error finding tee times: {e}")
            return False

    def fill_player_info(self) -> bool:
        """
        Fill in player information in the booking form.
        Player 1 is auto-filled with the logged-in member.
        """
        players = self.config['booking']['players']
        logger.info(f"Filling in {len(players)} additional player(s)...")

        try:
            time.sleep(1)

            # Debug: find all select elements to understand the form structure
            all_selects = self.driver.find_elements(By.TAG_NAME, "select")
            logger.info(f"Found {len(all_selects)} select elements on booking form")

            # The form typically has pairs of dropdowns for each player row:
            # - Player Type (Member/Guest/etc)
            # - Player Name

            # For each additional player (starting at player 2)
            for i, player_name in enumerate(players, start=2):
                logger.info(f"  Adding player {i}: {player_name}")

                # Find the row for this player - look for row with number "2", "3", etc.
                player_row = None
                try:
                    # The row has a td with just the player number
                    player_row = self.driver.find_element(
                        By.XPATH,
                        f"//tr[.//td[normalize-space(text())='{i}']]"
                    )
                    logger.info(f"    Found row for player {i}")
                except NoSuchElementException:
                    logger.warning(f"    Could not find row for player {i}")

                # Select Player Type = "Member"
                try:
                    if player_row:
                        # Find first select in this row (should be Player Type)
                        selects_in_row = player_row.find_elements(By.TAG_NAME, "select")
                        if len(selects_in_row) >= 1:
                            type_dropdown = selects_in_row[0]
                            select = Select(type_dropdown)
                            # Select "Member"
                            for option in select.options:
                                if 'member' in option.text.lower():
                                    select.select_by_visible_text(option.text)
                                    logger.info(f"    Selected type: {option.text}")
                                    break
                            time.sleep(0.5)
                except Exception as e:
                    logger.debug(f"    Could not select player type: {e}")

                # Select Player Name
                try:
                    name_dropdown = None
                    if player_row:
                        # Second dropdown in row is usually name
                        dropdowns = player_row.find_elements(By.XPATH, ".//select")
                        if len(dropdowns) >= 2:
                            name_dropdown = dropdowns[1]
                    else:
                        # Find by name attribute
                        name_dropdowns = self.driver.find_elements(
                            By.XPATH,
                            "//select[contains(@name, 'name') or contains(@name, 'Name') or contains(@name, 'Player')]"
                        )
                        # Filter to ones that contain member names
                        for dd in name_dropdowns:
                            options = Select(dd).options
                            if any(player_name.lower() in opt.text.lower() for opt in options):
                                name_dropdown = dd
                                break

                    if name_dropdown:
                        select = Select(name_dropdown)
                        # Try exact match first
                        try:
                            select.select_by_visible_text(player_name)
                        except NoSuchElementException:
                            # Try partial match
                            for option in select.options:
                                if player_name.lower() in option.text.lower():
                                    select.select_by_visible_text(option.text)
                                    break
                        time.sleep(0.5)
                        logger.info(f"    Selected: {player_name}")
                    else:
                        logger.warning(f"    Could not find name dropdown for player {i}")

                except Exception as e:
                    logger.error(f"Error selecting player {i}: {e}")
                    return False

            return True

        except Exception as e:
            logger.error(f"Error filling player info: {e}")
            return False

    def save_reservation(self) -> bool:
        """Click the Save button to confirm the reservation."""
        logger.info("Saving reservation...")

        try:
            # Find and click Save button
            save_selectors = [
                "//button[contains(text(), 'Save')]",
                "//input[@value='Save']",
                "//a[contains(text(), 'Save')]",
                "//button[@type='submit']",
                "//input[@type='submit']",
            ]

            for selector in save_selectors:
                try:
                    save_button = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )
                    save_button.click()
                    break
                except TimeoutException:
                    continue
            else:
                logger.error("Could not find Save button")
                return False

            # Wait for response
            time.sleep(3)

            # Check for success or error
            page_text = self.driver.page_source.lower()

            if 'error' in page_text or 'failed' in page_text or 'unable' in page_text:
                logger.error("Reservation may have failed - check for errors")
                return False

            if 'confirmed' in page_text or 'success' in page_text or 'booked' in page_text:
                logger.info("Reservation confirmed!")
                return True

            # No explicit message - assume success
            logger.info("Reservation saved (checking confirmation...)")
            return True

        except Exception as e:
            logger.error(f"Error saving reservation: {e}")
            return False

    def attempt_booking(self) -> bool:
        """Make one attempt to book a tee time."""
        logger.info("-" * 40)

        # Dismiss any info modal
        self.dismiss_info_modal()

        # Navigate to target date
        if not self.navigate_to_date(self.config['booking']['target_date']):
            logger.warning("Could not navigate to date, will retry...")
            return False

        # Try each course in preference order
        for course in self.config['booking']['course_preference']:
            logger.info(f"Trying course: {course}")

            if not self.select_course(course):
                logger.warning(f"Could not select course {course}")
                continue

            time.sleep(1)

            # Try to find and book a tee time
            if self.find_and_book_tee_time():
                return True

            logger.info(f"No suitable tee time found at {course}")

        return False

    def run(self, start_immediately: bool = False):
        """Main execution flow."""
        logger.info("=" * 60)
        logger.info("TeeTimer - Automated Tee Time Booking")
        logger.info("The Hills Country Club")
        logger.info("=" * 60)
        logger.info(f"Target: {self.config['booking']['target_date']} at {self.config['booking']['target_time']}")
        logger.info(f"Players: {self.config['booking']['num_players']}")
        logger.info(f"Courses: {', '.join(self.config['booking']['course_preference'])}")
        logger.info(f"Leeway: {self.config['booking']['leeway_hours']} hours")
        logger.info("=" * 60)

        try:
            # Initialize browser
            self._init_driver()

            # Wait until it's time to start (unless starting immediately)
            if not start_immediately:
                self._wait_until_start_time()

            # Login
            logger.info("Logging in...")
            if not self.login():
                logger.error("Failed to login - check credentials")
                return False

            # Navigate to tee times
            if not self.navigate_to_tee_times():
                logger.error("Failed to navigate to tee times")
                return False

            # Retry loop
            retry_interval = self.config['timing']['retry_interval_seconds']
            max_retries = (self.config['timing']['max_retry_minutes'] * 60) // retry_interval

            for attempt in range(max_retries):
                logger.info(f"\nBooking attempt {attempt + 1}/{max_retries}")

                try:
                    if self.attempt_booking():
                        logger.info("=" * 60)
                        logger.info("BOOKING SUCCESSFUL!")
                        logger.info("=" * 60)
                        return True
                except Exception as e:
                    logger.error(f"Error during booking attempt: {e}")

                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_interval} seconds...")
                    time.sleep(retry_interval)

                    # Re-navigate to tee times (don't just refresh - that loses the modal)
                    try:
                        # Check if we're still in the tee times modal
                        if "March" not in self.driver.page_source:
                            logger.info("Modal closed, re-navigating to tee times...")
                            self.driver.switch_to.default_content()
                            self.navigate_to_tee_times()
                    except:
                        pass

            logger.error("=" * 60)
            logger.error("Failed to book tee time after all attempts")
            logger.error("=" * 60)
            return False

        except KeyboardInterrupt:
            logger.info("\nBooking cancelled by user")
            return False
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            raise
        finally:
            if self.driver:
                try:
                    input("\nPress Enter to close browser...")
                except:
                    pass
                self.driver.quit()


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="TeeTimer - Automated Tee Time Booking for The Hills Country Club"
    )
    parser.add_argument(
        "-c", "--config",
        default="config.json",
        help="Path to config file (default: config.json)"
    )
    parser.add_argument(
        "--now",
        action="store_true",
        help="Start booking immediately without waiting for booking window"
    )
    parser.add_argument(
        "--test-login",
        action="store_true",
        help="Test login only, don't attempt booking"
    )

    args = parser.parse_args()

    teetimer = TeeTimer(args.config)

    if args.test_login:
        teetimer._init_driver()
        success = teetimer.login()
        if success:
            logger.info("Login test successful!")
            input("Press Enter to close browser...")
        teetimer.driver.quit()
        exit(0 if success else 1)

    success = teetimer.run(start_immediately=args.now)
    exit(0 if success else 1)


if __name__ == "__main__":
    main()
