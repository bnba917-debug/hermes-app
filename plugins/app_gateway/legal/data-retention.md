# 数据保留与注销说明（模板）

## 保留期限

| 数据类型 | 默认保留 | 说明 |
|---------|---------|------|
| 账户资料 | 账户存续期间 | 手机号哈希目录、注册时间 |
| 对话与消息 | 可配置（`data_retention_days`，默认 365 天） | 存储于会话数据库；Gateway 启动时自动清理已结束会话 |
| 审计日志 | 依运营策略 | 可能匿名化后更长保留 |
| 向量记忆摘要 | 随账户注销删除 | 调用 `DELETE /v1/me` 时擦除 |

## 注销

用户可通过 **`DELETE /v1/me`**（需 JWT，body: `{"confirm": true}`）自助注销账户，将删除：

- 用户注册信息（含该手机号 SMS OTP 记录）
- PostgreSQL 用户配置与 API Key（`hermes_app_user_profiles`）
- 会话与消息
- 工作区文件（含 MinIO 对象与本地 ``workspace-cache/<user_id>/``）
- 向量记忆
- 全部 refresh token（`POST /v1/auth/logout/all` 亦可仅撤销登录态）

**注意：** 已签发的 access JWT 在过期前仍可能有效（请使用较短 `jwt_access_ttl_minutes`）。

## 备份

若运营方有离线备份，可能在备份周期内仍存有副本；正式商用需在备份策略中约定擦除流程。
