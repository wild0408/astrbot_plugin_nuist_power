"""
astrbot_plugin_nuist_power
NUIST 电费查询插件 — AstrBot v4+

命令:
  /power                              - 查询当前电量
  /power bind <学号> <密码> <校区> <楼栋> <房间号> - 绑定账号 (自动解析)
  /power bindraw <学号> <密码> <xiaoqu_id> <loudong_id> <room_id> - 绑定 (原始ID)
  /power unbind                       - 解绑账号
  /power sub [分钟] [阈值]            - 开启订阅告警
  /power unsub                        - 取消订阅
  /power status                       - 查看状态
  /power set <校区> <楼栋> <房间号>   - 修改房间
  /power setraw <xiaoqu_id> <loudong_id> <room_id> - 修改房间 (原始ID)
  /power help                         - 帮助
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

            if not campus or not building or not room_number:
                self.logger.warning(f"WebUI 账号 {sid} 缺少校区/楼栋/房间号，跳过")
                continue

            try:
                if not resolver_token:
                    resolver_token = await self.api.login(sid, pwd)

                xq, ld, rm, err = await self.api.resolve_room(
                    resolver_token, campus, building, room_number
                )
                if err:
                    self.logger.warning(f"WebUI 账号 {sid} 解析失败: {err}")
                    continue

                await self.db.upsert_account(
                    user_id=target_user, student_id=sid, password=pwd,
                    room_id=rm, xiaoqu_id=xq, loudong_id=ld,
                )
                self.logger.info(f"WebUI 账号已同步: {sid} -> {campus} {building} {room_number}")
            except Exception as e:
                self.logger.error(f"WebUI 账号 {sid} 同步失败: {e}")

    # ---- 命令分发 ----

    @filter.command("power")
    async def power_cmd(self, event: AstrMessageEvent):
        args = event.message_str.strip().split()
        if len(args) < 2:
            result = await self._do_query(event)
            yield event.plain_result(result)
            return

        sub = args[1].lower()
        if sub == "bind":
            result = await self._do_bind(event, args[2:])
        elif sub == "bindraw":
            result = await self._do_bindraw(event, args[2:])
        elif sub == "unbind":
            result = await self._do_unbind(event)
        elif sub == "sub":
            result = await self._do_sub(event, args[2:])
        elif sub == "unsub":
            result = await self._do_unsub(event)
        elif sub == "status":
            result = await self._do_status(event)
        elif sub == "set":
            result = await self._do_set(event, args[2:])
        elif sub == "setraw":
            result = await self._do_setraw(event, args[2:])
        elif sub == "help":
            result = self._help_text()
        else:
            result = f"未知子命令: {sub}\n\n{self._help_text()}"
        yield event.plain_result(result)

    # ---- query ----

    async def _do_query(self, event: AstrMessageEvent) -> str:
        uid = _uid(event)
        account = await self.db.get_account(uid)
        if not account:
            return (
                "你还没有绑定账号!\n"
                "使用 /power bind <学号> <密码> <校区> <楼栋> <房间号> 绑定\n"
                "例如: /power bind <学号> <密码> 沁园 沁园22栋 214"
            )

        token = account.token
        if not token or not account.token_is_valid():
            try:
                token = await self.api.login(account.student_id, account.get_password())
                await self.db.update_token(uid, token)
            except Exception as e:
                return f"登录失败: {e}"

        params = self.api.build_room_params(account.room_id, account.xiaoqu_id, account.loudong_id)
        try:
            result, new_token = await self.api.query_with_refresh(
                token, account.student_id, account.get_password(), params
            )
            if new_token:
                await self.db.update_token(uid, new_token)
            label = f"{account.loudong_id} {account.room_id}"
            return self.api.format_result(result, label)
        except Exception as e:
            return f"查询失败: {e}"

    # ---- bind ----

    async def _do_bind(self, event: AstrMessageEvent, args: list) -> str:
        if len(args) < 5:
            return (
                "用法: /power bind <学号> <密码> <校区名> <楼栋名> <房间号>\n"
                "例如: /power bind <学号> <密码> 沁园 沁园22栋 214\n"
                "提示: 校区可选 沁园/晖园/硕园/文园 等"
            )
        sid, pwd, campus, building, room = args[0], args[1], args[2], args[3], args[4]

        try:
            token = await self.api.login(sid, pwd)
        except Exception as e:
            return f"登录失败: {e}"

        xq, ld, rm, err = await self.api.resolve_room(token, campus, building, room)
        if err:
            return f"绑定失败: {err}"

        uid = _uid(event)
        await self.db.upsert_account(uid, sid, pwd, rm, xq, ld)
        await self.db.update_token(uid, token)

        return (
            f"✅ 绑定成功!\n"
            f"  学号: {sid}\n"
            f"  校区: {campus}\n"
            f"  楼栋: {building}\n"
            f"  房间: {room}\n\n"
            f"使用 /power 查询电量"
        )

    # ---- bindraw ----

    async def _do_bindraw(self, event: AstrMessageEvent, args: list) -> str:
        if len(args) < 5:
            return (
                "用法: /power bindraw <学号> <密码> <xiaoqu_id> <loudong_id> <room_id>\n"
                "例如: /power bindraw <学号> <密码> 3&沁园 15&沁园22栋 16072&214"
            )
        sid, pwd, xq, ld, rm = args[0], args[1], args[2], args[3], args[4]
        try:
            token = await self.api.login(sid, pwd)
        except Exception as e:
            return f"登录失败: {e}"

        uid = _uid(event)
        await self.db.upsert_account(uid, sid, pwd, rm, xq, ld)
        await self.db.update_token(uid, token)
        return f"✅ 绑定成功! (原始ID模式)\n  学号: {sid}\n  使用 /power 查询电量"

    # ---- unbind ----

    async def _do_unbind(self, event: AstrMessageEvent) -> str:
        uid = _uid(event)
        if await self.db.delete_account(uid):
            return "✅ 已解绑账号"
        return "你还没有绑定账号"

    # ---- sub ----

    async def _do_sub(self, event: AstrMessageEvent, args: list) -> str:
        uid = _uid(event)
        account = await self.db.get_account(uid)
        if not account:
            return "请先使用 /power bind 绑定账号"

        interval = int(args[0]) if args and args[0].isdigit() else self.config.get("default_interval", 60)
        threshold = float(args[1]) if len(args) >= 2 else self.config.get("default_threshold", 10.0)

        await self.db.upsert_subscription(
            session_id=event.unified_msg_origin,
            account_id=account.id,
            interval_minutes=interval,
            threshold=threshold,
        )
        return (
            f"✅ 订阅已开启\n"
            f"  检查间隔: {interval} 分钟\n"
            f"  告警阈值: {threshold} 度\n"
            f"  电量低于 {threshold} 度时会自动提醒"
        )

    # ---- unsub ----

    async def _do_unsub(self, event: AstrMessageEvent) -> str:
        if await self.db.disable_subscription(event.unified_msg_origin):
            return "✅ 已取消订阅"
        return "当前没有活跃的订阅"

    # ---- status ----

    async def _do_status(self, event: AstrMessageEvent) -> str:
        uid = _uid(event)
        account = await self.db.get_account(uid)
        if not account:
            return "你还没有绑定账号\n使用 /power bind 绑定"

        lines = [
            "📊 账号状态",
            f"  用户: {uid}",
            f"  学号: {account.student_id}",
            f"  校区: {account.xiaoqu_id}",
            f"  楼栋: {account.loudong_id}",
            f"  房间: {account.room_id}",
        ]
        if account.token:
            h = self.api.token_remaining_hours(account.token)
            lines.append(f"  Token: {'有效' if h > 0 else '已过期'} (剩余 {h:.0f} 小时)")
        else:
            lines.append("  Token: 未缓存")

        sub = await self.db.get_subscription(event.unified_msg_origin)
        if sub:
            lines.append("")
            lines.append("📬 订阅状态")
            lines.append(f"  间隔: {sub.interval_minutes} 分钟")
            lines.append(f"  阈值: {sub.threshold} 度")
            if sub.last_check_at:
                lines.append(f"  上次检查: {sub.last_check_at.strftime('%Y-%m-%d %H:%M')}")
            if sub.last_balance is not None:
                lines.append(f"  上次余额: {sub.last_balance} 度")
        else:
            lines.append("")
            lines.append("📬 订阅: 未开启 (使用 /power sub 开启)")
        return "\n".join(lines)

    # ---- set ----

    async def _do_set(self, event: AstrMessageEvent, args: list) -> str:
        if len(args) < 3:
            return "用法: /power set <校区名> <楼栋名> <房间号>\n例如: /power set 沁园 沁园22栋 214"
        campus, building, room = args[0], args[1], args[2]

        uid = _uid(event)
        account = await self.db.get_account(uid)
        if not account:
            return "请先使用 /power bind 绑定账号"

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
            stmt = select(PowerAccount).where(PowerAccount.user_id == uid)
            result = await session.execute(stmt)
            acc = result.scalar_one_or_none()
            if acc:
                acc.xiaoqu_id = xq
                acc.loudong_id = ld
                acc.room_id = rm
                await session.commit()

        return f"✅ 房间信息已更新\n  校区: {campus}\n  楼栋: {building}\n  房间: {room}"

    # ---- setraw ----

    async def _do_setraw(self, event: AstrMessageEvent, args: list) -> str:
        if len(args) < 3:
            return "用法: /power setraw <xiaoqu_id> <loudong_id> <room_id>\n例如: /power setraw 3&沁园 15&沁园22栋 16072&214"
        xq, ld, rm = args[0], args[1], args[2]

        uid = _uid(event)
        account = await self.db.get_account(uid)
        if not account:
            return "请先使用 /power bind 绑定账号"

        async with self.db.async_session() as session:
            stmt = select(PowerAccount).where(PowerAccount.user_id == uid)
            result = await session.execute(stmt)
            acc = result.scalar_one_or_none()
            if acc:
                acc.xiaoqu_id = xq
                acc.loudong_id = ld
                acc.room_id = rm
                await session.commit()
        return f"✅ 房间信息已更新 (原始ID)\n  {xq} / {ld} / {rm}"

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

                async with self.db.async_session() as session:
                    stmt = select(PowerAccount).where(PowerAccount.id == sub.account_id)
                    result = await session.execute(stmt)
                    account = result.scalar_one_or_none()

                if not account:
                    continue

                token = account.token
                if not token or not account.token_is_valid():
                    token = await self.api.login(account.student_id, account.get_password())
                    await self.db.update_token(account.user_id, token)

                params = self.api.build_room_params(account.room_id, account.xiaoqu_id, account.loudong_id)
                result_data, new_token = await self.api.query_with_refresh(
                    token, account.student_id, account.get_password(), params
                )
                if new_token:
                    await self.db.update_token(account.user_id, new_token)

                balance = self.api.parse_balance(result_data)
                await self.db.update_subscription_check(sub.id, balance)

                if 0 <= balance < sub.threshold:
                    alert = (
                        f"⚡ 电量告警!\n"
                        f"  房间: {account.loudong_id} {account.room_id}\n"
                        f"  剩余电量: {balance} 度\n"
                        f"  告警阈值: {sub.threshold} 度\n"
                        f"  请及时充值!"
                    )
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
                await handler.send(
                    "astrbot_plugin_nuist_power",
                    [handler.build_message(message)],
                )
        except Exception as e:
            self.logger.warning(f"发送消息到 {session_id} 失败: {e}")

    # ---- 帮助 ----

    @staticmethod
    def _help_text() -> str:
        return (
            "NUIST 电费查询 命令帮助\n"
            + "-" * 24 + "\n"
            "/power                        — 查询电量\n"
            "/power bind <学号> <密码> <校区> <楼栋> <房间号>\n"
            "                               绑定账号 (自动解析校区/楼栋/房间)\n"
            "/power bindraw <学号> <密码> <xiaoqu_id> <loudong_id> <room_id>\n"
            "                               绑定账号 (原始ID，高级用户)\n"
            "/power unbind                 — 解绑账号\n"
            "/power sub [分钟] [阈值]      — 开启订阅\n"
            "/power unsub                  — 取消订阅\n"
            "/power status                 — 查看状态\n"
            "/power set <校区> <楼栋> <房间号>\n"
            "                               修改房间 (自动解析)\n"
            "/power setraw <xiaoqu_id> <loudong_id> <room_id>\n"
            "                               修改房间 (原始ID)\n"
            "/power help                   — 显示帮助\n"
            + "-" * 24 + "\n"
            "示例:\n"
            "  /power bind <学号> <密码> 沁园 沁园22栋 214\n"
            "  /power sub 60 5"
        )
