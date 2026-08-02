"""Tests for kintsugi.cognition.llm_client auth precedence.

CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`) takes precedence over
ANTHROPIC_API_KEY when both are present — verified working end-to-end with
a real API call this session; these tests just lock in the precedence/
construction logic without hitting the network.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from kintsugi.cognition.llm_client import AnthropicClient


class TestAuthPrecedence:
    def test_explicit_auth_token_used_over_settings(self):
        with patch("kintsugi.cognition.llm_client.AsyncAnthropic") as mock_cls:
            AnthropicClient(auth_token="explicit-oauth-token")
            mock_cls.assert_called_once_with(auth_token="explicit-oauth-token", api_key=None)

    def test_auth_token_takes_precedence_over_api_key(self):
        with patch("kintsugi.cognition.llm_client.AsyncAnthropic") as mock_cls:
            AnthropicClient(api_key="sk-explicit", auth_token="oauth-token")
            mock_cls.assert_called_once_with(auth_token="oauth-token", api_key=None)

    def test_falls_back_to_settings_oauth_token(self):
        fake_settings = MagicMock(CLAUDE_CODE_OAUTH_TOKEN="settings-oauth-token", ANTHROPIC_API_KEY="")
        with patch("kintsugi.cognition.llm_client.settings", fake_settings), \
             patch("kintsugi.cognition.llm_client.AsyncAnthropic") as mock_cls:
            AnthropicClient()
            mock_cls.assert_called_once_with(auth_token="settings-oauth-token", api_key=None)

    def test_api_key_used_when_no_oauth_token(self):
        with patch("kintsugi.cognition.llm_client.AsyncAnthropic") as mock_cls:
            AnthropicClient(api_key="sk-explicit")
            mock_cls.assert_called_once_with(api_key="sk-explicit")

    def test_no_credentials_falls_back_to_bare_client(self):
        fake_settings = MagicMock(CLAUDE_CODE_OAUTH_TOKEN="", ANTHROPIC_API_KEY="")
        with patch("kintsugi.cognition.llm_client.settings", fake_settings), \
             patch("kintsugi.cognition.llm_client.AsyncAnthropic") as mock_cls:
            AnthropicClient()
            mock_cls.assert_called_once_with()
