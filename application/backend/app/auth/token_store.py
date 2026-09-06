# -*- coding: utf-8 -*-
"""
Token Store S3 avec cache mémoire TTL 5 minutes.

Si S3 n'est pas configuré, les tokens sont gérés en mémoire uniquement
(bootstrap key). Quand S3 est configuré, les tokens sont stockés dans
_system/tokens.json sur le bucket S3.

Pattern identique au starter-kit Cloud Temple, adapté aux noms de
settings AdviceRoom (s3_endpoint, s3_access_key, s3_secret_key, s3_bucket).
"""

import sys
import time
import json
import hashlib
from typing import Optional

from ..config.settings import get_settings

# =============================================================================
# Erreurs
# =============================================================================


class TokenStorePersistenceError(RuntimeError):
    """
    La persistance S3 des tokens a échoué.

    Levée par les chemins d'ÉCRITURE (create, revoke) pour qu'un appelant ne
    puisse jamais croire une révocation acquise alors que S3 ne l'a pas
    enregistrée. Sans cela, la révocation ne vivait qu'en mémoire et le token
    redevenait actif au prochain rechargement — résurrection de token révoqué.
    """


# =============================================================================
# Token Store singleton
# =============================================================================

_token_store = None


def get_token_store() -> Optional["TokenStore"]:
    """Retourne le Token Store (None si S3 non configuré)."""
    return _token_store


def init_token_store():
    """Initialise le Token Store au démarrage (charge depuis S3 si configuré)."""
    global _token_store
    settings = get_settings()

    if settings.s3_endpoint and settings.s3_bucket:
        _token_store = TokenStore(settings)
        _token_store.load()
        print(
            f"🔑 Token Store S3 initialisé ({_token_store.count()} tokens)",
            file=sys.stderr,
        )
    else:
        print(
            "🔑 Token Store S3 non configuré (bootstrap key uniquement)",
            file=sys.stderr,
        )


# =============================================================================
# TokenStore — Stockage S3 + cache mémoire TTL
# =============================================================================


class TokenStore:
    """
    Gestion des tokens d'accès AdviceRoom.

    - Stockage sur S3 : _system/tokens.json
    - Cache mémoire avec TTL de 5 minutes
    - CRUD : create, list, info, revoke
    """

    CACHE_TTL = 300  # 5 minutes
    S3_KEY = "_system/tokens.json"

    def __init__(self, settings):
        self.settings = settings
        self._tokens: dict = {}  # hash → token_info
        self._cache_time: float = 0
        self._s3_client = None
        # True quand la dernière opération S3 a échoué : le cache mémoire peut
        # alors ignorer des révocations réellement enregistrées.
        self._degraded: bool = False

    @property
    def degraded(self) -> bool:
        """True si S3 est injoignable et que le cache mémoire est suspect."""
        return self._degraded

    def _get_s3(self):
        """Lazy-load du client S3 boto3 (config Dell ECS compatible)."""
        if self._s3_client is None:
            import boto3
            from botocore.config import Config as BotoConfig

            # Dell ECS requiert SigV2 ou payload_signing_enabled=False
            # (sinon XAmzContentSHA256Mismatch sur PutObject)
            config = BotoConfig(
                signature_version="s3",  # SigV2 legacy — compatible Dell ECS
                s3={"addressing_style": "path"},
            )
            self._s3_client = boto3.client(
                "s3",
                endpoint_url=self.settings.s3_endpoint,
                aws_access_key_id=self.settings.s3_access_key.get_secret_value(),
                aws_secret_access_key=self.settings.s3_secret_key.get_secret_value(),
                region_name=self.settings.s3_region,
                config=config,
            )
        return self._s3_client

    def load(self, strict: bool = False):
        """
        Charge les tokens depuis S3.

        Args:
            strict: si True, toute erreur autre qu'un objet absent est
                PROPAGÉE en TokenStorePersistenceError. À utiliser sur les
                chemins d'écriture : modifier un cache dont on ignore s'il est
                à jour, puis l'écrire, écrase les changements réels.
                Si False (chemin de LECTURE), le cache en place est conservé
                pour ne pas rendre toute l'authentification indisponible sur
                une panne S3 — mais le store est marqué dégradé, et les
                écritures resteront refusées tant que S3 ne répond pas.

        Un objet absent (NoSuchKey / 404) n'est PAS une erreur : c'est un store
        vide, légitime au premier démarrage.
        """
        try:
            s3 = self._get_s3()
            resp = s3.get_object(
                Bucket=self.settings.s3_bucket, Key=self.S3_KEY
            )
            data = json.loads(resp["Body"].read().decode())
            self._tokens = {t["hash"]: t for t in data.get("tokens", [])}
            self._cache_time = time.time()
            self._degraded = False
        except Exception as e:
            if "NoSuchKey" in str(e) or "404" in str(e):
                self._tokens = {}
                self._cache_time = time.time()
                self._degraded = False
                return
            # Le cache mémoire est désormais suspect : il peut ignorer des
            # révocations enregistrées sur S3 par un autre processus.
            self._degraded = True
            print(f"⚠️  Token Store S3 : {type(e).__name__}", file=sys.stderr)
            if strict:
                raise TokenStorePersistenceError(
                    "Token Store S3 illisible — opération refusée"
                ) from e

    def _save(self):
        """Sauvegarde les tokens sur S3."""
        try:
            s3 = self._get_s3()
            data = json.dumps(
                {"tokens": list(self._tokens.values())},
                indent=2,
                default=str,
            )
            s3.put_object(
                Bucket=self.settings.s3_bucket,
                Key=self.S3_KEY,
                Body=data.encode(),
                ContentType="application/json",
            )
            self._degraded = False
        except Exception as e:
            # Ne JAMAIS avaler : l'appelant doit pouvoir répondre 503 plutôt
            # que de confirmer une écriture qui n'a pas eu lieu.
            self._degraded = True
            print(f"⚠️  Token Store S3 save : {type(e).__name__}", file=sys.stderr)
            raise TokenStorePersistenceError(
                "Écriture du Token Store S3 impossible"
            ) from e

    def _maybe_refresh(self):
        """Rafraîchit le cache si le TTL est dépassé."""
        if time.time() - self._cache_time > self.CACHE_TTL:
            self.load()

    def get_by_hash(self, token_hash: str) -> Optional[dict]:
        """Cherche un token par son hash SHA-256. Vérifie l'expiration."""
        self._maybe_refresh()
        token = self._tokens.get(token_hash)
        if token and token.get("expires_at"):
            from datetime import datetime, timezone

            try:
                expires = datetime.fromisoformat(token["expires_at"])
                if datetime.now(timezone.utc) > expires:
                    return None  # Token expiré
            except (ValueError, TypeError):
                # FAIL-CLOSE : si expires_at est corrompu, rejeter le token
                return None
        return token

    def create(
        self,
        client_name: str,
        permissions: list,
        allowed_resources: list = None,
        expires_in_days: int = 90,
        email: str = "",
    ) -> dict:
        """Crée un nouveau token et le sauvegarde sur S3.

        Read-modify-write : recharge TOUJOURS depuis S3 avant d'ajouter
        pour éviter d'écraser les tokens existants (race condition ou cache périmé).
        """
        # strict=True : refuser d'écrire sur la base d'un cache dont on ignore
        # s'il est à jour — cela écraserait les tokens créés entre-temps.
        self.load(strict=True)
        import secrets
        from datetime import datetime, timezone, timedelta

        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

        now = datetime.now(timezone.utc)
        expires_at = None
        if expires_in_days and expires_in_days > 0:
            expires_at = (now + timedelta(days=expires_in_days)).isoformat()

        token_info = {
            "hash": token_hash,
            "client_name": client_name,
            "permissions": permissions,
            "allowed_resources": allowed_resources or [],
            "email": email,
            "created_at": now.isoformat(),
            "expires_at": expires_at,
            "revoked": False,
        }

        self._tokens[token_hash] = token_info
        try:
            self._save()
        except TokenStorePersistenceError:
            # Rollback mémoire : sans cela le token serait utilisable dans ce
            # processus alors qu'il n'existe nulle part, et disparaîtrait au
            # prochain rechargement.
            self._tokens.pop(token_hash, None)
            self._cache_time = 0.0  # force un rechargement au prochain accès
            raise

        return {"raw_token": raw_token, **token_info}

    def list_all(self) -> list:
        """Liste tous les tokens (sans les hash complets)."""
        self._maybe_refresh()
        return [
            {
                "client_name": t["client_name"],
                "permissions": t["permissions"],
                "email": t.get("email", ""),
                "hash_prefix": t["hash"][:12],
                "expires_at": t.get("expires_at"),
                "revoked": t.get("revoked", False),
            }
            for t in self._tokens.values()
        ]

    def revoke(self, hash_prefix: str) -> bool:
        """Révoque un token par préfixe de hash (≥8 caractères requis).

        Read-modify-write : recharge depuis S3 avant modification.
        """
        if len(hash_prefix) < 8:
            return False
        # strict=True : une révocation décidée sur un cache périmé, ou non
        # persistée, est pire qu'une révocation refusée — l'admin croirait le
        # token neutralisé.
        self.load(strict=True)
        for h, t in self._tokens.items():
            if h.startswith(hash_prefix):
                previous = dict(t)
                t["revoked"] = True
                t["revoked_at"] = (
                    __import__("datetime")
                    .datetime.now(__import__("datetime").timezone.utc)
                    .isoformat()
                )
                try:
                    self._save()
                except TokenStorePersistenceError:
                    # Rollback : ne pas laisser la mémoire divergée de S3.
                    self._tokens[h] = previous
                    self._cache_time = 0.0
                    raise
                # True signifie désormais « révoqué ET persisté sur S3 ».
                return True
        return False

    def count(self) -> int:
        """Nombre de tokens actifs."""
        return sum(
            1 for t in self._tokens.values() if not t.get("revoked", False)
        )
