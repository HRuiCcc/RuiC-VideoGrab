# RuiC-VideoGrab · 万能视频下载站

网页版全平台视频下载器：中间一个输入框，粘贴链接，一键下载。

**本地运行 · 本地保存 · 去水印 · 系统播放器打开 · 自选保存路径**

## 📸 项目展示

<div align="center">
  <img src="assets/demo/screenshot.png" alt="RuiC-VideoGrab 界面截图" width="720" />
  <br>
  <sub>界面截图：中间输入框 + 实时进度 + 下载历史</sub>
  <br><br>
  <img src="assets/demo/demo.gif" alt="RuiC-VideoGrab 使用演示" width="720" />
  <br>
  <sub>使用演示（[原视频下载](assets/demo/demo.mp4)）</sub>
</div>

## ✨ 功能

- 🔗 **中间大输入框**：粘贴即下，支持多链接批量排队（每行一条，并发 2 个任务）
- 🌐 **1000+ 平台**：基于 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 引擎，覆盖 YouTube / B站 / TikTok / Instagram / X(Twitter) / 微博 / 快手 等
- 🎵 **抖音专用引擎**：Playwright 真浏览器过风控，**无需登录 cookie**，无水印下载（图集自动打 zip）
- 🍠 **小红书专用适配器**：支持带 xsec_token 的分享链接，视频/图集（自动打包 zip）均支持
- 🛡️ **B站风控自举**：自动申请 buvid3/buvid4 绕过 412 风控，412 间歇发作自动重试
- 📊 **实时进度**：百分比 / 速度 / 剩余时间；下载历史持久化，重启不丢
- ▶️ **播放走系统播放器**：点「播放」直接用你电脑默认播放器打开文件
- 💾 **下载自选路径**：点「下载」弹系统另存为对话框，想存哪存哪
- 🍪 **Cookies 配置**：网页设置里粘贴 Netscape 格式 cookie，解锁高清/需登录内容

## 🚀 快速开始

```bash
./run.sh
# 打开 http://127.0.0.1:8900
```

首次运行自动：创建 venv → 安装依赖 → 安装无头 Chromium（抖音下载用，约 95MB）。需要本机有 Python 3.10+（macOS 自带 ffmpeg 更佳，用于音视频合并）。

手动方式：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium   # 抖音下载依赖
.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8900
```

## 🍪 配置登录 Cookies（可选）

抖音、B站、YouTube 已实现免登录下载；小红书多数笔记免登录可下。以下场景需要登录 cookie：小红书仅粉丝可见笔记、X/Instagram 高清、YouTube 年龄限制内容：

1. 浏览器安装 **Cookie-Editor** 类插件
2. 登录目标平台
3. 导出 **Netscape 格式** cookie
4. 打开页面右上角 ⚙ 设置 → 粘贴 → 保存（多个平台可合并粘贴）

## 🧪 测试

```bash
.venv/bin/python -m pytest tests/ -q
```

73 个测试覆盖：平台识别、任务队列/并发/状态流转、引擎路由、B站自举、412 重试、合并竞态恢复、成品路径选择、抖音提取纯函数、小红书 xsec_token/非标准 JSON 解析、系统打开与路径安全。

## 🏗️ 架构

```
frontend/index.html     单页 UI（无构建，原生 JS）
backend/
  main.py               FastAPI 薄路由层
  engine.py             深模块：Engine 接口 + YtDlpEngine / XhsEngine 适配器
  douyin.py             DouyinEngine：Playwright 真浏览器 + aweme_detail 提取
  tasks.py              TaskManager：队列 / 并发 / 持久化
  platforms.py          平台识别纯函数
  bilibili.py           B站风控自举（buvid cookie）
downloads/              下载产物（每个任务一个目录）
data/                   history.json + cookies.txt + 自举缓存
```

## ⚠️ 声明

下载内容仅供个人学习研究使用，请遵守各平台服务条款与版权规定，勿用于商业用途或二次分发。

## 赞赏支持

如果这个项目帮到了你，欢迎请我喝杯咖啡 ☕

<div align="center">
  <img src="assets/wechat-donate.png" width="300" alt="微信赞赏码" />
  <br>
  <sub>微信扫码赞赏</sub>
</div>
