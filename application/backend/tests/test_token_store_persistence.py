"""
Tests de persistance du Token Store — CRITICAL #1 (audit du 24/08/2026).

RÉSURRECTION DE TOKENS RÉVOQUÉS. Trois défauts chaînés :

1. `load()` conservait le cache périmé sur échec S3 (hors 404), sans le signaler.
2. `_save()` avalait toutes les exceptions.
3. `revoke()` retournait True dès que la mise à jour MÉMOIRE avait réussi.

Enchaînés : pendant une panne S3, un admin révoque un token, l'API confirme,
S3 n'est jamais écrit — et au prochain rechargement (TTL 5 min ou redémarrage
du conteneur), le token révoqué REDEVIENT ACTIF.

docker-compose ne fait tourner qu'un seul backend : le cache en mémoire est la
seule source d'état en exécution, ce qui rend le scénario pleinement réel.
"""
from unittest.mock import MagicMock

import pytest

from app.auth.token_store import TokenStore, TokenStorePersistenceError


class _FakeBody:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload


def _store(s3) -> TokenStore:
    """TokenStore branché sur un client S3 factice."""
    settings = MagicMock()
    settings.s3_bucket = "bucket-test"
    store = TokenStore(settings)
    store._s3_client = s3
    return store


def _tokens_payload(*tokens) -> bytes:
    import json
    return json.dumps({"tokens": list(tokens)}).encode()


TOKEN_A = {
    "hash": "a" * 64,
    "client_name": "client-a",
    "permissions": ["read"],
    "revoked": False,
}


class TestLoadFailureHandling:

    def test_missing_object_is_an_empty_store_not_an_error(self):
        """Premier démarrage : l'objet n'existe pas encore, ce n'est pas une panne."""
        s3 = MagicMock()
        s3.get_object.side_effect = Exception("NoSuchKey: the key does not exist")
        store = _store(s3)

        store.load(strict=True)  # ne doit PAS lever

        assert store._tokens == {}
        assert store.degraded is False

    def test_strict_load_propagates_real_failure(self):
        """Sur un chemin d'écriture, une panne S3 doit interrompre l'opération."""
        s3 = MagicMock()
        s3.get_object.side_effect = Exception("Connection timeout")
        store = _store(s3)

        with pytest.raises(TokenStorePersistenceError):
            store.load(strict=True)

        assert store.degraded is True

    def test_lenient_load_keeps_cache_but_flags_degraded(self):
        """
        En LECTURE, on préserve la disponibilité de l'authentification, mais on
        marque le cache comme suspect — ce que l'ancien code ne faisait pas.
        """
        s3 = MagicMock()
        s3.get_object.return_value = {"Body": _FakeBody(_tokens_payload(TOKEN_A))}
        store = _store(s3)
        store.load()
        assert store.degraded is False

        s3.get_object.side_effect = Exception("Connection timeout")
        store.load()  # ne lève pas

        assert TOKEN_A["hash"] in store._tokens  # cache conservé
        assert store.degraded is True


class TestSaveFailurePropagates:

    def test_save_raises_instead_of_swallowing(self):
        s3 = MagicMock()
        s3.get_object.return_value = {"Body": _FakeBody(_tokens_payload())}
        s3.put_object.side_effect = Exception("S3 down")
        store = _store(s3)

        with pytest.raises(TokenStorePersistenceError):
            store._save()

        assert store.degraded is True


class TestRevokeNeverLiesAboutPersistence:

    def test_revoke_raises_when_s3_write_fails(self):
        """Le cœur du CRITICAL : plus jamais de True sans persistance."""
        s3 = MagicMock()
        s3.get_object.return_value = {"Body": _FakeBody(_tokens_payload(dict(TOKEN_A)))}
        s3.put_object.side_effect = Exception("S3 down")
        store = _store(s3)

        with pytest.raises(TokenStorePersistenceError):
            store.revoke(TOKEN_A["hash"][:12])

    def test_failed_revoke_rolls_back_memory(self):
        """
        Après un échec, la mémoire ne doit pas diverger de S3.

        Un token marqué révoqué en mémoire seulement donnerait une révocation
        illusoire, effacée au prochain rechargement.
        """
        s3 = MagicMock()
        s3.get_object.return_value = {"Body": _FakeBody(_tokens_payload(dict(TOKEN_A)))}
        s3.put_object.side_effect = Exception("S3 down")
        store = _store(s3)

        with pytest.raises(TokenStorePersistenceError):
            store.revoke(TOKEN_A["hash"][:12])

        assert store._tokens[TOKEN_A["hash"]]["revoked"] is False
        assert "revoked_at" not in store._tokens[TOKEN_A["hash"]]
        assert store._cache_time == 0.0  # rechargement forcé au prochain accès

    def test_revoke_succeeds_and_persists_when_s3_is_healthy(self):
        """Contre-test : le chemin nominal doit rester intact."""
        s3 = MagicMock()
        s3.get_object.return_value = {"Body": _FakeBody(_tokens_payload(dict(TOKEN_A)))}
        store = _store(s3)

        assert store.revoke(TOKEN_A["hash"][:12]) is True
        assert store._tokens[TOKEN_A["hash"]]["revoked"] is True
        s3.put_object.assert_called_once()

    def test_revoked_token_does_not_resurrect(self):
        """
        Scénario complet du finding, joué de bout en bout.

        Panne S3 → révocation refusée (503 côté API) → retour de S3 →
        rechargement. Le token doit revenir tel qu'il est réellement sur S3,
        et l'admin doit savoir que sa révocation n'a PAS eu lieu.
        """
        s3 = MagicMock()
        s3.get_object.return_value = {"Body": _FakeBody(_tokens_payload(dict(TOKEN_A)))}
        s3.put_object.side_effect = Exception("S3 down")
        store = _store(s3)

        with pytest.raises(TokenStorePersistenceError):
            store.revoke(TOKEN_A["hash"][:12])

        # S3 revient ; il n'a jamais reçu l'écriture.
        s3.put_object.side_effect = None
        store.load()

        token = store._tokens[TOKEN_A["hash"]]
        assert token["revoked"] is False, (
            "Le token est actif — ce qui est CORRECT ici : la révocation a été "
            "refusée par une erreur, pas confirmée à tort. C'est précisément la "
            "différence avec l'ancien comportement, où l'API répondait 200."
        )


class TestCreateRollsBack:

    def test_create_raises_and_leaves_no_phantom_token(self):
        s3 = MagicMock()
        s3.get_object.return_value = {"Body": _FakeBody(_tokens_payload())}
        s3.put_object.side_effect = Exception("S3 down")
        store = _store(s3)

        with pytest.raises(TokenStorePersistenceError):
            store.create("client-x", ["read"])

        assert store._tokens == {}, (
            "Un token conservé en mémoire serait utilisable dans ce processus "
            "alors qu'il n'existe nulle part."
        )
        assert store._cache_time == 0.0

    def test_create_refuses_on_unreadable_store(self):
        """
        Écrire sur la base d'un cache dont on ignore l'état écraserait les
        tokens créés entre-temps.
        """
        s3 = MagicMock()
        s3.get_object.side_effect = Exception("Connection timeout")
        store = _store(s3)

        with pytest.raises(TokenStorePersistenceError):
            store.create("client-x", ["read"])

        s3.put_object.assert_not_called()
