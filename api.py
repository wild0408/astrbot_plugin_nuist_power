"""
NUIST Power Query API - async httpx wrapper.
Handles OAuth login, electricity balance queries, and cascading
campus/building/room resolution.
"""
import base64
import json
import time
from typing import Optional, Tuple, List

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

    # ---- Auth ----

    async def login(self, student_id: str, password: str) -> str:
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": self.CLIENT_AUTH,
            "synaccesssource": "pc",
            "origin": self.BASE_URL,
            "referer": f"{self.BASE_URL}/",
        }
        data = {
            "username": student_id,
            "password": password,
            "grant_type": "password",
            "scope": "all",
            "loginFrom": "pc",
            "logintype": "snoNew",
        }
        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            resp = await client.post(self.AUTH_URL, headers=headers, data=data)
            result = resp.json()
            token = result.get("access_token")
            if not token:
                raise RuntimeError(
                    f"login failed: {result.get('error_description', result)}"
                )
            return token

    # ---- Balance Query ----

    def _auth_headers(self, token: str) -> dict:
        return {
            "synjones-auth": f"bearer {token}",
            "synaccesssource": "pc",
            "origin": self.BASE_URL,
            "referer": f"{self.BASE_URL}/",
        }

    async def query(self, token: str, room_params: dict) -> dict:
        headers = self._auth_headers(token)
        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            resp = await client.post(
                self.QUERY_URL, headers=headers, data=room_params
            )
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
            result = resp.json()
            if result.get("code") != 200:
                raise RuntimeError(result.get("msg", "unknown error"))
            return result

    async def query_with_refresh(
        self, token: str, student_id: str, password: str, room_params: dict
    ) -> Tuple[dict, Optional[str]]:
        try:
            result = await self.query(token, room_params)
            return result, None
        except RuntimeError:
            pass
        new_token = await self.login(student_id, password)
        result = await self.query(new_token, room_params)
        return result, new_token

    # ---- Cascading Selector (Campus -> Building -> Room) ----

    async def _select_query(self, token: str, params: dict) -> List[dict]:
        headers = self._auth_headers(token)
        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            resp = await client.post(
                self.QUERY_URL, headers=headers, data=params
            )
            result = resp.json()
            if result.get("code") != 200:
                raise RuntimeError(result.get("msg", "select query failed"))
            return result.get("map", {}).get("data", [])

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
            try:
                v = float(val)
                return v
            except (ValueError, TypeError):
                continue
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
