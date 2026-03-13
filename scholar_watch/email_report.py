"""HTML email composition and SMTP sending."""

import logging
import smtplib
import uuid
from datetime import datetime
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session

from .charts import citation_timeline
from .config import AppConfig
from .metrics import MetricsCalculator
from .models import Researcher

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "email_templates"


def generate_report(config: AppConfig, session: Session) -> MIMEMultipart | None:
    """Generate the HTML email report with inline chart images."""
    researchers = (
        session.query(Researcher)
        .filter(Researcher.is_active.is_(True))
        .all()
    )

    if not researchers:
        logger.warning("No active researchers for report")
        return None

    calc = MetricsCalculator(session)
    researcher_data = []
    images = []  # (cid, png_bytes) pairs

    for r in researchers:
        metrics = calc.compute(r.scholar_id)
        if not metrics:
            continue

        # Generate citation chart as PNG
        chart_cid = None
        try:
            fig = citation_timeline(session, r.id)
            png_bytes = fig.to_image(format="png", width=650, height=300)
            cid = f"chart-{uuid.uuid4().hex[:8]}"
            images.append((cid, png_bytes))
            chart_cid = cid
        except Exception as e:
            logger.warning("Could not generate chart for %s: %s", r.name, e)

        researcher_data.append({
            "name": r.name,
            "scholar_id": r.scholar_id,
            "total_citations": metrics.total_citations,
            "h_index": metrics.h_index,
            "i10_index": metrics.i10_index,
            "velocity": metrics.citation_velocity,
            "citation_chart_cid": chart_cid,
            "trending": metrics.trending_papers[:5],
            "declining": metrics.declining_papers[:5],
        })

    if not researcher_data:
        logger.warning("No metrics data for report")
        return None

    # Render HTML
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("report.html")
    html_content = template.render(
        subject_prefix=config.email.subject_prefix,
        report_date=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        researchers=researcher_data,
    )

    # Build MIME message
    msg = MIMEMultipart("related")
    msg["Subject"] = f"{config.email.subject_prefix} Citation Report - {datetime.utcnow().strftime('%Y-%m-%d')}"
    msg["From"] = config.email.from_address
    msg["To"] = ", ".join(config.email.to_addresses)

    msg.attach(MIMEText(html_content, "html"))

    for cid, png_bytes in images:
        img = MIMEImage(png_bytes, _subtype="png")
        img.add_header("Content-ID", f"<{cid}>")
        img.add_header("Content-Disposition", "inline", filename=f"{cid}.png")
        msg.attach(img)

    return msg


def send_report(config: AppConfig, session: Session) -> bool:
    """Generate and send the email report."""
    if not config.email.enabled:
        logger.info("Email is disabled in config")
        return False

    msg = generate_report(config, session)
    if msg is None:
        return False

    smtp_cfg = config.email.smtp
    try:
        if smtp_cfg.use_tls:
            server = smtplib.SMTP(smtp_cfg.host, smtp_cfg.port)
            server.starttls()
        else:
            server = smtplib.SMTP(smtp_cfg.host, smtp_cfg.port)

        if smtp_cfg.username:
            server.login(smtp_cfg.username, smtp_cfg.password)

        server.sendmail(
            config.email.from_address,
            config.email.to_addresses,
            msg.as_string(),
        )
        server.quit()
        logger.info("Report email sent to %s", config.email.to_addresses)
        return True

    except Exception as e:
        logger.error("Failed to send email: %s", e)
        return False
