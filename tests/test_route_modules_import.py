"""Every route module main.py lists must import and expose a router.

main.py includes each module inside try/except and only logs a warning when one fails, so a
broken route used to vanish at startup. agent_v2 sat dead that way (a missing _get_llm_client)
until it was removed on 2026-10-01. This turns that silent skip into a test failure.
"""
import importlib

import pytest

from kintsugi.main import _route_modules


def test_the_route_list_is_not_empty():
    assert len(_route_modules) >= 5


@pytest.mark.parametrize("mod_path", _route_modules)
def test_every_listed_route_module_imports_with_a_router(mod_path):
    mod = importlib.import_module(mod_path)
    assert hasattr(mod, "router"), f"{mod_path} has no router"
