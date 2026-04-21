# -*- coding: utf-8 -*-
"""
Client HTTP pour l'API admin AdviceRoom (/admin/api/*).

Gère l'authentification Bearer token et les appels REST.
Utilisé par commands.py et shell.py.
"""

import json
from typing import Optional


class AdminClient:
    """Client REST pour les endpoints /admin/api/*."""

    def __init__(self, base_url: str, token: str = "", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _headers(self) -> dict:
        """Headers communs avec Bearer token."""
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    # ── Admin API calls ───────────────────────────────────────

    async def health(self) -> dict:
        """GET /admin/api/health"""
        return await self._get("/admin/api/health")

    async def whoami(self) -> dict:
        """GET /admin/api/whoami"""
        return await self._get("/admin/api/whoami")

    async def list_tokens(self) -> dict:
        """GET /admin/api/tokens"""
        return await self._get("/admin/api/tokens")

    async def create_token(
        self,
        client_name: str,
        permissions: list,
        email: str = "",
        expires_in_days: int = 90,
    ) -> dict:
        """POST /admin/api/tokens"""
        return await self._post("/admin/api/tokens", {
            "client_name": client_name,
            "permissions": permissions,
            "email": email,
            "expires_in_days": expires_in_days,
        })

    async def revoke_token(self, hash_prefix: str) -> dict:
        """DELETE /admin/api/tokens/{hash_prefix}"""
        return await self._delete(f"/admin/api/tokens/{hash_prefix}")

    async def list_models(self) -> dict:
        """GET /admin/api/models"""
        return await self._get("/admin/api/models")

    async def list_debates(self) -> dict:
        """GET /admin/api/debates"""
        return await self._get("/admin/api/debates")

    async def get_debate(self, debate_id: str) -> dict:
        """GET /admin/api/debates/{id}"""
        return await self._get(f"/admin/api/debates/{debate_id}")

    async def delete_debate(self, debate_id: str) -> dict:
        """DELETE /admin/api/debates/{id}"""
        return await self._delete(f"/admin/api/debates/{debate_id}")

    async def logs(self) -> dict:
        """GET /admin/api/logs"""
        return await self._get("/admin/api/logs")

    async def llm_activity(self) -> dict:
        """GET /admin/api/llm-activity"""
        return await self._get("/admin/api/llm-activity")

    # ── Public API calls (pas d'auth admin requise) ───────────

    async def get_providers(self) -> dict:
        """GET /api/v1/providers — liste modèles (API publique)."""
        return await self._get("/api/v1/providers")

    async def create_debate(self, question: str, participants: list) -> dict:
        """POST /api/v1/debates — créer un débat."""
        return await self._post("/api/v1/debates", {
            "question": question,
            "participants": participants,
        })

    async def stream_debate(self, stream_url: str):
        """
        GET stream NDJSON — yield les événements un par un.

        Args:
            stream_url: chemin relatif (ex: /api/v1/debates/{id}/stream)

        Yields:
            dict — chaque événement NDJSON parsé
        """
        import httpx

        url = f"{self.base_url}{stream_url}"
        async with httpx.AsyncClient(timeout=600) as client:
            async with client.stream(
                "GET", url,
                headers={**self._headers(), "Accept": "application/x-ndjson"},
            ) as resp:
                resp.raise_for_status()
                buffer = ""
                async for raw_chunk in resp.aiter_text():
                    buffer += raw_chunk
                    lines = buffer.split("\n")
                    buffer = lines.pop()
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            continue

    # ── HTTP helpers ──────────────────────────────────────────

    async def _get(self, path: str) -> dict:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{self.base_url}{path}",
                    headers=self._headers(),
                )
                return self._parse(resp)
        except httpx.ConnectError:
            return {"status": "error", "message": f"Serveur non accessible: {self.base_url}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def _post(self, path: str, data: dict) -> dict:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}{path}",
                    headers=self._headers(),
                    json=data,
                )
                return self._parse(resp)
        except httpx.ConnectError:
            return {"status": "error", "message": f"Serveur non accessible: {self.base_url}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def _delete(self, path: str) -> dict:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.delete(
                    f"{self.base_url}{path}",
                    headers=self._headers(),
                )
                return self._parse(resp)
        except httpx.ConnectError:
            return {"status": "error", "message": f"Serveur non accessible: {self.base_url}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @staticmethod
    def _parse(resp) -> dict:
        """Parse une réponse HTTP en dict."""
        try:
            data = resp.json()
            if resp.status_code == 401:
                data["status"] = "error"
                data.setdefault("message", "Token admin requis (401)")
            return data
        except Exception:
            return {
                "status": "error",
                "message": resp.text or f"HTTP {resp.status_code}",
                "status_code": resp.status_code,
            }
