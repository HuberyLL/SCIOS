"""Email notification service — renders DailyBrief as HTML and sends via SMTP."""

from __future__ import annotations

import logging
from email.message import EmailMessage

import aiosmtplib

from src.agents.monitoring.schemas import DailyBrief
from src.core.config import get_settings

logger = logging.getLogger(__name__)


def _render_html(brief: DailyBrief) -> str:
    """Convert a DailyBrief into a self-contained HTML email body."""

    paper_rows: list[str] = []
    for p in brief.new_hot_papers:
        authors = ", ".join(p.authors) if p.authors else "N/A"
        link = f'<a href="{p.url}">{p.title}</a>' if p.url else p.title
        paper_rows.append(
            f"<tr>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{link}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{authors}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee;text-align:center'>{p.year}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee;text-align:center'>{p.citation_count}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{p.relevance_reason}</td>"
            f"</tr>"
        )

    papers_table = ""
    if paper_rows:
        papers_table = (
            "<table style='border-collapse:collapse;width:100%;font-size:14px'>"
            "<thead><tr style='background:#f5f5f5'>"
            "<th style='padding:8px 10px;text-align:left'>Title</th>"
            "<th style='padding:8px 10px;text-align:left'>Authors</th>"
            "<th style='padding:8px 10px;text-align:center'>Year</th>"
            "<th style='padding:8px 10px;text-align:center'>Citations</th>"
            "<th style='padding:8px 10px;text-align:left'>Relevance</th>"
            "</tr></thead>"
            f"<tbody>{''.join(paper_rows)}</tbody>"
            "</table>"
        )

    sources_html = ""
    if brief.sources:
        items = "".join(f"<li>{s}</li>" for s in brief.sources)
        sources_html = f"<h3>Sources</h3><ul>{items}</ul>"

    return (
        "<html><body style='font-family:Arial,sans-serif;color:#333;max-width:720px;margin:auto'>"
        f"<h2>SCIOS Daily Brief — {brief.topic}</h2>"
        f"<p style='color:#666'>Period since: {brief.since_date}</p>"
        "<h3>Hot Papers</h3>"
        f"{papers_table or '<p>No new papers found.</p>'}"
        f"<h3>Trend Summary</h3>"
        f"<p>{brief.trend_summary or 'N/A'}</p>"
        f"{sources_html}"
        "<hr style='margin-top:24px;border:none;border-top:1px solid #ddd'>"
        "<p style='font-size:12px;color:#999'>Sent by SCIOS — Smart Research Agent</p>"
        "</body></html>"
    )


async def send_daily_brief_email(brief: DailyBrief, recipient: str) -> bool:
    """Render *brief* as HTML and send via SMTP.

    Returns True on success, False on failure (logged, never raises).
    """
    settings = get_settings()

    if not settings.smtp_server or not settings.smtp_username:
        logger.warning("SMTP not configured — skipping email send")
        return False

    try:
        html = _render_html(brief)

        msg = EmailMessage()
        msg["Subject"] = f"SCIOS Daily Brief — {brief.topic}"
        msg["From"] = settings.smtp_username
        msg["To"] = recipient
        msg.set_content(f"SCIOS Daily Brief for {brief.topic} (since {brief.since_date})")
        msg.add_alternative(html, subtype="html")

        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_server,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            use_tls=settings.smtp_port == 465,
            start_tls=settings.smtp_port != 465,
        )

        logger.info("Email sent to %s for topic '%s'", recipient, brief.topic)
        return True

    except Exception:
        logger.exception("Failed to send email to %s", recipient)
        return False
