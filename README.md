# Hermes App — 单实例多用户版

基于 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 扩展的 **App Gateway** 方案：手机号注册登录、每用户独立工作区与 API Key、Flutter 跨端客户端。

## 功能

- 多用户 JWT 鉴权 + 手机号 OTP（开发模式可用固定验证码）
- 每用户隔离的 workspace / 配置 / 凭证
- Flutter 客户端（Web / Android / iOS）
- PostgreSQL + Redis 持久化，可选 MinIO 对象存储
- SSE 流式对话、工具调用、**生成文件一键下载**

## 快速开始

```bash
# 1. 基础设施
docker compose -f docker-compose.app-gateway-postgres.yml up -d

# 2. 安装（Python 3.11+）
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -e .

# 3. 配置 ~/.hermes/config.yaml（见下方示例）
hermes app-gateway start

# 4. Flutter Web 客户端
cd plugins/app_gateway/flutter_app
flutter pub get && flutter run -d chrome
```

配置示例：[plugins/app_gateway/config.example.yaml](plugins/app_gateway/config.example.yaml)

详细文档：[plugins/app_gateway/README.md](plugins/app_gateway/README.md)

## 目录

| 路径 | 说明 |
|------|------|
| `plugins/app_gateway/` | 后端 Gateway + Flutter App |
| `plugins/app_admin/` | 管理后台（可选） |
| `docker-compose.app-gateway-postgres.yml` | Postgres / Redis / MinIO |
| `tests/plugins/test_app_gateway*.py` | 自动化测试 |

## 安全说明

**不要提交或上传以下内容：**

- `~/.hermes/`（用户数据、会话、API Key）
- `.env` / `.venv/`
- Flutter `build/`、`.dart_tool/`

生产环境请设置强随机 `jwt_secret`，关闭 `expose_dev_code`，并配置真实 SMS 服务商。

## 上游项目

本仓库 fork 自 [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)（MIT License）。完整 Agent 能力、CLI、Gateway 平台集成等请参阅上游文档。

## License

MIT — 见 [LICENSE](LICENSE)。
