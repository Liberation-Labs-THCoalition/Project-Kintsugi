"""Web dashboard — real-time view of the agent fleet, BDI state, skills,
and Oracle Loop status. Server-rendered Jinja2 + htmx; zero build step."""

from kintsugi.dashboard.routes import router, static_dir

__all__ = ["router", "static_dir"]
