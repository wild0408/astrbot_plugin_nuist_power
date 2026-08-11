"""
astrbot_plugin_nuist_power
NUIST 电费查询插件 — AstrBot v4+

命令:
  /power                    - 查询电量
  /power bind <学号> <密码> <校区> <楼栋> <房间号>
  /power bindraw <学号> <密码> <xiaoqu_id> <loudong_id> <room_id>
  /power unbind             - 解绑
  /power sub [分钟] [阈值] [严重阈值]
  /power unsub              - 取消订阅
  /power status             - 查看状态
  /power history            - 余额历史 + 用量估算
  /power set <校区> <楼栋> <房间号>
  /power setraw <xiaoqu_id> <loudong_id> <room_id>
  /power campuses           - 查看校区
  /power buildings <校区>   - 查看楼栋
  /power list               - 查看全部账号
  /power help               - 帮助
"""
import asyncio
import os
import time
from datetime import datetime, timezone

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger
from astrbot.api.web import json_response, error_response, request
from sqlalchemy import select

from .api import NUISTPowerAPI
from .models import DBManager, PowerAccount

FALLBACK_CAMPUSES = ["沁园", "晖园", "硕园", "文园", "人才公寓三期", "商铺"]


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
        self.db = DBManager(f"sqlite+aiosqlite:///{os.path.join(data_dir, 'power.db')}")
        asyncio.create_task(self._init_and_poll())

        # ---- WebUI API ----
        PLUGIN_NAME = "astrbot_plugin_nuist_power"
        context.register_web_api(f"/{PLUGIN_NAME}/dashboard/overview", self._web_overview, ["GET"], "仪表盘概览")
        context.register_web_api(f"/{PLUGIN_NAME}/dashboard/history", self._web_history, ["GET"], "余额历史")
        context.register_web_api(f"/{PLUGIN_NAME}/dashboard/history_grouped", self._web_history_grouped, ["GET"], "聚合历史")
        context.register_web_api(f"/{PLUGIN_NAME}/dashboard/all", self._web_all, ["GET"], "全部账号")

    async def _init_and_poll(self):
        try:
            await self.db.init()
            await self._sync_managed_accounts()
            self.logger.info("NUIST 电费插件初始化完成 [BUILD 20260809-2300]")
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

    # ---- Token helper ----

    async def _get_any_token(self, uid: str = None) -> str:
        if uid:
            acc = await self.db.get_account(uid)
            if acc and acc.token and acc.token_is_valid():
                return acc.token
        raise RuntimeError("no_accounts")

    # ---- WebUI ----

    async def _sync_managed_accounts(self):
        managed = self.config.get("managed_accounts", [])
        if not managed:
            return
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
                continue
            try:
                token = await self.api.login(sid, pwd)
                xq, ld, rm, err = await self.api.resolve_room(token, campus, building, room_number)
                if err:
                    self.logger.warning(f"WebUI {sid} 解析失败: {err}")
                    continue
                await self.db.upsert_account(target_user, sid, pwd, rm, xq, ld)
                await self.db.update_token(target_user, token)
                self.logger.info(f"WebUI 同步: {sid}")
            except Exception as e:
                self.logger.error(f"WebUI {sid} 同步失败: {e}")

    # ---- 命令分发 ----

    @filter.command("power")
    async def power_cmd(self, event: AstrMessageEvent):
        args = event.message_str.strip().split()
        if len(args) < 2:
            yield event.plain_result(await self._do_query(event))
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
        else:
            result = f"未知子命令: {sub}\n\n{self._help_text()}"
        yield event.plain_result(result)

    # ---- Query ----

    async def _do_query(self, event: AstrMessageEvent) -> str:
        uid = _uid(event)
        account = await self.db.get_account(uid)
        if not account:
            return (
                "你还没有绑定账号!\n\n"
                f"可选校区: {', '.join(FALLBACK_CAMPUSES)}\n"
                "先用 /power campuses 查看校区，/power buildings <校区> 查看楼栋\n"
                "然后: /power bind <学号> <密码> <校区> <楼栋> <房间号>\n"
                "例如: /power bind <学号> <密码> 沁园 沁园22栋 214"
            )
        return await self._query_single(account)

    async def _query_single(self, account: PowerAccount) -> str:
        result = await self._query_single_raw(account)
        balance = self.api.parse_balance(result)
        await self.db.add_record(account.id, balance)
        records = await self.db.get_records(account.id, 10)
        records.reverse()
        est = self.api.estimate_daily_consumption(records)
        bld = account.loudong_id.split("&")[-1]
        rm = account.room_id.split("&")[-1]
        label = f"{bld} {rm}号房"
        msg = self.api.format_result(result, label)
        if est["enough_data"]:
            msg += (f"\n📊 预计每日用电: {est['daily']} 度\n"
                    f"   预计可用: {est['days_remaining']} 天")
        return msg

    async def _query_single_raw(self, account: PowerAccount) -> dict:
        token = account.token
        if not token or not account.token_is_valid():
            token = await self.api.login(account.student_id, account.get_password())
            await self.db.update_token(account.user_id, token)
        params = self.api.build_room_params(account.room_id, account.xiaoqu_id, account.loudong_id)
        result, new_token = await self.api.query_with_refresh(
            token, account.student_id, account.get_password(), params)
        if new_token:
            await self.db.update_token(account.user_id, new_token)
        return result

    # ---- Bind ----

    async def _do_bind(self, event: AstrMessageEvent, args: list) -> str:
        if len(args) < 5:
            return (
                "用法: /power bind <学号> <密码> <校区> <楼栋> <房间号>\n\n"
                f"可选校区: {', '.join(FALLBACK_CAMPUSES)}\n"
                "先用 /power campuses 和 /power buildings <校区> 浏览\n\n"
                "例如: /power bind <学号> <密码> 沁园 沁园22栋 214"
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
        return (f"✅ 绑定成功!\n  学号: {sid}\n  校区: {campus}\n"
                f"  楼栋: {building}\n  房间: {room}\n\n使用 /power 查询电量")

    async def _do_bindraw(self, event: AstrMessageEvent, args: list) -> str:
        if len(args) < 5:
            return ("用法: /power bindraw <学号> <密码> <xiaoqu_id> <loudong_id> <room_id>\n"
                    "例如: /power bindraw <学号> <密码> 3&沁园 15&沁园22栋 16072&214")
        sid, pwd, xq, ld, rm = args[0], args[1], args[2], args[3], args[4]
        try:
            token = await self.api.login(sid, pwd)
        except Exception as e:
            return f"登录失败: {e}"
        uid = _uid(event)
        await self.db.upsert_account(uid, sid, pwd, rm, xq, ld)
        await self.db.update_token(uid, token)
        return f"✅ 绑定成功! (原始ID)\n  学号: {sid}\n使用 /power 查询电量"

    async def _do_unbind(self, event: AstrMessageEvent, args: list) -> str:
        if await self.db.delete_account(_uid(event)):
            return "✅ 已解绑账号"
        return "你还没有绑定账号"

    # ---- Sub ----

    async def _do_sub(self, event: AstrMessageEvent, args: list) -> str:
        uid = _uid(event)
        account = await self.db.get_account(uid)
        if not account:
            return "请先绑定账号: /power bind <学号> <密码> <校区> <楼栋> <房间号>"
        interval = int(args[0]) if args and args[0].isdigit() else self.config.get("default_interval", 60)
        threshold = float(args[1]) if len(args) >= 2 else self.config.get("default_threshold", 10.0)
        critical = float(args[2]) if len(args) >= 3 else self.config.get("default_critical_threshold", 5.0)
        await self.db.upsert_subscription(
            session_id=event.unified_msg_origin, account_id=account.id,
            interval_minutes=interval, threshold=threshold, critical_threshold=critical)
        return (f"✅ 订阅已开启\n  检查间隔: {interval} 分钟\n"
                f"  普通告警: 低于 {threshold} 度\n  严重告警: 低于 {critical} 度")

    async def _do_unsub(self, event: AstrMessageEvent, args: list) -> str:
        if await self.db.disable_subscription(event.unified_msg_origin):
            return "✅ 已取消订阅"
        return "当前没有活跃的订阅"

    # ---- Status ----

    async def _do_status(self, event: AstrMessageEvent) -> str:
        uid = _uid(event)
        account = await self.db.get_account(uid)
        if not account:
            return "你还没有绑定账号\n使用 /power bind 绑定"
        bld = account.loudong_id.split("&")[-1]
        rm = account.room_id.split("&")[-1]
        lines = ["📊 账号状态", f"  学号: {account.student_id}",
                 f"  房间: {bld} {rm}号房"]
        if account.token:
            h = self.api.token_remaining_hours(account.token)
            lines.append(f"  Token: {'有效' if h > 0 else '已过期'} ({h:.0f}h)")
        else:
            lines.append("  Token: 未缓存")
        sub = await self.db.get_subscription_by_account(account.id)
        if sub:
            lines.append(f"  📬 订阅: 每{sub.interval_minutes}分钟, "
                         f"告警<{sub.threshold}度, 严重<{sub.critical_threshold}度")
        else:
            lines.append("  📬 未订阅 (使用 /power sub 开启)")
        return "\n".join(lines)

    # ---- History ----

    async def _do_history(self, event: AstrMessageEvent, args: list) -> str:
        uid = _uid(event)
        account = await self.db.get_account(uid)
        if not account:
            return "你还没有绑定账号"
        records = await self.db.get_records(account.id, 10)
        if not records:
            return "暂无历史记录\n使用 /power 查询一次后开始记录"
        bld = account.loudong_id.split("&")[-1]
        rm = account.room_id.split("&")[-1]
        lines = [f"📈 余额历史 — {bld} {rm}号房", "-" * 28]
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
        if len(args) < 3:
            return ("用法: /power set <校区名> <楼栋名> <房间号>\n"
                    f"可选校区: {', '.join(FALLBACK_CAMPUSES)}\n例如: /power set 沁园 沁园23栋 301")
        campus, building, room = args[0], args[1], args[2]
        uid = _uid(event)
        account = await self.db.get_account(uid)
        if not account:
            return "请先绑定账号"
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
            acc = (await session.execute(stmt)).scalar_one_or_none()
            if acc:
                acc.xiaoqu_id = xq; acc.loudong_id = ld; acc.room_id = rm
                await session.commit()
        return f"✅ 房间已更新: {campus} {building} {room}"

    async def _do_setraw(self, event: AstrMessageEvent, args: list) -> str:
        if len(args) < 3:
            return "用法: /power setraw <xiaoqu_id> <loudong_id> <room_id>\n例如: /power setraw 3&沁园 15&沁园22栋 16072&214"
        xq, ld, rm = args[0], args[1], args[2]
        uid = _uid(event)
        account = await self.db.get_account(uid)
        if not account:
            return "请先绑定账号"
        async with self.db.async_session() as session:
            stmt = select(PowerAccount).where(PowerAccount.id == account.id)
            acc = (await session.execute(stmt)).scalar_one_or_none()
            if acc:
                acc.xiaoqu_id = xq; acc.loudong_id = ld; acc.room_id = rm
                await session.commit()
        return f"✅ 房间已更新 (原始ID)"

    # ---- Campuses ----

    async def _do_campuses(self, event: AstrMessageEvent, args: list) -> str:
        try:
            token = await self._get_any_token(_uid(event))
            campuses = await self.api.get_campuses(token)
            lines = ["🏫 可选校区 (实时):"]
            for c in campuses:
                lines.append(f"  {c['name']}")
            lines.append(f"\n共 {len(campuses)} 个校区")
            return "\n".join(lines)
        except RuntimeError as e:
            if str(e) == "no_accounts":
                lines = ["🏫 可选校区 (离线, 绑定后可获取实时列表):"]
                for c in FALLBACK_CAMPUSES:
                    lines.append(f"  {c}")
                lines.append(f"\n共 {len(FALLBACK_CAMPUSES)} 个校区")
                return "\n".join(lines)
            return f"获取失败: {e}"

    async def _do_buildings(self, event: AstrMessageEvent, args: list) -> str:
        if not args:
            return f"用法: /power buildings <校区名>\n可选: {', '.join(FALLBACK_CAMPUSES)}"
        campus = args[0]
        try:
            token = await self._get_any_token(_uid(event))
        except RuntimeError as e:
            if str(e) == "no_accounts":
                return "请先绑定一个账号 (用于获取 Token)，然后才能查询楼栋列表"
            return f"获取 Token 失败: {e}"
        try:
            campuses = await self.api.get_campuses(token)
        except Exception as e:
            return f"获取校区列表失败: {e}"
        xq_id = next((c["value"] for c in campuses if c["name"] == campus), None)
        if not xq_id:
            return f"未找到校区「{campus}」，可选: {', '.join(c['name'] for c in campuses)}"
        try:
            buildings = await self.api.get_buildings(token, xq_id)
        except Exception as e:
            return f"获取楼栋列表失败: {e}"
        lines = [f"🏢 {campus} — 楼栋 ({len(buildings)} 栋):"]
        for b in buildings:
            lines.append(f"  {b['name']}")
        return "\n".join(lines)

    # ---- List ----

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
            lines.append(f"\n  {acc.student_id} — {bld} {rm}号房 ({acc.user_id})")
            subs = sub_map.get(acc.id, [])
            if subs:
                for s in subs:
                    lines.append(f"    📬 订阅: 每{s.interval_minutes}分钟, "
                                 f"告警<{s.threshold}度, 严重<{s.critical_threshold}度")
            else:
                lines.append(f"    📬 未订阅")
        total_subs = sum(len(v) for v in sub_map.values())
        lines.append(f"\n共 {len(accounts)} 个账号, {total_subs} 个活跃订阅")
        return "\n".join(lines)

    # ---- Poll ----

    async def _poll_all_subscriptions(self):
        subs = await self.db.get_all_enabled_subscriptions()
        now_ts = time.time()
        for sub in subs:
            try:
                # Respect interval: skip if not due yet
                if sub.last_check_at:
                    try:
                        last_ts = sub.last_check_at.timestamp()
                        if (now_ts - last_ts) / 60 < sub.interval_minutes:
                            continue
                    except Exception:
                        pass
                account = await self.db.get_account_by_id(sub.account_id)
                if not account:
                    continue
                token = account.token
                if not token or not account.token_is_valid():
                    token = await self.api.login(account.student_id, account.get_password())
                    await self.db.update_token(account.user_id, token)
                params = self.api.build_room_params(account.room_id, account.xiaoqu_id, account.loudong_id)
                result_data, new_token = await self.api.query_with_refresh(
                    token, account.student_id, account.get_password(), params)
                if new_token:
                    await self.db.update_token(account.user_id, new_token)
                balance = self.api.parse_balance(result_data)
                prev_balance = sub.last_balance
                await self.db.update_subscription_check(sub.id, balance)
                # Only record if balance changed (avoid duplicate history entries)
                if prev_balance is None or abs(balance - prev_balance) > 0.001:
                    await self.db.add_record(account.id, balance)

                bld = account.loudong_id.split("&")[-1]
                rm = account.room_id.split("&")[-1]
                if balance < sub.critical_threshold:
                    alert = (f"🚨 严重电量告警!\n  房间: {bld} {rm}号房\n"
                             f"  剩余电量: {balance} 度\n  严重阈值: {sub.critical_threshold} 度\n  请立即充值!")
                    await self._send_to_session(sub.session_id, alert)
                    admin = self.config.get("admin_alert_session", "").strip()
                    if admin and admin != sub.session_id:
                        await self._send_to_session(admin, alert)
                elif balance < sub.threshold:
                    alert = (f"⚡ 电量告警!\n  房间: {bld} {rm}号房\n"
                             f"  剩余电量: {balance} 度\n  告警阈值: {sub.threshold} 度\n  请及时充值!")
                    await self._send_to_session(sub.session_id, alert)
                    admin = self.config.get("admin_alert_session", "").strip()
                    if admin and admin != sub.session_id:
                        await self._send_to_session(admin, alert)
            except Exception as e:
                self.logger.error(f"订阅 {sub.id} 检查失败: {e}", exc_info=True)

    async def _send_to_session(self, session_id: str, message: str):
        try:
            # AstrBot v4.27+ uses context directly
            await self.context.send_message(session_id, message)
        except AttributeError:
            try:
                handler = self.context.get_send_handler(session_id)
                if handler:
                    await handler.send("astrbot_plugin_nuist_power", [handler.build_message(message)])
            except Exception:
                self.logger.warning(f"发送告警到 {session_id} 失败 (API 不兼容)")
        except Exception as e:
            self.logger.warning(f"发送告警到 {session_id} 失败: {e}")

    # ---- WebUI Handlers ----

    async def _web_overview(self):
        """Return dashboard overview: all accounts + subscriptions + latest balance."""
        try:
            accounts = await self.db.get_all_accounts()
            subs = await self.db.get_all_subscriptions()
            sub_map = {}
            for s in subs:
                sub_map.setdefault(s.account_id, []).append({
                    "id": s.id, "interval_minutes": s.interval_minutes,
                    "threshold": s.threshold, "critical_threshold": s.critical_threshold,
                    "enabled": s.enabled, "last_check_at": str(s.last_check_at) if s.last_check_at else None,
                    "last_balance": s.last_balance,
                })

            items = []
            for acc in accounts:
                records = await self.db.get_records(acc.id, limit=30)
                history = [{"balance": r.balance, "time": str(r.recorded_at)} for r in reversed(records)]

                # Calculate daily consumption from history
                daily_info = self.api.estimate_daily_consumption(list(reversed(records))) if len(records) >= 2 else None

                # Try to get latest balance
                latest_balance = history[-1]["balance"] if history else None

                items.append({
                    "id": acc.id,
                    "user_id": acc.user_id,
                    "student_id": acc.student_id,
                    "building": acc.loudong_id.split("&")[-1] if "&" in acc.loudong_id else acc.loudong_id,
                    "room": acc.room_id.split("&")[-1] if "&" in acc.room_id else acc.room_id,
                    "campus": acc.xiaoqu_id.split("&")[-1] if "&" in acc.xiaoqu_id else acc.xiaoqu_id,
                    "token_valid": acc.token_is_valid(),
                    "token_hours": self.api.token_remaining_hours(acc.token) if acc.token else 0,
                    "latest_balance": latest_balance,
                    "daily_consumption": daily_info,
                    "subscriptions": sub_map.get(acc.id, []),
                    "history": history,
                })
            return json_response({"accounts": items, "username": request.username})
        except Exception as e:
            return error_response(str(e))

    async def _web_history(self):
        """Return balance history for a specific account."""
        account_id = request.query.get("account_id", type=int)
        limit = request.query.get("limit", 30, type=int)
        if not account_id:
            return error_response("account_id is required")
        try:
            records = await self.db.get_records(account_id, limit=limit)
            data = [{"balance": r.balance, "time": str(r.recorded_at)} for r in reversed(records)]
            return json_response({"history": data, "account_id": account_id})
        except Exception as e:
            return error_response(str(e))

    async def _web_history_grouped(self):
        """Return balance history aggregated by day or month."""
        account_id = request.query.get("account_id", type=int)
        group = request.query.get("group", "raw")
        if not account_id:
            return error_response("account_id is required")
        if group not in ("raw", "day", "month"):
            return error_response("group must be raw, day, or month")
        try:
            from collections import defaultdict
            records = await self.db.get_records(account_id, limit=500)
            records = list(reversed(records))  # oldest first

            if group == "raw":
                data = [{"balance": r.balance, "time": str(r.recorded_at)} for r in records]
            else:
                buckets = defaultdict(list)
                for r in records:
                    t = r.recorded_at
                    if group == "day":
                        key = t.strftime("%Y-%m-%d")
                    else:  # month
                        key = t.strftime("%Y-%m")
                    buckets[key].append(r.balance)
                data = []
                for key in sorted(buckets.keys()):
                    vals = buckets[key]
                    data.append({
                        "balance": round(sum(vals) / len(vals), 4),
                        "time": key,
                        "count": len(vals),
                    })
            return json_response({"history": data, "account_id": account_id, "group": group})
        except Exception as e:
            return error_response(str(e))

    async def _web_all(self):
        """Return all accounts and subscriptions (admin view)."""
        try:
            accounts = await self.db.get_all_accounts()
            subs = await self.db.get_all_subscriptions()
            sub_map = {}
            for s in subs:
                sub_map.setdefault(s.account_id, []).append({
                    "id": s.id, "session_id": s.session_id,
                    "interval_minutes": s.interval_minutes,
                    "threshold": s.threshold, "critical_threshold": s.critical_threshold,
                    "enabled": s.enabled, "last_balance": s.last_balance,
                })
            items = []
            for acc in accounts:
                items.append({
                    "id": acc.id, "user_id": acc.user_id, "student_id": acc.student_id,
                    "building": acc.loudong_id.split("&")[-1] if "&" in acc.loudong_id else acc.loudong_id,
                    "room": acc.room_id.split("&")[-1] if "&" in acc.room_id else acc.room_id,
                    "campus": acc.xiaoqu_id.split("&")[-1] if "&" in acc.xiaoqu_id else acc.xiaoqu_id,
                    "token_valid": acc.token_is_valid(),
                    "subscriptions": sub_map.get(acc.id, []),
                })
            return json_response({"accounts": items, "total": len(items), "username": request.username})
        except Exception as e:
            return error_response(str(e))

    @staticmethod
    def _help_text() -> str:
        return (
            "NUIST 电费查询 命令帮助\n" + "-" * 24 + "\n"
            "/power                        — 查询电量\n"
            "/power bind <学号> <密码> <校区> <楼栋> <房号>\n"
            "/power bindraw ...           — 绑定 (原始ID)\n"
            "/power unbind                — 解绑\n"
            "/power sub [分钟] [阈值] [严重阈值]\n"
            "/power unsub                 — 取消订阅\n"
            "/power status                — 查看状态\n"
            "/power history               — 余额历史 + 用量估算\n"
            "/power set <校区> <楼栋> <房号>\n"
            "/power setraw ...            — 修改 (原始ID)\n"
            "/power campuses              — 查看校区\n"
            "/power buildings <校区>      — 查看楼栋\n"
            "/power list                  — 查看全部账号\n"
            "/power help                  — 帮助\n" + "-" * 24 + "\n"
            "典型流程:\n"
            "  1. /power campuses          — 看看有哪些校区\n"
            "  2. /power buildings 沁园    — 看看沁园有哪些楼栋\n"
            "  3. /power bind <学号> <密码> 沁园 沁园22栋 214\n"
            "  4. /power                   — 查询电量\n"
            "  5. /power sub 60 10 5       — 订阅: 60分钟, <10度告警, <5度严重\n"
            "  6. /power history            — 查看用电趋势\n"
        )
