"""
astrbot_plugin_nuist_power
NUIST 电费查询插件 — AstrBot v4+

命令:
  /power [标签]                       - 查询电量 (多房间时显示全部或指定标签)
  /power bind <标签> <学号> <密码> <校区> <楼栋> <房间号>
  /power bindraw <标签> <学号> <密码> <xiaoqu_id> <loudong_id> <room_id>
  /power unbind [标签]                - 解绑 (不指定标签则列出可解绑项)
  /power sub [标签] [分钟] [阈值] [严重阈值]
  /power unsub [标签]
  /power status                       - 查看所有绑定及订阅状态
  /power history [标签]               - 查看余额历史
  /power set <标签> <校区> <楼栋> <房间号>
  /power setraw <标签> <xiaoqu_id> <loudong_id> <room_id>
  /power campuses                     - 查看可选校区
  /power buildings <校区>             - 查看校区内的楼栋
  /power list                         - (管理) 查看所有账号与订阅
  /power help
"""
import asyncio
import os
from datetime import datetime, timezone

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger
from sqlalchemy import select

from .api import NUISTPowerAPI
from .models import DBManager, PowerAccount, PowerSubscription


def _uid(event: AstrMessageEvent) -> str:
    return f"{event.get_sender_id()}@{event.get_platform_name()}"


class NUISTPowerPlugin(Star):

    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        self.api = NUISTPowerAPI()

        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(plugin_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        db_path = os.path.join(data_dir, "power.db")

        self.db = DBManager(f"sqlite+aiosqlite:///{db_path}")
        asyncio.create_task(self._init_and_poll())

    # ---- 生命周期 ----

    async def _init_and_poll(self):
        try:
            await self.db.init()
            await self._sync_managed_accounts()
            self.logger.info("NUIST 电费插件初始化完成")
        except Exception as e:
            self.logger.error(f"插件初始化失败: {e}")
            return
        while True:
            try:
                await self._poll_all_subscriptions()
            except Exception as e:
                self.logger.error(f"轮询出错: {e}")
            await asyncio.sleep(60)

    async def terminate(self):
        self.logger.info("NUIST 电费插件已卸载")

    # ---- WebUI 账号同步 ----

    async def _sync_managed_accounts(self):
        managed = self.config.get("managed_accounts", [])
        if not managed:
            return
        resolver_token = None
        for entry in managed:
            if not isinstance(entry, dict):
                continue
            sid = entry.get("student_id", "").strip()
            pwd = entry.get("password", "").strip()
            if not sid or not pwd:
                continue
            campus = entry.get("campus", "").strip()
            building = entry.get("building", "").strip()
            room_number = entry.get("room_number", "").strip()
            target_user = entry.get("user_id", "").strip() or "admin"
            label = entry.get("label", "").strip() or "default"
            if not campus or not building or not room_number:
                continue
            try:
                if not resolver_token:
                    resolver_token = await self.api.login(sid, pwd)
                xq, ld, rm, err = await self.api.resolve_room(
                    resolver_token, campus, building, room_number)
                if err:
                    self.logger.warning(f"WebUI {sid} 解析失败: {err}")
                    continue
                await self.db.upsert_account(
                    user_id=target_user, student_id=sid, password=pwd,
                    room_id=rm, room_label=label, xiaoqu_id=xq, loudong_id=ld)
                self.logger.info(f"WebUI 同步: {sid} -> {label}")
            except Exception as e:
                self.logger.error(f"WebUI {sid} 同步失败: {e}")

    # ---- 命令分发 ----

    @filter.command("power")
    async def power_cmd(self, event: AstrMessageEvent):
        args = event.message_str.strip().split()
        if len(args) < 2:
            result = await self._do_query(event)
            yield event.plain_result(result)
            return

        sub = args[1].lower()
        rest = args[2:]

        handlers = {
            "bind": self._do_bind, "bindraw": self._do_bindraw,
            "unbind": self._do_unbind, "sub": self._do_sub,
            "unsub": self._do_unsub, "status": self._do_status,
            "set": self._do_set, "setraw": self._do_setraw,
            "history": self._do_history, "list": self._do_list,
            "campuses": self._do_campuses, "buildings": self._do_buildings,
            "help": lambda e, a: self._help_text(),
            "h": lambda e, a: self._help_text(),
        }
        handler = handlers.get(sub)
        if handler:
            if asyncio.iscoroutinefunction(handler):
                result = await handler(event, rest)
            else:
                result = handler(event, rest)
        elif sub == "query":
            label = rest[0] if rest else None
            result = await self._do_query(event, label)
        else:
            # Try as a room label (e.g. /power 宿舍)
            result = await self._do_query(event, sub)
        yield event.plain_result(result)

    # ---- Query ----

    async def _do_query(self, event: AstrMessageEvent, label: str = None) -> str:
        uid = _uid(event)
        if label:
            account = await self.db.get_account(uid, label)
            if not account:
                return f"未找到标签为「{label}」的绑定\n使用 /power status 查看已绑定房间"
            return await self._query_single(account)
        else:
            accounts = await self.db.get_accounts_by_user(uid)
            if not accounts:
                return ("你还没有绑定账号!\n"
                        "使用 /power bind <标签> <学号> <密码> <校区> <楼栋> <房间号> 绑定\n"
                        "例如: /power bind 宿舍 <学号> <密码> 沁园 沁园22栋 214")
            if len(accounts) == 1:
                return await self._query_single(accounts[0])
            # Multiple rooms — query all
            lines = ["⚡ 电费查询结果"]
            for acc in accounts:
                try:
                    result = await self._query_single_raw(acc)
                    lines.append(f"\n📌 [{acc.room_label}] {acc.loudong_id.split('&')[-1]} {acc.room_id.split('&')[-1]}")
                    lines.append(f"   余额: {self.api.parse_balance(result)} 度")
                except Exception as e:
                    lines.append(f"\n📌 [{acc.room_label}] 查询失败: {e}")
            return "\n".join(lines)

    async def _query_single(self, account: PowerAccount) -> str:
        result = await self._query_single_raw(account)
        balance = self.api.parse_balance(result)
        await self.db.add_record(account.id, balance)

        # Usage estimation
        records = await self.db.get_records(account.id, 10)
        records.reverse()  # oldest first
        est = self.api.estimate_daily_consumption(records)

        label = f"{account.loudong_id} {account.room_id}"
        msg = self.api.format_result(result, label)
        if est["enough_data"]:
            msg += (f"\n📊 预计每日用电: {est['daily']} 度\n"
                    f"   预计可用: {est['days_remaining']} 天")
        return msg

    async def _query_single_raw(self, account: PowerAccount) -> dict:
        token = account.token
        if not token or not account.token_is_valid():
            token = await self.api.login(account.student_id, account.get_password())
            await self.db.update_token(account.user_id, account.room_label, token)
        params = self.api.build_room_params(account.room_id, account.xiaoqu_id, account.loudong_id)
        result, new_token = await self.api.query_with_refresh(
            token, account.student_id, account.get_password(), params)
        if new_token:
            await self.db.update_token(account.user_id, account.room_label, new_token)
        return result

    # ---- Bind ----

    async def _do_bind(self, event: AstrMessageEvent, args: list) -> str:
        if len(args) < 6:
            return ("用法: /power bind <标签> <学号> <密码> <校区> <楼栋> <房间号>\n"
                    "例如: /power bind 宿舍 <学号> <密码> 沁园 沁园22栋 214\n"
                    "标签用于区分多房间, 如: 宿舍, 实验室, 老家")
        label, sid, pwd, campus, building, room = args[0], args[1], args[2], args[3], args[4], args[5]
        try:
            token = await self.api.login(sid, pwd)
        except Exception as e:
            return f"登录失败: {e}"
        xq, ld, rm, err = await self.api.resolve_room(token, campus, building, room)
        if err:
            return f"绑定失败: {err}"
        uid = _uid(event)
        await self.db.upsert_account(uid, sid, pwd, rm, label, xq, ld)
        await self.db.update_token(uid, label, token)
        return (f"✅ 绑定成功! [{label}]\n"
                f"  学号: {sid}\n  校区: {campus}\n  楼栋: {building}\n  房间: {room}\n\n"
                f"使用 /power {label} 查询该房间电量")

    # ---- Bindraw ----

    async def _do_bindraw(self, event: AstrMessageEvent, args: list) -> str:
        if len(args) < 6:
            return ("用法: /power bindraw <标签> <学号> <密码> <xiaoqu_id> <loudong_id> <room_id>\n"
                    "例如: /power bindraw 宿舍 <学号> <密码> 3&沁园 15&沁园22栋 16072&214")
        label, sid, pwd, xq, ld, rm = args[0], args[1], args[2], args[3], args[4], args[5]
        try:
            token = await self.api.login(sid, pwd)
        except Exception as e:
            return f"登录失败: {e}"
        uid = _uid(event)
        await self.db.upsert_account(uid, sid, pwd, rm, label, xq, ld)
        await self.db.update_token(uid, label, token)
        return f"✅ 绑定成功! [{label}]  学号: {sid}\n使用 /power {label} 查询电量"

    # ---- Unbind ----

    async def _do_unbind(self, event: AstrMessageEvent, args: list) -> str:
        uid = _uid(event)
        if not args:
            accounts = await self.db.get_accounts_by_user(uid)
            if not accounts:
                return "你还没有绑定账号"
            labels = [a.room_label for a in accounts]
            return ("请指定要解绑的标签:\n/power unbind " + "\n/power unbind ".join(labels))
        label = args[0]
        if await self.db.delete_account(uid, label):
            return f"✅ 已解绑 [{label}]"
        return f"未找到标签为「{label}」的绑定"

    # ---- Sub ----

    async def _do_sub(self, event: AstrMessageEvent, args: list) -> str:
        uid = _uid(event)
        label = args[0] if args and not args[0].isdigit() else "default"
        rest = args[1:] if (args and not args[0].isdigit()) else args

        account = await self.db.get_account(uid, label)
        if not account:
            return f"未找到标签为「{label}」的绑定\n使用 /power status 查看已绑定房间"

        interval = int(rest[0]) if rest and rest[0].isdigit() else self.config.get("default_interval", 60)
        threshold = float(rest[1]) if len(rest) >= 2 else self.config.get("default_threshold", 10.0)
        critical = float(rest[2]) if len(rest) >= 3 else self.config.get("default_critical_threshold", 5.0)

        await self.db.upsert_subscription(
            session_id=event.unified_msg_origin,
            account_id=account.id,
            interval_minutes=interval,
            threshold=threshold,
            critical_threshold=critical,
        )
        return (f"✅ 订阅已开启 [{label}]\n"
                f"  检查间隔: {interval} 分钟\n"
                f"  普通告警: 低于 {threshold} 度\n"
                f"  严重告警: 低于 {critical} 度 (提高告警频率)")

    # ---- Unsub ----

    async def _do_unsub(self, event: AstrMessageEvent, args: list) -> str:
        label = args[0] if args else None
        uid = _uid(event)
        if label:
            account = await self.db.get_account(uid, label)
            if not account:
                return f"未找到标签为「{label}」的绑定"
            account_id = account.id
        else:
            account_id = None
        if await self.db.disable_subscription(event.unified_msg_origin, account_id):
            return "✅ 已取消订阅"
        return "当前没有活跃的订阅"

    # ---- Status ----

    async def _do_status(self, event: AstrMessageEvent) -> str:
        uid = _uid(event)
        accounts = await self.db.get_accounts_by_user(uid)
        if not accounts:
            return "你还没有绑定账号\n使用 /power bind 绑定"

        lines = ["📊 账号状态"]
        for acc in accounts:
            bld = acc.loudong_id.split("&")[-1]
            rm = acc.room_id.split("&")[-1]
            lines.append(f"\n  📌 [{acc.room_label}] {acc.student_id}")
            lines.append(f"     {bld} {rm}号房")
            if acc.token:
                h = self.api.token_remaining_hours(acc.token)
                lines.append(f"     Token: {'有效' if h > 0 else '已过期'} ({h:.0f}h)")
            else:
                lines.append(f"     Token: 未缓存")

            sub = await self.db.get_subscription_by_account(acc.id)
            if sub:
                lines.append(f"     📬 订阅: 每{sub.interval_minutes}分钟, "
                             f"告警<{sub.threshold}度, 严重<{sub.critical_threshold}度")
            else:
                lines.append(f"     📬 未订阅")

        lines.append(f"\n共 {len(accounts)} 个绑定\n"
                      "使用 /power history [标签] 查看历史")
        return "\n".join(lines)

    # ---- History ----

    async def _do_history(self, event: AstrMessageEvent, args: list) -> str:
        uid = _uid(event)
        label = args[0] if args else "default"
        account = await self.db.get_account(uid, label)
        if not account:
            accounts = await self.db.get_accounts_by_user(uid)
            if not accounts:
                return "你还没有绑定账号"
            # Try to use first account
            account = accounts[0]
            label = account.room_label

        records = await self.db.get_records(account.id, 10)
        if not records:
            return f"[{label}] 暂无历史记录\n使用 /power {label} 查询一次后开始记录"

        bld = account.loudong_id.split("&")[-1]
        rm = account.room_id.split("&")[-1]
        lines = [f"📈 余额历史 [{label}] — {bld} {rm}号房", "-" * 28]
        for rec in reversed(records):
            t = rec.recorded_at.strftime("%m/%d %H:%M") if rec.recorded_at else "?"
            lines.append(f"  {t}  |  {rec.balance} 度")

        if len(records) >= 2:
            est = self.api.estimate_daily_consumption(list(reversed(records)))
            if est["enough_data"]:
                lines.append("-" * 28)
                lines.append(f"📊 日均用电: {est['daily']} 度")
                lines.append(f"   预计可用: {est['days_remaining']} 天")
        return "\n".join(lines)

    # ---- Set ----

    async def _do_set(self, event: AstrMessageEvent, args: list) -> str:
        if len(args) < 4:
            return ("用法: /power set <标签> <校区名> <楼栋名> <房间号>\n"
                    "例如: /power set 宿舍 沁园 沁园23栋 301")
        label, campus, building, room = args[0], args[1], args[2], args[3]
        uid = _uid(event)
        account = await self.db.get_account(uid, label)
        if not account:
            return f"未找到标签为「{label}」的绑定"
        token = account.token
        if not token or not account.token_is_valid():
            try:
                token = await self.api.login(account.student_id, account.get_password())
            except Exception as e:
                return f"登录失败: {e}"
        xq, ld, rm, err = await self.api.resolve_room(token, campus, building, room)
        if err:
            return f"修改失败: {err}"
        async with self.db.async_session() as session:
            stmt = select(PowerAccount).where(PowerAccount.id == account.id)
            result = await session.execute(stmt)
            acc = result.scalar_one_or_none()
            if acc:
                acc.xiaoqu_id = xq; acc.loudong_id = ld; acc.room_id = rm
                await session.commit()
        return f"✅ [{label}] 已更新: {campus} {building} {room}"

    # ---- Setraw ----

    async def _do_setraw(self, event: AstrMessageEvent, args: list) -> str:
        if len(args) < 4:
            return "用法: /power setraw <标签> <xiaoqu_id> <loudong_id> <room_id>"
        label, xq, ld, rm = args[0], args[1], args[2], args[3]
        uid = _uid(event)
        account = await self.db.get_account(uid, label)
        if not account:
            return f"未找到标签为「{label}」的绑定"
        async with self.db.async_session() as session:
            stmt = select(PowerAccount).where(PowerAccount.id == account.id)
            result = await session.execute(stmt)
            acc = result.scalar_one_or_none()
            if acc:
                acc.xiaoqu_id = xq; acc.loudong_id = ld; acc.room_id = rm
                await session.commit()
        return f"✅ [{label}] 已更新 (原始ID)"

    # ---- Campuses ----

    async def _do_campuses(self, event: AstrMessageEvent, args: list) -> str:
        uid = _uid(event)
        account = await self.db.get_account(uid)
        if not account:
            account = (await self.db.get_all_accounts() or [None])[0]
        if not account:
            return "请先绑定一个账号 (用于获取 Token)，然后才能查询校区列表"
        token = account.token
        if not token or not account.token_is_valid():
            try:
                token = await self.api.login(account.student_id, account.get_password())
            except Exception as e:
                return f"登录失败: {e}"
        try:
            campuses = await self.api.get_campuses(token)
        except Exception as e:
            return f"获取校区列表失败: {e}"
        lines = ["🏫 可选校区:"]
        for c in campuses:
            lines.append(f"  {c['name']}")
        lines.append(f"\n共 {len(campuses)} 个校区\n使用 /power buildings <校区名> 查看楼栋")
        return "\n".join(lines)

    # ---- Buildings ----

    async def _do_buildings(self, event: AstrMessageEvent, args: list) -> str:
        if not args:
            return "用法: /power buildings <校区名>\n例如: /power buildings 沁园"
        campus = args[0]

        uid = _uid(event)
        account = await self.db.get_account(uid)
        if not account:
            accounts = await self.db.get_all_accounts()
            account = accounts[0] if accounts else None
        if not account:
            return "请先绑定一个账号 (用于获取 Token)"
        token = account.token
        if not token or not account.token_is_valid():
            try:
                token = await self.api.login(account.student_id, account.get_password())
            except Exception as e:
                return f"登录失败: {e}"
        try:
            campuses = await self.api.get_campuses(token)
        except Exception as e:
            return f"获取校区列表失败: {e}"
        xq_id = next((c["value"] for c in campuses if c["name"] == campus), None)
        if not xq_id:
            names = [c["name"] for c in campuses]
            return f"未找到校区「{campus}」，可选: {', '.join(names)}"
        try:
            buildings = await self.api.get_buildings(token, xq_id)
        except Exception as e:
            return f"获取楼栋列表失败: {e}"
        lines = [f"🏢 {campus} — 楼栋列表:"]
        for b in buildings:
            lines.append(f"  {b['name']}")
        lines.append(f"\n共 {len(buildings)} 栋")
        return "\n".join(lines)

    # ---- List (admin) ----

    async def _do_list(self, event: AstrMessageEvent, args: list) -> str:
        accounts = await self.db.get_all_accounts()
        all_subs = await self.db.get_all_subscriptions()
        sub_map = {}
        for s in all_subs:
            if s.enabled:
                sub_map.setdefault(s.account_id, []).append(s)

        if not accounts:
            return "暂无绑定账号"

        lines = ["📋 全部绑定账号"]
        for acc in accounts:
            bld = acc.loudong_id.split("&")[-1]
            rm = acc.room_id.split("&")[-1]
            lines.append(f"\n  [{acc.room_label}] {acc.student_id} — {bld} {rm}号房")
            subs = sub_map.get(acc.id, [])
            if subs:
                for s in subs:
                    lines.append(f"    📬 订阅: 每{s.interval_minutes}分钟, "
                                 f"告警<{s.threshold}度, 严重<{s.critical_threshold}度")
            else:
                lines.append(f"    📬 未订阅")

        # Count stats
        total_subs = sum(len(v) for v in sub_map.values())
        lines.append(f"\n共 {len(accounts)} 个账号, {total_subs} 个活跃订阅")
        return "\n".join(lines)

    # ---- 后台轮询 ----

    async def _poll_all_subscriptions(self):
        subs = await self.db.get_all_enabled_subscriptions()
        now = datetime.now(timezone.utc)

        for sub in subs:
            try:
                if sub.last_check_at:
                    elapsed = (now - sub.last_check_at).total_seconds() / 60
                    if elapsed < sub.interval_minutes:
                        continue

                account = await self.db.get_account_by_id(sub.account_id)
                if not account:
                    continue

                token = account.token
                if not token or not account.token_is_valid():
                    token = await self.api.login(account.student_id, account.get_password())
                    await self.db.update_token(account.user_id, account.room_label, token)

                params = self.api.build_room_params(account.room_id, account.xiaoqu_id, account.loudong_id)
                result_data, new_token = await self.api.query_with_refresh(
                    token, account.student_id, account.get_password(), params)
                if new_token:
                    await self.db.update_token(account.user_id, account.room_label, new_token)

                balance = self.api.parse_balance(result_data)
                await self.db.update_subscription_check(sub.id, balance)
                await self.db.add_record(account.id, balance)

                if balance < sub.critical_threshold:
                    alert = (f"🚨 严重电量告警!\n"
                             f"  房间: [{account.room_label}] {account.loudong_id} {account.room_id}\n"
                             f"  剩余电量: {balance} 度\n"
                             f"  严重阈值: {sub.critical_threshold} 度\n"
                             f"  请立即充值!")
                    await self._send_to_session(sub.session_id, alert)
                    admin = self.config.get("admin_alert_session", "").strip()
                    if admin and admin != sub.session_id:
                        await self._send_to_session(admin, alert)
                elif balance < sub.threshold:
                    alert = (f"⚡ 电量告警!\n"
                             f"  房间: [{account.room_label}] {account.loudong_id} {account.room_id}\n"
                             f"  剩余电量: {balance} 度\n"
                             f"  告警阈值: {sub.threshold} 度\n"
                             f"  请及时充值!")
                    await self._send_to_session(sub.session_id, alert)
                    admin = self.config.get("admin_alert_session", "").strip()
                    if admin and admin != sub.session_id:
                        await self._send_to_session(admin, alert)

            except Exception as e:
                self.logger.error(f"订阅 {sub.id} 检查失败: {e}")

    async def _send_to_session(self, session_id: str, message: str):
        try:
            handler = self.context.get_send_handler(session_id)
            if handler:
                await handler.send("astrbot_plugin_nuist_power",
                                   [handler.build_message(message)])
        except Exception as e:
            self.logger.warning(f"发送到 {session_id} 失败: {e}")

    # ---- 帮助 ----

    @staticmethod
    def _help_text() -> str:
        return (
            "NUIST 电费查询 命令帮助\n"
            + "-" * 24 + "\n"
            "/power [标签]                 — 查询电量 (多房间默认全部)\n"
            "/power bind <标签> <学号> <密码> <校区> <楼栋> <房号>\n"
            "/power bindraw <标签> ...    — 绑定 (原始ID)\n"
            "/power unbind [标签]         — 解绑\n"
            "/power sub [标签] [分钟] [阈值] [严重阈值]\n"
            "/power unsub [标签]          — 取消订阅\n"
            "/power status                — 查看全部绑定状态\n"
            "/power history [标签]        — 余额历史 + 用量估算\n"
            "/power set <标签> <校区> <楼栋> <房号>\n"
            "/power setraw <标签> ...     — 修改 (原始ID)\n"
            "/power campuses              — 查看可选校区\n"
            "/power buildings <校区>      — 查看楼栋列表\n"
            "/power list                  — 查看全部账号与订阅\n"
            "/power help                  — 帮助\n"
            + "-" * 24 + "\n"
            "示例:\n"
            "  /power bind 宿舍 <学号> <密码> 沁园 沁园22栋 214\n"
            "  /power bind 实验室 <学号> <密码> 沁园 沁园22栋 101\n"
            "  /power 宿舍                 — 只查宿舍\n"
            "  /power sub 宿舍 60 10 5     — 订阅: 60分钟, <10度提醒, <5度严重\n"
            "  /power history 宿舍          — 查看宿舍用电历史"
        )
