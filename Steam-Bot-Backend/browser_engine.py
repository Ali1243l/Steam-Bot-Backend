"""

browser_engine.py - Generic Headless Browser Automation Pattern

Provides a robust, reusable Playwright async runner with automated error handling,

failure screenshots, and dynamic DOM interaction flows.

"""

import asyncio

import logging

from pathlib import Path

from datetime import datetime

from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

# Configure structured logging

logger = logging.getLogger("browser_engine")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class AutomationRunner:

    """Manages headless browser lifecycle, failure snapshots, and execution workflows."""

    def init(self, screenshot_dir: str = "./artifacts/screenshots"):

        self.screenshot_dir = Path(screenshot_dir)

        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

        self.browser: Optional[Browser] = None

        self.context: Optional[BrowserContext] = None

        self.page: Optional[Page] = None

    async def _capture_failure_artifact(self, page: Optional[Page], context_name: str) -> None:

        """Captures a screenshot and DOM dump when an unexpected failure occurs."""

        if not page:

            return

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

        filename = f"failure_{context_name}_{timestamp}.png"

        filepath = self.screenshot_dir / filename

        try:

            await page.screenshot(path=str(filepath), full_page=True)

            logger.warning(f"[ARTIFACT:SCREENSHOT] Captured failure state at: {filepath}")

        except Exception as snap_err:

            logger.error(f"[ARTIFACT:FAILED] Could not write failure screenshot: {snap_err}")

    async def execute_form_flow(

        self,

        target_url: str,

        verification_token: str,

        new_contact_value: str,

        timeout_ms: int = 15000,

    ) -> bool:

        """

        Navigates to a target settings view, triggers an edit modal, inputs

        form values, and dispatches the submission.

        """

        async with async_playwright() as p:

            logger.info("[BROWSER:LAUNCH] Initializing headless Chromium...")

            # Headless mode enabled by default for cloud environments (e.g., VPS/Docker)

            self.browser = await p.chromium.launch(

                headless=True,

                args=[

                    "--no-sandbox",

                    "--disable-setuid-sandbox",

                    "--disable-dev-shm-usage",  # Critical for containerized runners

                ],

            )

            # Define standard viewport and locale

            self.context = await self.browser.new_context(

                viewport={"width": 1280, "height": 720},

                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",

            )

            self.page = await self.context.new_page()

            try:

                # 1. Navigate to target URL

                logger.info(f"[NAVIGATE] Opening: {target_url}")

                await self.page.goto(target_url, wait_until="networkidle", timeout=timeout_ms)

                # 2. Locate and click target button (e.g., 'Update Contact Info')

                button_locator = self.page.get_by_role("button", name="Update Contact Info")

                logger.info("[ACTION:CLICK] Waiting for action button to become visible...")

                await button_locator.wait_for(state="visible", timeout=timeout_ms)

                await button_locator.click()

                # 3. Wait for dynamic modal / form container to mount

                modal_locator = self.page.locator('[role="dialog"], .modal-container, form#contact-form')

                logger.info("[WAIT:MODAL] Awaiting dynamic form container...")

                await modal_locator.wait_for(state="visible", timeout=timeout_ms)

                # 4. Fill verification token field

                token_input = modal_locator.locator('input[name="token"], input[placeholder*="Code" i]')

                logger.info("[INPUT:TOKEN] Supplying verification token...")

                await token_input.wait_for(state="visible", timeout=timeout_ms)

                await token_input.fill(verification_token)

                # 5. Fill new contact string field

                contact_input = modal_locator.locator('input[name="contact"], input[type="email"], input[placeholder*="Contact" i]')

                logger.info("[INPUT:CONTACT] Supplying new contact string...")

                await contact_input.wait_for(state="visible", timeout=timeout_ms)

                await contact_input.fill(new_contact_value)

                # 6. Click confirmation / submit button

                submit_btn = modal_locator.get_by_role("button", name="Save")

                logger.info("[ACTION:SUBMIT] Submitting form...")

                await submit_btn.wait_for(state="visible", timeout=timeout_ms)

                await submit_btn.click()

                # 7. Await response indicator or modal close

                await modal_locator.wait_for(state="hidden", timeout=timeout_ms)

                logger.info("[SUCCESS] Form flow completed successfully.")

                return True

            except PlaywrightTimeoutError as timeout_err:

                logger.error(f"[TIMEOUT] Element interaction timed out: {timeout_err}")

                await self._capture_failure_artifact(self.page, "timeout")

                return False

            except Exception as err:

                logger.exception(f"[ERROR] Automation step failed: {err}")

                await self._capture_failure_artifact(self.page, "error")

                return False

            finally:

                logger.info("[BROWSER:CLOSE] Cleaning up browser context...")

                if self.context:

                    await self.context.close()

                if self.browser:

                    await self.browser.close()

# Example demonstration

if __name__ == "__main__":

    runner = AutomationRunner()

    

    # Run the workflow with sample test parameters

    success = asyncio.run(

        runner.execute_form_flow(

            target_url="https://store.steampowered.com/account/",

            verification_token="ABC12",

            new_contact_value="user@example.com",

        )

    )

    print(f"Execution finished. Result: {success}")
