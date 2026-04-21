"""
S3 DebateStore — Persistence des débats sur S3 Dell ECS Cloud Temple.

Configuration HYBRIDE SigV2/SigV4 requise pour Dell ECS :
- SigV2 pour les opérations data (PUT/GET/DELETE)
- SigV4 pour les opérations metadata (HEAD/LIST)

Ref: DESIGN/S3_DELL_ECS_CT.md

Structure S3 :
    debates/{debate_id}.json     → Débat complet sérialisé
    debates/{debate_id}_events.ndjson → Événements NDJSON bruts (replay)
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from ...config.settings import get_settings

logger = logging.getLogger(__name__)

__all__ = ["S3DebateStore", "get_debate_store"]

# Singleton
_store: Optional["S3DebateStore"] = None


def get_debate_store() -> "S3DebateStore":
    """Lazy singleton pour le store S3."""
    global _store
    if _store is None:
        _store = S3DebateStore()
    return _store


class S3DebateStore:
    """
    Persistence des débats sur S3 Dell ECS (hybride SigV2/SigV4).

    Opérations :
    - save_debate(debate_dict) → stocke le JSON complet
    - load_debate(debate_id) → charge un débat depuis S3
    - list_debates() → liste les débats sauvegardés
    - delete_debate(debate_id) → supprime un débat
    - save_events(debate_id, events) → stocke les événements NDJSON
    """

    PREFIX = "debates/"

    def __init__(self):
        settings = get_settings()
        self._bucket = settings.s3_bucket
        self._available = bool(
            settings.s3_endpoint and settings.s3_access_key and settings.s3_secret_key
        )

        if not self._available:
            logger.warning("⚠ S3 non configuré — persistence désactivée")
            return

        # Client SigV2 pour PUT/GET/DELETE (données)
        config_v2 = BotoConfig(
            region_name=settings.s3_region or "fr1",
            signature_version="s3",  # SigV2 legacy
            s3={"addressing_style": "path"},
            retries={"max_attempts": 3, "mode": "adaptive"},
        )
        self._client_data = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=config_v2,
        )

        # Client SigV4 pour HEAD/LIST (métadonnées)
        config_v4 = BotoConfig(
            region_name=settings.s3_region or "fr1",
            signature_version="s3v4",
            s3={"addressing_style": "path", "payload_signing_enabled": False},
            retries={"max_attempts": 3, "mode": "adaptive"},
        )
        self._client_meta = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=config_v4,
        )

        logger.info(
            f"✓ S3 DebateStore initialisé — bucket={self._bucket}, "
            f"endpoint={settings.s3_endpoint}"
        )

    @property
    def available(self) -> bool:
        return self._available

    # ── Save ────────────────────────────────────────────────

    def save_debate(self, debate_dict: Dict[str, Any]) -> bool:
        """
        Sauvegarde un débat complet sur S3 (JSON).

        Args:
            debate_dict: Le débat sérialisé en dict (via serialize_debate_full).

        Returns:
            True si succès, False sinon.
        """
        if not self._available:
            return False

        debate_id = debate_dict.get("id", "unknown")
        key = f"{self.PREFIX}{debate_id}.json"

        try:
            body = json.dumps(debate_dict, ensure_ascii=False, indent=2)
            self._client_data.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=body.encode("utf-8"),
                ContentType="application/json",
            )
            logger.info(f"✓ Débat {debate_id} sauvegardé sur S3 ({len(body)} bytes)")
            return True
        except ClientError as e:
            logger.error(f"✗ S3 save_debate {debate_id}: {e}")
            return False

    def save_events(self, debate_id: str, events: List[Dict]) -> bool:
        """
        Sauvegarde les événements NDJSON bruts (pour replay/export).

        Args:
            debate_id: ID du débat.
            events: Liste des événements NDJSON.

        Returns:
            True si succès, False sinon.
        """
        if not self._available:
            return False

        key = f"{self.PREFIX}{debate_id}_events.ndjson"

        try:
            lines = [
                json.dumps(e, ensure_ascii=False) for e in events
            ]
            body = "\n".join(lines)
            self._client_data.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=body.encode("utf-8"),
                ContentType="application/x-ndjson",
            )
            logger.info(
                f"✓ Événements {debate_id} sauvegardés sur S3 "
                f"({len(events)} events, {len(body)} bytes)"
            )
            return True
        except ClientError as e:
            logger.error(f"✗ S3 save_events {debate_id}: {e}")
            return False

    # ── Load ────────────────────────────────────────────────

    def load_debate(self, debate_id: str) -> Optional[Dict[str, Any]]:
        """
        Charge un débat depuis S3.

        Returns:
            Le dict du débat, ou None si non trouvé.
        """
        if not self._available:
            return None

        key = f"{self.PREFIX}{debate_id}.json"

        try:
            resp = self._client_data.get_object(
                Bucket=self._bucket, Key=key
            )
            body = resp["Body"].read().decode("utf-8")
            return json.loads(body)
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            logger.error(f"✗ S3 load_debate {debate_id}: {e}")
            return None

    def load_events(self, debate_id: str) -> Optional[List[Dict]]:
        """
        Charge les événements NDJSON d'un débat.

        Returns:
            Liste des événements, ou None si non trouvés.
        """
        if not self._available:
            return None

        key = f"{self.PREFIX}{debate_id}_events.ndjson"

        try:
            resp = self._client_data.get_object(
                Bucket=self._bucket, Key=key
            )
            body = resp["Body"].read().decode("utf-8")
            events = []
            for line in body.strip().split("\n"):
                if line.strip():
                    events.append(json.loads(line))
            return events
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            logger.error(f"✗ S3 load_events {debate_id}: {e}")
            return None

    # ── List ────────────────────────────────────────────────

    def list_debates(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Liste les débats sauvegardés sur S3.

        Returns:
            Liste de dicts {id, key, size, last_modified}.
        """
        if not self._available:
            return []

        try:
            resp = self._client_meta.list_objects_v2(
                Bucket=self._bucket,
                Prefix=self.PREFIX,
                MaxKeys=limit,
            )
            results = []
            for obj in resp.get("Contents", []):
                key = obj["Key"]
                # Filtrer : seulement les .json (pas _events.ndjson)
                if key.endswith(".json"):
                    debate_id = key.replace(self.PREFIX, "").replace(".json", "")
                    results.append({
                        "id": debate_id,
                        "key": key,
                        "size": obj["Size"],
                        "last_modified": obj["LastModified"].isoformat()
                        if hasattr(obj["LastModified"], "isoformat")
                        else str(obj["LastModified"]),
                    })
            return results
        except ClientError as e:
            logger.error(f"✗ S3 list_debates: {e}")
            return []

    # ── Delete ──────────────────────────────────────────────

    def delete_debate(self, debate_id: str) -> bool:
        """Supprime un débat et ses événements de S3."""
        if not self._available:
            return False

        try:
            for suffix in [".json", "_events.ndjson"]:
                key = f"{self.PREFIX}{debate_id}{suffix}"
                try:
                    self._client_data.delete_object(
                        Bucket=self._bucket, Key=key
                    )
                except ClientError:
                    pass  # Ignore si le fichier n'existe pas
            logger.info(f"✓ Débat {debate_id} supprimé de S3")
            return True
        except Exception as e:
            logger.error(f"✗ S3 delete_debate {debate_id}: {e}")
            return False

    # ── Health check ────────────────────────────────────────

    def test_connectivity(self) -> Dict[str, Any]:
        """Teste la connectivité S3."""
        if not self._available:
            return {"status": "disabled", "details": "S3 non configuré"}

        try:
            self._client_meta.head_bucket(Bucket=self._bucket)
            return {"status": "ok", "bucket": self._bucket}
        except ClientError as e:
            return {"status": "error", "details": str(e)}
