# VoiceLoop - 语音备忘录纪要工具

VoiceLoop 监听 Apple 语音备忘录目录，自动将新录音转录为文字、生成结构化纪要，并智能重命名为 `YYYYMMDD_主题.m4a`。支持投资尽调访谈、企业会议等多种对话场景，每周自动生成周报。

## 功能

1. **自动监听**：后台监控语音备忘录目录，新录音自动处理
2. **ASR 转录**：默认本地 MLX Qwen3-ASR，可选 API 模式，输出 Markdown 格式转录文本
3. **AI 纪要生成**：通用自适应 prompt，支持投资尽调、企业会议、融资路演等场景，自动识别对话类型并选取相关板块
4. **智能重命名**：提取主题后重命名为 `YYYYMMDD_主题`
5. **音频压缩**：自动将大码率（无损）录音压缩为 64kbps 单声道 AAC，节省存储空间
6. **iCloud 同步**：纪要和周报自动同步到指定 iCloud 文件夹
7. **周报汇总**：支持自定义星期自动生成周报，支持手动触发

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

# 安装自动周报 cron（默认每周五）
python -m voiceloop install-cron --day fri
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
| `minutes --date YYYYMMDD` | 生成某天纪要 |
| `install-cron` | 安装自动周报 cron |
| `install-cron --day fri` | 指定星期五生成周报 |
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

### 纪要引擎

- `kimi`（默认）：调用 Kimi Code API，自动读取 `~/.kimi/credentials/kimi-code.json`
- `codex`：使用 Codex CLI
- `mock`：测试用

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `VOICELOOP_SOURCE_DIR` | 语音备忘录源目录 | `~/Library/Group Containers/.../Recordings/` |
| `VOICELOOP_DATA_DIR` | 数据输出目录 | `./data` |
| `VOICELOOP_SYNC_DIR` | iCloud 同步目录 | `~/Library/Mobile Documents/com~apple~CloudDocs/数据同步/voiceloop` |
| `VOICELOOP_REPO_ROOT` | 项目根目录 | 包安装目录 |
| `VOICELOOP_ASR_API_URL` | 外部 ASR API 地址 | — |
| `VOICELOOP_ASR_API_KEY` | 外部 ASR API 密钥 | — |
| `VOICELOOP_ASR_API_MODEL` | 外部 ASR 模型名 | — |
| `KIMI_API_KEY` | Kimi API 备用密钥 | — |

## 生成的文件

每个录音一个文件夹：

```
data/
  20260522_币圈投资方式与个人调性思考/
    20260522_币圈投资方式与个人调性思考.m4a   ← 音频（自动压缩后）
    20260522_币圈投资方式与个人调性思考.md    ← 转录文本
    20260522_币圈投资方式与个人调性思考.md    ← 结构化纪要
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
- `ffmpeg` + `ffprobe`（用于音频压缩和 .qta 转换）

## 注意事项

1. **iCloud 同步**：新录音可能先以占位符形式出现，工具会自动等待下载完成
2. **音频压缩**：仅在码率 > 128 kbps 时触发压缩，已压缩文件不会重复处理
3. **重命名安全**：仅对 iOS 默认命名格式（`YYYYMMDD HHMMSS-UUID.m4a`）的文件重命名
4. **监听模式**：`watch` 前台运行，按 Ctrl+C 停止；建议使用 `screen` 或 `tmux` 常驻
5. **周报定时**：cron 默认每周五午夜执行，Mac 需保持开机
