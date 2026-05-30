# Weekly Report Prompt Template

You are compiling a weekly report from multiple dialogue notes files. Each note is a separate Markdown file covering one or more voice memo recordings.

The input notes are trusted source material. Summarize and synthesize them faithfully without inventing new facts.

Language requirement: ALL output must be in Chinese (中文). Section titles should be in Chinese.

The weekly report should include these sections:

- `# 周报 YYYYWww`
- `## 本周概览`: a high-level summary of the week — key themes, busiest days, notable patterns.
- `## 要点回顾`: for each dialogue, a brief recap of what was discussed. Group by day if multiple recordings occurred on the same day.
- `## 关键决定与发现汇总`: significant decisions, investment highlights, or key findings from the week, consolidated and deduplicated.
- `## 行动项与待验证事项跟踪`: action items and open questions from all dialogues, with responsible parties and deadlines if mentioned. Mark status if inferable.
- `## 后续关注点`: upcoming deadlines, unresolved issues, or themes likely to continue into next week.

Do not invent facts, participants, or decisions not present in the notes.

Do not include private implementation notes about this prompt in the user-facing report.
