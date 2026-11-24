from datetime import datetime
import json
import os
from pathlib import Path
import pytest

from voiceloop import dashboard, sessions
from voiceloop.cli import build_parser, run


def test_classify_category():
    # Explicit declared categories
    assert dashboard.classify_category("工作汇报", "某主题", declared_category="尽调与路演") == "尽调与路演"
    assert dashboard.classify_category("工作汇报", "某主题", declared_category="课程与学术") == "课程与学术"
    assert dashboard.classify_category("工作汇报", "某主题", declared_category="会议与协作") == "会议与协作"
    assert dashboard.classify_category("工作汇报", "某主题", declared_category="日常与其他") == "日常与其他"

    # Daily / casual / entertainment override (even if text contains words like 商业 or 分享)
    assert dashboard.classify_category("家庭非正式闲聊 / 亲子日常互动", "家庭亲子互动与日常闲聊", "录音中没有商业、投资或工作议题") == "日常与其他"
    assert dashboard.classify_category("演唱会现场 / 非正式互动", "邓紫棋深圳站演唱会现场片段（巡演第175场）") == "日常与其他"
    assert dashboard.classify_category("音乐现场演唱 / 非正式个人分享", "演唱《孤独》现场分享与月亮下的个人独白") == "日常与其他"
    assert dashboard.classify_category("未指定场景", "日常闲聊片段", "并非会议") == "日常与其他"
    assert dashboard.classify_category("非正式录音片段", "语音备忘录中的歌词片段") == "日常与其他"
    assert dashboard.classify_category("公共交通语音播报", "校巴二号线欢迎语音播报") == "日常与其他"
    assert dashboard.classify_category("非正式日常对话", "收款提示与日常简短对话") == "日常与其他"

    # Heuristic classification for work & academic
    assert dashboard.classify_category("融资路演", "商业模式与技术汇报") == "尽调与路演"
    assert dashboard.classify_category("投资尽调访谈", "标的公司概况") == "尽调与路演"
    assert dashboard.classify_category("大学课堂讲授、课前非正式闲聊", "分类算法与广告业应用课堂讲授（含课前游戏闲聊）") == "课程与学术"
    assert dashboard.classify_category("大学课堂授课（商业分析）", "考前复习与项目说明") == "课程与学术"
    assert dashboard.classify_category("求职与职业经验分享", "校友交流") == "课程与学术"
    assert dashboard.classify_category("企业内部会议", "周会工作安排与站会复盘") == "会议与协作"


def test_is_placeholder():
    # Placeholders must be True
    assert dashboard._is_placeholder("（本对话为课堂讲授，无当场决策）")
    assert dashboard._is_placeholder("（无明确分配的待办事项...）")
    assert dashboard._is_placeholder("（不适用）")
    assert dashboard._is_placeholder("（不适用，此为课程场景）")
    assert dashboard._is_placeholder("暂无内容")
    assert dashboard._is_placeholder("无。")
    assert dashboard._is_placeholder("无")
    assert dashboard._is_placeholder("- [ ] 无明确分配的待办事项")
    assert dashboard._is_placeholder("- 暂无内容")
    assert dashboard._is_placeholder("- （无）")

    # Colon-ending header lines must be True
    assert dashboard._is_placeholder("高置信度待验证：")
    assert dashboard._is_placeholder("中/低置信度：")
    assert dashboard._is_placeholder("叶玲玲在分享中明确提出三个尚无答案的问题：")
    assert dashboard._is_placeholder("- [ ] 关键待办:")

    # Non-actionable or disclaimer remarks must be True
    assert dashboard._is_placeholder('- [ ] 歌手表示"尽快带着新音乐来见你们"（面向观众的口头预告，非明确分工的正式行动项）')
    assert dashboard._is_placeholder("非正式行动项")
    assert dashboard._is_placeholder("属于挑战陈述而非明确待议问题")

    # Real action items and questions must be False
    assert not dashboard._is_placeholder("- [ ] 提交商业计划书BP至投资人（张总/本周五）")
    assert not dashboard._is_placeholder("下周二前完成期末大作业提交")
    assert not dashboard._is_placeholder("硬件采购单价在Q3是否有上浮风险？")


def test_parse_note_with_yaml_and_callouts(tmp_path: Path):
    note_file = tmp_path / "meeting.md"
    note_content = """---
title: "商业架构与技术路演"
date: 2026-11-10
scene: "融资路演"
category: "尽调与路演"
tags:
  - voiceloop
  - 路演
  - AI
entities:
  - DeepSeek
  - OPPO
---

# 纪要 20261110

## 主题
商业架构与技术路演

## 场景
融资路演

## 参与方 / 访谈对象
张总、李总

## 核心摘要
> [!summary] 核心结论与摘要
> 本次路演重点介绍了 [[DeepSeek]] 与 [[OPPO]] 软硬件协同方案，拟启动 Pre-A 轮融资。

## 可视化结构图
```mermaid
flowchart TD
    A["基础设施层 (算子优化)"] --> B["模型与应用层"]
```

## 关键事实与数据
- 融资金额计划为 5000 万元人民币
- 当前核心团队 25 人，其中研发占比 80%

## 决策
- 正式启动 Pre-A 轮融资进程
- （本对话为路演，无其他日常决策）

## 待办
- [ ] 提交详细财务预测模型与商业计划书（李总/11月15日）
- （无明确分配的待办事项）

## 存疑点 / 待验证事项
> [!warning] 存疑与待核实
- 供应链代工厂交付周期是否可能延期至 Q4？
- 暂无内容
"""
    note_file.write_text(note_content, encoding="utf-8")

    parsed = dashboard.parse_note(
        note_file,
        "20261110_商业架构与技术路演",
        {"duration": 1850.0, "part_count": 2, "start": "2026-11-10T14:30:00+08:00"},
    )

    assert parsed["topic"] == "商业架构与技术路演"
    assert parsed["date"] == "2026-11-10"
    assert parsed["scene"] == "融资路演"
    assert parsed["category"] == "尽调与路演"
    assert parsed["participants"] == "张总、李总"
    assert parsed["summary"] == "本次路演重点介绍了 [[DeepSeek]] 与 [[OPPO]] 软硬件协同方案，拟启动 Pre-A 轮融资。"
    assert "DeepSeek" in parsed["entities"]
    assert "OPPO" in parsed["entities"]
    assert len(parsed["facts"]) == 2
    assert parsed["decisions"] == ["正式启动 Pre-A 轮融资进程"]
    assert parsed["todos"] == ["提交详细财务预测模型与商业计划书（李总/11月15日）"]
    assert parsed["questions"] == ["供应链代工厂交付周期是否可能延期至 Q4？"]
    assert parsed["mermaid"] is not None
    assert "flowchart TD" in parsed["mermaid"]
    assert parsed["part_count"] == 2
    assert "30分" in parsed["duration_str"]


def test_parse_note_legacy_format(tmp_path: Path):
    note_file = tmp_path / "meeting.md"
    note_content = """# 纪要 20261105

## 主题
大学课堂商业分析复习

## 场景
大学课堂授课（商业分析）

## 核心摘要
本次复习课梳理了逻辑回归、假设检验的核心公式与应用案例。

## 待办
（本对话为课堂讲授，无当场决策与待办）

## 决策
（不适用）

## 未解决问题
暂无内容
"""
    note_file.write_text(note_content, encoding="utf-8")

    parsed = dashboard.parse_note(note_file, "20261105_大学课堂商业分析复习")

    assert parsed["topic"] == "大学课堂商业分析复习"
    assert parsed["date"] == "2026-11-05"
    assert parsed["category"] == "课程与学术"
    assert parsed["summary"] == "本次复习课梳理了逻辑回归、假设检验的核心公式与应用案例。"
    assert parsed["todos"] == []
    assert parsed["decisions"] == []
    assert parsed["questions"] == []


def test_collect_valid_notes_and_exclusions(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # 1. Valid note
    valid_dir = data_dir / "20261110_商业路演"
    valid_dir.mkdir()
    (valid_dir / "20261110_商业路演.md").write_text(
        "---\ntitle: \"商业路演\"\ncategory: \"尽调与路演\"\n---\n## 主题\n商业路演\n## 核心摘要\n摘要内容\n",
        encoding="utf-8",
    )

    # 2. Empty topic folder
    empty_dir = data_dir / "20261110_空白录音无有效内容"
    empty_dir.mkdir()
    (empty_dir / "20261110_空白录音无有效内容.md").write_text("## 核心摘要\n无有效内容\n", encoding="utf-8")

    # 3. Tmp dir
    tmp_dir = data_dir / "tmp_20261110_123456"
    tmp_dir.mkdir()
    (tmp_dir / "meeting.md").write_text("临时文件", encoding="utf-8")

    # 4. Folder with session has_content=False
    no_content_dir = data_dir / "20261111_误触录音"
    no_content_dir.mkdir()
    (no_content_dir / "meeting.md").write_text("误触", encoding="utf-8")

    # 5. Superseded folder
    superseded_dir = data_dir / "20261109_旧录音Part1"
    superseded_dir.mkdir()
    (superseded_dir / "meeting.md").write_text("旧录音", encoding="utf-8")

    canonical_dir = data_dir / "20261109_合并录音"
    canonical_dir.mkdir()
    (canonical_dir / "meeting.md").write_text(
        "---\ntitle: \"合并录音\"\ncategory: \"会议与协作\"\n---\n## 主题\n合并录音\n## 核心摘要\n合并摘要\n",
        encoding="utf-8",
    )

    # Register into index
    index_state = {
        "version": 1,
        "recordings": {
            "r1": {"folder": "20261109_旧录音Part1", "start": "2026-11-09T10:00:00+08:00", "duration": 100},
            "r2": {"folder": "20261109_合并录音", "start": "2026-11-09T10:05:00+08:00", "duration": 200},
            "r3": {"folder": "20261111_误触录音", "start": "2026-11-11T10:00:00+08:00", "duration": 10},
        },
        "sessions": {
            "20261109_合并录音": {"members": ["r1", "r2"], "has_content": True},
            "20261111_误触录音": {"members": ["r3"], "has_content": False},
        },
        "separated": [],
    }
    sessions.save_index(data_dir, index_state)

    # 6. Trivial 4-line recording where summary == topic and no facts/todos
    trivial_dir = data_dir / "20260608_20260608录音片段"
    trivial_dir.mkdir()
    (trivial_dir / "meeting.md").write_text("# 纪要 20260608\n\n## 主题\n20260608录音片段\n\n## 核心摘要\n20260608录音片段\n", encoding="utf-8")

    # 7. Accidental cashier / transit noise recordings
    transit_dir = data_dir / "20261023_校巴二号线欢迎语音播报"
    transit_dir.mkdir()
    (transit_dir / "meeting.md").write_text("## 场景\n公共交通语音播报（非会议内容）\n## 核心摘要\n自动语音播报。\n", encoding="utf-8")

    cashier_dir = data_dir / "20260905_收款提示日常对话"
    cashier_dir.mkdir()
    (cashier_dir / "meeting.md").write_text("## 场景\n日常\n## 核心摘要\n收款成功提示，无有效纪要信息可整理。\n", encoding="utf-8")

    sync_dir = tmp_path / "sync"
    sync_dir.mkdir()
    # Create stale copies in sync_dir for transit and cashier
    (sync_dir / "20261023_校巴二号线欢迎语音播报.md").write_text("stale", encoding="utf-8")
    (sync_dir / "20260905_收款提示日常对话.md").write_text("stale", encoding="utf-8")

    notes = dashboard.collect_valid_notes(data_dir, sync_dir=sync_dir)
    found_folders = [n["folder_name"] for n in notes]

    assert "20261110_商业路演" in found_folders
    assert "20261109_合并录音" in found_folders
    assert "20261110_空白录音无有效内容" not in found_folders
    assert "tmp_20261110_123456" not in found_folders
    assert "20261111_误触录音" not in found_folders
    assert "20261109_旧录音Part1" not in found_folders
    assert "20260608_20260608录音片段" not in found_folders
    assert "20261023_校巴二号线欢迎语音播报" not in found_folders
    assert "20260905_收款提示日常对话" not in found_folders

    # Check stale files were moved to .voiceloop-superseded
    assert not (sync_dir / "20261023_校巴二号线欢迎语音播报.md").exists()
    assert (sync_dir / ".voiceloop-superseded" / "20261023_校巴二号线欢迎语音播报.md").exists()
    assert (sync_dir / ".voiceloop-superseded" / "20260905_收款提示日常对话.md").exists()

    # Check session duration aggregated for merged note
    merged_note = next(n for n in notes if n["folder_name"] == "20261109_合并录音")
    assert merged_note["duration"] == 300.0
    assert merged_note["part_count"] == 2


def test_generate_dashboard_and_enrichment(tmp_path: Path):
    data_dir = tmp_path / "data"
    sync_dir = tmp_path / "sync"
    weekly_dir = tmp_path / "weekly"
    data_dir.mkdir()
    sync_dir.mkdir()
    weekly_dir.mkdir()

    # Create a valid recording folder with meeting notes
    rec_dir = data_dir / "20261110_DeepSeek路演"
    rec_dir.mkdir()
    raw_meeting = (
        "# 纪要 20261110\n\n"
        "## 主题\nDeepSeek路演\n\n"
        "## 场景\n融资路演\n\n"
        "## 核心摘要\n> [!summary] 核心结论与摘要\n> 讨论了开源模型与商业化方案。\n\n"
        "## 待办\n- [ ] 梳理投资机构清单（张总/周五）\n\n"
        "## 存疑点 / 待验证事项\n- 算力成本测算是否有20%下调空间？\n"
    )
    (rec_dir / "20261110_DeepSeek路演.md").write_text(raw_meeting, encoding="utf-8")

    # Create a weekly report
    (weekly_dir / "20261108_weekly_2026W45.md").write_text("# 2026W45 周报\n周报内容\n", encoding="utf-8")

    # Run dashboard generation with enrichment
    result = dashboard.generate_dashboard(data_dir, sync_dir=sync_dir, enrich_synced=True)

    assert result["command"] == "dashboard"
    assert result["notes_count"] == 1
    assert result["categories"]["尽调与路演"] == 1
    assert result["enriched_count"] == 1

    # Check generated files in data_dir
    dash_md = data_dir / "00_纪要看板.md"
    dash_html = data_dir / "dashboard.html"
    assert dash_md.exists()
    assert dash_html.exists()

    md_content = dash_md.read_text(encoding="utf-8")
    assert "---" in md_content
    assert "title: \"VoiceLoop 语音纪要全局看板\"" in md_content
    assert "pie showData" in md_content
    assert "[[20261110_DeepSeek路演|DeepSeek路演]]" in md_content
    assert "梳理投资机构清单" in md_content
    assert "算力成本测算是否有20%下调空间？" in md_content
    assert "2026W45 周报" in md_content
    assert "[[DeepSeek]]" in md_content

    html_content = dash_html.read_text(encoding="utf-8")
    assert "<!doctype html>" in html_content
    assert "VoiceLoop 语音知识库看板" in html_content
    assert "DeepSeek路演" in html_content
    assert 'class="app-shell"' in html_content
    assert 'id="detailDrawer"' in html_content
    assert 'role="dialog"' in html_content
    assert "__NOTES_JSON__" not in html_content
    assert not any(symbol in html_content for symbol in ("🎙️", "💼", "📚", "🤝", "💬", "🔍", "✅", "⚠️"))

    # Check synced copies
    assert (sync_dir / "00_纪要看板.md").exists()
    assert (sync_dir / "dashboard.html").exists()

    # Check synced note enrichment
    synced_note = sync_dir / "20261110_DeepSeek路演.md"
    assert synced_note.exists()
    synced_text = synced_note.read_text(encoding="utf-8")
    assert synced_text.startswith("---\n")
    assert "title: \"DeepSeek路演\"" in synced_text
    assert "category: \"尽调与路演\"" in synced_text
    assert "[[00_纪要看板|返回全局看板]]" in synced_text

    # Raw file in data_dir was untouched
    assert (rec_dir / "20261110_DeepSeek路演.md").read_text(encoding="utf-8") == raw_meeting


def test_html_dashboard_escapes_embedded_script_data():
    note = {
        "folder_name": "20261110_脚本安全",
        "file_path": "/tmp/meeting.md",
        "date": "2026-11-10",
        "topic": "</script><script>alert('xss')</script>",
        "scene": "方案评审",
        "category": "会议与协作",
        "participants": "",
        "summary": "验证嵌入数据不会中断看板脚本。",
        "facts": [],
        "decisions": [],
        "todos": [],
        "questions": [],
        "tags": ["voiceloop"],
        "entities": [],
        "mermaid": None,
        "duration": None,
        "duration_str": "—",
        "part_count": 1,
    }

    rendered = dashboard.render_html_dashboard([note], [])

    assert "</script><script>alert('xss')</script>" not in rendered
    assert "\\u003c/script\\u003e\\u003cscript\\u003ealert('xss')\\u003c/script\\u003e" in rendered
    assert 'data-theme="dark"' in rendered
    assert 'id="searchInput"' in rendered
    assert 'id="sortSelect"' in rendered


def test_maybe_refresh_dashboard(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    sync_dir = tmp_path / "sync"
    data_dir.mkdir()
    sync_dir.mkdir()

    rec_dir = data_dir / "20261110_周会"
    rec_dir.mkdir()
    (rec_dir / "20261110_周会.md").write_text(
        "---\ntitle: \"研发周会\"\ncategory: \"会议与协作\"\n---\n## 主题\n研发周会\n## 核心摘要\n安排本周冲刺任务。\n",
        encoding="utf-8",
    )

    # 1. Before dashboard is created: maybe_refresh_dashboard does nothing
    dashboard.maybe_refresh_dashboard(data_dir, sync_dir)
    assert not (data_dir / "00_纪要看板.md").exists()

    # 2. Explicit VOICELOOP_AUTO_DASHBOARD=1 enables refresh
    monkeypatch.setenv("VOICELOOP_AUTO_DASHBOARD", "1")
    dashboard.maybe_refresh_dashboard(data_dir, sync_dir)
    assert (data_dir / "00_纪要看板.md").exists()
    assert (sync_dir / "00_纪要看板.md").exists()

    # 3. Add new note and call maybe_refresh_dashboard (with VOICELOOP_AUTO_DASHBOARD unset)
    monkeypatch.delenv("VOICELOOP_AUTO_DASHBOARD", raising=False)
    rec_dir2 = data_dir / "20261111_学术交流"
    rec_dir2.mkdir()
    (rec_dir2 / "20261111_学术交流.md").write_text(
        "---\ntitle: \"学术交流研讨\"\ncategory: \"课程与学术\"\n---\n## 主题\n学术交流研讨\n## 核心摘要\n学术前沿。\n",
        encoding="utf-8",
    )

    dashboard.maybe_refresh_dashboard(data_dir, sync_dir)
    updated_md = (data_dir / "00_纪要看板.md").read_text(encoding="utf-8")
    assert "学术交流研讨" in updated_md
    assert "研发周会" in updated_md


def test_auto_refresh_uses_fresh_process_instead_of_cached_renderer(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    sync_dir = tmp_path / "sync"
    data_dir.mkdir()
    sync_dir.mkdir()
    (data_dir / "00_纪要看板.md").write_text("initialized", encoding="utf-8")
    calls = []

    monkeypatch.setattr(
        dashboard,
        "generate_dashboard",
        lambda *args, **kwargs: pytest.fail("stale in-process renderer must not be called"),
    )

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return dashboard.subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(dashboard.subprocess, "run", run)
    dashboard.maybe_refresh_dashboard(data_dir, sync_dir)

    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[:4] == [dashboard.sys.executable, "-m", "voiceloop", "dashboard"]
    assert command[command.index("--data-dir") + 1] == str(data_dir)
    assert command[command.index("--sync-dir") + 1] == str(sync_dir)
    assert "--no-enrich-notes" in command
    assert "--no-sync" not in command
    assert kwargs["capture_output"] is True
    assert kwargs["timeout"] == 120


def test_cli_dashboard_command(tmp_path: Path):
    data_dir = tmp_path / "data"
    sync_dir = tmp_path / "sync"
    data_dir.mkdir()
    sync_dir.mkdir()

    rec_dir = data_dir / "20261110_团队周会"
    rec_dir.mkdir()
    (rec_dir / "20261110_团队周会.md").write_text(
        "---\ntitle: \"团队周会\"\ncategory: \"会议与协作\"\n---\n## 主题\n团队周会\n## 核心摘要\n团队周会要点。\n",
        encoding="utf-8",
    )

    parser = build_parser()
    args = parser.parse_args([
        "dashboard",
        "--data-dir", str(data_dir),
        "--sync-dir", str(sync_dir),
    ])

    result = run(args)
    assert result["command"] == "dashboard"
    assert result["notes_count"] == 1
    assert (data_dir / "00_纪要看板.md").exists()
    assert (sync_dir / "00_纪要看板.md").exists()

    # Test --no-sync
    other_sync = tmp_path / "other_sync"
    args_no_sync = parser.parse_args([
        "dashboard",
        "--data-dir", str(data_dir),
        "--sync-dir", str(other_sync),
        "--no-sync",
    ])
    result_no_sync = run(args_no_sync)
    assert result_no_sync["synced_markdown"] is None
    assert not (other_sync / "00_纪要看板.md").exists()


def test_enrich_idempotency():
    raw = "# 纪要 20261110\n\n## 主题\n测试\n\n## 核心摘要\n测试内容\n"
    parsed = {
        "topic": "测试",
        "date": "2026-11-10",
        "scene": "会议",
        "category": "会议与协作",
        "tags": ["voiceloop", "会议"],
        "entities": ["Agent"],
    }
    enriched1 = dashboard.enrich_note_markdown(raw, parsed)
    assert enriched1.startswith("---\n")
    assert "[[00_纪要看板|返回全局看板]]" in enriched1

    # Enriching already enriched content should not add second frontmatter or second backlink
    enriched2 = dashboard.enrich_note_markdown(enriched1, parsed)
    assert enriched2.count("---") == 3  # 2 for YAML block + 1 for divider
    assert enriched2.count("[[00_纪要看板|返回全局看板]]") == 1
    assert enriched2 == enriched1


def test_enrich_synced_notes_updates_old_category(tmp_path: Path):
    data_dir = tmp_path / "data"
    sync_dir = tmp_path / "sync"
    data_dir.mkdir()
    sync_dir.mkdir()

    folder_name = "20260705_家庭亲子互动与日常闲聊"
    rec_dir = data_dir / folder_name
    rec_dir.mkdir()
    (rec_dir / f"{folder_name}.md").write_text(
        "# 纪要 20260705\n\n## 主题\n家庭亲子互动与日常闲聊\n\n## 场景\n家庭非正式闲聊 / 亲子日常互动\n\n## 核心摘要\n这是一段家庭闲聊，无工作议题。\n",
        encoding="utf-8",
    )

    # Suppose sync_dir previously had an old frontmatter with incorrect category "尽调与路演"
    old_synced = (
        "---\n"
        "title: \"家庭亲子互动与日常闲聊\"\n"
        "date: 2026-07-05\n"
        "scene: \"家庭非正式闲聊\"\n"
        "category: \"尽调与路演\"\n"
        "tags:\n  - voiceloop\n---\n\n"
        "# 纪要 20260705\n\n## 主题\n家庭亲子互动与日常闲聊\n\n## 核心摘要\n这是一段家庭闲聊，无工作议题。\n\n---\n> [!info] 知识库索引：[[00_纪要看板|返回全局看板]]\n"
    )
    (sync_dir / f"{folder_name}.md").write_text(old_synced, encoding="utf-8")

    # Run dashboard generation with enrichment
    result = dashboard.generate_dashboard(data_dir, sync_dir=sync_dir, enrich_synced=True)
    assert result["notes_count"] == 1
    assert result["categories"]["日常与其他"] == 1

    # Verify that the synced file in sync_dir has its category updated to "日常与其他"
    updated_synced = (sync_dir / f"{folder_name}.md").read_text(encoding="utf-8")
    assert 'category: "日常与其他"' in updated_synced
    assert 'category: "尽调与路演"' not in updated_synced
    assert updated_synced.count("[[00_纪要看板|返回全局看板]]") == 1


def test_empty_data_dir_generates_clean_dashboard(tmp_path: Path):
    empty_data = tmp_path / "empty_data"
    empty_data.mkdir()

    result = dashboard.generate_dashboard(empty_data)
    assert result["command"] == "dashboard"
    assert result["notes_count"] == 0
    assert (empty_data / "00_纪要看板.md").exists()
    assert (empty_data / "dashboard.html").exists()

    md = (empty_data / "00_纪要看板.md").read_text(encoding="utf-8")
    assert "纪要总数**：0 篇" in md
    assert "当前暂无未完成待办事项" in md


def test_pipe_escaping_in_tables(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    rec_dir = data_dir / "20261110_复杂主题"
    rec_dir.mkdir()
    (rec_dir / "20261110_复杂主题.md").write_text(
        "---\ntitle: \"架构A | 架构B对比\"\nscene: \"方案A | 方案B评审\"\ncategory: \"会议与协作\"\n---\n"
        "## 主题\n架构A | 架构B对比\n\n"
        "## 场景\n方案A | 方案B评审\n\n"
        "## 核心摘要\n比较了选项1 | 选项2的吞吐量与成本。\n",
        encoding="utf-8",
    )
    result = dashboard.generate_dashboard(data_dir)
    assert result["notes_count"] == 1
    md = (data_dir / "00_纪要看板.md").read_text(encoding="utf-8")
    # Must escape pipes in table cells or alias
    assert "架构A / 架构B对比" in md or "架构A \\| 架构B对比" in md


def test_auto_refresh_via_sync_session(tmp_path: Path):
    data_dir = tmp_path / "data"
    sync_dir = tmp_path / "sync"
    data_dir.mkdir()
    sync_dir.mkdir()

    # Initialize dashboard first so maybe_refresh_dashboard becomes active
    dashboard.generate_dashboard(data_dir, sync_dir=sync_dir)
    assert (data_dir / "00_纪要看板.md").exists()
    assert (sync_dir / "00_纪要看板.md").exists()

    # Now add a new recording session and call sync_session
    rec_dir = data_dir / "20261112_新路演"
    rec_dir.mkdir()
    (rec_dir / "20261112_新路演.md").write_text(
        "---\ntitle: \"新路演项目\"\ncategory: \"尽调与路演\"\n---\n## 主题\n新路演项目\n## 核心摘要\n路演内容。\n",
        encoding="utf-8",
    )
    (rec_dir / "20261112_新路演.m4a").write_bytes(b"audio")

    # Register into index
    rid = sessions.source_id(rec_dir / "20261112_新路演.m4a")
    sessions.register_recording(
        data_dir,
        rec_dir,
        rid,
        {"source_name": "20261112_新路演.m4a", "start": "2026-11-12T10:00:00+08:00", "duration": 100},
        True,
    )

    synced_path = sessions.sync_session(data_dir, rec_dir, sync_dir)
    assert synced_path is not None

    # Verify that dashboard was auto-refreshed and now includes "新路演项目"
    updated_dash = (data_dir / "00_纪要看板.md").read_text(encoding="utf-8")
    assert "新路演项目" in updated_dash
    updated_cloud_dash = (sync_dir / "00_纪要看板.md").read_text(encoding="utf-8")
    assert "新路演项目" in updated_cloud_dash
