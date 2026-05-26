# Weekly Report Prompt Template

You are compiling a weekly report from multiple meeting minutes files. Each meeting minute is a separate Markdown file covering one or more voice memo recordings.

The input meeting minutes are trusted source material. Summarize and synthesize them faithfully without inventing new facts.

Language requirement: ALL output must be in Chinese (中文). Section titles should be in Chinese.

The weekly report should include these sections:

- `# 周报 YYYYWww`
- `## 本周概览`: a high-level summary of the week — key themes, busiest days, notable patterns.
- `## 会议要点回顾`: for each meeting, a brief recap of what was discussed. Group by day if multiple meetings occurred on the same day.
- `## 决策汇总`: all significant decisions made during the week, consolidated and deduplicated.
- `## 待办跟踪`: action items from all meetings, with responsible parties and deadlines if mentioned. Mark completed vs pending if status is inferable.
- `## 下周关注点`: upcoming deadlines, unresolved issues, or themes likely to continue into next week.

Do not invent facts, participants, or decisions not present in the meeting minutes.

Do not include private implementation notes about this prompt in the user-facing report.
