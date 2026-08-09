# NUIST 电费查询

[![AstrBot](https://img.shields.io/badge/AstrBot-%3E%3D4.17.0-blue)](https://github.com/AstrBotDevs/AstrBot)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green)](https://www.python.org/)

南京信息工程大学电费余额查询插件，支持多用户绑定、定时订阅、低电量自动告警。

## 功能

- **🔍 余额查询** — 一键查询宿舍电费余额
- **🔗 智能绑定** — 只需输入校区名+楼栋名+房间号，自动通过 API 解析为内部 ID
- **📬 定时订阅** — 可自定义检查间隔，电量低于阈值自动推送告警
- **🖥️ WebUI 管理** — 支持在 AstrBot 插件管理页面直接配置账号和参数
- **🔑 Token 缓存** — 登录一次缓存约 70 天，无需频繁登录

## 安装

### 方式一：插件市场安装

在 AstrBot WebUI → 插件管理 → 插件市场，搜索 `astrbot_plugin_nuist_power` 安装。

### 方式二：手动安装

```bash
cd AstrBot/data/plugins
git clone https://github.com/wild0408/astrbot_plugin_nuist_power
pip install httpx
```

然后在 WebUI 中启用插件。

## 命令

| 命令 | 说明 | 示例 |
|------|------|------|
| `/power` | 查询当前绑定账号的电量余额 | `/power` |
| `/power bind` | 绑定账号（自动解析校区/楼栋/房间） | `/power bind <学号> <密码> 沁园 沁园22栋 214` |
| `/power bindraw` | 绑定账号（使用原始 ID） | `/power bindraw <学号> <密码> 3&沁园 15&沁园22栋 16072&214` |
| `/power unbind` | 解绑当前账号 | `/power unbind` |
| `/power sub` | 开启定时订阅 + 低电量告警 | `/power sub 60 5` |
| `/power unsub` | 取消订阅 | `/power unsub` |
| `/power status` | 查看绑定状态和订阅状态 | `/power status` |
| `/power set` | 修改房间信息（自动解析） | `/power set 沁园 沁园23栋 301` |
| `/power setraw` | 修改房间信息（原始 ID） | `/power setraw 3&沁园 16&沁园23栋 16200&301` |
| `/power help` | 显示帮助 | `/power help` |

### 绑定示例

```
/power bind <学号> <密码> 沁园 沁园22栋 214
```

插件会自动查询 API 将 `沁园` / `沁园22栋` / `214` 解析为内部 ID，无需手动查找数字编号。

支持的校区：`沁园` `晖园` `硕园` `文园` `人才公寓三期` `商铺`

## WebUI 配置

在插件管理页面点击「配置」可设置：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| 默认检查间隔 | 新订阅默认多久检查一次（分钟） | 60 |
| 默认告警阈值 | 电量低于此值时发送告警（度） | 10 |
| 管理员告警会话 | 可选的全局告警接收会话 ID | 空 |
| 托管账号 | 管理员统一管理的账号列表 | 空 |

## 依赖

- `httpx` — 异步 HTTP 客户端
- `sqlmodel` — ORM（AstrBot 自带）
- `aiosqlite` — SQLite 异步驱动（AstrBot 自带）

## 原理

通过 NUIST 一卡通网站的 API 查询电费余额：

1. `/berserker-auth/oauth/token` — 学号密码登录获取 JWT Token（有效期约 70 天）
2. `/charge/feeitem/getThirdData?type=select&level=0` — 获取校区列表
3. `/charge/feeitem/getThirdData?type=select&level=1` — 获取楼栋列表
4. `/charge/feeitem/getThirdData?type=select&level=2` — 获取房间列表
5. `/charge/feeitem/getThirdData?type=IEC&level=3` — 查询电费余额

## 注意事项

- 密码使用 base64 编码存储在本地 SQLite 数据库中，非生产级加密，仅适合个人部署
- 请勿频繁查询，建议订阅间隔 ≥ 30 分钟
- 仅支持南京信息工程大学一卡通系统

## License

MIT
