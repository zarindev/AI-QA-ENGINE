"""HTML → PDF with the same Chrome QA Pilot already uses (no WeasyPrint / GTK to install).

The HTML is written next to the PDF so relative image paths resolve, then printed by headless Chrome.
"""

from __future__ import annotations

import base64
from pathlib import Path

from selenium.webdriver.common.print_page_options import PrintOptions

from app.browser.driver import BrowserSession
from app.storage.repository import Repository


def html_to_pdf(
    repo: Repository, html: str, html_path: Path, pdf_path: Path, landscape: bool = False
) -> Path:
    repo.write_text(html_path, html)
    options = PrintOptions()
    options.background = True
    options.orientation = "landscape" if landscape else "portrait"
    options.page_width, options.page_height = 21.0, 29.7  # A4, cm
    options.margin_top = options.margin_bottom = 1.2
    options.margin_left = options.margin_right = 1.2
    with BrowserSession(headless=True, width=1240, height=1754) as session:
        session.navigate(html_path.resolve().as_uri())
        session.wait_ready(timeout_s=8)
        data = session.driver.print_page(options)
    repo.write_bytes(pdf_path, base64.b64decode(data))
    return pdf_path
