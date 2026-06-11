# App 运行截图指南

宣传 / GitHub README 展示用。请将截图保存为本目录下的 PNG（推荐宽度 1080px 左右，单张 < 500KB）。

## 建议拍摄的界面

| 文件名 | 内容 | 说明 |
|--------|------|------|
| `login.png` | 登录页 | 手机号输入 + 验证码；**不要**露出真实手机号 |
| `onboarding.png` | 首次配置 | 模型选择 + API Key 填写（Key 打码或留空） |
| `chat.png` | 主对话 | 一问一答，展示流式回复 |
| `chat-tools.png` | 工具调用 | 可选：展示「工具: write_file」等活动状态 |
| `chat-files.png` | 生成文件 | 可选：回复下方文件芯片，点击可下载 |
| `sessions.png` | 会话列表 | 侧栏多会话 |

## Web 端截图（Windows）

1. 启动依赖与 Gateway（见根目录 README）
2. 启动 Flutter Web：
   ```powershell
   cd plugins\app_gateway\flutter_app
   flutter run -d chrome
   ```
3. 浏览器打开 `http://127.0.0.1:8080`（或终端提示的地址）
4. **F12** → 切换设备工具栏 → 选 **iPhone 14 Pro** 或 **Pixel 7**（竖屏更像 App）
5. **Win + Shift + S** 区域截图，或浏览器全页截图扩展
6. 保存为上述文件名，放入本目录

## 手机真机 / 模拟器

- **Android**：`flutter run -d android`，电源键 + 音量下截图
- **iOS 模拟器**：`Cmd + S`（Mac）

## 隐私检查（提交前必做）

- [ ] 无真实手机号、验证码（可打码 `138****1234`）
- [ ] 无 API Key、JWT、用户 ID
- [ ] 无本地路径（如 `C:\Users\...`）
- [ ] 对话内容无客户隐私

## 更新 README

截图放好后，根目录 `README.md` 的「应用预览」会自动引用这些文件。提交：

```bash
git add docs/screenshots/*.png README.md
git commit -m "docs: add app screenshots"
git push
```
