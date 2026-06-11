# Hermes App（Flutter）

一套代码，运行在 **Web / iOS / Android**，对接 [App Gateway](../README.md)。配合后端单实例架构，可支撑 **1000+ 注册用户**、**100+ 路聊天并发**。

## 功能

- 手机号 + 验证码登录（开发码 `111111`）
- 入驻：选择模型 + 填写 API Key
- 聊天：SSE 流式输出，多用户同时在线互不干扰
- 相册发图（多模态 `image_url`）
- 录音 → STT → 发送（iOS/Android；Web 暂提示用文字）
- TTS 播放最后一条回复（移动端本地文件）
- 技能列表

## 环境

1. 安装 [Flutter SDK](https://docs.flutter.dev/get-started/install) 3.22+
2. 启动网关：

```bash
hermes app-gateway start
```

3. **Web 必配 CORS**（`~/.hermes/config.yaml`）：

```yaml
app_gateway:
  cors_origins:
    - "http://localhost:8080"
    - "http://127.0.0.1:8080"
```

## 首次生成平台工程

本目录只包含 `lib/` 源码。若缺少 `android/`、`ios/`、`web/`，在目录内执行：

```bash
cd plugins/app_gateway/flutter_app
flutter create . --project-name hermes_app
flutter pub get
```

## 打包 Android APK

**Windows（本机已装 Flutter + Android SDK）：**

```powershell
cd d:\workspace\hermes-agent-main
powershell -ExecutionPolicy Bypass -File scripts\build_hermes_android_apk.ps1
```

产物：

- `plugins/app_gateway/flutter_app/build/app/outputs/flutter-apk/app-release.apk`
- `dist/hermes-app-release.apk`（复制一份便于查找）

安装到真机：

```bash
adb install -r dist\hermes-app-release.apk
```

**无本机 Flutter：** 在 GitHub 仓库 Actions 里手动运行 **Build Hermes Android APK**，下载 artifact。

## 真机 USB 直连调试（推荐开发时用）

比打 APK 更快：改代码后热重载，无需每次安装包。

### 1. 手机端

1. **设置 → 关于手机** → 连点「版本号」7 次，打开开发者选项  
2. **设置 → 开发者选项** → 开启 **USB 调试**  
3. 数据线连接电脑，弹窗点 **允许 USB 调试**（可勾选「始终允许」）

### 2. 电脑端（Windows）

```powershell
# 首次：装 JDK（若未装）
winget install Microsoft.OpenJDK.17

# 首次：装 Android 命令行 SDK（若 adb 不存在）
powershell -ExecutionPolicy Bypass -File scripts\install_android_sdk.ps1

# 启动网关（另开终端）
hermes app-gateway start

# USB 调试 + 自动填局域网网关地址
powershell -ExecutionPolicy Bypass -File scripts\run_android_usb_debug.ps1
```

脚本会安装 `platform-tools`（adb）、编译所需 platform/build-tools，并执行 `flutter run -d android`。

### 3. 网关地址（配置文件，不在登录页填写）

真机调试时修改 **`assets/app_config.json`** 或构建参数：

```json
{ "gateway_url": "http://192.168.1.10:8787" }
```

或使用：`flutter run -d android --dart-define=HERMES_DEV_GATEWAY=http://你的电脑IP:8787`

- 验证码开发环境：**111111**  
- 确认 `~/.hermes/config.yaml` 里 `app_gateway.host: "0.0.0.0"`

### 4. 常见问题

| 现象 | 处理 |
|------|------|
| `flutter devices` 没有手机 | 换数据线（需传数据）、重装手机 USB 驱动、运行 `adb devices` 看是否 `unauthorized` |
| `adb` 找不到 | 完成 `install_android_sdk.ps1` 或 Android Studio SDK Manager 安装 Platform-Tools |
| 登录连不上网关 | 手机与电脑同一 WiFi；Windows 防火墙放行 **8787**；网关地址用电脑 WLAN IP |
| 构建报 symlink | Windows **设置 → 系统 → 开发者选项 → 开发人员模式** 打开 |

手动调试：

```powershell
$env:PATH = "C:\flutter\bin;$env:LOCALAPPDATA\Android\Sdk\platform-tools;" + $env:PATH
adb devices
cd plugins\app_gateway\flutter_app
flutter run -d android --dart-define=HERMES_DEV_GATEWAY=http://你的电脑IP:8787
```

## 运行

```bash
# 模拟器 / 真机
flutter run

# Chrome（Web）
flutter run -d chrome

# Android
flutter run -d android

# iOS（macOS）
flutter run -d ios
```

真机访问电脑上的网关时，编辑 `assets/app_config.json` 中的 `gateway_url` 为电脑局域网 IP（例如 `http://192.168.1.10:8787`），Web 可改 `web/config.json`，并确保 `app_gateway.host: "0.0.0.0"`。

## 网关地址配置

| 场景 | 配置文件 |
|------|----------|
| Android / iOS 打包 | `assets/app_config.json` |
| Web（Chrome） | `web/config.json`（部署后可改，刷新即可） |
| 临时调试 | `--dart-define=HERMES_DEV_GATEWAY=http://...` |

优先级：`dart-define` > Web `config.json` > `assets/app_config.json` > 默认 `http://127.0.0.1:8787`

## 目录结构

```
lib/
  api/hermes_api.dart      # HTTP + SSE
  config/app_config.dart
  services/settings_store.dart
  state/app_state.dart
  screens/                 # 登录 / 入驻 / 聊天 / 技能
  util/file_bytes.dart     # 平台文件 IO
```

## Android 权限

`flutter create` 后确认 `android/app/src/main/AndroidManifest.xml` 包含：

```xml
<uses-permission android:name="android.permission.INTERNET"/>
<uses-permission android:name="android.permission.RECORD_AUDIO"/>
```

## iOS 权限

`ios/Runner/Info.plist`：

```xml
<key>NSMicrophoneUsageDescription</key>
<string>语音输入需要麦克风</string>
<key>NSPhotoLibraryUsageDescription</key>
<string>发送图片需要相册</string>
```

## 与 CLI 对齐

Agent 能力由服务端 `platform_toolset: app_gateway`（`hermes-cli` 工具集）提供；客户端只负责 UI 与 API 调用。后续阶段见 [ALIGNMENT_PLAN.md](../ALIGNMENT_PLAN.md)。
