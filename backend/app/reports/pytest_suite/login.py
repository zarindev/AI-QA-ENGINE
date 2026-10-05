"""Login page: finds the password field and the user-name field before it, so it works on most login forms."""

from __future__ import annotations

from pages.base import BasePage
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

USER_FIELDS = (
    "input[type=email], input[autocomplete=username], input[name*=user i], input[name*=email i], "
    "input[id*=user i], input[id*=email i], input[name*=login i], input[type=text]"
)


class LoginPage(BasePage):
    def login(self, path: str, username: str, password: str) -> None:
        self.open(path)
        pw = WebDriverWait(self.driver, 15, ignored_exceptions=[StaleElementReferenceException]).until(
            lambda d: next(
                (e for e in d.find_elements(By.CSS_SELECTOR, "input[type=password]") if e.is_displayed()),
                None,
            )
        )
        form = pw.find_elements(By.XPATH, "ancestor::form[1]")
        scope = form[0] if form else self.driver
        user = next((e for e in scope.find_elements(By.CSS_SELECTOR, USER_FIELDS) if e.is_displayed()), None)
        assert user is not None, f"No user-name field next to the password field on {self.driver.current_url}"
        user.clear()
        user.send_keys(username)
        pw.clear()
        pw.send_keys(password + Keys.ENTER)
        WebDriverWait(self.driver, 20, ignored_exceptions=[StaleElementReferenceException]).until(
            lambda d: not any(
                e.is_displayed() for e in d.find_elements(By.CSS_SELECTOR, "input[type=password]")
            )
        )
        self.wait_ready()
