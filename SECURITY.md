# Security Policy — AdviceRoom

*[Version française ci-dessous](#politique-de-sécurité--adviceroom)*

## Reporting a vulnerability

**Please do not open a public issue for a security vulnerability.** A public
report exposes every deployment of AdviceRoom until a fix ships.

Use **GitHub private vulnerability reporting**: the *Report a vulnerability*
button under this repository's **Security** tab. The report stays private until
disclosure, and the discussion stays attached to the repository.

### What to include

The more of this you can provide, the faster we can confirm and fix:

- the affected version or commit;
- the type of issue and the component involved;
- steps to reproduce, or a proof of concept;
- the impact you believe it has.

### What to expect

| Step | Target |
| --- | --- |
| Acknowledgement of your report | 5 business days |
| Initial assessment and severity | 10 business days |
| Fix or mitigation plan communicated | 30 days for high and critical severity |

We will keep you informed as the fix progresses, and credit you in the
`CHANGELOG.md` when the fix ships — unless you prefer to stay anonymous.

## Scope

AdviceRoom orchestrates debates between several LLMs and exposes an MCP server,
a REST API and an admin console. Reports are in scope when they concern:

- authentication, authorization, or tenant isolation between debates;
- the admin console (`/admin`) and its API;
- the MCP server and its tools;
- handling of API keys and tokens;
- leakage of debate content — questions, LLM responses, tool results — into
  logs, exports, or error messages.

### Out of scope

- Vulnerabilities in third-party LLM providers themselves. Report those to the
  provider; tell us if AdviceRoom's integration makes them worse.
- Prompt injection *between debate participants*. It is an inherent property of
  an LLM-to-LLM architecture, documented as a known risk. We harden against it
  in depth, but do not treat it as a closable vulnerability. A report showing
  that it crosses a **security boundary** — reaching authentication, another
  tenant's data, or the host — is very much in scope.
- Findings that require an already-compromised administrator token, unless they
  amount to a privilege escalation beyond what that token already grants.
- Missing hardening headers with no demonstrated impact.

## Supported versions

The project is pre-1.0: only the latest released version receives security
fixes. Deployments are expected to track releases.

---

# Politique de sécurité — AdviceRoom

## Signaler une vulnérabilité

**N'ouvrez pas d'issue publique pour une vulnérabilité.** Un signalement public
expose tous les déploiements d'AdviceRoom jusqu'à la publication du correctif.

Utilisez le **signalement privé GitHub** : le bouton *Report a vulnerability*
sous l'onglet **Security** de ce dépôt. Le signalement reste privé jusqu'à la
divulgation, et la discussion demeure attachée au dépôt.

### Quoi transmettre

Plus votre signalement contient d'éléments, plus la confirmation et la
correction seront rapides :

- la version ou le commit concerné ;
- le type de faille et le composant touché ;
- les étapes de reproduction, ou une preuve de concept ;
- l'impact que vous estimez.

### Ce que nous nous engageons à faire

| Étape | Délai visé |
| --- | --- |
| Accusé de réception | 5 jours ouvrés |
| Évaluation initiale et criticité | 10 jours ouvrés |
| Correctif ou plan de mitigation communiqué | 30 jours pour les criticités haute et critique |

Nous vous tenons informé de l'avancement, et vous créditons dans le
`CHANGELOG.md` à la publication du correctif — sauf si vous préférez rester
anonyme.

## Périmètre

AdviceRoom orchestre des débats entre plusieurs LLMs et expose un serveur MCP,
une API REST et une console d'administration. Sont dans le périmètre les
signalements portant sur :

- l'authentification, l'autorisation, ou l'isolation entre débats ;
- la console d'administration (`/admin`) et son API ;
- le serveur MCP et ses outils ;
- le traitement des clés d'API et des tokens ;
- la fuite de contenu de débat — questions, réponses des LLMs, résultats
  d'outils — dans les journaux, les exports ou les messages d'erreur.

### Hors périmètre

- Les vulnérabilités des fournisseurs LLM tiers eux-mêmes. Signalez-les au
  fournisseur ; dites-le nous si l'intégration d'AdviceRoom les aggrave.
- L'injection de prompt *entre participants d'un débat*. C'est une propriété
  inhérente à une architecture LLM-to-LLM, documentée comme risque connu. Nous
  nous en défendons en profondeur, sans la considérer comme une vulnérabilité
  refermable. En revanche, un signalement démontrant qu'elle franchit une
  **frontière de sécurité** — atteinte à l'authentification, aux données d'un
  autre locataire, ou à l'hôte — est pleinement dans le périmètre.
- Les découvertes nécessitant un token administrateur déjà compromis, sauf si
  elles constituent une élévation de privilèges au-delà de ce que ce token
  permet déjà.
- L'absence d'en-têtes de durcissement sans impact démontré.

## Versions supportées

Le projet est en pré-1.0 : seule la dernière version publiée reçoit les
correctifs de sécurité. Les déploiements sont censés suivre les publications.
