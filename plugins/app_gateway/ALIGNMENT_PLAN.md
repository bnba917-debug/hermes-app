# App Gateway ↔ CLI 对齐计划

> 分阶段把移动 App 能力拉到与 `hermes` CLI 同级（多租户 + HTTP 形态保留）。

## 阶段总览

| 阶段 | 目标 | 状态 |
|------|------|------|
| **1** | 多模态消息（图文）与 api_server 同解析 | ✅ 本 PR |
| **2** | 工具集默认 `hermes-cli`（`app_gateway` 平台） | ✅ 本 PR |
| **3** | 语音 HTTP：`/v1/audio/transcribe`、`/v1/audio/speech` | ✅ 本 PR |
| **4** | `clarify` / 审批 / `/stop` 的 SSE 事件协议 | ✅ 本 PR（tool/approval SSE + `/v1/chat/stop`） |
| **5** | `/v1/runs` 长任务（对齐 api_server Runs API） | 部分（stop/approval 已接入 chat run_id；独立 Runs API 待做） |
| **6** | App 原生 UI（非 `/tester`）与 TUI 功能菜单 | ✅ Flutter 历史/新会话/停止/工具活动 |

## 阶段 1 — 图文消息

- `chat_messages.py` 复用 `api_server._normalize_multimodal_content`
- `POST /v1/chat/completions` 支持 `content: [{type:text},{type:image_url}]`

## 阶段 2 — 工具集

- `hermes_cli/platforms.py` 注册 `app_gateway` → 默认 **`hermes-app-gateway`**（多租户安全子集）
- `app_gateway.platform_toolset: app_gateway`（解析为 `hermes-app-gateway`）
- 可用 `hermes tools` 为 `app_gateway` 平台单独开关 toolset

## 阶段 3 — 语音

- `POST /v1/audio/transcribe` — 上传音频 → STT（`transcribe_audio`）
- `POST /v1/audio/speech` — 文本 → TTS（`text_to_speech_tool`）
- 需配置 `stt` / `tts`（与 CLI 相同）

## 客户端集成示例

```text
1. 录音 → POST /v1/audio/transcribe → 得到文本
2. POST /v1/chat/completions（可多模态 content）
3. 可选 POST /v1/audio/speech 播报回复
```

## 配置片段

```yaml
app_gateway:
  platform_toolset: app_gateway   # 解析为 hermes-cli 工具

platform_toolsets:
  app_gateway:
    - hermes-cli   # 与 CLI 一致；也可用 hermes tools 细调
```
