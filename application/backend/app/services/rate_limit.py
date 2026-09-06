"""
Rate limiting applicatif — findings HIGH #2 et #5 de l'audit du 24/08/2026.

PROBLÈME. Aucun contrôle de débit n'existait sur la création de débats, ouverte
par TROIS voies (REST `/api/v1/debates`, admin `/admin/api/debates`, outil MCP
`debate_create`). Chaque débat mobilise jusqu'à 5 LLMs plus un synthétiseur, sur
des questions pouvant atteindre 200 000 caractères : un porteur de token valide
pouvait donc épuiser le budget LLM en boucle. Symétriquement, la création de
tokens admin n'était pas limitée — un accès admin compromis produisait des
tokens sans fin.

DEUX GARDES COMPLÉMENTAIRES, car elles ne couvrent pas le même abus :

- le DÉBIT (`SlidingWindowLimiter`) borne les créations par unité de temps,
  contre les rafales ;
- le QUOTA (`enforce_active_debate_quota`) borne les débats simultanés d'un même
  client, contre l'accumulation lente. Un attaquant patient respectant le débit
  saturerait sinon les appels LLM concurrents.

PORTÉE. L'état est en mémoire de processus. C'est suffisant ici : le
docker-compose ne fait tourner qu'UN backend, et le registre `_active_debates`
est déjà lui-même en mémoire — un limiteur distribué n'apporterait aucune
garantie que l'application ne possède pas déjà. Redis est déclaré dans les
settings et les dépendances, mais n'est importé nulle part dans le code : s'en
servir ici introduirait une dépendance réelle pour une garantie que le
déploiement actuel ne peut pas exploiter. À reconsidérer le jour où plusieurs
backends tourneront en parallèle.

CLÉ. Le `client_name` du token, identité déjà utilisée pour la propriété des
débats (`debate.owner`) par les trois voies.
"""
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Iterable, Optional

from ..config.settings import get_settings

__all__ = [
    "RateLimitExceeded",
    "SlidingWindowLimiter",
    "get_debate_creation_limiter",
    "get_token_creation_limiter",
    "enforce_active_debate_quota",
    "reset_rate_limiters",
]


class RateLimitExceeded(Exception):
    """
    Débit ou quota dépassé.

    `retry_after` porte le nombre de secondes à attendre quand il est connu
    (fenêtre glissante). Il vaut None pour un quota de ressources simultanées :
    l'attente y dépend de la fin d'un débat, pas de l'écoulement du temps —
    annoncer un délai serait mensonger.
    """

    def __init__(self, message: str, retry_after: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after


class SlidingWindowLimiter:
    """
    Fenêtre glissante par clé.

    Fenêtre glissante et non compteur à intervalle fixe : un compteur remis à
    zéro à heure ronde autorise le double de la limite à cheval sur deux
    intervalles.
    """

    def __init__(self, max_events: int, window_seconds: float):
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._events: Dict[str, Deque[float]] = defaultdict(deque)

    def check(self, key: str, *, now: Optional[float] = None) -> None:
        """
        Enregistre une tentative et lève si la limite est franchie.

        L'appel qui dépasse la limite n'est PAS enregistré : sinon une rafale
        continue repousserait indéfiniment la fenêtre et le client resterait
        bloqué bien après avoir cessé.
        """
        if self.max_events <= 0:
            return  # limite désactivée

        now = time.monotonic() if now is None else now
        bucket = self._events[key]

        horizon = now - self.window_seconds
        while bucket and bucket[0] <= horizon:
            bucket.popleft()

        if len(bucket) >= self.max_events:
            retry_after = max(1, int(bucket[0] + self.window_seconds - now) + 1)
            raise RateLimitExceeded(
                f"Limite de {self.max_events} requêtes par "
                f"{int(self.window_seconds)}s atteinte",
                retry_after=retry_after,
            )

        bucket.append(now)

    def reset(self, key: Optional[str] = None) -> None:
        """Vide l'historique (une clé, ou tout). Réservé aux tests."""
        if key is None:
            self._events.clear()
        else:
            self._events.pop(key, None)


# ============================================================
# Limiteurs partagés
# ============================================================

_debate_limiter: Optional[SlidingWindowLimiter] = None
_token_limiter: Optional[SlidingWindowLimiter] = None


def get_debate_creation_limiter() -> SlidingWindowLimiter:
    """Limiteur de création de débats, commun aux trois voies d'entrée."""
    global _debate_limiter
    if _debate_limiter is None:
        settings = get_settings()
        _debate_limiter = SlidingWindowLimiter(
            max_events=settings.rate_limit_debates_per_minute,
            window_seconds=60.0,
        )
    return _debate_limiter


def get_token_creation_limiter() -> SlidingWindowLimiter:
    """Limiteur de création de tokens admin (HIGH #5)."""
    global _token_limiter
    if _token_limiter is None:
        settings = get_settings()
        _token_limiter = SlidingWindowLimiter(
            max_events=settings.rate_limit_tokens_per_minute,
            window_seconds=60.0,
        )
    return _token_limiter


def reset_rate_limiters() -> None:
    """Réinitialise les limiteurs partagés. Réservé aux tests."""
    global _debate_limiter, _token_limiter
    _debate_limiter = None
    _token_limiter = None


# ============================================================
# Quota de débats simultanés
# ============================================================

# Statuts considérés comme consommant des ressources LLM.
_ACTIVE_STATUSES = {"created", "running", "paused"}


def count_active_debates(debates: Iterable, client_name: str) -> int:
    """Compte les débats non terminés appartenant à ce client."""
    total = 0
    for debate in debates:
        if getattr(debate, "owner", "") != client_name:
            continue
        status = getattr(debate, "status", None)
        # DebateStatus hérite de str : `.value` si disponible, sinon la valeur.
        status_value = getattr(status, "value", status)
        if status_value in _ACTIVE_STATUSES:
            total += 1
    return total


def enforce_active_debate_quota(debates: Iterable, client_name: str) -> None:
    """
    Refuse un nouveau débat si le client en a déjà trop en cours.

    Complète le débit : sans ce quota, un client respectant la fenêtre
    accumulerait des débats simultanés et saturerait quand même les appels LLM.
    """
    settings = get_settings()
    limit = settings.rate_limit_max_active_debates
    if limit <= 0:
        return  # quota désactivé

    active = count_active_debates(debates, client_name)
    if active >= limit:
        raise RateLimitExceeded(
            f"Quota de {limit} débats simultanés atteint "
            f"({active} en cours). Attendez qu'un débat se termine."
        )
