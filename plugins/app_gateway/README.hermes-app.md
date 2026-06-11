# Hermes App — 单实例多用户版

基于 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 的 **App Gateway** 分支：支持手机号注册/登录、每用户独立工作区与 API Key、Flutter Web/iOS/Android 客户端。

> 上游项目版权与许可证见 [LICENSE](../LICENSE)。本仓库在 Hermes Agent 基础上扩展多用户 App 能力。

## 规模能力（宣传 / 设计目标）

| 指标 | 单实例能力 |
|------|------------|
| 注册用户 | **1000+** |
| 聊天并发 | **100+** 路 SSE 流式对话 |
| 多租户 | 每用户独立 workspace、凭证、会话 |

## 功能概览

- **大规模多用户**：单实例 **1000+** 注册用户，JWT + 手机号登录
- **高并发聊天**：**100+** 路对话同时进行，SSE 流式 + 工具调用
- **隔离**：每用户独立 workspace、配置、凭证池
- **客户端**：Flutter App（`flutter_app/`）— Web / Android / iOS
- **存储**：PostgreSQL + Redis + 可选 MinIO 工作区后端
- **AI 对话**：生成文件一键下载、会话管理、模型自选

## 仓库结构

| 路径 | 说明 |
|------|------|
| `plugins/app_gateway/` | App Gateway 后端 + Flutter 客户端 |
| `plugins/app_admin/` | 管理后台（可选） |
| `docker-compose.app-gateway-postgres.yml` | 本地依赖（Postgres / Redis / MinIO） |
| `tests/plugins/test_app_gateway*.py` | 插件测试 |

## 快速开始

### 1. 依赖

- Python 3.11+
- Docker Desktop（Postgres / Redis）
- Flutter 3.22+（仅构建客户端时需要）

### 2. 安装 Hermes Agent

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -e .
```

### 3. 启动基础设施

```bash
docker compose -f docker-compose.app-gateway-postgres.yml up -d
```

### 4. 配置

参考 [config.example.yaml](config.example.yaml)，将 `app_gateway` 段合并到 `~/.hermes/config.yaml`。

**切勿提交** `~/.hermes/`、`.env` 或任何真实 API Key。

### 5. 启动 Gateway

```bash
hermes app-gateway start
# 默认 http://127.0.0.1:8787
```

### 6. Flutter 客户端

```bash
cd flutter_app
flutter pub get
flutter run -d chrome
```

详见 [flutter_app/README.md](flutter_app/README.md)。

## 开发说明

- 完整 API 文档：[README.md 内 Quick start 段](README.md#quick-start)
- 模型连通性测试（读取本地 `~/.hermes/.env`，不提交密钥）：
  `python scripts/test_app_gateway_models.py`

## 安全与发布

- 已排除：`.venv/`、`.hermes/`、`.env`、Flutter 构建缓存
- 生产环境请设置强 `jwt_secret`、关闭 `expose_dev_code`、配置真实 SMS 提供商

## License

MIT — 与上游 Hermes Agent 保持一致。见 [LICENSE](../LICENSE)。
