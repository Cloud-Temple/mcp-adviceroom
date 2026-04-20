#!/usr/bin/env python3
"""
AdviceRoom — Test de connectivite des services externes.

Teste les 4 providers LLM + S3 avec des vrais appels.
Affiche la progression en temps reel avec couleurs ANSI.

Usage :
    cd application/backend && source .venv/bin/activate
    python ../../scripts/test_llm_providers.py
    python ../../scripts/test_llm_providers.py llmaas    # un seul provider
"""
import asyncio, os, sys, time
from pathlib import Path

# --- Couleurs ANSI ---
C_RESET  = "\033[0m"
C_BOLD   = "\033[1m"
C_DIM    = "\033[2m"
C_GREEN  = "\033[32m"
C_RED    = "\033[31m"
C_YELLOW = "\033[33m"
C_CYAN   = "\033[36m"
C_WHITE  = "\033[37m"
C_BLUE   = "\033[34m"
C_MAGENTA = "\033[35m"

def ok(t):    return f"{C_GREEN}{t}{C_RESET}"
def fail(t):  return f"{C_RED}{t}{C_RESET}"
def warn(t):  return f"{C_YELLOW}{t}{C_RESET}"
def dim(t):   return f"{C_DIM}{t}{C_RESET}"
def bold(t):  return f"{C_BOLD}{t}{C_RESET}"
def cyan(t):  return f"{C_CYAN}{t}{C_RESET}"
def blue(t):  return f"{C_BLUE}{t}{C_RESET}"

# --- Charger .env ---
ROOT = Path(__file__).parent.parent
ENV = ROOT / ".env"

def load_env():
    if not ENV.exists():
        print(fail("ERREUR:") + f" .env non trouve ({ENV})")
        sys.exit(1)
    with open(ENV) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

load_env()
sys.path.insert(0, str(ROOT / "application" / "backend"))

# --- Config des tests ---
TESTS = [
    {
        "id": "llmaas", "name": "LLMaaS Cloud Temple (SNC)",
        "key_env": "LLMAAS_API_KEY", "model": "qwen3.5:27b",
        "provider_cls": "app.services.llm.llmaas.LLMaaSProvider",
    },
    {
        "id": "google", "name": "Google Gemini",
        "key_env": "GEMINI_API_KEY", "model": "gemini-3.1-pro-preview",
        "provider_cls": "app.services.llm.google.GoogleProvider",
    },
    {
        "id": "openai", "name": "OpenAI GPT",
        "key_env": "OPENAI_API_KEY", "model": "gpt-5.2",
        "provider_cls": "app.services.llm.openai.OpenAIProvider",
    },
    {
        "id": "anthropic", "name": "Anthropic Claude",
        "key_env": "ANTHROPIC_API_KEY", "model": "claude-opus-4-6",
        "provider_cls": "app.services.llm.anthropic.AnthropicProvider",
    },
]

QUESTION = "Quel est l'avantage principal de Kubernetes ?"
MESSAGES = [
    {"role": "system", "content": "Reponds en UNE phrase courte en francais."},
    {"role": "user", "content": QUESTION},
]


def import_class(dotted_path):
    """Import dynamique : 'app.services.llm.llmaas.LLMaaSProvider' -> class."""
    module_path, _, cls_name = dotted_path.rpartition(".")
    import importlib
    mod = importlib.import_module(module_path)
    return getattr(mod, cls_name)


async def test_one_provider(cfg):
    """Teste un provider LLM : connectivite + chat completion."""
    key = os.getenv(cfg["key_env"], "")
    if not key or key.startswith("your-"):
        return {"status": "skip", "reason": f"{cfg['key_env']} absente"}

    try:
        cls = import_class(cfg["provider_cls"])
        provider = cls()
    except Exception as e:
        return {"status": "fail", "reason": f"Import: {e}"}

    # Connectivite
    try:
        conn = await provider.test_connectivity()
        if conn.get("status") not in ("ok", "disabled"):
            return {"status": "fail", "reason": f"Connectivite: {conn}"}
    except Exception as e:
        return {"status": "fail", "reason": f"Connectivite: {e}"}

    # Chat completion
    t0 = time.monotonic()
    try:
        resp = await provider.chat_completion(
            messages=MESSAGES, model_override=cfg["model"],
            temperature=0.5, max_tokens=200,
        )
        ms = int((time.monotonic() - t0) * 1000)

        if resp.finish_reason == "error":
            return {"status": "fail", "reason": (resp.content or "?")[:100], "ms": ms}
        if not resp.content:
            return {"status": "warn", "reason": "Reponse vide", "ms": ms,
                    "model": resp.model, "tokens": resp.usage}

        return {
            "status": "ok", "ms": ms,
            "response": resp.content.replace("\n", " ")[:120],
            "model": resp.model,
            "tokens": resp.usage.get("total_tokens", "?") if resp.usage else "?",
        }
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        return {"status": "fail", "reason": str(e)[:100], "ms": ms}


async def test_s3():
    """Teste la connectivite S3 Dell ECS."""
    endpoint = os.getenv("S3_ENDPOINT", "")
    access = os.getenv("S3_ACCESS_KEY", "")
    secret = os.getenv("S3_SECRET_KEY", "")
    bucket = os.getenv("S3_BUCKET", "")

    if not endpoint or not access or access.startswith("your-"):
        return {"status": "skip", "reason": "S3 non configure"}

    try:
        import boto3
        from botocore.config import Config as BotoConfig

        s3 = boto3.client(
            "s3", endpoint_url=endpoint,
            aws_access_key_id=access, aws_secret_access_key=secret,
            region_name=os.getenv("S3_REGION", "fr1"),
            config=BotoConfig(signature_version="s3v4"),
        )

        t0 = time.monotonic()
        # Test : lister les objets du bucket (max 5)
        resp = s3.list_objects_v2(Bucket=bucket, MaxKeys=5)
        ms = int((time.monotonic() - t0) * 1000)

        count = resp.get("KeyCount", 0)
        return {
            "status": "ok", "ms": ms,
            "detail": f"Bucket '{bucket}' accessible, {count} objets visibles",
        }
    except Exception as e:
        return {"status": "fail", "reason": str(e)[:120]}


# --- Affichage ---

def header():
    w = 62
    print()
    print(f"  {C_CYAN}{C_BOLD}{'=' * w}{C_RESET}")
    print(f"  {C_CYAN}{C_BOLD}  AdviceRoom -- Test Services Externes{C_RESET}")
    print(f"  {C_CYAN}{C_BOLD}{'=' * w}{C_RESET}")
    print(f"  {dim('Config')} : {ENV.name}")
    print(f"  {dim('Question')} : {QUESTION}")
    print()


def section(title):
    print(f"  {C_BLUE}{C_BOLD}--- {title} ---{C_RESET}")
    print()


def show_before(name, model, key_env):
    """Affiche ce qu'on va tester AVANT de le faire."""
    key = os.getenv(key_env, "")
    masked = key[:8] + "..." if len(key) > 8 else "(vide)"
    print(f"    {bold(name)}")
    print(f"    {dim('Modele')}  : {model}")
    print(f"    {dim('Cle')}     : {masked}")
    sys.stdout.write(f"    {dim('Test')}    : ")
    sys.stdout.flush()


def show_after(result):
    """Affiche le resultat APRES le test."""
    st = result["status"]
    if st == "ok":
        ms = result.get("ms", "?")
        print(ok("OK") + dim(f" ({ms}ms)"))
        if result.get("response"):
            print(f"    {dim('Reponse')} : {C_WHITE}\"{result['response']}\"{C_RESET}")
        if result.get("model"):
            print(f"    {dim('Modele')}  : {result['model']}")
        if result.get("tokens"):
            print(f"    {dim('Tokens')}  : {result['tokens']}")
        if result.get("detail"):
            print(f"    {dim('Detail')}  : {result['detail']}")
    elif st == "skip":
        print(warn("SKIP") + dim(f" - {result.get('reason', '')}"))
    elif st == "warn":
        print(warn("WARN") + dim(f" - {result.get('reason', '')}"))
    else:
        print(fail("FAIL") + dim(f" - {result.get('reason', '')}"))
    print()


def summary(results):
    ok_n = sum(1 for r in results if r["status"] == "ok")
    skip_n = sum(1 for r in results if r["status"] == "skip")
    fail_n = sum(1 for r in results if r["status"] in ("fail", "warn"))
    total = len(results)

    w = 62
    print(f"  {C_CYAN}{'=' * w}{C_RESET}")
    parts = []
    if ok_n:   parts.append(ok(f"{ok_n} OK"))
    if skip_n: parts.append(warn(f"{skip_n} SKIP"))
    if fail_n: parts.append(fail(f"{fail_n} FAIL"))
    print(f"  {bold('Resultat')} : {' / '.join(parts)}  ({total} tests)")

    llm_ok = sum(1 for r in results[:4] if r.get("status") == "ok")  # 4 premiers = LLM
    if llm_ok >= 2:
        print(f"  {ok('>> Pret pour un debat')} ({llm_ok} providers LLM fonctionnels)")
    elif llm_ok == 1:
        print(f"  {warn('>> 1 seul LLM OK, il en faut 2 minimum')}")
    else:
        print(f"  {fail('>> Aucun LLM fonctionnel')}")
    print()


# --- Main ---

async def main():
    header()

    target = sys.argv[1] if len(sys.argv) > 1 else None
    tests = TESTS
    if target and target != "s3":
        tests = [t for t in TESTS if t["id"] == target]
        if not tests:
            print(fail(f"  Provider inconnu: '{target}'"))
            print(dim(f"  Disponibles: {', '.join(t['id'] for t in TESTS)}, s3"))
            sys.exit(1)

    results = []

    # LLM Providers
    if not target or target != "s3":
        section("LLM Providers")
        for cfg in tests:
            show_before(cfg["name"], cfg["model"], cfg["key_env"])
            r = await test_one_provider(cfg)
            show_after(r)
            results.append(r)

    # S3
    if not target or target == "s3":
        section("S3 Storage (Dell ECS)")
        endpoint = os.getenv("S3_ENDPOINT", "(non configure)")
        bucket = os.getenv("S3_BUCKET", "(non configure)")
        print(f"    {bold('S3 Dell ECS')}")
        print(f"    {dim('Endpoint')} : {endpoint}")
        print(f"    {dim('Bucket')}   : {bucket}")
        sys.stdout.write(f"    {dim('Test')}     : ")
        sys.stdout.flush()
        r = await test_s3()
        show_after(r)
        results.append(r)

    # Resume
    if len(results) > 1:
        summary(results)


if __name__ == "__main__":
    asyncio.run(main())
