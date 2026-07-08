import markdownify
from markdownify import MarkdownConverter
import json
import sys
import re
import csv
import time
import sys
from dotenv import load_dotenv
from pathlib import Path
from bs4 import BeautifulSoup
from loguru import logger
from datetime import datetime, timezone
import anthropic

load_dotenv()
client = anthropic.Anthropic()

DATE_IN_FILENAME = re.compile(r'\d{4}-\d{2}-\d{2}|'
                              r'\d{8}(?!\d)|'
                              r'\d{4}年\d{1,2}月\d{1,2}日'
                              )


class OneNoteMarkdownConverter(MarkdownConverter):
    def convert_style(self, el, text, **kwargs):
        """ This function is opended for the customized markdownfication when needed."""
        return ""


def _normalize_date(dt_str: str):
    if not dt_str:
        return ""
    if 'T' in dt_str:
        return dt_str.split('T')[0]
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', dt_str):
        return dt_str
    if re.fullmatch(r'\d{8}', dt_str):
        return f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:8]}"
    m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', dt_str)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return dt_str


def _classify_note_type(filename: str):
    return 'daily_log' if DATE_IN_FILENAME.search(filename) else 'knowledge_summary'


def _try_promote(soup, li, heading_level):
    """Promote a li with nested ol to a heading tag in-place."""
    if heading_level > 3:
        return

    child_ol = li.find('ol', recursive=False)
    if not child_ol:
        return

    child_ol.extract()
    heading_text = li.get_text(strip=True)

    if not heading_text:
        li.append(child_ol)
        return

    h_tag = soup.new_tag(f'h{heading_level}')
    h_tag.string = heading_text
    li.replace_with(h_tag)
    h_tag.insert_after(child_ol)

    for sub_li in list(child_ol.find_all('li', recursive=False)):
        _try_promote(soup, sub_li, heading_level + 1)


def promote_list_headings(soup):
    """Convert outermost ol>li-with-children to h2/h3 heading structure."""
    body = soup.find('body')
    if not body:
        return

    # OneNote exports wrap content in body>div — handle both body and body>div
    containers = [body] + list(body.find_all('div', recursive=False))
    for container in containers:
        for top_ol in list(container.find_all('ol', recursive=False)):
            for li in list(top_ol.find_all('li', recursive=False)):
                _try_promote(soup, li, heading_level=2)


def _html_to_md(html: str) -> OneNoteMarkdownConverter:
    soup = BeautifulSoup(html, "html.parser")
    for img in soup.find_all("img"):
        if img.get("alt"):
            img["alt"] = " ".join(img["alt"].split())
    promote_list_headings(soup)
    # with open("output.html", "w", encoding="utf-8") as f:
    #     f.write(str(soup))
    return OneNoteMarkdownConverter(heading_style="ATX",
                                    bullets="-",
                                    newline_style="backslash",
                                    ).convert(str(soup))


def extract_llm_fields(title: str, plain_text: str):
    """Ask Claude to extract tags (keywords) and a short alias. Retry on rate limit."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2000,
                messages=[{
                    "role": "user",
                    "content": (
                        "Analyze this note and extract:\n"
                        "1. reshape the hierarchy: Reshape the hierarchy of content bt no changing any original letters,"
                        "   after reshaping, the new content should fitted with the markdown. A good fitness means:"
                        "   (i)標題用 # / ## / ###  (ii)清單用 (iii)圖片、標題、清單之間留空行 (iv) 不要把新元素黏在上一行尾巴。"
                        "2. tags: 5-10 keywords (technical terms; mix Chinese/English to match the note's language)\n"
                        "3. alias: one concise short title (2-6 words, same language as the main title)\n\n"
                        f"Title: {title}\n"
                        f"Content :\n{plain_text}\n\n"
                        'Reply ONLY with valid JSON: {"tags": ["tag1", ...], "alias": "short title", "new_content": "# Here is note header 1..."}'
                    )
                }]
            )
            raw = response.content[0].text
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if not m:
                raise ValueError(f"No JSON in response: {raw!r}")
            return json.loads(m.group())
        except anthropic.RateLimitError as e:
            if attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                time.sleep(wait)
                continue
            raise
        except Exception:
            raise


def load_csv(csv_path: Path) -> list[dict]:
    try:
        with open(csv_path, newline='', encoding='utf-8') as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        logger.error(f"File {csv_path} not existed.")
        raise
    except PermissionError:
        logger.error(f"錯誤：沒有讀取 '{csv_path}' 的權限。")
        raise
    except Exception as e:
        logger.error(f"發生未預期的錯誤：{e}")
        raise


def save_csv(csv_path: Path, rows: list[dict]) -> None:
    if not rows:
        logger.warning(f"No information written to {str(csv_path)}")
        return
    try:
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    except PermissionError:
        logger.error(f"錯誤：沒有寫入 '{str(csv_path)}' 的權限。")
        raise
    except Exception as e:
        logger.error(f"發生未預期的錯誤：{e}")
        raise


def _get_create_date(target_html_path: Path) -> tuple[str, Path, list]:
    """Return tuple of (create_date_str, csv_path, rows) from CSV file containing page's metadata of each section."""
    csv_candidates = list(target_html_path.parent.glob('*_pages_metadata.csv'))
    if not csv_candidates:
        return "", None, []
    csv_path = csv_candidates[0]
    rows = load_csv(csv_path)
    if rows:
        for row in rows:
            if Path(row.get('html_path', '')) == target_html_path:
                create_date_str = _normalize_date(row.get('created_datetime', ''))
                return create_date_str, csv_path, rows
    return "", csv_path, rows


def _update_csv_row(rows: list[dict],
                    html_path: Path,
                    md_path: Path,
                    export_dt: str) -> list[dict]:
    for row in rows:
        if 'markdownExportDateTime' not in row.keys():
            row.setdefault('markdownExportDateTime', '')
        if 'markdown_path' not in row.keys():
            row.setdefault('markdown_path', '')

    html_str = str(html_path)
    for row in rows:
        if row.get('html_path') == html_str:
            row['markdownExportDateTime'] = export_dt
            row['markdown_path'] = str(md_path)
            return rows

    # Page not in CSV yet — append a minimal row
    rows.append({'title': html_path.stem,
                 'created_datetime': '',
                 'modified_datetime': '',
                 'html_path': html_str,
                 'markdownExportDateTime': export_dt,
                 'markdown_path': str(md_path),
                 })
    return rows


def t_html_to_markdown(SELECTED_NOTEBOOK: list[str], EXPORT_DIR: str | Path):
    total_pages = 0
    total_imgs = 0

    for nb_name in SELECTED_NOTEBOOK:
        nb_src = EXPORT_DIR / nb_name if isinstance(EXPORT_DIR, Path) else Path(EXPORT_DIR) / nb_name
        if not nb_src.is_dir():
            logger.error(f"⚠️  Notebook not found: {nb_name}, skip this notebook.")
            continue

        logger.info(f"📓 Founded notebook: {nb_name}")

        for html_path in sorted(nb_src.rglob("*.html")):
            html_path_new = html_path.parent/(html_path.stem+"_直接跑llm_haiku")
            md_path = html_path_new.with_suffix(".md")

            html_content = html_path.read_text(encoding="utf-8")
            plain_text = BeautifulSoup(html_content, "html.parser").get_text(' ', strip=True)

            # Calling LLM for Keyword Extraction
            try:
                llm = extract_llm_fields(html_path.stem, plain_text)
                tags = llm.get('tags', [])
                alias = llm.get('alias', html_path.stem)
                md_body = llm.get('new_content', plain_text)
            except Exception as e:
                logger.warning(f"  ⚠️  LLM extraction failed: {e}")
                tags, alias = [], html_path.stem

            tags_yaml = '\n'.join(f'  - "{t}"' for t in tags)

            # Read from metadata csv file
            create_date, csv_path, csv_rows = _get_create_date(html_path)
            note_type = _classify_note_type(html_path.stem)
            frontmatter = ("---\n"
                           f"tags:\n{tags_yaml}\n"
                           f'date: "{create_date}"\n'
                           f"type: {note_type}\n"
                           f'alias: "{alias}"\n'
                           "---\n\n"
                           )

            # Concatenate and save final content of .md file
            # md_body = _html_to_md(html_content)
            export_dt = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            md_path.write_text(frontmatter + md_body, encoding="utf-8")

            # update metadata by adding info of .md file
            if csv_path:
                new_csv_rows = _update_csv_row(csv_rows, html_path, md_path, export_dt)
                save_csv(csv_path, new_csv_rows)

            # briefly summarize the processing status
            img_count = md_body.count("![")
            total_imgs += img_count
            total_pages += 1
            logger.info(
                f"Notebook Section [{html_path.parent.name}]: {html_path.stem}.md (with {img_count} imgs, {note_type})")

            # Short delay to avoid hitting API rate limits 429
            time.sleep(0.5)

    logger.success(f"✅ Done — {total_pages} pages, {total_imgs} image refs")
    logger.success(f"Output to: {nb_src}")


if __name__ == "__main__":

    EXPORT_DIR = Path("/Users/little_po/Desktop/Obsidian/OneNote-Export")
    SELECTED = ["生技製劑筆記本/法規"]
    t_html_to_markdown(SELECTED, EXPORT_DIR)
