# Papiers de recherche — AdviceRoom

> Fondements académiques du protocole de débat multi-LLM (voir `DESIGN/architecture.md` §2)

## Index des papiers

| # | Fichier | Titre complet | Source | Pages |
|---|---------|---------------|--------|-------|
| 1 | `01-multi-llm-debate-neurips2024.pdf` | **Multi-LLM Debate: Framework, Principals, and Interventions** — Estornell & Liu | NeurIPS 2024 | ~20 |
| 2 | `02-free-mad-2509.11035.pdf` | **Free-MAD: Consensus-Free Multi-Agent Debate** | arXiv 2509.11035 | 14 |
| 3 | `03-stability-detection-2510.12697.pdf` | **Multi-Agent Debate for LLM Judges with Adaptive Stability Detection** | arXiv 2510.12697 | 10 |
| 4 | `04-debate-protocols-2603.28813.pdf` | **The Impact of Multi-Agent Debate Protocols on Debate Quality** | arXiv 2603.28813 | 6 |
| 5 | `05-can-llm-debate-2511.07784.pdf` | **Can LLM Agents Really Debate?** | arXiv 2511.07784 | 12 |
| 6 | `06-consensus-diversity-2502.16565.pdf` | **Unraveling the Consensus-Diversity Tradeoff in Adaptive Multi-Agent System** | arXiv 2502.16565 (EMNLP 2025) | 3+ |
| 7 | `07-persona-driven-coling2025-2406.19643.pdf` | **Debate-to-Write: A Persona-Driven Multi-Agent Framework for Diverse Argument Generation** | arXiv 2406.19643 (COLING 2025) | ~15 |
| 8 | `08-society-of-thought-2601.10825.pdf` | **Reasoning Models Generate Societies of Thought** | arXiv 2601.10825 | 10 |
| 9 | `09-tool-mad-2601.04742.pdf` | **Tool-MAD: A Multi-Agent Debate Framework for Fact Verification with Diverse Tool Augmentation** | arXiv 2601.04742 | 13 |

## Résumés et intégration dans AdviceRoom

### [1] Multi-LLM Debate (NeurIPS 2024)
**Framework théorique bayésien** pour le débat multi-LLM. Montre que quand les modèles partagent des capacités similaires, le débat converge vers l'opinion majoritaire — problématique si cette majorité reflète un biais d'entraînement partagé. Propose 3 interventions pour améliorer l'efficacité du débat.

→ **Intégré dans AdviceRoom :** Positions initiales générées en **parallèle** (anti-ancrage) pour éviter la convergence vers la majorité erronée.

---

### [2] Free-MAD (arXiv 2509.11035)
**Paradigme consensus-free** : élimine le besoin de consensus entre agents. Introduit un mécanisme de décision basé sur le **score de la trajectoire entière** du débat (pas juste le dernier round). Deux modes : conformité et **anti-conformité** (via Chain-of-Thought pour identifier les failles). Fonctionne même en un seul round.

→ **Intégré dans AdviceRoom :** Verdict par **analyse de trajectoire**, challenge obligatoire (anti-conformité), dissensus accepté comme issue valide.

---

### [3] Stability Detection (arXiv 2510.12697)
**Détection adaptative de stabilité** via un modèle Beta-Binomial mixte + test de **Kolmogorov-Smirnov** (KS). Permet un arrêt intelligent du débat quand les positions se stabilisent, au lieu d'un nombre fixe de rounds. Surpasse le vote majoritaire en précision tout en réduisant les coûts.

→ **Intégré dans AdviceRoom :** **Arrêt adaptatif** basé sur 3 métriques (position delta, confidence delta, argument novelty) avec seuil de stabilité configurable (défaut 0.85).

---

### [4] Debate Protocols (arXiv 2603.28813)
**Comparaison contrôlée** de 3 protocoles de débat : Within-Round (WR), Cross-Round (CR), et Rank-Adaptive Cross-Round (RA-CR). Révèle un **trade-off entre interaction et convergence** : RA-CR converge plus vite mais WR génère plus de références croisées. Le "No-Interaction" maximise la diversité d'arguments.

→ **Intégré dans AdviceRoom :** Round-robin (Cross-Round) avec challenge obligatoire — compromis entre convergence et diversité.

---

### [5] Can LLM Agents Really Debate? (arXiv 2511.07784)
Étude contrôlée montrant que les **LLMs tendent au conformisme** : ils adoptent la position majoritaire même quand elle est incorrecte. Le biais majoritaire est identifié comme le **défi #1** du débat multi-LLM. Le vote majoritaire seul explique l'essentiel des gains de performance attribués au débat.

→ **Intégré dans AdviceRoom :** Anti-conformité **forcée dans le prompt** + validation post-tour + retry si pas de challenge substantif.

---

### [6] Consensus-Diversity Trade-off (arXiv 2502.16565 / EMNLP 2025)
Montre que le **consensus implicite** (agents échangent mais décident indépendamment) surpasse le consensus explicite (prompts, votes) dans les environnements dynamiques. La **diversité partielle booste l'exploration** et la robustesse. Trop de consensus tue l'adaptabilité.

→ **Intégré dans AdviceRoom :** Le **dissensus structuré** est accepté comme une issue valide du débat, pas un échec.

---

### [7] Persona-Driven / Debate-to-Write (COLING 2025)
Framework multi-agent où chaque agent reçoit un **persona** (description + croyances depuis une perspective unique). La diversité des personas maximise la diversité et la persuasion des arguments. 3 étapes : attribution de persona → débat pour planification → rédaction.

→ **Intégré dans AdviceRoom :** Attribution **automatique de personas** (Pragmatique, Analyste risques, Expert technique, Avocat du diable, Visionnaire) selon le nombre de participants.

---

### [8] Society of Thought (arXiv 2601.10825)
Découvre que les **modèles de raisonnement** (DeepSeek-R1, QwQ-32B) simulent implicitement un débat multi-perspectives en interne — une "société de la pensée". Ce n'est pas juste du calcul étendu, c'est de la simulation de conflit entre perspectives avec des traits de personnalité distincts. Valide le concept fondamental du débat multi-LLM.

→ **Intégré dans AdviceRoom :** Valide le concept fondamental — si un seul LLM simule un débat interne, un débat explicite entre LLMs devrait être encore plus riche.

---

### [9] Tool-MAD (arXiv 2601.04742)
Framework de débat multi-agent avec **outils externes hétérogènes** pour le fact-checking. Chaque agent reçoit un outil distinct (search API, RAG). Mécanisme de **reformulation adaptative** des requêtes pendant le débat. Détection quantitative des hallucinations. +5.5% de précision vs frameworks existants.

→ **Intégré dans AdviceRoom :** Tous les LLMs ont accès aux **mêmes outils** (Perplexity, Graph-Memory, calc, etc.) pendant le débat.

---

## 7 principes extraits de ces papiers

1. **Anti-ancrage** : positions initiales en parallèle → [1]
2. **Anti-conformité** : challenge obligatoire par round → [2, 5]
3. **Personas diversifiées** : angles d'analyse attribués automatiquement → [7]
4. **Pas de consensus forcé** : dissensus structuré accepté → [2, 6]
5. **Arrêt adaptatif** : détection de stabilité → [3]
6. **Verdict par trajectoire** : analyse du débat entier → [2]
7. **Outils pour tous** : accès aux mêmes outils → [9]
