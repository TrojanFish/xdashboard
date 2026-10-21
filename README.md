# Personal Alpha Studio (X-Dashboard)

> **Reddit 高信噪比情报 → X (Twitter) 原创深度长文与大 V 截流策展工作台**  
> 专为 X 平台 **Original Content Rewards（原创奖励计划）** 与 **冲刺 500 蓝标粉 + 50 万有效曝光门槛** 量身打造。

---

## 📖 背景与设计理念

在 X 平台全面废除旧版广告分成、施行 **原创内容奖励（Original Content Rewards）** 后：
- **纯搬运死路一条**：直接搬运原图、转载视频或跨平台无脑抓取会被算法直接判定为非原创并剥夺分钱资格；
- **全自动脚本发帖极易封号**：缺乏真人交互轨迹极易触发 *Inauthentic Behavior* 封号风控；
- **新算法只看有效停留时长（Dwell Time）与主页曝光**。

**Personal Alpha Studio** 采用 **“人机协同情报策展（Human-in-the-Loop）”** 模式：
1. 以 Reddit 作为底层情绪风向标与一手实践内幕库；
2. 通过三级漏斗（数学斜率 + 争议比 + Flash 极速初筛）过滤 95% 平庸贴；
3. 提取 Top 15 高赞神评与争议反驳，交由大模型以 **「AI 架构师 × 资本/量化观察者」** 复合人设输出深度长推；
4. 配套生成 **大 V 评论区狙击文案** 与 **16:9 原生暗黑风数据对比卡**，一键复制直达 X 网页端确认发送，100% 具备真人创作者特征。

---

## ✨ 核心特性

- **🎯 冲刺 500 粉丝专属武器库（Reply Sniper）**
  - 为每个热点自动浓缩 60~90 词极高密度的前排神评。
  - 自动提炼核心实体并生成 **X 高级搜索指令链接**，一键直达刚发帖的大 V 评论区抢前排吸粉。
- **🧠 交叉复合人设（AI × Capital Alpha）**
  - 单账号兼发 AI 与金融领域的终极解法：聊 AI 必聊算力成本、SaaS 护城河与巨头资本开支；聊金融必用第一性原理与工程逻辑拆解，受众画像高度统一。
- **🎨 16:9 原生暗黑数据卡片生成器**
  - 结构化 JSON 驱动指标网格（红/绿/灰三色情感高亮），仿 Bloomberg / Mac 终端质感。
  - 浏览器端 `html-to-image` 2.5 倍超采样渲染，支持**一键写入剪贴板**（在 X 发帖框直接 `Ctrl+V` 粘贴配图）。
  - 卡片主标题与右下角水印支持在前端鼠标点击直接修改。
- **🛡️ 规避风控与去 AI 味（Anti-Slop Filter）**
  - 严禁出现“在 Reddit 看到”等搬运字眼，以一手观察视角重构。
  - 严格封杀 *delve, tapestry, game-changer, 🚀, 🧵* 等机械公关套话。
- **⏱️ 后台非阻塞定时巡航**
  - 基于 APScheduler 的自动化引擎，全天候静默扫描与二创，草稿入库待审。
- **🔒 企业级公网安全防护**
  - 默认使用非标服务端口（`28828`），内置 HTTP Basic Auth 密码验证，防止 VPS 公网端口被全网扫描探测。

---

## 🛠️ 技术栈

- **后端核心**：Python 3.12, FastAPI, Uvicorn, APScheduler, Requests, Pydantic v2
- **AI 引擎**：Google GenAI SDK (`google-genai`), `gemini-2.5-flash`（初筛） + `gemini-2.5-pro`（深度二创）
- **持久化层**：SQLite 3（轻量单文件、Docker 卷挂载）
- **前端工作台**：TailwindCSS, HTML5, html-to-image
- **部署方式**：Docker, Docker Compose

---

## 🚀 VPS Docker 极速部署教程（推荐）

适合部署在海外 VPS（Ubuntu / Debian / CentOS），7×24 小时无人值守挂机。

### 1. 安装 Docker 与 Docker Compose
如果 VPS 尚未安装 Docker，可执行官方一键脚本：
```bash
# Ubuntu / Debian
curl -fsSL https://get.docker.com | bash -s docker
systemctl enable --now docker

# 安装 Docker Compose 插件（若未包含）
apt-get update && apt-get install -y docker-compose-plugin
```

### 2. 克隆项目到服务器
```bash
git clone https://github.com/TrojanFish/xdashboard.git /opt/xdashboard
cd /opt/xdashboard
```

### 3. 配置环境变量
从示例文件复制一份 `.env`：
```bash
cp .env.example .env
nano .env   # 或使用 vim .env
```
修改核心配置项：
```ini
# 必填：你的 Google Gemini API 密钥 (在 https://aistudio.google.com/ 免费获取)
GEMINI_API_KEY=AIzaSy...

# 必填：工作台登录密码（务必修改为强密码）
STUDIO_PASSWORD=YourStrongPasswordHere

# 服务对外端口（默认 28828）
PORT=28828

# 你的 X 账号 Handle（用于卡片右下角水印）
X_HANDLE=@YourTechCapitalHandle

# 后台自动巡航间隔（默认每 30 分钟扫描一次）
SCAN_INTERVAL_MINUTES=30

# 【海外 VPS 必备：防 Reddit 403 封锁二选一】
# 方案 A (推荐)：填写住宅代理 URL (HTTP/Socks5)
REDDIT_PROXY_URL=

# 方案 B (免费)：在 https://www.reddit.com/prefs/apps 注册 script 应用填入凭据
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
```

> **⚠️ 关于海外 VPS 机房 IP 被 Reddit 拦截的说明**：  
> Reddit 近期对主流公有云机房（AWS, DigitalOcean, Vultr, Hetzner 等）IP 进行了全面封禁（返回 `403 Forbidden`）。  
> - **推荐做法**：配置 `REDDIT_PROXY_URL`（住宅代理）；  
> - **或者**：在 Reddit 免费申请个人 Script 类型 API 填入 `REDDIT_CLIENT_ID` 与 `SECRET`，系统将自动使用 OAuth 协议免封禁请求。

### 4. 放行防火墙端口
确保 VPS 云厂商安全组（Security Group）或系统防火墙开放了 `28828` 端口：
```bash
# UFW (Ubuntu/Debian)
ufw allow 28828/tcp

# Firewalld (CentOS/Alibaba Cloud Linux)
firewall-cmd --zone=public --add-port=28828/tcp --permanent
firewall-cmd --reload
```

### 5. 一键构建并启动容器
```bash
docker compose up -d --build
```

### 6. 验证与访问
- 检查容器运行状态：
  ```bash
  docker compose ps
  ```
- 检查运行实时日志：
  ```bash
  docker compose logs -f
  ```
- 打开浏览器访问：
  ```text
  http://<你的VPS公网IP>:28828
  ```
  在弹出的认证窗口中输入：
  - **Username**: `admin`
  - **Password**: 你在 `.env` 中设置的 `STUDIO_PASSWORD`

---

## 💻 本地开发运行教程

若想先在个人 PC 或 Mac 本地运行调试：

### 1. 准备环境
```bash
git clone https://github.com/TrojanFish/xdashboard.git
cd xdashboard

# 创建并激活虚拟环境 (可选但推荐)
python -m venv venv
# Windows:
.\venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置文件
```bash
# 复制配置文件
cp .env.example .env
```
编辑 `.env`，填入 `GEMINI_API_KEY` 与自定义的 `STUDIO_PASSWORD`。本地开发网络环境下，Reddit 代理配置留空即可。

### 3. 启动服务
```bash
python -m uvicorn app.web.main:app --host 127.0.0.1 --port 28828 --reload
```
打开浏览器访问 [http://127.0.0.1:28828](http://127.0.0.1:28828)。

---

## 🔧 常用运维与管理命令

```bash
# 查看实时日志
docker compose logs -f --tail=100

# 重启服务
docker compose restart

# 停止服务
docker compose down

# 更新代码并重新构建
git pull
docker compose up -d --build

# 备份数据库
cp data/studio.db data/studio.db.bak_$(date +%Y%m%d)
```

---

## 📂 项目文件索引

```text
xdashboard/
├── Dockerfile                  # 容器镜像构建配置（暴露端口 28828）
├── docker-compose.yml          # 容器服务编排
├── requirements.txt            # Python 依赖清单
├── .env.example                # 环境变量配置模板
├── .gitignore                  # Git 忽略配置（防泄露密钥与数据文件）
├── README.md                   # 项目全套说明与部署文档
├── data/                       # 持久化存储挂载卷
│   ├── .gitkeep
│   └── studio.db               # SQLite 数据库（自动初始化 4 张核心表）
└── app/
    ├── config.py               # 全局环境与配置加载
    ├── database.py             # 数据库模型、监控源与人设初始化
    ├── scheduler.py            # 后台非阻塞定时抓取与合成调度
    ├── ingestors/
    │   └── reddit.py           # Reddit 防封禁高信噪比采集插件
    ├── engine/
    │   ├── schemas.py          # Pydantic 结构化数据定义
    │   └── synthesizer.py      # Flash 初筛 + Pro 交叉二创引擎
    └── web/
        ├── main.py             # FastAPI 路由、密码认证与服务入口
        └── templates/
            └── index.html      # 暗黑风看板 UI（双模式精修与卡片生成）
```

---

## ⚖️ License

本项目采用 [MIT License](LICENSE) 开源协议。
