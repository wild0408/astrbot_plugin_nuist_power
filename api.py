"""
NUIST Power Query API - async httpx wrapper.
Handles OAuth login, electricity balance queries, and cascading
campus/building/room resolution.
"""
import base64
import json
import ssl
import time
from collections.abc import Callable
from datetime import timezone as _tz
from typing import List, Optional, Tuple

import httpx


class NUISTPowerAPI:
    """Async client for NUIST electricity query API."""

    BASE_URL = "https://icard.nuist.edu.cn"
    AUTH_URL = f"{BASE_URL}/berserker-auth/oauth/token"
    QUERY_URL = f"{BASE_URL}/charge/feeitem/getThirdData"
    CLIENT_AUTH = (
        "Basic bW9iaWxlX3NlcnZpY2VfcGxhdGZvcm06"
        "bW9iaWxlX3NlcnZpY2VfcGxhdGZvcm1fc2VjcmV0"
    )
    FEEITEMID = "448"
    TIMEOUT = 15

    def __init__(
        self,
        proxy: str = None,
        allow_insecure_tls_fallback: bool = True,
        on_tls_fallback: Optional[Callable[[str], None]] = None,
    ):
        self.proxy = proxy
        self.allow_insecure_tls_fallback = allow_insecure_tls_fallback
        self.on_tls_fallback = on_tls_fallback
        self._tls_fallback_warned = False

    def _client(self, verify: bool = True):
        kwargs = {
            "timeout": self.TIMEOUT,
            "verify": verify,
        }
        if self.proxy:
            kwargs["proxy"] = self.proxy
        return httpx.AsyncClient(**kwargs)

    @staticmethod
    def _is_certificate_error(exc: BaseException) -> bool:
        current = exc
        seen = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if isinstance(current, ssl.SSLCertVerificationError):
                return True
            if "CERTIFICATE_VERIFY_FAILED" in str(current).upper():
                return True
            current = current.__cause__ or current.__context__
        return False

    async def _post(self, url: str, *, headers: dict, data: dict) -> httpx.Response:
        """POST with a narrowly-scoped fallback for the campus server's broken chain."""
        try:
            async with self._client(verify=True) as client:
                return await client.post(url, headers=headers, data=data)
        except httpx.ConnectError as exc:
            if not (
                self.allow_insecure_tls_fallback
                and self._is_certificate_error(exc)
            ):
                raise
            if not self._tls_fallback_warned:
                if self.on_tls_fallback:
                    self.on_tls_fallback(
                        "icard.nuist.edu.cn 证书链校验失败，本次请求将对固定学校域名关闭 TLS 校验重试。"
                    )
                self._tls_fallback_warned = True
            async with self._client(verify=False) as client:
                return await client.post(url, headers=headers, data=data)

    @staticmethod
    def _json_response(resp: httpx.Response, operation: str) -> dict:
        try:
            try:
                text = resp.content.decode("utf-8")
            except UnicodeDecodeError:
                # Some error responses are GBK despite declaring UTF-8.
                text = resp.content.decode("gb18030")
            result = json.loads(text)
        except (UnicodeDecodeError, ValueError) as exc:
            raise RuntimeError(
                f"{operation} failed: HTTP {resp.status_code}, invalid JSON response"
            ) from exc
        if not isinstance(result, dict):
            raise RuntimeError(f"{operation} failed: unexpected response format")
        if not 200 <= resp.status_code < 300:
            detail = (
                result.get("error_description")
                or result.get("message")
                or result.get("msg")
                or result.get("error")
                or result
            )
            raise RuntimeError(
                f"{operation} failed: HTTP {resp.status_code}: {detail}"
            )
        return result

    # ---- Auth ----

    async def login(self, student_id: str, password: str) -> str:
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": self.CLIENT_AUTH,
            "synaccesssource": "pc",
            "origin": self.BASE_URL,
            "referer": f"{self.BASE_URL}/",
            "accept": "application/json, text/plain, */*",
            "user-agent": "Mozilla/5.0 (AstrBot NUIST Power Plugin)",
        }
        data = {
            "username": student_id,
            "password": password,
            "grant_type": "password",
            "scope": "all",
            "loginFrom": "pc",
            "logintype": "snoNew",
        }
        resp = await self._post(self.AUTH_URL, headers=headers, data=data)
        result = self._json_response(resp, "login")
        token = result.get("access_token")
        if not token:
            detail = (
                result.get("error_description")
                or result.get("message")
                or result.get("msg")
                or result.get("error")
                or result
            )
            raise RuntimeError(f"login failed: {detail}")
        return token

    # ---- Balance Query ----

    def _auth_headers(self, token: str) -> dict:
        return {
            "synjones-auth": f"bearer {token}",
            "synaccesssource": "pc",
            "origin": self.BASE_URL,
            "referer": f"{self.BASE_URL}/",
            "accept": "application/json, text/plain, */*",
            "user-agent": "Mozilla/5.0 (AstrBot NUIST Power Plugin)",
        }

    async def query(self, token: str, room_params: dict) -> dict:
        headers = self._auth_headers(token)
        resp = await self._post(self.QUERY_URL, headers=headers, data=room_params)
        result = self._json_response(resp, "power query")
        if str(result.get("code")) != "200":
            raise RuntimeError(
                result.get("message") or result.get("msg") or "unknown error"
            )
        return result

    async def query_with_refresh(
        self, token: str, student_id: str, password: str, room_params: dict
    ) -> Tuple[dict, Optional[str]]:
        try:
            result = await self.query(token, room_params)
            return result, None
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError):
            raise  # Network error — don''t try re-login, let caller handle
        except RuntimeError:
            pass
        new_token = await self.login(student_id, password)
        result = await self.query(new_token, room_params)
        return result, new_token

    # ---- Cascading Selector (Campus -> Building -> Room) ----

    async def _select_query(self, token: str, params: dict) -> List[dict]:
        headers = self._auth_headers(token)
        resp = await self._post(self.QUERY_URL, headers=headers, data=params)
        result = self._json_response(resp, "selector query")
        if str(result.get("code")) != "200":
            raise RuntimeError(
                result.get("message") or result.get("msg") or "select query failed"
            )
        data = result.get("map", {}).get("data", [])
        if not isinstance(data, list):
            raise RuntimeError("selector query failed: unexpected data format")
        return data

    async def get_campuses(self, token: str) -> List[dict]:
        return await self._select_query(token, {
            "type": "select", "level": "0", "feeitemid": self.FEEITEMID,
        })

    async def get_buildings(self, token: str, xiaoqu_id: str) -> List[dict]:
        return await self._select_query(token, {
            "type": "select", "level": "1", "feeitemid": self.FEEITEMID,
            "xiaoqu_id": xiaoqu_id,
        })

    async def get_rooms(self, token: str, xiaoqu_id: str,
                        loudong_id: str) -> List[dict]:
        return await self._select_query(token, {
            "type": "select", "level": "2", "feeitemid": self.FEEITEMID,
            "xiaoqu_id": xiaoqu_id, "loudong_id": loudong_id,
        })

    async def resolve_room(
        self, token: str, campus_name: str, building_name: str, room_number: str,
    ) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """
        Resolve human-readable names to API IDs.
        Returns (xiaoqu_id, loudong_id, room_id, error_message).
        """
        try:
            campuses = await self.get_campuses(token)
        except Exception as e:
            return None, None, None, f"cannot get campus list: {e}"

        xiaoqu_id = next(
            (c["value"] for c in campuses if c.get("name") == campus_name), None
        )
        if not xiaoqu_id:
            names = [c.get("name", "?") for c in campuses]
            return None, None, None, (
                f"campus '{campus_name}' not found. available: {', '.join(names)}"
            )

        try:
            buildings = await self.get_buildings(token, xiaoqu_id)
        except Exception as e:
            return None, None, None, f"cannot get building list: {e}"

        loudong_id = next(
            (b["value"] for b in buildings if b.get("name") == building_name), None
        )
        if not loudong_id:
            names = [b.get("name", "?") for b in buildings[:12]]
            return None, None, None, (
                f"building '{building_name}' not found in '{campus_name}'. "
                f"available: {', '.join(names)}"
            )

        try:
            rooms = await self.get_rooms(token, xiaoqu_id, loudong_id)
        except Exception as e:
            return None, None, None, f"cannot get room list: {e}"

        room_id = next(
            (r["value"] for r in rooms if r.get("name") == room_number), None
        )
        if not room_id:
            names = [r.get("name", "?") for r in rooms[:16]]
            return None, None, None, (
                f"room '{room_number}' not found in '{building_name}'. "
                f"available: {', '.join(names)}"
            )

        return xiaoqu_id, loudong_id, room_id, None

    # ---- Helpers ----

    @staticmethod
    def parse_balance(result: dict) -> float:
        show_data = result.get("map", {}).get("showData", {})
        for key, val in show_data.items():
            if "剩余" in key and "电量" in key:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    pass
        return -1.0

    @staticmethod
    def format_result(result: dict, room_label: str = "") -> str:
        show_data = result.get("map", {}).get("showData", {})
        lines = ["⚡ NUIST 电费查询结果"]
        if room_label:
            lines.append(f"📍 房间: {room_label}")
        lines.append("-" * 30)
        for key, val in show_data.items():
            unit = " 度" if "电" in key else ""
            lines.append(f"  {key}: {val}{unit}")
        lines.append("-" * 30)
        return "\n".join(lines)

    @staticmethod
    def decode_jwt(token: str) -> Optional[dict]:
        try:
            payload = token.split(".")[1]
            payload += "=" * (4 - len(payload) % 4)
            return json.loads(base64.urlsafe_b64decode(payload))
        except Exception:
            return None

    @staticmethod
    def estimate_daily_consumption(records: list) -> dict:
        """
        Estimate daily power consumption from a list of balance records.
        records should be sorted by time (oldest first).
        Returns {"daily": float, "days_remaining": float, "enough_data": bool}.
        """
        if len(records) < 2:
            return {"daily": 0, "days_remaining": 0, "enough_data": False}
        first = records[0]
        last = records[-1]
        consumed = first.balance - last.balance
        t1 = first.recorded_at
        t2 = last.recorded_at
        if t1.tzinfo is None:
            t1 = t1.replace(tzinfo=_tz.utc)
        if t2.tzinfo is None:
            t2 = t2.replace(tzinfo=_tz.utc)
        hours = (t2 - t1).total_seconds() / 3600
        if hours < 0.5 or consumed <= 0:
            return {"daily": 0, "days_remaining": 0, "enough_data": False}
        daily = (consumed / hours) * 24
        days = last.balance / daily if daily > 0 else 999
        return {"daily": round(daily, 2), "days_remaining": round(days, 1), "enough_data": True}

    @staticmethod
    def token_remaining_hours(token: str) -> float:
        data = NUISTPowerAPI.decode_jwt(token)
        if not data:
            return 0.0
        exp = data.get("exp", 0)
        remaining = exp - time.time()
        return max(0.0, remaining / 3600)

    @staticmethod
    def build_room_params(
        room_id: str, xiaoqu_id: str, loudong_id: str,
    ) -> dict:
        return {
            "type": "IEC", "level": "3", "feeitemid": NUISTPowerAPI.FEEITEMID,
            "xiaoqu_id": xiaoqu_id, "loudong_id": loudong_id, "room_id": room_id,
        }
