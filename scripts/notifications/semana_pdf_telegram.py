#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[2]
SOURCE_MD = ROOT / "planning" / "weeks" / "semana_actual.md"
OUTPUT_DIR = ROOT / "planning" / "weeks" / "generated"
OUTPUT_PDF = OUTPUT_DIR / "semana_actual.pdf"
CONFIG_PATH = ROOT / "telegram" / "bot_config.yaml"
STATE_PATH = ROOT / "telegram" / ".semana_actual_state.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate semana_actual PDF and send it via Telegram")
    subparsers = parser.add_subparsers(dest="command", required=True)

    send_now = subparsers.add_parser("send-now", help="Generate PDF and send immediately")
    send_now.add_argument("--force", action="store_true", help="Send even if content hash is unchanged")

    watch = subparsers.add_parser("watch", help="Watch semana_actual.md and send on changes")
    watch.add_argument("--interval", type=int, default=30, help="Polling interval in seconds")
    return parser.parse_args()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_config() -> dict[str, str]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Missing Telegram config at {CONFIG_PATH}. Create it from telegram/bot_config.yaml.example"
        )
    data = load_yaml(CONFIG_PATH).get("telegram", {})
    bot_token = str(data.get("bot_token") or "").strip()
    chat_id = str(data.get("chat_id") or "").strip()
    caption_prefix = str(data.get("caption_prefix") or "Running Coach").strip()
    if not bot_token or not chat_id:
        raise ValueError("Telegram config must define bot_token and chat_id")
    return {"bot_token": bot_token, "chat_id": chat_id, "caption_prefix": caption_prefix}


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    with STATE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_state(state: dict[str, Any]) -> None:
    ensure_dir(STATE_PATH.parent)
    with STATE_PATH.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, ensure_ascii=True)
        handle.write("\n")


def parse_table_block(lines: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for index, line in enumerate(lines):
        if index == 1:
            continue
        parts = [cell.strip() for cell in line.strip().strip("|").split("|")]
        rows.append(parts)
    return rows


def build_markdown_table(rows: list[list[str]], styles: dict[str, ParagraphStyle]) -> Table:
    wrapped_rows: list[list[Any]] = []
    for row_index, row in enumerate(rows):
        wrapped_row: list[Any] = []
        for cell in row:
            style = styles["table_header"] if row_index == 0 else styles["table_cell"]
            wrapped_row.append(Paragraph(cell.replace("`", ""), style))
        wrapped_rows.append(wrapped_row)

    col_widths = None
    if rows and len(rows[0]) == 5:
        col_widths = [2.0 * cm, 6.2 * cm, 2.0 * cm, 4.8 * cm, 3.0 * cm]

    table = Table(wrapped_rows, repeatRows=1, colWidths=col_widths)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dddddd")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("LEADING", (0, 0), (-1, -1), 10),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def markdown_to_story(markdown_text: str) -> list[Any]:
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleCenter", parent=styles["Title"], alignment=TA_CENTER, spaceAfter=12)
    h1_style = ParagraphStyle("H1", parent=styles["Heading1"], spaceAfter=10)
    h2_style = ParagraphStyle("H2", parent=styles["Heading2"], spaceAfter=8)
    body_style = ParagraphStyle("Body", parent=styles["BodyText"], leading=14, spaceAfter=6)
    bullet_style = ParagraphStyle("Bullet", parent=styles["BodyText"], leftIndent=14, bulletIndent=0, leading=14, spaceAfter=4)
    code_style = ParagraphStyle("Code", parent=styles["BodyText"], fontName="Courier", leading=12, spaceAfter=6)
    table_header_style = ParagraphStyle("TableHeader", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=8, leading=10)
    table_cell_style = ParagraphStyle("TableCell", parent=styles["BodyText"], fontSize=8, leading=10)

    style_map = {
        "table_header": table_header_style,
        "table_cell": table_cell_style,
    }

    story: list[Any] = []
    lines = markdown_text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        stripped = line.strip()

        if not stripped:
            story.append(Spacer(1, 0.2 * cm))
            index += 1
            continue

        if stripped.startswith("|"):
            table_lines = [stripped]
            index += 1
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index].strip())
                index += 1
            rows = parse_table_block(table_lines)
            table = build_markdown_table(rows, style_map)
            story.append(table)
            story.append(Spacer(1, 0.25 * cm))
            continue

        if stripped.startswith("# "):
            story.append(Paragraph(stripped[2:], title_style))
            index += 1
            continue

        if stripped.startswith("## "):
            story.append(Paragraph(stripped[3:], h1_style))
            index += 1
            continue

        if stripped.startswith("### "):
            story.append(Paragraph(stripped[4:], h2_style))
            index += 1
            continue

        if stripped.startswith("- "):
            story.append(Paragraph(f"• {stripped[2:]}", bullet_style))
            index += 1
            continue

        if stripped[:2].isdigit() and stripped[1:3] == ". ":
            story.append(Paragraph(stripped, bullet_style))
            index += 1
            continue

        if stripped.startswith("```"):
            code_lines: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code_lines.append(lines[index].rstrip())
                index += 1
            story.append(Preformatted("\n".join(code_lines), code_style))
            index += 1
            continue

        story.append(Paragraph(stripped.replace("`", ""), body_style))
        index += 1

    return story


def build_pdf(source_path: Path, output_path: Path) -> None:
    ensure_dir(output_path.parent)
    markdown_text = source_path.read_text(encoding="utf-8")
    story = markdown_to_story(markdown_text)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title="semana_actual",
    )
    doc.build(story)


def telegram_caption(caption_prefix: str) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"{caption_prefix}: semana_actual.pdf ({timestamp})"


def send_pdf_via_telegram(pdf_path: Path, config: dict[str, str]) -> None:
    command = [
        "curl",
        "-sS",
        "-X",
        "POST",
        f"https://api.telegram.org/bot{config['bot_token']}/sendDocument",
        "-F",
        f"chat_id={config['chat_id']}",
        "-F",
        f"caption={telegram_caption(config['caption_prefix'])}",
        "-F",
        f"document=@{pdf_path}",
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    response = json.loads(result.stdout)
    if not response.get("ok"):
        raise RuntimeError(f"Telegram API returned failure: {response}")


def send_semana_pdf(force: bool) -> None:
    if not SOURCE_MD.exists():
        raise FileNotFoundError(f"Missing source markdown: {SOURCE_MD}")
    config = load_config()
    current_hash = file_hash(SOURCE_MD)
    state = load_state()
    if not force and state.get("last_hash") == current_hash:
        print("No changes detected in semana_actual.md")
        return
    build_pdf(SOURCE_MD, OUTPUT_PDF)
    send_pdf_via_telegram(OUTPUT_PDF, config)
    state.update(
        {
            "last_hash": current_hash,
            "last_sent_at": datetime.utcnow().isoformat() + "Z",
            "last_pdf": str(OUTPUT_PDF.relative_to(ROOT)),
        }
    )
    save_state(state)
    print(f"Sent {OUTPUT_PDF}")


def watch_semana(interval: int) -> None:
    print(f"Watching {SOURCE_MD} every {interval}s")
    while True:
        try:
            send_semana_pdf(force=False)
        except Exception as exc:
            print(f"Watch iteration failed: {exc}")
        time.sleep(interval)


def main() -> None:
    args = parse_args()
    if args.command == "send-now":
        send_semana_pdf(force=args.force)
        return
    if args.command == "watch":
        watch_semana(interval=args.interval)
        return
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
