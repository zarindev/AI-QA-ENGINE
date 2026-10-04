from __future__ import annotations

import pytest

from app.core.safety import ActionContext, SafetyGuard


@pytest.fixture
def safe(settings):
    return SafetyGuard("safe", settings["safety"], preserve_session=True)


@pytest.fixture
def full(settings):
    return SafetyGuard("full", settings["safety"], preserve_session=True)


@pytest.mark.parametrize(
    "text",
    [
        "Delete patient",
        "Remove from cart",
        "Cancel appointment",
        "Pay now",
        "Checkout",
        "Place order",
        "Transfer funds",
        "Reset App State",
        "Refund",
        "Discharge patient",
    ],
)
def test_safe_mode_blocks_destructive_clicks(safe, text):
    assert not safe.check(ActionContext(kind="click", text=text)).allowed


@pytest.mark.parametrize(
    "text", ["Save patient", "View details", "Add to cart", "Next page", "Patients", "Deleted items"]
)
def test_safe_mode_allows_harmless_clicks(safe, text):
    # "Deleted items" is a view, not an action: whole-word matching must not treat it as "delete"
    assert safe.check(ActionContext(kind="click", text=text)).allowed


def test_attributes_and_context_are_checked(safe):
    assert not safe.check(ActionContext(kind="click", text="", attributes={"id": "btn-delete-4"})).allowed
    assert not safe.check(ActionContext(kind="click", text="OK", context="Confirm payment of $40")).allowed


def test_session_enders_blocked_while_exploring(safe, full):
    for g in (safe, full):
        assert not g.check(ActionContext(kind="click", text="Log out")).allowed
        assert not g.check(ActionContext(kind="navigate", href="https://x.test/logout")).allowed


def test_full_mode_allows_deny_list_but_never_always_blocked(full):
    assert full.check(ActionContext(kind="click", text="Delete patient")).allowed
    assert full.check(ActionContext(kind="submit", text="Create invoice")).allowed
    assert not full.check(ActionContext(kind="click", text="Delete account")).allowed
    assert not full.check(ActionContext(kind="navigate", href="https://x.test/admin/factory-reset")).allowed


def test_safe_mode_only_submits_search_forms(safe):
    assert safe.check(ActionContext(kind="submit", text="Search")).allowed
    assert safe.check(ActionContext(kind="submit", text="Go", form_is_safe=True)).allowed
    assert not safe.check(ActionContext(kind="submit", text="Save patient")).allowed
    assert not safe.check(ActionContext(kind="upload", text="Avatar")).allowed
    assert safe.check(ActionContext(kind="type", text="Name")).allowed


@pytest.mark.parametrize(
    "url,allowed",
    [
        ("https://x.test/add_remove_elements/", True),
        ("https://x.test/payments", True),
        ("https://x.test/inventory.html", True),
        ("https://x.test/users/5/delete", False),
        ("https://x.test/item?action=delete&id=3", False),
        ("https://x.test/checkout-step-one.html", False),
        ("https://x.test/cart/remove-item/4", False),
        ("https://x.test/pay/123", False),
        ("https://x.test/web/index.php/maintenance/purgeEmployee", False),
        ("https://x.test/web/index.php/pim/viewEmployeeList", True),
    ],
)
def test_navigation_checks_url_segments(safe, url, allowed):
    assert safe.check(ActionContext(kind="navigate", href=url)).allowed is allowed


def test_javascript_void_href_is_not_an_action(safe):
    assert safe.check(ActionContext(kind="click", text="Add to cart", href="javascript:void(0);")).allowed
