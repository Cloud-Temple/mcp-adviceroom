# Audit des papiers de recherche vs architecture.md

> **Date** : 20 avril 2026
> **Objectif** : Vérifier que `DESIGN/architecture.md` reflète fidèlement les papiers de recherche référencés (§2.1)

---

## Résumé exécutif

| #   | Papier                           | Verdict                   | Divergences                                                                    |
| --- | -------------------------------- | ------------------------- | ------------------------------------------------------------------------------ |
| [1] | Multi-LLM Debate (NeurIPS 2024)  | ⚠️ Interprétation libre | Le papier propose diversity pruning, pas "anti-ancrage par parallélisation"    |
| [2] | Free-MAD (2509.11035)            | ✅ Bon alignement         | Approche score-based vs synthétiseur LLM — différente mais valide              |
| [3] | Stability Detection (2510.12697) | ⚠️ Simplification       | AdviceRoom utilise des heuristiques simples, pas le Beta-Binomial+KS du papier |
| [4] | Debate Protocols (2603.28813)    | ✅ Correct                | Round-robin = bon compromis                                                    |
| [5] | Can LLM Debate? (2511.07784)     | ✅ Excellent              | Anti-conformité forcée = bonne réponse au problème identifié                   |
| [6] | Consensus-Diversity (2502.16565) | ✅ Excellent              | Dissensus structuré parfaitement aligné                                        |
| [7] | Persona-Driven (COLING 2025)     | ✅ Bon alignement         | Personas fixes vs dynamiques = amélioration future possible                    |
| [8] | Society of Thought (2601.10825)  | ✅ Validation             | Pas d'implémentation directe, valide le concept                                |
| [9] | Tool-MAD (2601.04742)            | ⚠️ Divergence           | Le papier donne des outils DIFFÉRENTS par agent, AdviceRoom donne les mêmes    |

**Score global : 6/9 bien alignés, 3/9 avec divergences mineures à clarifier.**

---

## Audit détaillé par papier

### [1] Multi-LLM Debate — NeurIPS 2024

**Auteurs :** Andrew Estornell (ByteDance), Yang Liu (UC Santa Cruz)
**Fichier :** `01-multi-llm-debate-neurips2024.pdf`

#### Passages décisifs

**Theorem 5.1 — Echo Chamber (p.5) :**
> "Suppose all n agents have identical configurations. Then the probability that a round of debate results in a change to the most likely concept approaches 0. A greater number of similar agents results in **static debate dynamics**, in essence defeating the purpose of debate."

**Theorem 5.2 — Tyranny of the Majority (p.5) :**
> "If a large number of models provide similar responses to a task x, then those repeated answers will **drown out** the single provided by the other models' responses, as well as the task x itself."

**Theorem 5.4 — Shared Misconceptions (p.5-6) :**
> "When a common misconception is shared among the models, debate is less effective and is likely to **converge to erroneous concepts**. [...] it is likely that other models will possess the same misconception unless specifically trained to avoid such errors due to the **high correlation in training data** between models."

**§6 — Trois interventions proposées :**
1. **Diversity Pruning** : sélectionner les k réponses qui maximisent l'entropie informationnelle (KL divergence entre réponses)
2. **Quality Pruning** : sélectionner les k réponses les plus pertinentes à la question
3. **Misconception Refutation** : identifier et réfuter les misconceptions dans les réponses

#### Comparaison avec architecture.md

| Aspect                   | architecture.md                                                                                  | Papier                                                                         | Verdict |
| ------------------------ | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------ | ------- |
| Description contribution | "Framework théorique bayésien. Identifie risque de convergence vers opinion majoritaire erronée" | ✅ Exact                                                                       | ✅      |
| Intégration              | "Positions initiales en parallèle (anti-ancrage)"                                                | Le papier propose diversity pruning, quality pruning, misconception refutation | ⚠️    |

#### ⚠️ Divergence identifiée

Le papier ne recommande **pas** la parallélisation des positions initiales comme intervention. C'est une déduction logique du problème d'echo chamber, mais pas une solution explicitement proposée par les auteurs. Les 3 interventions du papier (diversity pruning entre rounds, quality pruning, misconception refutation) ne sont pas implémentées dans AdviceRoom.

**Opportunités manquées :**
- Diversity pruning pourrait filtrer les réponses pour maximiser la diversité entre rounds
- Misconception refutation pourrait enrichir le VerdictSynthesizer

---

### [2] Free-MAD — arXiv 2509.11035

**Auteurs :** Yu Cui et al. (Beijing Institute of Technology)
**Fichier :** `02-free-mad-2509.11035.pdf`

#### Passages décisifs

**§4.2 — Anti-conformité (p.4-5) :**
> "We instruct agents to carefully assess the discrepancies between their own answers and those from peers. Agents are expected to **change their beliefs only if there is a clear indication that their own answer is incorrect**, rather than aiming to reach consensus with others."

**§4.3 — Score-based trajectory (p.5) :**
> "The mechanism evaluates the likelihood of an answer being correct by tracking whether agents exhibit a **shift in their opinions across rounds**. [...] answers that agents abandon are considered more likely to be incorrect, whereas newly adopted answers are treated as more likely to be correct."

**Abstract (p.1) :**
> "FREE-MAD significantly improves reasoning performance while requiring **only a single-round debate** and thus reducing token costs."

#### Comparaison avec architecture.md

| Aspect                              | architecture.md                         | Papier                                   | Verdict     |
| ----------------------------------- | --------------------------------------- | ---------------------------------------- | ----------- |
| "Paradigme consensus-free"          | ✅                                      | ✅                                       | ✅          |
| "Évalue la trajectoire entière"     | ✅                                      | ✅ (score-based)                         | ✅          |
| "Mode conformité + anti-conformité" | ✅                                      | ✅ (FREE-MAD-N vs FREE-MAD-C)            | ✅          |
| "Challenge obligatoire"             | AdviceRoom force un challenge structuré | Free-MAD encourage l'évaluation critique | ⚠️ Nuance |

#### Nuances

- L'anti-conformité de Free-MAD est un **prompt encourageant la pensée critique** ; AdviceRoom va plus loin avec un **challenge obligatoire + validation post-tour + retry**. Approche plus prescriptive mais plus robuste.
- Free-MAD utilise un **scoring algorithmique** de la trajectoire ; AdviceRoom utilise un **LLM synthétiseur**. Deux approches valides pour des contextes différents (QA fermé vs débat ouvert).
- Free-MAD montre qu'**1 seul round peut suffire** avec un bon scoring de trajectoire — non exploité dans AdviceRoom (min 2 rounds).

---

### [3] Stability Detection — arXiv 2510.12697

**Auteurs :** Tianyu Hu et al. (Arizona State, UNC Chapel Hill)
**Fichier :** `03-stability-detection-2510.12697.pdf`

#### Passages décisifs

**§5.1 — Modèle Beta-Binomial (p.6) :**
> "We model S_t as a time-varying mixture of two Beta-Binomial distributions [...] This model captures different behavioral regimes among judges (e.g., attentive vs. inattentive)."

**§5.3 — KS test (p.7) :**
> "Stability is detected by monitoring distributional similarity across rounds using the Kolmogorov–Smirnov (KS) statistic."

**Theorem 4.2 — Debate > Majority Vote (p.5-6) :**
> "Under the preceding assumptions, the final accuracy of the debated outcome D(Z^T) exceeds that of initial majority vote MV(Z^0)."

#### Comparaison avec architecture.md

| Aspect                              | architecture.md                                                             | Papier                                                      | Verdict        |
| ----------------------------------- | --------------------------------------------------------------------------- | ----------------------------------------------------------- | -------------- |
| "Détection adaptative de stabilité" | ✅                                                                          | ✅                                                          | ✅             |
| "Beta-Binomial + test KS"           | Cité dans §2.1                                                              | C'est la méthode exacte du papier                           | ✅ description |
| Implémentation §13                  | 3 heuristiques simples (position delta, confidence delta, argument novelty) | Modèle statistique formel (Beta-Binomial mixture + EM + KS) | ⚠️           |

#### ⚠️ Divergence identifiée

Le §2.1 de architecture.md cite "Beta-Binomial + test KS" comme contribution du papier, ce qui est exact. Mais le §13 implémente des **heuristiques simples** qui n'ont rien à voir avec le Beta-Binomial. C'est un choix **pragmatique et raisonnable** (le papier original est pour LLM-as-Judge sur des tâches fermées, pas du débat ouvert), mais l'architecture devrait clarifier que l'implémentation est **inspirée** du papier, pas une reproduction.

**Correction recommandée :** ajouter une note dans §13 expliquant pourquoi on utilise des heuristiques simplifiées au lieu du Beta-Binomial.

---

### [4] Debate Protocols — arXiv 2603.28813

**Auteurs :** (non identifié dans l'extrait lu)
**Fichier :** `04-debate-protocols-2603.28813.pdf`

#### Passages décisifs (via Perplexity)

- Compare 3 protocoles : Within-Round (WR), Cross-Round (CR), Rank-Adaptive CR (RA-CR)
- "**RA-CR achieves faster convergence** than CR" mais réduit la diversité
- "**WR produces stronger interaction-rich quality signals**"
- "**NI (No-Interaction) maximizes Argument Diversity**"
- "A **trade-off between interaction and convergence**"
- "Interaction-rich and convergence-oriented protocols should be selected **conditionally**"

#### Comparaison avec architecture.md

| Aspect                                           | architecture.md         | Papier                             | Verdict              |
| ------------------------------------------------ | ----------------------- | ---------------------------------- | -------------------- |
| "RA-CR converge plus vite mais réduit diversité" | ✅                      | ✅                                 | ✅                   |
| "Round-robin avec challenge obligatoire"         | Cross-Round + challenge | Papier ne propose pas le challenge | ✅ (addition valide) |

**✅ Bien aligné.** Le round-robin d'AdviceRoom correspond au protocole Cross-Round (CR) du papier, qui est le meilleur compromis. Le challenge obligatoire est une addition d'AdviceRoom inspirée de [2] et [5].

**Opportunité :** le papier suggère de rendre le protocole configurable selon le besoin — AdviceRoom pourrait proposer différents modes.

---

### [5] Can LLM Agents Really Debate? — arXiv 2511.07784

**Fichier :** `05-can-llm-debate-2511.07784.pdf`

#### Passages décisifs (via Perplexity + PDF)

- "LLM agents show strong **conformity to the majority view**, even when the minority position is better supported by evidence"
- "**Confabulation consensus** : agents reinforce each other's hallucinated rationales"
- "**Majority voting alone drives most performance gains** typically attributed to multi-agent debate"
- Propose **AgentAuditor** : audit evidence-based au lieu du vote majoritaire

#### Comparaison avec architecture.md

| Aspect                                  | architecture.md                 | Papier                       | Verdict |
| --------------------------------------- | ------------------------------- | ---------------------------- | ------- |
| "LLMs tendent au conformisme"           | ✅                              | ✅                           | ✅      |
| "Biais majoritaire = défi #1"           | ✅                              | ✅                           | ✅      |
| "Anti-conformité forcée dans le prompt" | ✅ + validation post-tour (§14) | Le papier valide le problème | ✅      |

**✅ Excellent alignement.** AdviceRoom adresse frontalement le problème identifié avec §14 (enforcement anti-conformité) qui va au-delà du simple prompt.

**Manqué :** AgentAuditor (audit evidence-based) pourrait inspirer une amélioration future du VerdictSynthesizer.

---

### [6] Consensus-Diversity Trade-off — arXiv 2502.16565 / EMNLP 2025

**Fichier :** `06-consensus-diversity-2502.16565.pdf`

#### Passages décisifs (via Perplexity)

- "**Implicit consensus outperforms explicit coordination** in dynamic environments"
- "Partial deviation from group norms **boosts exploration, robustness, and overall performance**"
- "Explicit coordination mechanisms risk **premature homogenization**"
- Testé sur : Dynamic Disaster Response, Information Spread, Public-Goods Provision

#### Comparaison avec architecture.md

| Aspect                               | architecture.md                 | Papier | Verdict |
| ------------------------------------ | ------------------------------- | ------ | ------- |
| "Un peu de désaccord est sain"       | ✅                              | ✅     | ✅      |
| "Trop de consensus tue l'adaptation" | ✅                              | ✅     | ✅      |
| "Dissensus structuré accepté"        | ✅ (verdict "dissensus" valide) | ✅     | ✅      |

**✅ Excellent alignement.** Le verdict à 3 issues (consensus, consensus_partiel, dissensus) d'AdviceRoom est une implémentation fidèle de la philosophie du papier.

---

### [7] Persona-Driven / Debate-to-Write — COLING 2025, arXiv 2406.19643

**Auteurs :** Hu, Zhe et al.
**Fichier :** `07-persona-driven-coling2025-2406.19643.pdf`

#### Passages décisifs (via Perplexity)

- "Each persona is formalized as a brief description paired with a **claim on the topic**"
- "The model is directed to generate personas representing a **diverse range of communities and perspectives**"
- "Multi-persona collaboration brings **unique perspectives and expertise**, crafting more compelling arguments"
- "**Debate-driven planning** enables fluid and nonlinear development of ideas"
- 3 étapes : persona assignment → debate-based planning → argument writing

#### Comparaison avec architecture.md

| Aspect                                      | architecture.md                 | Papier                                         | Verdict     |
| ------------------------------------------- | ------------------------------- | ---------------------------------------------- | ----------- |
| "Personas distinctes maximise la diversité" | ✅                              | ✅                                             | ✅          |
| §3.5 : 5 personas prédéfinis                | Personas FIXES                  | Papier génère personas DYNAMIQUEMENT par sujet | ⚠️ Nuance |
| Attribution automatique                     | ✅ (table selon N participants) | ✅ (sélection de N parmi pool)                 | ✅          |

**✅ Bon alignement.** L'implémentation AdviceRoom est simplifiée (personas fixes vs dynamiques) mais fidèle au principe. L'override possible par l'utilisateur dans l'API est un bon ajout.

**Amélioration future possible :** générer les personas dynamiquement selon la question (ex: question juridique → persona "juriste" au lieu de "pragmatique").

---

### [8] Society of Thought — arXiv 2601.10825

**Fichier :** `08-society-of-thought-2601.10825.pdf`

#### Passages décisifs (via Perplexity)

- "Advanced reasoning models achieve enhanced reasoning not through extended computation alone, but by simulating **multi-agent-like interactions between diverse internal cognitive perspectives**"
- "Distinct internal perspectives function as **separate entities characterized by specific personality dimensions** and expertise domains"
- "Reframes Chain-of-Thought: from a **linear computational scaling law to a social scaling phenomenon**"
- "Conversational behaviors: question-answering sequences, explicit perspective shifts, **conflict and debate**, reconciliation"

#### Comparaison avec architecture.md

| Aspect                                               | architecture.md | Papier | Verdict |
| ---------------------------------------------------- | --------------- | ------ | ------- |
| "Simulent implicitement un débat multi-perspectives" | ✅              | ✅     | ✅      |
| "Valide le concept fondamental"                      | ✅              | ✅     | ✅      |

**✅ Parfaitement aligné.** Ce papier est une validation conceptuelle. Si un seul LLM simule un débat interne pour mieux raisonner, un débat explicite entre LLMs avec des personas attribuées devrait être encore plus puissant.

---

### [9] Tool-MAD — arXiv 2601.04742

**Auteurs :** Seyeon Jeong et al.
**Fichier :** `09-tool-mad-2601.04742.pdf`

#### Passages décisifs (via Perplexity)

- "Each agent in the debate framework is assigned a **distinct external tool**, such as a search API or RAG module"
- "**Adaptive query formulation** mechanism that iteratively refines evidence retrieval based on the flow of the debate"
- "Integrates **Faithfulness and Answer Relevance scores** for quantitative hallucination detection"
- "+5.5% accuracy improvement over state-of-the-art MAD frameworks"

#### Comparaison avec architecture.md

| Aspect                                     | architecture.md            | Papier                          | Verdict |
| ------------------------------------------ | -------------------------- | ------------------------------- | ------- |
| "Débat multi-agent avec outils dynamiques" | ✅                         | ✅                              | ✅      |
| "Tous les LLMs ont accès aux outils"       | **MÊMES outils pour tous** | **DIFFÉRENTS outils par agent** | ⚠️    |

#### ⚠️ Divergence identifiée

Tool-MAD donne des **outils HÉTÉROGÈNES** à chaque agent (un a accès à search, un autre à RAG, etc.) pour maximiser la diversité des sources d'information. AdviceRoom donne les **mêmes outils à tous**.

**Opportunité :** on pourrait coupler les outils aux personas — l'Expert technique utilise `shell` et `perplexity_doc`, l'Analyste risques utilise `memory_search` et `perplexity_search`, etc.

**Autre manque :** le scoring Faithfulness/Answer Relevance pour détecter les hallucinations n'est pas dans AdviceRoom. Pourrait enrichir le VerdictSynthesizer.

---

## Corrections recommandées pour architecture.md

### 1. §2.1 — Corriger la description de [1]

**Avant :** "Intégré : Positions initiales en parallèle (anti-ancrage)"
**Après :** "Intégré : Positions initiales en parallèle (anti-ancrage, déduit du théorème echo chamber). Note : le papier propose aussi diversity pruning et misconception refutation (non implémentés en v1)"

### 2. §2.1 — Préciser [3]

**Avant :** "Intégré : Détection de stabilité pour arrêt adaptatif"
**Après :** "Intégré : Détection de stabilité pour arrêt adaptatif (approche simplifiée par heuristiques, inspirée du Beta-Binomial+KS du papier — voir §13)"

### 3. §2.1 — Corriger [9]

**Avant :** "Intégré : Tous les LLMs ont accès aux outils"
**Après :** "Intégré : Tous les LLMs ont accès aux outils (le papier original attribue des outils différents par agent — amélioration future possible)"

### 4. §13 — Ajouter note de clarification

Ajouter en tête de §13 :
> **Note** : Le papier [3] utilise un modèle statistique formel (Beta-Binomial mixture + EM + KS test) pour la détection de stabilité dans un contexte LLM-as-Judge. Pour le débat ouvert d'AdviceRoom, nous adoptons une approche simplifiée par heuristiques (position delta, confidence delta, argument novelty) qui est plus adaptée à notre format structuré de réponses. L'approche Beta-Binomial pourrait être envisagée en v2 si les heuristiques s'avèrent insuffisantes.
