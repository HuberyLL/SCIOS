"""Tests for src.services.notification — email rendering & sending."""

from __future__ import annotations

import pytest

from src.agents.monitoring.schemas import DailyBrief, HotPaper
from src.services.notification import _render_html, send_daily_brief_email


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_brief() -> DailyBrief:
    return DailyBrief(
        topic="LLM Alignment",
        since_date="2025-06-01",
        new_hot_papers=[
            HotPaper(
                title="RLHF Revisited",
                authors=["Alice", "Bob"],
                year=2025,
                url="https://example.com/rlhf",
                citation_count=42,
                relevance_reason="Key RLHF improvement",
            ),
            HotPaper(
                title="Constitutional AI v2",
                authors=["Charlie"],
                year=2025,
                url="https://example.com/cai",
                citation_count=10,
                relevance_reason="Novel self-supervision approach",
            ),
        ],
        trend_summary="Recent work focuses on scalable oversight for language models.",
        sources=["Semantic Scholar", "Tavily"],
    )


# ---------------------------------------------------------------------------
# _render_html
# ---------------------------------------------------------------------------


class TestRenderHtml:
    def test_contains_topic_and_papers(self, sample_brief: DailyBrief):
        html = _render_html(sample_brief)
        assert "LLM Alignment" in html
        assert "2025-06-01" in html
        assert "RLHF Revisited" in html
        assert "https://example.com/rlhf" in html
        assert "Constitutional AI v2" in html
        assert "Alice" in html

    def test_contains_trend_summary(self, sample_brief: DailyBrief):
        html = _render_html(sample_brief)
        assert "scalable oversight" in html

    def test_contains_sources(self, sample_brief: DailyBrief):
        html = _render_html(sample_brief)
        assert "Semantic Scholar" in html
        assert "Tavily" in html

    def test_no_papers(self):
        brief = DailyBrief(topic="Empty", since_date="2025-01-01")
        html = _render_html(brief)
        assert "No new papers found" in html


# ---------------------------------------------------------------------------
# send_daily_brief_email
# ---------------------------------------------------------------------------


class TestSendEmail:
    async def test_success(self, sample_brief: DailyBrief, mocker):
        mocker.patch(
            "src.services.notification.get_settings",
            return_value=mocker.MagicMock(
                smtp_server="smtp.example.com",
                smtp_port=465,
                smtp_username="sender@example.com",
                smtp_password="secret",
            ),
        )
        mock_send = mocker.patch("src.services.notification.aiosmtplib.send", return_value={})

        result = await send_daily_brief_email(sample_brief, "user@example.com")

        assert result is True
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args
        assert call_kwargs.kwargs["hostname"] == "smtp.example.com"
        assert call_kwargs.kwargs["username"] == "sender@example.com"

    async def test_missing_config_returns_false(self, sample_brief: DailyBrief, mocker):
        mocker.patch(
            "src.services.notification.get_settings",
            return_value=mocker.MagicMock(smtp_server="", smtp_username=""),
        )

        result = await send_daily_brief_email(sample_brief, "user@example.com")

        assert result is False

    async def test_smtp_error_returns_false(self, sample_brief: DailyBrief, mocker):
        mocker.patch(
            "src.services.notification.get_settings",
            return_value=mocker.MagicMock(
                smtp_server="smtp.example.com",
                smtp_port=587,
                smtp_username="sender@example.com",
                smtp_password="secret",
            ),
        )
        mocker.patch(
            "src.services.notification.aiosmtplib.send",
            side_effect=ConnectionRefusedError("Connection refused"),
        )

        result = await send_daily_brief_email(sample_brief, "user@example.com")

        assert result is False

    async def test_use_tls_for_port_465(self, sample_brief: DailyBrief, mocker):
        mocker.patch(
            "src.services.notification.get_settings",
            return_value=mocker.MagicMock(
                smtp_server="smtp.example.com",
                smtp_port=465,
                smtp_username="sender@example.com",
                smtp_password="secret",
            ),
        )
        mock_send = mocker.patch("src.services.notification.aiosmtplib.send", return_value={})

        await send_daily_brief_email(sample_brief, "user@example.com")

        assert mock_send.call_args.kwargs["use_tls"] is True
        assert mock_send.call_args.kwargs["start_tls"] is False

    async def test_starttls_for_port_587(self, sample_brief: DailyBrief, mocker):
        mocker.patch(
            "src.services.notification.get_settings",
            return_value=mocker.MagicMock(
                smtp_server="smtp.example.com",
                smtp_port=587,
                smtp_username="sender@example.com",
                smtp_password="secret",
            ),
        )
        mock_send = mocker.patch("src.services.notification.aiosmtplib.send", return_value={})

        await send_daily_brief_email(sample_brief, "user@example.com")

        assert mock_send.call_args.kwargs["use_tls"] is False
        assert mock_send.call_args.kwargs["start_tls"] is True
