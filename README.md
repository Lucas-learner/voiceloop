# VoiceLoop - 语音备忘录纪要工具

VoiceLoop 监听 Apple 语音备忘录目录，自动将新录音转录为文字、生成结构化纪要（投资尽调、企业会议、融资路演等场景自适应），压缩大码率音频，智能重命名为 `YYYYMMDD_主题`，同步纪要到 iCloud，并每周自动生成周报。

## 用 AI 代理安装（推荐）

本工具适合交给 AI 代理（Kimi Code、Claude Code、Codex 等）完成安装和验证。在你的工作目录中向代理提供仓库 URL：

```
https://github.com/Lucas-learner/voiceloop
```

然后告诉代理："帮我安装这个仓库"。代理会克隆仓库、创建虚拟环境、安装依赖、运行 `doctor` 检查环境，并用 mock 引擎验证端到端流程。

安装、验证、操作、调试的完整代理操作手册见 [AGENTS.md](AGENTS.md)。普通用户通常不需要直接运行 README 中的命令。

## 功能说明

VoiceLoop 专注一件事：把语音备忘录里的新录音，自动变成归档好的「音频 + 转录 + 结构化纪要」，并按周汇总。

它**不**录制麦克风音频，**不**处理非语音备忘录来源，**不**进行说话人识别或声纹分离。

运行流程：

```
Apple 语音备忘录同步到 Mac
  -> watchdog 检测到新 .m4a/.qta
  -> 等待 iCloud 下载完成，复制到 data/临时目录
  -> 大码率音频压缩为 64kbps 单声道 AAC（ffmpeg）
  -> ASR 转录（本地 MLX Qwen3-ASR / 外部 API）
  -> AI 生成结构化纪要并提取主题（Kimi / Codex）
  -> 重命名归档为 data/YYYYMMDD_主题/
  -> 按录音时间和上下文检查续录，更新所属会话的完整转写与纪要
  -> 纪要同步到 iCloud
  -> 每周定时生成周报（cron，默认周一 00:00 即周日午夜，汇总刚结束的完整一周）
```

## 主要命令

```bash
# 检查环境
python -m voiceloop doctor

# 启动监听（前台运行，Ctrl+C 停止）
python -m voiceloop watch

# 或将 watch 挂载为 launchd 服务（登录自启、自动重启，推荐常驻）
python -m voiceloop install-watch

# 手动处理单个文件
python -m voiceloop process-file ~/path/to/recording.m4a

# 用 mock 引擎验证端到端流程（无需真实模型/密钥）
python -m voiceloop process-file examples/sample_audio/sample.m4a --asr-engine mock --minutes-engine mock

# 手动生成本周周报
python -m voiceloop weekly

# 手动生成上周（刚结束的完整一周）周报
python -m voiceloop weekly --last-week

# 生成 Obsidian 看板 (00_纪要看板.md) 与 HTML 视觉仪表盘 (dashboard.html)
python -m voiceloop dashboard

# 安装自动周报 cron（默认周一 00:00，即周日午夜，汇总刚结束的一周）
python -m voiceloop install-cron
```

## 使用模式

- **常驻模式（推荐）**：`install-watch` 将监听挂载为 launchd 服务，新录音随到随处理，日志在 `logs/voiceloop_watch.log`
- **手动模式**：需要时用 `process-file` 处理单个录音，或用 `asr` / `minutes` / `sync` 按日期批量补跑
- **定时周报**：`install-cron` 安装 cron 后每周自动生成周报；若当周没有任何录音纪要则自动跳过

## 手动安装

```bash
git clone https://github.com/Lucas-learner/voiceloop.git
cd voiceloop

# 创建虚拟环境并安装
uv venv
source .venv/bin/activate
uv pip install -e ".[qwen-asr,kimi]"

# 检查环境
python -m voiceloop doctor
```

## CLI 命令

| 命令 | 说明 |
|------|------|
| `watch` | 启动文件监听，自动处理新录音 |
| `process-file <path>` | 手动处理单个录音文件 |
| `sessions` | 查看会话、原始录音名称和 ID |
| `merge <文件夹A> <文件夹B> ...` | 手动合并会话，更新第一个文件夹的转写和纪要 |
| `split <文件夹> --part <录音ID或原文件名>` | 把指定录音拆为独立会话，可重复传 `--part` |
| `weekly` | 生成周报（默认本周） |
| `weekly --date 2026W21` | 生成指定周的周报 |
| `dashboard` | 生成 Obsidian 知识库看板 (`00_纪要看板.md`) 与 HTML 视觉看板 (`dashboard.html`) |
| `sync --date YYYYMMDD` | 批量同步语音备忘录 |
| `asr --date YYYYMMDD` | 批量转录某天音频 |
| `minutes --date YYYYMMDD` | 生成某天纪要 |
| `install-cron` | 安装自动周报 cron |
| `install-cron --day fri` | 指定星期五生成周报（默认为周一 00:00，汇总刚结束的一周） |
| `remove-cron` | 移除 cron |
| `install-watch` | 将 watch 挂载为 launchd 服务（登录自启、退出自动重启），日志在 `logs/voiceloop_watch.log` |
| `remove-watch` | 卸载 watch 服务 |
| `doctor` | 环境检查 |

## 引擎配置

### ASR 引擎

- `mlx`（默认）：本地 MLX Qwen3-ASR，需安装 `mlx-qwen3-asr`，首次运行需下载模型
- `api`：调用外部 API（如 Whisper），需配置环境变量：
  ```bash
  export VOICELOOP_ASR_API_URL="https://api.openai.com/v1/audio/transcriptions"
  export VOICELOOP_ASR_API_KEY="sk-..."
  export VOICELOOP_ASR_API_MODEL="whisper-1"
  ```
- `mock`：测试用，返回假数据

### 纪要引擎

- `kimi`（默认）：使用 `kimi-for-coding`，可通过 `KIMI_MODEL` 覆盖；读取 `KIMI_API_KEY` 或 `~/.kimi/credentials/kimi-code.json`
- `deepseek`：使用 DeepSeek OpenAI 兼容接口，需设置 `DEEPSEEK_API_KEY`；默认模型 `deepseek-flash`，可通过 `DEEPSEEK_MODEL` 覆盖
- `api`：其他 OpenAI Chat Completions 兼容接口，需设置 `VOICELOOP_LLM_API_KEY`、`VOICELOOP_LLM_BASE_URL`、`VOICELOOP_LLM_MODEL`
- `codex`：使用 Codex CLI
- `mock`：测试用

在 `.env` 中设置 `VOICELOOP_MINUTES_ENGINE=deepseek`（或 `api`）可同时切换监视服务、手动处理和周报的默认引擎；也可分别传 `--minutes-engine` / `--engine`。修改定时周报的引擎后需重新执行 `install-cron`，使已安装的旧任务移除固定的 `--engine kimi` 参数。

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
| `VOICELOOP_MINUTES_ENGINE` | 纪要及周报默认引擎 | `kimi` |
| `VOICELOOP_SESSION_GAP_MINUTES` | 续录候选的最大中断间隔，分钟；设为 `0` 关闭自动归组 | `10` |
| `KIMI_MODEL` | Kimi 模型 ID | `kimi-for-coding` |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | — |
| `DEEPSEEK_MODEL` | DeepSeek 模型 ID | `deepseek-flash` |
| `VOICELOOP_LLM_API_KEY` / `VOICELOOP_LLM_BASE_URL` / `VOICELOOP_LLM_MODEL` | 自定义兼容接口配置 | — |

## 生成的文件

每个录音保留一个来源文件夹；多段归入同一会话后，在会话主文件夹更新完整转写和统一纪要：

```
data/
  .sessions.json                                          ← 会话归组与拆分决定
  20260616_国产算力性能优化技术融资路演/
    .recording_transcript.md                              ← 本段原始转写
    .recording_minutes.md                                 ← 本段原始纪要
    20260616_国产算力性能优化技术融资路演.m4a              ← 音频（自动压缩后）
    20260616_国产算力性能优化技术融资路演_transcript.md    ← 转录文本（主会话为完整转写）
    20260616_国产算力性能优化技术融资路演.md               ← 结构化纪要
weekly/
  YYYYMMDD_weekly_YYYYWww.md                               ← 周报（日期为当周周日）
```

## 录音中断与续录

新录音先独立转写、生成纪要；随后查找前段结束到后段开始间隔不超过 10 分钟的会话，由当前纪要模型对比前段结尾和后段开头。只有明确判断为同一次对话接续、置信度至少 0.9 且给出依据时才合并。这个分数是模型自评，不代表准确率保证；主题相同不足以合并。证据不足、多个会话同时匹配、录音时间/时长缺失、录音重叠或模型失败时保留独立结果。`mock`、`codex` 纪要引擎支持手动合并和拆分，自动内容判断目前支持 `kimi`、`deepseek`、`api`。

时间优先读取语音备忘录文件名，其次读取音频内嵌的创建时间；时长通过 `ffprobe` 获取，不使用下载时间或文件修改时间推算。因此后半段录了很久、晚同步或先于前半段到达，也仍可归组。跨日录音可以归为同一会话，周报按最早录音开始的本地日期统计一次。

合并后的转写按录音开始时间排列，注明分段来源、时间及中断间隔，缺失内容不补写；统一纪要根据全部转写重新生成。主文件夹及云端文件名保持稳定。各段音频、隐藏的原始转写 `.recording_transcript.md` 和原始纪要 `.recording_minutes.md` 都保留在来源文件夹。周报通过 `data/.sessions.json` 排除已归入其他会话的来源文件夹；云端已发布的分段纪要移到 `.voiceloop-superseded/` 保留备份，主目录只留下会话纪要。请连同这些隐藏文件一起备份、移动数据目录。

手动纠正或合并历史录音：

```bash
# 查看会话及每段录音的原始文件名、完整 ID、来源目录
python -m voiceloop sessions

# 文件夹名称可替换为完整路径；合并结果更新在第一个会话文件夹
python -m voiceloop merge '20261110_项目访谈' '20261110_项目访谈_1'

# 将一段录音从会话中拆出；--part 也可使用 sessions 返回的完整 ID
python -m voiceloop split '20261110_项目访谈' --part '20261110 143700-UUID.m4a'
```

拆分后，两边会话分别重新生成纪要并同步；拆分决定持久保存，两组录音之间不会再次自动合并，手动 `merge` 可以覆盖此决定。手动操作不会发送 iMessage。既有历史文件夹不会被后台扫描改写；显式 `merge` 可导入含一个音频和转写文件的旧文件夹（兼容 Markdown/CSV）。重复处理相同音频会复用已归档结果，不会重复转写或追加；合并/拆分的模型生成失败时保留原结果。

## 快捷别名（可选）

在 `~/.zshrc` 中添加（路径改为你的实际克隆位置）：

```bash
export VOICELOOP_ROOT="$HOME/projects/tools/voiceloop"
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

## 运行边界

1. **iCloud 同步**：新录音可能先以占位符形式出现，工具会自动等待下载完成
2. **音频压缩**：仅在码率 > 128 kbps 时触发压缩，已压缩文件不会重复处理
3. **重命名安全**：仅对 iOS 默认命名格式（`YYYYMMDD HHMMSS-UUID.m4a`）的文件重命名
4. **周报定时**：cron 默认每周一 00:00（即周日午夜）执行，汇总刚结束的完整一周（含周日白天），Mac 需保持开机；若该周没有任何录音纪要，则自动跳过、不生成周报
5. **中文输出**：转录与纪要默认面向中文场景

## 测试

```bash
# 运行全部测试
pytest

# mock 引擎端到端验证
python -m voiceloop process-file examples/sample_audio/sample.m4a --asr-engine mock --minutes-engine mock
```

## 给 AI 代理的说明

本仓库内置 [AGENTS.md](AGENTS.md)，包含架构说明、关键模块、扩展方式（新增 ASR / 纪要引擎）、prompt 模板位置与调试要点。代理在安装、排障或修改本工具时应优先阅读该文件。
