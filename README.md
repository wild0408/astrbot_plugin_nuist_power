# NUIST 电费查询

[![AstrBot](https://img.shields.io/badge/AstrBot-%3E%3D4.17.0-blue)](https://github.com/AstrBotDevs/AstrBot)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

南京信息工程大学电费余额查询 AstrBot 插件，支持绑定查询、定时订阅、低电量告警、用量估算。

## 功能

- 🔍 **余额查询** — 一键查询宿舍电费余额
- 🔗 **智能绑定** — 输入校区名 + 楼栋名 + 房间号，自动解析为内部 ID
- 📬 **定时订阅** — 自定义检查间隔，电量低于阈值自动推送告警（普通 + 严重两级）
- 🔕 **告警去重** — 同一告警级别只推送一次，电量恢复后重新激活
- 📊 **用量估算** — 根据历史数据推算日均用电量和预计可用天数
- 📈 **余额历史** — 每次查询自动记录，支持原始/按天/按月聚合视图
- 🖥️ **WebUI 仪表盘** — 可视化概览面板：余额卡片、趋势图表、用户管理
- ✏️ **在线编辑** — 直接在仪表盘编辑账号信息、订阅参数，无需聊天命令
- 🏫 **校区/楼栋浏览** — `/power campuses` 查看所有校区，`/power buildings <校区>` 查看楼栋列表
- 🌐 **代理支持** — 支持 HTTP 代理，校外访问校园内网

## 安装

### 方式一：插件市场

AstrBot WebUI → 插件管理 → 插件市场，搜索 `astrbot_plugin_nuist_power`。

### 方式二：手动安装

```bash
cd AstrBot/data/plugins
git clone https://github.com/wild0408/astrbot_plugin_nuist_power
pip install httpx
```

WebUI 中启用插件。

## 命令

| 命令 | 说明 |
|------|------|
| `/power` | 查询电量 + 用量估算 |
| `/power bind <学号> <密码> <校区> <楼栋> <房号>` | 绑定账号 |
| `/power bindraw <学号> <密码> <xiaoqu_id> <loudong_id> <room_id>` | 绑定 (原始ID) |
| `/power unbind` | 解绑账号 |
| `/power sub [分钟] [阈值] [严重阈值]` | 开启订阅告警 |
| `/power unsub` | 取消订阅 |
| `/power status` | 查看状态 |
| `/power history` | 余额历史 + 用量趋势 |
| `/power set <校区> <楼栋> <房号>` | 修改房间 |
| `/power campuses` | 查看可选校区 |
| `/power buildings <校区>` | 查看楼栋列表 |
| `/power list` | 查看全部绑定账号 |
| `/power help` | 帮助 |

### 典型流程

```
/power campuses                      # 看看有哪些校区
/power buildings 沁园                # 看看沁园有哪些楼栋
/power bind 学号 密码 沁园 沁园22栋 214   # 绑定
/power                               # 查询电量
/power sub 60 10 5                   # 订阅: 每60分钟, <10度提醒, <5度严重
/power history                       # 查看用电趋势
```

## WebUI 配置

| 配置项 | 说明 | 默认 |
|--------|------|------|
| 默认检查间隔 | 新订阅检查频率 (分钟) | 60 |
| 普通告警阈值 | 低于此值发普通告警 (度) | 10 |
| 严重告警阈值 | 低于此值发严重告警 (度) | 5 |
| HTTP 代理地址 | 如 `http://127.0.0.1:10809`，校外访问校园网时填写 | 空 |
| 管理员告警会话 | 全局告警接收会话 ID（群聊推荐）| 空 |
| 托管账号 | 批量管理账号列表 | 空 |

> **代理说明**：如果直连 `icard.nuist.edu.cn` 超时，说明你不在校园网环境。在「HTTP 代理地址」中填写你的代理即可（注意是 HTTP 端口，非 SOCKS5 端口）。

## WebUI 仪表盘

插件内置可视化仪表盘，在 AstrBot WebUI 插件详情页打开：

- **📊 仪表盘** — 摘要卡片（绑定数/订阅数/告警数/Token 状态）、余额历史折线图（Chart.js，支持原始/按天/按月）
- **👥 用户管理** — 全部账号列表，支持在线编辑（修改学号/密码/房间/订阅参数）和删除解绑
- **🎨 亮暗主题** — 自动跟随 AstrBot WebUI 主题切换

## 开发

```bash
cd AstrBot/data/plugins
git clone https://github.com/wild0408/astrbot_plugin_nuist_power
cd astrbot_plugin_nuist_power
pip install httpx
```

修改代码后重载插件即可（仅修改 `pages/` 时刷新 WebUI 页面即可）。

### 项目结构

```
astrbot_plugin_nuist_power/
├── main.py              # 插件主入口 (命令 + Web API + 后台轮询)
├── api.py               # NUIST API 异步封装
├── models.py            # 数据库模型 (SQLModel + aiosqlite)
├── _conf_schema.json    # WebUI 配置 Schema
├── metadata.yaml        # 插件元数据
├── requirements.txt     # httpx
├── pages/
│   └── dashboard/
│       ├── index.html   # 仪表盘骨架
│       ├── app.js       # Bridge 通信 + Chart.js 渲染
│       └── style.css    # 亮暗主题样式
└── data/
    └── power.db         # SQLite 数据库 (自动创建)
```

## 依赖

- `httpx` — 异步 HTTP
- `sqlmodel` + `aiosqlite` — AstrBot 自带

## 原理

1. `/berserker-auth/oauth/token` — 学号密码登录，JWT 有效期约 70 天
2. `/charge/feeitem/getThirdData?type=select&level=0` — 获取校区列表
3. `/charge/feeitem/getThirdData?type=select&level=1` — 获取楼栋列表
4. `/charge/feeitem/getThirdData?type=select&level=2` — 获取房间列表
5. `/charge/feeitem/getThirdData?type=IEC&level=3` — 查询电费余额

## 注意事项

- 密码 base64 存储于本地 SQLite，非生产级加密，仅适合个人部署
- 请勿频繁查询，建议订阅间隔 ≥ 30 分钟
- 仅支持南京信息工程大学一卡通系统
- 服务器 `icard.nuist.edu.cn` 为校内服务器，校外访问需配置代理或 VPN
- 告警推送依赖 AstrBot 平台能力，QQ 私聊主动推送可能受限，建议使用群聊做告警接收

## License

MIT
