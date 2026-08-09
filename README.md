# NUIST 电费查询

[![AstrBot](https://img.shields.io/badge/AstrBot-%3E%3D4.17.0-blue)](https://github.com/AstrBotDevs/AstrBot)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

南京信息工程大学电费余额查询 AstrBot 插件，支持绑定查询、定时订阅、低电量告警、用量估算。

## 功能

- 🔍 **余额查询** — 一键查询宿舍电费余额，显示剩余电量等详细信息
- 🔗 **智能绑定** — 只需输入校区名 + 楼栋名 + 房间号，自动通过 API 解析为内部 ID，无需手动查找数字编号
- 📬 **定时订阅** — 自定义检查间隔，电量低于阈值自动推送告警（支持普通提醒 + 严重告警两级）
- 📊 **用量估算** — 根据历史数据自动推算日均用电量和预计可用天数
- 📈 **余额历史** — 每次查询自动记录，`/power history` 查看趋势
- 🖥️ **WebUI 管理** — 支持在 AstrBot 插件管理页面配置默认参数和托管账号
- 🏫 **校区发现** — `/power campuses` 和 `/power buildings <校区>` 浏览可选校区和楼栋

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
/power campuses                    # 看看有哪些校区
/power buildings 沁园              # 看看沁园有哪些楼栋
/power bind <学号> <密码> 沁园 沁园22栋 214   # 绑定
/power                             # 查询电量
/power sub 60 10 5                 # 订阅: 每60分钟, <10度提醒, <5度严重
/power history                     # 查看用电趋势
```

### 告警示例

普通告警 (电量 < 10 度):
> ⚡ 电量告警!
>   房间: 沁园22栋 214号房
>   剩余电量: 8.5 度
>   告警阈值: 10.0 度
>   请及时充值!

严重告警 (电量 < 5 度):
> 🚨 严重电量告警!
>   房间: 沁园22栋 214号房
>   剩余电量: 3.2 度
>   严重阈值: 5.0 度
>   请立即充值!

## WebUI 配置

| 配置项 | 说明 | 默认 |
|--------|------|------|
| 默认检查间隔 | 新订阅检查频率 (分钟) | 60 |
| 普通告警阈值 | 低于此值发普通告警 (度) | 10 |
| 严重告警阈值 | 低于此值发严重告警 (度) | 5 |
| 管理员告警会话 | 全局告警接收会话 ID | 空 |
| 托管账号 | 批量管理账号列表 | 空 |

托管账号支持填写：学号、密码、校区名、楼栋名、房间号、用户标识。保存后自动登录并解析房间 ID 写入数据库。

## 依赖

- `httpx` — 异步 HTTP
- `sqlmodel` + `aiosqlite` — AstrBot 自带

## 原理

1. `/berserker-auth/oauth/token` — 学号密码登录，JWT Token 有效期约 70 天
2. `/charge/feeitem/getThirdData?type=select&level=0` — 获取校区列表
3. `/charge/feeitem/getThirdData?type=select&level=1` — 获取楼栋列表
4. `/charge/feeitem/getThirdData?type=select&level=2` — 获取房间列表
5. `/charge/feeitem/getThirdData?type=IEC&level=3` — 查询电费余额

## 注意

- 密码 base64 存储于本地 SQLite，非生产级加密，仅适合个人部署
- 请勿频繁查询，建议订阅间隔 ≥ 30 分钟
- 仅支持南京信息工程大学一卡通系统

## License

MIT
