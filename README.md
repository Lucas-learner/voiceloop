# VoiceLoop - 语音备忘录会议纪要工具

VoiceLoop 监听 Apple 语音备忘录目录，自动将新录音转录为文字、生成结构化会议纪要，并智能重命名为 `YYYYMMDD_主题.m4a`。每周日自动生成周报，汇总一周的会议要点。

## 功能

1. **自动监听**：后台监控语音备忘录目录，新录音自动处理
2. **ASR 转录**：默认本地 MLX Qwen3-ASR，可选 API 模式
3. **AI 会议纪要**：支持 mock / codex / kimi 多引擎，默认 kimi
4. **智能重命名**：仅对默认命名文件提取主题后重命名
5. **周报汇总**：每周日自动生成周报，支持手动触发

## 快速开始

```bash
# 进入项目目录
cd /Users/apple/projects/tools/voiceloop

# 创建虚拟环境并安装
uv venv
source .venv/bin/activate
uv pip install -e ".[qwen-asr,kimi]"

# 检查环境
python -m voiceloop doctor

# 启动监听（前台运行）
python -m voiceloop watch

# 手动处理单个文件
python -m voiceloop process-file ~/path/to/recording.m4a

# 手动生成本周周报
python -m voiceloop weekly

# 安装周日自动周报 cron
python -m voiceloop install-cron --dry-run
python -m voiceloop install-cron
```

## CLI 命令

| 命令 | 说明 |
|------|------|
| `watch` | 启动文件监听，自动处理新录音 |
| `process-file <path>` | 手动处理单个录音文件 |
| `weekly` | 生成周报（默认本周） |
| `weekly --date 2026W21` | 生成指定周的周报 |
| `sync --date YYYYMMDD` | 批量同步语音备忘录 |
| `asr --date YYYYMMDD` | 批量转录某天音频 |
| `minutes --date YYYYMMDD` | 生成某天会议纪要 |
| `install-cron` | 安装周日自动周报 cron |
| `remove-cron` | 移除 cron |
| `doctor` | 环境检查 |

## 引擎配置

### ASR 引擎

- `mlx`（默认）：本地 MLX Qwen3-ASR，需安装 `mlx-qwen3-asr`
- `api`：调用外部 API（如 Whisper），需配置环境变量：
  ```bash
  export VOICELOOP_ASR_API_URL="https://api.openai.com/v1/audio/transcriptions"
  export VOICELOOP_ASR_API_KEY="sk-..."
  export VOICELOOP_ASR_API_MODEL="whisper-1"
  ```
- `mock`：测试用，返回假数据

### 会议纪要引擎

- `kimi`（默认）：调用 Kimi Code API，自动读取 `~/.kimi/credentials/kimi-code.json`
- `codex`：使用 Codex CLI
- `mock`：测试用

## 生成的文件

每个录音一个文件夹：

```
data/
  20260522_币圈投资方式与个人调性思考/
    20260522_币圈投资方式与个人调性思考.m4a   ← 同步副本
    20260522_币圈投资方式与个人调性思考.csv   ← 转录文本
    20260522_币圈投资方式与个人调性思考.md    ← 会议纪要
  20260522_项目立项讨论/
    20260522_项目立项讨论.m4a
    20260522_项目立项讨论.csv
    20260522_项目立项讨论.md
weekly/
  weekly_YYYYWww.md                            ← 周报
```

## 快捷别名

在 `~/.zshrc` 中添加：

```bash
export VOICELOOP_ROOT="/Users/apple/projects/tools/voiceloop"
alias vl='cd "$VOICELOOP_ROOT" && source .venv/bin/activate && python -m voiceloop'
alias vlwatch='cd "$VOICELOOP_ROOT" && source .venv/bin/activate && python -m voiceloop watch'
alias vlweekly='cd "$VOICELOOP_ROOT" && source .venv/bin/activate && python -m voiceloop weekly'
alias vldoctor='cd "$VOICELOOP_ROOT" && source .venv/bin/activate && python -m voiceloop doctor'
```

## 环境要求

- macOS（语音备忘录同步依赖）
- Python 3.10+
- `uv` 包管理器
- `ffmpeg`（用于 .qta 转换，可选）

## 注意事项

1. **iCloud 同步**：新录音可能先以占位符形式出现，工具会自动等待下载完成
2. **重命名安全**：仅对 iOS 默认命名格式（`YYYYMMDD HHMMSS-UUID.m4a`）的文件重命名
3. **监听模式**：`watch` 前台运行，按 Ctrl+C 停止；建议使用 `screen` 或 `tmux` 常驻
4. **周报定时**：cron 每周日午夜执行，Mac 需保持开机
