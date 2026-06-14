from .utils.audit_log import log_llm_call, log_page_conversion, _now_utc
from markdownify import MarkdownConverter
import os
import re
import csv
import sys
import time
import uuid
from dotenv import load_dotenv
from pathlib import Path
from bs4 import BeautifulSoup
from loguru import logger
from datetime import datetime, timezone
from google import genai
from google.genai import types
from google.oauth2.service_account import Credentials

load_dotenv()

# ── GEMINI MODEL 常數 ──────────────────────────────────────────────────────────
RESHAPE_MODEL = "gemini-2.5-flash-lite"

gemini_response_schema = {'type': 'object',
                          'title': 'NoteAnalysisResult',
                          'properties': {
                              'tags': {
                                  'type': 'array',
                                  'items': {'type': 'string'},
                                  'description': '5-10 keywords (technical terms; mix Chinese/English)'
                              },
                              'alias': {
                                  'type': 'string',
                                  'description': 'one concise short title (2-6 words, same language as the main title)'
                              },
                              'new_content': {
                                  'type': 'string',
                                  'description': 'Reshaped content fitted with Markdown hierarchy. (i) Use #/##/### (ii) Use lists (iii) Keep blank lines between elements (iv) Do not stick new elements to the end of the previous line.'
                              }
                          },
                          'required': ['tags', 'alias', 'new_content']
                          }


def _get_genai_client() -> genai.Client:
    """
        初始化 google-genai client。
    """
    json_path = os.getenv("AGENT_PLATFORM_USER_CREDENTIALS")
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    credentials = Credentials.from_service_account_file(json_path, scopes=scopes)

    project = os.getenv("GCP_PROJECT_ID")
    location = "us-central1"
    if not project or not credentials:
        raise EnvironmentError(
            "找不到 GCP_PROJECT_ID / AGENT_PLATFORM_USER_CREDENTIALS ，請確認已設定在 .env 或 secret managers 中。"
        )
    return genai.Client(vertexai=True,
                        project=project,
                        location=location,
                        credentials=credentials)


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
    DATE_IN_FILENAME = re.compile(r'\d{4}-\d{2}-\d{2}|'
                                  r'\d{8}(?!\d)|'
                                  r'\d{4}年\d{1,2}月\d{1,2}日'
                                  )

    return 'daily_log' if DATE_IN_FILENAME.search(filename) else 'knowledge_summary'


def extract_llm_fields(html_path: Path, plain_text: str, session_id: str):
    """Ask Gemini to reshape content and extract tags/alias. Retry on rate limit."""
    max_retries = 3

    prompts = f"""Analyze this note and extract:
                    1. reshape the hierarchy: Reshape the hierarchy of content but no changing any original letters, after reshaping, the new content should fitted with the markdown. A good fitness means:
                        (i) 標題用 # / ## / ###
                        (ii) 清單用 - 或 *
                        (iii) 圖片、標題、清單之間留空行
                        (iv) 不要把新元素黏在上一行尾巴
                        (v) 如文章中有「詞彙(terminology)定義」、「參考資料連結」或「參考資料文件名稱」，把他們移到整篇文章的前面，當作前言，然後才排序其他主文標題。
                        (vi) 如果遇到![]()這樣的文字，代表它是使用者事先清理過後與 markdown 語法相容的圖片link，**請不要隨意移出他原本所屬的章節，但可以調整縮排，也可以生成簡易3-5行圖片概述(並且標注此段為「AI生成圖釋」)**。
                    2. tags: 5-10 keywords (technical terms; mix Chinese/English to match the note's language)
                    3. alias: one concise short title (2-6 words, same language as the main title)

                    Title: {html_path.stem}
                    Content:
                    {plain_text}
                """

    for attempt in range(max_retries):
        t0 = time.perf_counter()
        try:
            client = _get_genai_client()
            logger.info(f"Calling Model: {RESHAPE_MODEL}...")
            response = client.models.generate_content(model=RESHAPE_MODEL,
                                                      contents=prompts,
                                                      config=types.GenerateContentConfig(
                                                          temperature=0.2,   # 調低變異度，讓結構化擷取更穩定
                                                          response_mime_type='application/json',
                                                          response_json_schema=gemini_response_schema,
                                                      ),
                                                      )

            # Fetch result，response.parse returns a Python Dict
            raw = response.parsed
            if not raw:
                raise ValueError(f"No JSON in response: {raw}")

            # Tracking TPM to avoid exceeding rate-limit
            input_tokens = response.usage_metadata.prompt_token_count       # input

            # Record the detail for billing profiling when needed
            output_tokens = response.usage_metadata.candidates_token_count  # output
            thinking_tokens = response.usage_metadata.thoughts_token_count  # reasoning
            total_used = response.usage_metadata.total_token_count          # input + output + reasoning = total
            logger.debug(f"input_tokens {input_tokens} + output_tokens {output_tokens} "
                         f"+ thinking_tokens {thinking_tokens} = {total_used} total tokens")

            # Write in log
            log_llm_call(session_id=session_id,
                         model=RESHAPE_MODEL,
                         html_path=str(html_path),
                         attempt=attempt+1,
                         status="successed",
                         latency_ms=int((time.perf_counter() - t0) * 1000),
                         input_tokens=input_tokens,
                         output_tokens=output_tokens,
                         thinking_tokens=thinking_tokens,
                         error_msg=None,
                         application=Path(__file__).resolve().name,
                         )
            return raw
        except Exception as e:
            log_llm_call(session_id=session_id,
                         model=RESHAPE_MODEL,
                         html_path=str(html_path),
                         attempt=attempt+1,
                         status="failed",
                         latency_ms=int((time.perf_counter() - t0) * 1000),
                         input_tokens=None,
                         output_tokens=None,
                         thinking_tokens=None,
                         error_msg=str(e),
                         application=Path(__file__).resolve().name,
                         )
            logger.warning(f'error on calling {RESHAPE_MODEL}: {e}, retry for {attempt} attempts.')
            continue


def load_csv(csv_path: Path) -> list[dict]:
    try:
        with open(csv_path, newline='', encoding='utf-8') as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        logger.error(f"File {csv_path} not existed.")
        raise
    except PermissionError:
        logger.error(f"Error: No permission to read '{csv_path}'")
        raise
    except Exception as e:
        logger.error(f"Error: Unexpected error, msg: {e}")
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
        logger.error(f"Error: No permission to write '{csv_path}'")
        raise
    except Exception as e:
        logger.error(f"Error: Unexpected error, msg: {e}")
        raise


def _get_create_date(target_html_path: Path) -> tuple[str, Path, list]:
    """Return tuple of (create_date_str, csv_path, rows) from CSV file 
    containing page's metadata of each section.
    """
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


def convert_img_tag_to_md_str(html_content: str) -> BeautifulSoup:
    soup = BeautifulSoup(html_content, "html.parser")

    for img in soup.find_all("img"):
        alt = " ".join(img.get("alt", "").split()) or "image"
        src = img.get("src", "")
        img.replace_with(f"\n![{alt}]({src})\n")  # Convert to markdown string
    return soup


def t_html_to_markdown(SELECTED_NOTEBOOK: list[str], EXPORT_DIR: str | Path) -> list[dict]:
    """Transform HTML pages to markdown content. Returns a list of page dicts for the Load step."""
    session_id = uuid.uuid4().hex
    pages = []

    for nb_name in SELECTED_NOTEBOOK:
        nb_src = EXPORT_DIR / nb_name if isinstance(EXPORT_DIR, Path) else Path(EXPORT_DIR) / nb_name
        if not nb_src.is_dir():
            logger.error(f"⚠️  Notebook not found: {nb_name}, skip this notebook.")
            continue

        logger.info(f"📓 Founded notebook: {nb_name}")
        for html_path in sorted(nb_src.rglob("*.html")):
            md_path = html_path.with_suffix(".md")
            page_status = "successed"
            page_error = None

            html_content = html_path.read_text(encoding="utf-8")
            img_count = len(BeautifulSoup(html_content, "html.parser").find_all("img"))

            soup = convert_img_tag_to_md_str(html_content)
            plain_text = soup.get_text(' ', strip=True)

            try:
                llm = extract_llm_fields(html_path, plain_text, session_id)
                tags = llm.get('tags', [])
                alias = llm.get('alias', html_path.stem)
                md_body = llm.get('new_content', plain_text)
            except Exception as e:
                logger.warning(f"  ⚠️  LLM extraction failed: {e}")
                tags, alias, md_body = [], html_path.stem, plain_text
                page_status = "upstream_task_failed"
                page_error = str(e)

            tags_yaml = '\n'.join(f'  - "{t}"' for t in tags)
            create_date, csv_path, csv_rows = _get_create_date(html_path)
            note_type = _classify_note_type(html_path.stem)
            frontmatter = ("---\n"
                           f"tags:\n{tags_yaml}\n"
                           f'date: "{create_date}"\n'
                           f"type: {note_type}\n"
                           f'alias: "{alias}"\n'
                           "---\n\n"
                           )

            pages.append({"session_id": session_id,
                          "notebook": nb_name,
                          "section": html_path.parent.name,
                          "page_title": html_path.stem,
                          "html_path": html_path,
                          "md_path": md_path,
                          "content": frontmatter + md_body,
                          "csv_path": csv_path,
                          "csv_rows": csv_rows,
                          "note_type": note_type,
                          "img_count": img_count,
                          "page_status": page_status,
                          "page_error": page_error,
                          "export_dt": _now_utc(),
                          })

            logger.info(
                f"Notebook Section [{html_path.parent.name}]: {html_path.stem}.md (with {img_count} imgs, {note_type})")

            time.sleep(0.5)

    return pages
