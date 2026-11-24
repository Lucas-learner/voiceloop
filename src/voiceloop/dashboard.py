"""Obsidian Knowledge Base & Visual Dashboard for VoiceLoop.

Parses valid session minutes and generates:
1. `00_纪要看板.md` (Obsidian-native Markdown Dashboard with MOC, Callouts, and Mermaid charts)
2. `dashboard.html` (Standalone, zero-dependency, modern visual HTML Dashboard with live search and category tabs)
3. Optional synced-note frontmatter enrichment so existing notes in `sync_dir` gain YAML frontmatter
   and backlinks to `[[00_纪要看板]]`.
"""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any

from .sessions import atomic_write, load_index, weekly_membership

# Categories
CATEGORY_INVESTMENT = "尽调与路演"
CATEGORY_ACADEMIC = "课程与学术"
CATEGORY_MEETING = "会议与协作"
CATEGORY_DAILY = "日常与其他"
VALID_CATEGORIES = [CATEGORY_INVESTMENT, CATEGORY_ACADEMIC, CATEGORY_MEETING, CATEGORY_DAILY]

# Patterns for empty / accidental recordings
_EMPTY_TOPIC_OR_FOLDER_PATTERN = re.compile(
    r"无有效内容|无实质内容|无有效信息|空白录音|空白音频|误触|无对话内容|无内容|转录.*为空|转录内容未提供"
)

# Patterns for placeholder lines in action items, questions, and decisions
_PLACEHOLDER_REGEX = re.compile(
    r"^([（(]?\s*(不适用|无|暂无|未提及|无明确|无特殊|本对话为.*无|无当场|无实质|无具体|无待办|无决策|待定|无讨论|暂无内容|无。?)[)）]?|"
    r"[（(].*不适用.*[)）]|[（(].*无.*决策.*[)）]|[（(].*无.*待办.*[)）]|暂无内容|无。?)$",
    re.IGNORECASE,
)

# Known entity and technology keywords for heuristic extraction
_KNOWN_ENTITIES = [
    "DeepSeek", "OPPO", "Apple", "OpenAI", "Google", "Microsoft", "Meta",
    "Tencent", "ByteDance", "腾讯", "阿里", "字节", "百度", "英伟达", "NVIDIA",
    "Lumos", "Loki", "Pulsebomb", "Flash Attention", "Transformer", "Agent",
    "LLM", "RAG", "MLX", "Metal", "Python", "PyTorch", "vLLM", "FastAPI",
    "商业分析", "统计学", "机器学习", "深度学习", "强化学习", "大语言模型", "机器人",
    "算力", "芯片", "半导体", "投行", "创投", "量化投资", "一级市场", "二级市场",
]


def _is_placeholder(line: str) -> bool:
    """Return True if line is a placeholder like '（本对话为课堂讲授，无当场决策）' or '暂无内容'."""
    text = line.strip()
    if not text:
        return True

    # Strip bullets/checkboxes/callout markers
    cleaned = re.sub(r"^(?:-\s*\[[ xX]\]\s*|-\s*|\*\s*|\d+[.)]\s*|>\s*)", "", text).strip()
    if not cleaned:
        return True

    # Colon-ending section headers or lead-in prompts (e.g. "高置信度待验证：", "中/低置信度：")
    if cleaned.endswith((":", "：")):
        return True

    # Non-actionable remarks or disclaimer phrases
    for disclaim in (
        "非明确分工的正式行动项",
        "非正式行动项",
        "属于挑战陈述而非明确待议问题",
        "非强制分配",
        "非明确分工",
    ):
        if disclaim in cleaned:
            return True

    # Common exact or short placeholders
    if cleaned in ("无", "无。", "暂无内容", "暂无", "不适用", "未提及", "待定", "无待办", "无决策", "无未解决问题"):
        return True

    # Chinese/English parentheses wrapping
    if (cleaned.startswith("（") and cleaned.endswith("）")) or (cleaned.startswith("(") and cleaned.endswith(")")):
        return True

    # Check for prefix or substring matches
    for prefix in ("不适用", "无明确", "暂无", "未提及", "无特殊", "本对话为", "无当场", "无实质", "无具体", "无待办", "无决策", "无讨论"):
        if cleaned.startswith(prefix):
            return True

    if "不适用" in cleaned or "无明确分配" in cleaned or "暂无内容" in cleaned or "无当场决策" in cleaned:
        return True

    return False


def classify_category(scene: str, topic: str, content: str = "", declared_category: str | None = None) -> str:
    """Classify dialogue into one of 4 categories: 尽调与路演, 课程与学术, 会议与协作, 日常与其他."""
    # 1. declared_category check
    if declared_category and declared_category in VALID_CATEGORIES:
        return declared_category
    if declared_category:
        for cat in VALID_CATEGORIES:
            if cat in declared_category or declared_category in cat:
                return cat

    text_header = f"{scene} {topic}".lower()
    text_full = f"{scene} {topic} {content}".lower()

    # 2. Priority 1: Direct strong header matches
    # A. 尽调与路演 header 词
    if any(k in text_header for k in ("路演", "尽调", "融资", "创投", "商业模式", "估值", "标的", "ts", "bp")):
        return CATEGORY_INVESTMENT

    # B. 课程与学术 header 词（含 课堂、课程、授课、讲授 等，不含泛词“分享”）
    academic_header_kws = (
        "课堂", "课程", "授课", "讲授", "复习", "考试", "讲座", "求职", "实习",
        "学术", "论文", "校友", "书院", "导师", "大作业", "答疑", "期中", "期末",
    )
    if any(k in text_header for k in academic_header_kws):
        return CATEGORY_ACADEMIC

    # C. 会议与协作 header 词（注意排除“非会议”后再匹配“会议”）
    clean_meeting_header = re.sub(r"非会议|并非会议|不是会议|无会议", "", text_header)
    meeting_header_kws = ("会议", "周会", "工作安排", "站会", "复盘", "协议审阅", "内部沟通", "工作会")
    if any(k in clean_meeting_header for k in meeting_header_kws):
        return CATEGORY_MEETING

    # D. 日常与其他 header 词
    daily_keywords = ("闲聊", "亲子", "家庭", "日常", "演唱会", "音乐现场", "演唱", "歌词", "播报", "收款")
    if any(k in text_header for k in daily_keywords):
        return CATEGORY_DAILY

    # 3. Priority 2: Keyword scoring fallback
    scores = {
        CATEGORY_INVESTMENT: 0,
        CATEGORY_ACADEMIC: 0,
        CATEGORY_MEETING: 0,
        CATEGORY_DAILY: 0,
    }

    investment_kws = ["路演", "尽调", "融资", "投资", "商业模式", "公司概况", "估值", "创投", "项目演示", "标的", "商业计划", "创始人", "机构调研", "投资者", "bp", "ts", "券商"]
    academic_kws = ["课堂", "课程", "授课", "复习", "考试", "讲座", "求职", "实习", "校友", "书院", "学术", "论文", "报告修改", "导师", "挑战赛", "作业", "知识点", "方法框架", "考研", "期末", "教学", "商学院"]
    meeting_kws = ["会议", "指导", "工作安排", "协议审阅", "讨论", "周会", "内部", "站会", "复盘", "决策", "评审", "研讨", "工作会", "协作"]
    daily_kws = ["闲聊", "亲子", "家庭", "日常", "演唱会", "音乐现场", "演唱", "歌词", "播报", "收款", "游戏"]

    clean_meeting_full = re.sub(r"非会议|并非会议|不是会议|无会议", "", text_full)

    for kw in investment_kws:
        if kw in text_header:
            scores[CATEGORY_INVESTMENT] += 3
        elif kw in text_full:
            scores[CATEGORY_INVESTMENT] += 1

    for kw in academic_kws:
        if kw in text_header:
            scores[CATEGORY_ACADEMIC] += 3
        elif kw in text_full:
            scores[CATEGORY_ACADEMIC] += 1

    for kw in meeting_kws:
        if kw in clean_meeting_header:
            scores[CATEGORY_MEETING] += 3
        elif kw in clean_meeting_full:
            scores[CATEGORY_MEETING] += 1

    for kw in daily_kws:
        if kw in text_header:
            scores[CATEGORY_DAILY] += 3
        elif kw in text_full:
            scores[CATEGORY_DAILY] += 1

    best_cat = max(scores, key=lambda k: scores[k])
    if scores[best_cat] > 0:
        return best_cat
    return CATEGORY_DAILY


def format_duration(seconds: float | None) -> str:
    """Format duration seconds into human readable Chinese duration string."""
    if seconds is None or seconds <= 0:
        return "—"
    sec = int(round(seconds))
    if sec >= 3600:
        hours = sec // 3600
        mins = (sec % 3600) // 60
        return f"{hours}小时{mins}分"
    if sec >= 60:
        mins = sec // 60
        remainder = sec % 60
        return f"{mins}分{remainder}秒" if remainder > 0 else f"{mins}分钟"
    return f"{sec}秒"


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Extract YAML frontmatter if present at the top of content, returning (data, body)."""
    match = re.match(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n(.*)$", content, re.DOTALL)
    if not match:
        return {}, content

    yaml_block = match.group(1)
    body = match.group(2)

    try:
        import yaml
        parsed = yaml.safe_load(yaml_block)
        if isinstance(parsed, dict):
            return parsed, body
    except Exception:
        pass

    # Simple regex fallback if PyYAML is absent or fails
    fallback_data: dict[str, Any] = {}
    for line in yaml_block.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip().strip("\"'")
            if val.startswith("[") and val.endswith("]"):
                fallback_data[key] = [v.strip().strip("\"'") for v in val[1:-1].split(",") if v.strip()]
            else:
                fallback_data[key] = val
    return fallback_data, body


def parse_note(md_path: Path, folder_name: str, session_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Parse a single meeting note file into a structured dictionary."""
    content = md_path.read_text(encoding="utf-8")
    meta = session_meta or {}

    frontmatter, body = parse_frontmatter(content)

    # 1. Date
    date_str = ""
    if frontmatter.get("date"):
        val = str(frontmatter["date"]).strip()
        date_str = val[:10] if len(val) >= 10 else val
    elif meta.get("start"):
        try:
            date_str = datetime.fromisoformat(meta["start"]).strftime("%Y-%m-%d")
        except Exception:
            pass
    if not date_str:
        day_match = re.match(r"^(\d{4})(\d{2})(\d{2})", folder_name)
        if day_match:
            date_str = f"{day_match.group(1)}-{day_match.group(2)}-{day_match.group(3)}"

    # 2. Extract sections from markdown body
    # Split by ## headings
    sections: dict[str, str] = {}
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in body.splitlines():
        heading_match = re.match(r"^##\s+(.+)$", line.strip())
        if heading_match:
            if current_heading:
                sections[current_heading] = "\n".join(current_lines).strip()
            current_heading = heading_match.group(1).strip()
            current_lines = []
        elif current_heading is not None:
            current_lines.append(line)

    if current_heading:
        sections[current_heading] = "\n".join(current_lines).strip()

    # 3. Topic
    topic = ""
    if frontmatter.get("title"):
        topic = str(frontmatter["title"]).strip()
    elif "主题" in sections and sections["主题"]:
        topic = sections["主题"].splitlines()[0].strip()
    if not topic:
        folder_match = re.match(r"^\d{8}_(.+)$", folder_name)
        topic = folder_match.group(1) if folder_match else folder_name
    topic = re.sub(r"\[\[(.*?)\]\]", r"\1", topic).strip().strip("`*\"'")

    # 4. Scene
    scene = ""
    if frontmatter.get("scene"):
        scene = str(frontmatter["scene"]).strip()
    elif "场景" in sections and sections["场景"]:
        scene = sections["场景"].splitlines()[0].strip()
    if not scene:
        scene = "未指定场景"

    # 5. Category
    declared_category = frontmatter.get("category")
    category = classify_category(scene, topic, body, declared_category=declared_category)

    # 6. Participants
    participants = ""
    for k in ("参与方 / 访谈对象", "参与方", "访谈对象"):
        if k in sections and sections[k]:
            participants = sections[k].strip()
            break

    # 7. Summary
    raw_summary = ""
    for k in ("核心摘要", "摘要"):
        if k in sections and sections[k]:
            raw_summary = sections[k].strip()
            break

    # Strip callout syntax: > [!summary] 核心结论与摘要, > ...
    summary_lines = []
    for s_line in raw_summary.splitlines():
        s_line = s_line.strip()
        if re.match(r"^>\s*\[!summary\]", s_line, re.IGNORECASE):
            continue
        if s_line.startswith(">"):
            s_line = s_line[1:].strip()
        if s_line:
            summary_lines.append(s_line)
    clean_summary = "\n".join(summary_lines).strip()
    if not clean_summary and body:
        # Fallback: first 3 non-empty, non-heading lines of body
        fallback_lines = []
        for line in body.splitlines():
            line_s = line.strip()
            if line_s and not line_s.startswith(("#", "-", ">", "```", "---")):
                fallback_lines.append(line_s)
                if len(fallback_lines) >= 3:
                    break
        clean_summary = "\n".join(fallback_lines)

    # 8. Key facts
    facts: list[str] = []
    for k in ("关键事实与数据", "事实与数据"):
        if k in sections and sections[k]:
            for line in sections[k].splitlines():
                if not _is_placeholder(line):
                    item = re.sub(r"^(?:-\s*|\*\s*|\d+[.)]\s*)", "", line.strip()).strip()
                    if item:
                        facts.append(item)
            break

    # 9. Decisions
    decisions: list[str] = []
    if "决策" in sections and sections["决策"]:
        for line in sections["决策"].splitlines():
            if not _is_placeholder(line):
                item = re.sub(r"^(?:-\s*|\*\s*|\d+[.)]\s*)", "", line.strip()).strip()
                if item:
                    decisions.append(item)

    # 10. Todos
    todos: list[str] = []
    if "待办" in sections and sections["待办"]:
        for line in sections["待办"].splitlines():
            if not _is_placeholder(line):
                item = re.sub(r"^(?:-\s*\[[ xX]\]|-\s*|\*\s*|\d+[.)]\s*)", "", line.strip()).strip()
                if item:
                    todos.append(item)

    # 11. Questions & Doubts
    questions: list[str] = []
    for k in ("未解决问题", "存疑点 / 待验证事项", "存疑点", "待验证事项"):
        if k in sections and sections[k]:
            for line in sections[k].splitlines():
                if re.match(r"^>\s*\[!warning\]", line.strip(), re.IGNORECASE):
                    continue
                if line.strip().startswith(">"):
                    line = line.strip()[1:].strip()
                if not _is_placeholder(line):
                    item = re.sub(r"^(?:-\s*|\*\s*|\d+[.)]\s*|\?\s*|❓\s*)", "", line.strip()).strip()
                    if item:
                        questions.append(item)

    # 12. Mermaid Visual Flowchart
    mermaid_block: str | None = None
    mermaid_match = re.search(r"```mermaid\s*\r?\n(.*?)\r?\n```", content, re.DOTALL)
    if mermaid_match:
        mermaid_block = mermaid_match.group(1).strip()

    # 13. Tags & Entities
    tags_set: set[str] = set()
    entities_set: set[str] = set()

    # From frontmatter
    fm_tags = frontmatter.get("tags")
    if isinstance(fm_tags, list):
        tags_set.update(str(t).strip() for t in fm_tags if t)
    elif isinstance(fm_tags, str):
        tags_set.update(t.strip() for t in fm_tags.split(",") if t.strip())

    fm_entities = frontmatter.get("entities")
    if isinstance(fm_entities, list):
        entities_set.update(str(e).strip() for e in fm_entities if e)
    elif isinstance(fm_entities, str):
        entities_set.update(e.strip() for e in fm_entities.split(",") if e.strip())

    # From WikiLinks [[...]] in content
    for link in re.findall(r"\[\[(.*?)\]\]", content):
        clean_link = link.split("|")[0].strip()
        if clean_link and clean_link != "00_纪要看板" and clean_link != folder_name and clean_link != topic:
            if any(term in clean_link for term in ("看板", "目录", "首页")):
                continue
            entities_set.add(clean_link)

    # Heuristic entities
    search_target = f"{topic} {scene} {clean_summary}"
    for ke in _KNOWN_ENTITIES:
        if ke in search_target:
            entities_set.add(ke)

    tags_set.add("voiceloop")
    tags_set.add(category)

    duration = meta.get("duration")
    duration_str = format_duration(duration)
    part_count = int(meta.get("part_count") or 1)

    return {
        "folder_name": folder_name,
        "file_path": str(md_path),
        "date": date_str,
        "topic": topic,
        "scene": scene,
        "category": category,
        "participants": participants,
        "summary": clean_summary,
        "facts": facts,
        "decisions": decisions,
        "todos": todos,
        "questions": questions,
        "tags": sorted(tags_set),
        "entities": sorted(entities_set),
        "mermaid": mermaid_block,
        "duration": duration,
        "duration_str": duration_str,
        "part_count": part_count,
    }


def _archive_superseded_cloud_note(sync_dir: Path | None, folder_name: str) -> None:
    if not sync_dir or not sync_dir.is_dir():
        return
    stale = sync_dir / f"{folder_name}.md"
    if stale.is_file():
        archive = sync_dir / ".voiceloop-superseded"
        archive.mkdir(exist_ok=True)
        dest = archive / stale.name
        if dest.exists():
            import uuid
            dest = archive / f"{stale.stem}_{uuid.uuid4().hex[:8]}.md"
        try:
            stale.replace(dest)
        except OSError:
            pass


def collect_valid_notes(data_dir: Path, sync_dir: Path | None = None) -> list[dict[str, Any]]:
    """Scan data_dir for valid recording notes, excluding superseded and empty sessions."""
    if not data_dir.exists():
        return []

    state = load_index(data_dir)
    superseded, session_days = weekly_membership(data_dir)

    notes: list[dict[str, Any]] = []

    for folder in data_dir.iterdir():
        if not folder.is_dir() or folder.name.startswith((".", "tmp_")):
            continue
        if folder.name in superseded:
            continue

        day_match = re.match(r"^(\d{8})_(.+)$", folder.name)
        if not day_match:
            continue

        # Exclude folders that match empty keywords
        if _EMPTY_TOPIC_OR_FOLDER_PATTERN.search(folder.name):
            _archive_superseded_cloud_note(sync_dir, folder.name)
            continue

        # Check sessions.json status if available
        session_info = state.get("sessions", {}).get(folder.name)
        if session_info and not session_info.get("has_content", True):
            _archive_superseded_cloud_note(sync_dir, folder.name)
            continue

        # Locate note markdown
        candidates = [folder / f"{folder.name}.md", folder / "meeting.md"]
        note_file = next((p for p in candidates if p.is_file()), None)
        if not note_file:
            continue

        # Assemble session metadata
        session_meta: dict[str, Any] = {
            "start": session_days.get(folder.name),
            "duration": None,
            "part_count": 1,
        }
        if session_info:
            members = session_info.get("members", [])
            session_meta["part_count"] = len(members) if members else 1
            total_dur = 0.0
            first_start = None
            for rid in members:
                rec = state.get("recordings", {}).get(rid, {})
                dur = rec.get("duration")
                if dur:
                    try:
                        total_dur += float(dur)
                    except (ValueError, TypeError):
                        pass
                if not first_start and rec.get("start"):
                    first_start = rec.get("start")
            session_meta["duration"] = total_dur if total_dur > 0 else None
            if first_start:
                session_meta["start"] = first_start

        parsed = parse_note(note_file, folder.name, session_meta)

        # 1. Double check topic for empty/accidental markers
        if _EMPTY_TOPIC_OR_FOLDER_PATTERN.search(parsed["topic"]):
            _archive_superseded_cloud_note(sync_dir, folder.name)
            continue

        summary = parsed["summary"].strip()
        topic = parsed["topic"].strip()
        scene = parsed["scene"].strip()

        # 2. Skip empty / trivial fragment recordings
        if not summary:
            _archive_superseded_cloud_note(sync_dir, folder.name)
            continue
        if summary == topic and not parsed["facts"] and not parsed["todos"]:
            _archive_superseded_cloud_note(sync_dir, folder.name)
            continue

        # 3. Skip accidental/environmental noise recordings (e.g. transit announcements, cashier prompts)
        if any(kw in summary for kw in ("无有效纪要信息", "公共交通语音播报")) or any(kw in scene for kw in ("无有效纪要信息", "公共交通语音播报")):
            _archive_superseded_cloud_note(sync_dir, folder.name)
            continue

        notes.append(parsed)

    # Sort descending by date, then folder name
    notes.sort(key=lambda n: (n["date"], n["folder_name"]), reverse=True)
    return notes


def collect_weekly_files(data_dir: Path, sync_dir: Path | None = None) -> list[dict[str, str]]:
    """Collect all weekly report markdown files from data_dir.parent/weekly and sync_dir."""
    candidates_dirs = [data_dir.parent / "weekly"]
    if sync_dir and sync_dir.exists():
        candidates_dirs.append(sync_dir)

    seen_names: set[str] = set()
    reports: list[dict[str, str]] = []

    for d in candidates_dirs:
        if not d.is_dir():
            continue
        for file in sorted(d.glob("*_weekly_*.md"), reverse=True):
            if file.name in seen_names:
                continue
            seen_names.add(file.name)
            # Example filename: 20261108_weekly_2026W45.md
            match = re.match(r"^(\d{8})_weekly_(.+)\.md$", file.name)
            if match:
                date_part = match.group(1)
                week_label = match.group(2)
                formatted_date = f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:]}"
                display = f"{week_label} 周报 ({formatted_date})"
            else:
                display = file.stem
            reports.append({
                "stem": file.stem,
                "filename": file.name,
                "display": display,
                "path": str(file),
            })

    reports.sort(key=lambda r: r["filename"], reverse=True)
    return reports


def render_obsidian_dashboard(notes: list[dict[str, Any]], weekly_files: list[dict[str, str]]) -> str:
    """Generate 00_纪要看板.md with Obsidian-native MOC, Callouts, and Mermaid diagrams."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Metrics calculation
    total_notes = len(notes)
    total_seconds = sum(n["duration"] for n in notes if n.get("duration"))
    total_duration_str = format_duration(total_seconds if total_seconds > 0 else None)

    cat_counts = {cat: 0 for cat in VALID_CATEGORIES}
    for n in notes:
        c = n["category"]
        if c in cat_counts:
            cat_counts[c] += 1
        else:
            cat_counts[CATEGORY_DAILY] += 1

    all_todos: list[tuple[dict[str, Any], str]] = []
    all_questions: list[tuple[dict[str, Any], str]] = []
    month_counts: dict[str, int] = {}
    all_entities_count: dict[str, int] = {}
    all_tags_count: dict[str, int] = {}

    for n in notes:
        # Keep global action items and questions focused on core work/academic categories
        if n["category"] != CATEGORY_DAILY:
            for t in n["todos"]:
                all_todos.append((n, t))
            for q in n["questions"]:
                all_questions.append((n, q))

        m = n["date"][:7] if len(n["date"]) >= 7 else "未知月份"
        month_counts[m] = month_counts.get(m, 0) + 1

        for ent in n["entities"]:
            all_entities_count[ent] = all_entities_count.get(ent, 0) + 1
        for tag in n["tags"]:
            all_tags_count[tag] = all_tags_count.get(tag, 0) + 1

    lines = [
        "---",
        "title: \"VoiceLoop 语音纪要全局看板\"",
        f"updated: {now_str}",
        "tags:",
        "  - voiceloop",
        "  - dashboard",
        "  - moc",
        "---",
        "",
        "# 🎙️ VoiceLoop 语音知识库看板",
        "",
        "> [!abstract] 知识库导航概览",
        f"> - **纪要总数**：{total_notes} 篇",
        f"> - **累计录音时长**：{total_duration_str}",
        f"> - **场景分类分布**：💼 尽调与路演 ({cat_counts[CATEGORY_INVESTMENT]}) 篇 ｜ 📚 课程与学术 ({cat_counts[CATEGORY_ACADEMIC]}) 篇 ｜ 🤝 会议与协作 ({cat_counts[CATEGORY_MEETING]}) 篇 ｜ 💬 日常与其他 ({cat_counts[CATEGORY_DAILY]}) 篇",
        f"> - **待跟进行动项**：{len(all_todos)} 项",
        f"> - **待验证与存疑问题**：{len(all_questions)} 项",
        "",
        "## 📊 纪要全景可视化",
        "",
        "### 场景分类占比",
        "```mermaid",
        "pie showData",
        "    title 纪要场景分类占比",
    ]

    for cat in VALID_CATEGORIES:
        count = cat_counts[cat]
        lines.append(f'    "{cat}" : {count}')

    lines.extend([
        "```",
        "",
        "### 月度纪要沉淀趋势",
        "| 月份 | 纪要篇数 | 进度条 |",
        "| :--- | :--- | :--- |",
    ])

    sorted_months = sorted(month_counts.keys(), reverse=True)
    if sorted_months:
        max_m = max(month_counts.values()) or 1
        for m in sorted_months:
            c = month_counts[m]
            bar_len = int(round((c / max_m) * 10))
            bar = "█" * max(1, bar_len)
            lines.append(f"| {m} | {c} 篇 | `{bar}` |")
    else:
        lines.append("| 暂无数据 | 0 篇 | — |")

    # Global Todos
    lines.extend([
        "",
        "## ✅ 全局待办与行动项池 (Action Items)",
        "",
    ])
    if all_todos:
        for note, todo in all_todos:
            # Escape pipe in folder/topic for links
            folder_ref = note["folder_name"]
            topic_ref = note["topic"].replace("|", "/")
            lines.append(f"- [ ] {todo} — 来自 [[{folder_ref}|{topic_ref}]] ({note['date']})")
    else:
        lines.append("> *当前暂无未完成待办事项*")

    # Global Open Questions & Verifications
    lines.extend([
        "",
        "## ⚠️ 待验证与未解决问题池 (Open Questions & Verifications)",
        "",
    ])
    if all_questions:
        for note, question in all_questions:
            folder_ref = note["folder_name"]
            topic_ref = note["topic"].replace("|", "/")
            lines.append(f"- ❓ {question} — 来自 [[{folder_ref}|{topic_ref}]] ({note['date']})")
    else:
        lines.append("> *当前暂无待验证事项*")

    # Categorized Knowledge Map
    lines.extend([
        "",
        "## 🗂️ 场景分类索引 (Knowledge Map)",
        "",
    ])

    subsections = [
        (CATEGORY_INVESTMENT, "💼 投资尽调与融资路演"),
        (CATEGORY_ACADEMIC, "📚 课程教学与经验分享"),
        (CATEGORY_MEETING, "🤝 会议决策与工作协作"),
        (CATEGORY_DAILY, "💬 日常沟通与灵感记录"),
    ]

    for cat_key, sub_title in subsections:
        cat_notes = [n for n in notes if n["category"] == cat_key]
        lines.extend([
            f"### {sub_title}",
            "",
            "| 日期 | 纪要主题 (双链) | 细分场景 | 核心摘要速览 |",
            "| :--- | :--- | :--- | :--- |",
        ])
        if cat_notes:
            for n in cat_notes:
                folder_ref = n["folder_name"]
                topic_ref = n["topic"].replace("|", "/")
                scene_ref = n["scene"].replace("|", "/")
                # Single line summary preview
                summary_preview = n["summary"].replace("\n", " ").replace("|", "\\|").strip()
                if len(summary_preview) > 90:
                    summary_preview = summary_preview[:90] + "..."
                if not summary_preview:
                    summary_preview = "—"
                lines.append(f"| {n['date']} | [[{folder_ref}|{topic_ref}]] | {scene_ref} | {summary_preview} |")
        else:
            lines.append("| — | *暂无此类纪要* | — | — |")
        lines.append("")

    # Weekly reports archive
    lines.extend([
        "## 📅 周报归档 (Weekly Reports)",
        "",
    ])
    if weekly_files:
        for w in weekly_files:
            lines.append(f"- [[{w['stem']}|{w['display']}]]")
    else:
        lines.append("*暂无周报记录*")
    lines.append("")

    # Entities and Tags for Obsidian Graph View
    lines.extend([
        "## 🔗 核心实体与跨库联动标签 (与 AI Daily 联动)",
        "",
        "### 核心实体",
        "",
    ])
    sorted_entities = sorted(all_entities_count.items(), key=lambda x: x[1], reverse=True)
    if sorted_entities:
        pills = [f"[[{ent}]]`({count})`" for ent, count in sorted_entities]
        lines.append(" · ".join(pills))
    else:
        lines.append("*暂无提取到的核心实体*")

    lines.extend([
        "",
        "### 知识库标签云",
        "",
    ])
    sorted_tags = sorted(all_tags_count.items(), key=lambda x: x[1], reverse=True)
    if sorted_tags:
        tag_pills = [f"#{tag}" for tag, _ in sorted_tags]
        lines.append(" ".join(tag_pills))
    else:
        lines.append("*暂无标签*")
    lines.append("")

    return "\n".join(lines)


def render_html_dashboard(notes: list[dict[str, Any]], weekly_files: list[dict[str, str]]) -> str:
    """Generate a standalone, zero-dependency interactive dashboard from the HTML template."""
    total_seconds = sum(n["duration"] for n in notes if n.get("duration"))
    cat_counts = {cat: 0 for cat in VALID_CATEGORIES}
    for note in notes:
        category = note["category"] if note["category"] in cat_counts else CATEGORY_DAILY
        cat_counts[category] += 1

    def script_json(value: Any) -> str:
        return (
            json.dumps(value, ensure_ascii=False)
            .replace("&", "\\u0026")
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029")
        )

    replacements = {
        "__NOW__": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "__TOTAL_NOTES__": str(len(notes)),
        "__TOTAL_DURATION__": format_duration(total_seconds if total_seconds > 0 else None),
        "__TOTAL_TODOS__": str(sum(len(n["todos"]) for n in notes if n["category"] != CATEGORY_DAILY)),
        "__TOTAL_QUESTIONS__": str(sum(len(n["questions"]) for n in notes if n["category"] != CATEGORY_DAILY)),
        "__WEEKLY_COUNT__": str(len(weekly_files)),
        "__COUNT_INVESTMENT__": str(cat_counts[CATEGORY_INVESTMENT]),
        "__COUNT_ACADEMIC__": str(cat_counts[CATEGORY_ACADEMIC]),
        "__COUNT_MEETING__": str(cat_counts[CATEGORY_MEETING]),
        "__COUNT_DAILY__": str(cat_counts[CATEGORY_DAILY]),
        "__CATEGORY_INVESTMENT__": CATEGORY_INVESTMENT,
        "__CATEGORY_ACADEMIC__": CATEGORY_ACADEMIC,
        "__CATEGORY_MEETING__": CATEGORY_MEETING,
        "__CATEGORY_DAILY__": CATEGORY_DAILY,
        "__NOTES_JSON__": script_json(notes),
        "__WEEKLY_JSON__": script_json(weekly_files),
        "__DAILY_CATEGORY_JSON__": script_json(CATEGORY_DAILY),
    }
    template = Path(__file__).with_name("dashboard_template.html").read_text(encoding="utf-8")
    for token, value in replacements.items():
        template = template.replace(token, value)
    return template


def enrich_note_markdown(raw_md: str, parsed_note: dict[str, Any]) -> str:
    """Enrich a meeting markdown note with YAML frontmatter and [[00_纪要看板]] backlink."""
    # Cleanly extract body even if frontmatter already exists
    _, body = parse_frontmatter(raw_md)

    title = parsed_note.get("topic", "未命名纪要").replace('"', '\\"')
    date_val = parsed_note.get("date", "")
    scene = parsed_note.get("scene", "未指定场景").replace('"', '\\"')
    category = parsed_note.get("category", CATEGORY_DAILY)
    tags = parsed_note.get("tags") or ["voiceloop", category]
    entities = parsed_note.get("entities") or []

    yaml_lines = [
        "---",
        f'title: "{title}"',
        f"date: {date_val}",
        f'scene: "{scene}"',
        f'category: "{category}"',
        "tags:",
    ]
    for t in tags:
        yaml_lines.append(f"  - {t}")
    if entities:
        yaml_lines.append("entities:")
        for e in entities:
            yaml_lines.append(f"  - {e}")
    yaml_lines.append("---")
    yaml_lines.append("")

    body_clean = body.strip()
    if "00_纪要看板" not in body_clean:
        body_clean = body_clean + "\n\n---\n> [!info] 知识库索引：[[00_纪要看板|返回全局看板]]"

    return "\n".join(yaml_lines) + "\n" + body_clean + "\n"


def enrich_synced_notes(data_dir: Path, sync_dir: Path, notes: list[dict[str, Any]]) -> int:
    """Enrich synced markdown notes in sync_dir with YAML frontmatter without touching data_dir."""
    if not sync_dir.exists():
        return 0

    enriched_count = 0
    for note in notes:
        folder_name = note["folder_name"]
        synced_file = sync_dir / f"{folder_name}.md"

        # Prioritize reading raw note from data_dir source file
        source_candidates = [
            data_dir / folder_name / f"{folder_name}.md",
            data_dir / folder_name / "meeting.md",
        ]
        source_file = next((p for p in source_candidates if p.is_file()), None)

        raw_md = None
        if source_file:
            raw_md = source_file.read_text(encoding="utf-8")
        elif synced_file.is_file():
            raw_md = synced_file.read_text(encoding="utf-8")

        if raw_md is not None:
            enriched = enrich_note_markdown(raw_md, note)
            existing_synced = synced_file.read_text(encoding="utf-8") if synced_file.is_file() else None
            if enriched != existing_synced:
                atomic_write(synced_file, enriched)
                enriched_count += 1

    return enriched_count


def generate_dashboard(
    data_dir: Path,
    sync_dir: Path | None = None,
    enrich_synced: bool = False,
) -> dict[str, Any]:
    """Generate both Obsidian markdown dashboard (00_纪要看板.md) and HTML dashboard."""
    data_dir.mkdir(parents=True, exist_ok=True)

    notes = collect_valid_notes(data_dir, sync_dir=sync_dir)
    weekly_files = collect_weekly_files(data_dir, sync_dir=sync_dir)

    md_content = render_obsidian_dashboard(notes, weekly_files)
    html_content = render_html_dashboard(notes, weekly_files)

    md_path = data_dir / "00_纪要看板.md"
    html_path = data_dir / "dashboard.html"

    atomic_write(md_path, md_content)
    atomic_write(html_path, html_content)

    synced_md: Path | None = None
    synced_html: Path | None = None
    enriched_count = 0

    if sync_dir:
        sync_dir.mkdir(parents=True, exist_ok=True)
        synced_md = sync_dir / "00_纪要看板.md"
        synced_html = sync_dir / "dashboard.html"
        shutil.copy2(md_path, synced_md)
        shutil.copy2(html_path, synced_html)

        if enrich_synced:
            enriched_count = enrich_synced_notes(data_dir, sync_dir, notes)

    cat_counts = {cat: 0 for cat in VALID_CATEGORIES}
    for n in notes:
        cat_counts[n["category"]] = cat_counts.get(n["category"], 0) + 1

    return {
        "command": "dashboard",
        "notes_count": len(notes),
        "categories": cat_counts,
        "markdown_path": str(md_path),
        "html_path": str(html_path),
        "synced_markdown": str(synced_md) if synced_md else None,
        "synced_html": str(synced_html) if synced_html else None,
        "enriched_count": enriched_count,
    }


def maybe_refresh_dashboard(data_dir: Path, sync_dir: Path | None = None) -> None:
    """Best-effort dashboard refresh if dashboard already exists or auto-refresh is explicitly enabled.

    Does not run if dashboard has never been initialized, preserving isolation in tests.
    """
    should_refresh = (
        os.environ.get("VOICELOOP_AUTO_DASHBOARD") == "1"
        or (data_dir / "00_纪要看板.md").exists()
        or (sync_dir is not None and (sync_dir / "00_纪要看板.md").exists())
    )
    if not should_refresh:
        return

    try:
        generate_dashboard(data_dir, sync_dir=sync_dir, enrich_synced=False)
    except Exception as exc:
        print(f"[Dashboard] Auto-refresh failed: {exc}", file=sys.stderr)
