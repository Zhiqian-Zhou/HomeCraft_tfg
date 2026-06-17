"""Top-K retrieval of exemplar reference buildings for a user prompt.

The retrievable corpus is pre-filtered by the Stage-6 evaluator's composite
score (top-30% by default; see `tools/build_retrieval_index.py`). Within
that filtered subset, ranking is pure TF-IDF cosine similarity over
`title + description + style + category + size_bucket`. Composite scores
are exposed in the result dict as diagnostic metadata but do NOT participate
in ranking — once a building is in the index, all of them are considered
"good enough" and text relevance is the sole tiebreaker.

The index must be pre-built once with:

    python3 tools/score_corpus.py            # evaluate every building (~1 min)
    python3 tools/build_retrieval_index.py   # filter top-30% and fit TF-IDF

Usage:

    from pipeline.agents.retriever import retrieve
    hits = retrieve("a small medieval cottage", k=5)
    # → list of {id, title, score, composite_score, style, category, ...}
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import numpy as np
import scipy.sparse as sp

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_DIR = REPO_ROOT / "scratch" / "retrieval"


class _LoadedIndex:
    """Holds the precomputed index in memory after first access."""

    def __init__(self, index_dir: Path | None = None) -> None:
        idx_dir = Path(index_dir) if index_dir is not None else INDEX_DIR
        self.index_dir = idx_dir
        self.building_ids: list[str] = json.loads(
            (idx_dir / "building_ids.json").read_text(encoding="utf-8"))
        self.metadata: dict = json.loads(
            (idx_dir / "metadata.json").read_text(encoding="utf-8"))
        self.matrix = sp.load_npz(idx_dir / "tfidf_matrix.npz")
        # Canonicalise the CSR ONCE so concurrent reads (the gym runs 10 build
        # threads) never trigger scipy's lazy sort_indices/sum_duplicates on the
        # shared matrix — that race corrupted the CSR ("indices and data should
        # have the same number of elements") and crashed most parallel builds.
        if hasattr(self.matrix, "sum_duplicates"):
            self.matrix.sum_duplicates()
            self.matrix.sort_indices()
        self.vocab: dict[str, int] = json.loads(
            (idx_dir / "tfidf_vocab.json").read_text(encoding="utf-8"))
        # Precompute IDF once (was recomputed from the shared matrix on every
        # query → repeated concurrent scipy ops on idx.matrix, the race source).
        n_docs = self.matrix.shape[0]
        binary = (self.matrix > 0).astype(np.float32)
        df = np.asarray(binary.sum(axis=0)).ravel()
        self.idf = np.log((1 + n_docs) / (1 + df)) + 1.0
        # Row-normalise ONCE so retrieve() is a plain (immutable) matmul instead
        # of sklearn cosine_similarity normalising the shared matrix per call.
        from sklearn.preprocessing import normalize as _normalize
        self.matrix_norm = _normalize(self.matrix, axis=1, copy=True).tocsr()
        self.matrix_norm.sort_indices()
        # Composite scores aligned to building_ids — used only as informative
        # metadata in returned hits; ranking is pure TF-IDF.
        cs_path = idx_dir / "composite_scores.json"
        if cs_path.exists():
            self.composite_scores: list[float] = json.loads(
                cs_path.read_text(encoding="utf-8"))
        else:
            self.composite_scores = [0.0] * len(self.building_ids)


_INDEX: _LoadedIndex | None = None
_INDEX_LOCK = threading.Lock()


def _index() -> _LoadedIndex:
    """Thread-safe via double-checked locking."""
    global _INDEX
    if _INDEX is None:
        with _INDEX_LOCK:
            if _INDEX is None:
                if not (INDEX_DIR / "building_ids.json").exists():
                    raise FileNotFoundError(
                        "Retrieval index not built. Run: "
                        "`python3 tools/score_corpus.py` then "
                        "`python3 tools/build_retrieval_index.py`")
                _INDEX = _LoadedIndex()
    return _INDEX


def _reset_index_cache() -> None:
    """Test helper: invalidate the memoized index so the next retrieve()
    re-reads from disk. Production callers should not need this — restart
    the process to pick up a rebuilt index.
    """
    global _INDEX
    _INDEX = None


def _query_tfidf_row(prompt: str, idx: _LoadedIndex) -> sp.csr_matrix:
    """Build a 1×vocab_size sparse row for the query prompt.

    Computes the query TF directly (lowercase, unigrams + bigrams over
    tokens in vocab) weighted by IDF inferred from the corpus matrix.
    Avoids needing the pickled sklearn vectorizer.
    """
    tokens = re.findall(r"[a-z][a-z0-9_-]+", prompt.lower())
    grams: set[str] = set(tokens)
    for i in range(len(tokens) - 1):
        grams.add(tokens[i] + " " + tokens[i + 1])

    idf = idx.idf                         # precomputed once at load (thread-safe)

    cols, data = [], []
    for g in grams:
        col = idx.vocab.get(g)
        if col is None:
            continue
        cols.append(col)
        data.append(idf[col])
    if not cols:
        return sp.csr_matrix((1, idx.matrix.shape[1]))
    row = sp.csr_matrix(
        (data, ([0] * len(cols), cols)),
        shape=(1, idx.matrix.shape[1]),
        dtype=np.float32)
    norm = float(np.sqrt(row.multiply(row).sum()))
    if norm > 0:
        row = row / norm
    return row


def retrieve(prompt: str, *, k: int = 5,
             min_score: float = 0.0,
             boost_category: str | None = None) -> list[dict]:
    """Return top-K exemplar buildings for the given prompt.

    Ranking is pure TF-IDF cosine similarity over the quality-filtered
    corpus (the index already excludes buildings outside the top-30% by
    composite). `composite_score` is returned for diagnostic auditability.

    Args:
        prompt: natural-language description from the user
        k: number of exemplars to return
        min_score: drop hits with score below this threshold

    Returns: list of dicts, each:
        {id, title, score, composite_score, style, category, size_bucket,
         voxels_count, bbox_size, description_short}
    """
    idx = _index()
    q = _query_tfidf_row(prompt, idx)        # already L2-normalised
    # Cosine = q · matrix_norm.T (both row-normalised). Direct matmul on the
    # pre-normalised, immutable matrix — no per-call sklearn normalize on the
    # shared CSR, so 10 parallel gym builds can't race-corrupt it.
    tfidf_scores = np.asarray((q @ idx.matrix_norm.T).todense()).ravel()  # (n,)

    # Rank by TF-IDF + a category bonus so exemplars match the building TYPE
    # (raw TF-IDF over short descriptions is noisy — it returned a windmill as
    # the top hit for "palace"). `score` in the output stays the raw TF-IDF.
    rank_scores = tfidf_scores
    if boost_category:
        bonus = np.array(
            [0.15 if (idx.metadata.get(bid, {}).get("category")
                      == boost_category) else 0.0
             for bid in idx.building_ids])
        rank_scores = tfidf_scores + bonus

    if k >= len(rank_scores):
        order = np.argsort(-rank_scores)
    else:
        cand = np.argpartition(-rank_scores, k)[:k]
        order = cand[np.argsort(-rank_scores[cand])]

    out = []
    for i in order:
        score = float(tfidf_scores[i])
        if score < min_score:
            continue
        bid = idx.building_ids[i]
        meta = idx.metadata.get(bid, {})
        out.append({
            "id":               bid,
            "title":            meta.get("title", ""),
            "score":            score,
            "composite_score":  float(idx.composite_scores[i])
                                if i < len(idx.composite_scores) else None,
            "style":            meta.get("style", []),
            "category":         meta.get("category", ""),
            "size_bucket":      meta.get("size_bucket", ""),
            "voxels_count":     meta.get("voxels_count", 0),
            "bbox_size":        meta.get("bbox_size", [0, 0, 0]),
            "description_short": meta.get("description_short", ""),
        })
    return out


# ────────────────────────────────────────────────────────────────────────
#  Skill retrieval — RAG-A queries by skill_category (v4 feature).
#  Independent index from the building corpus: small (~150 skills), so we
#  load + scan on each call. TF-IDF over description + tags + parameters,
#  filtered by skill_category before ranking.
# ────────────────────────────────────────────────────────────────────────

_SKILLS_DIR = REPO_ROOT / "rag" / "skills"


class _LoadedSkills:
    """Lazy-loaded skill catalog, refreshed when files change."""

    def __init__(self, skills_dir: Path | None = None) -> None:
        self.skills_dir = Path(skills_dir) if skills_dir else _SKILLS_DIR
        self.entries: list[dict] = []
        self.mtime: float = 0.0

    def _maybe_refresh(self) -> None:
        # Cheap mtime check on the directory to invalidate cache when
        # new skills are added (e.g. by the generation batches in Phase B).
        try:
            now = max((p.stat().st_mtime for p in self.skills_dir.glob("*.json")),
                       default=0.0)
        except FileNotFoundError:
            now = 0.0
        if now <= self.mtime and self.entries:
            return
        self.entries = []
        for p in sorted(self.skills_dir.glob("*.json")):
            try:
                self.entries.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001
                continue
        self.mtime = now


_SKILLS: _LoadedSkills | None = None
_SKILLS_LOCK = threading.Lock()


def _skills() -> _LoadedSkills:
    """Thread-safe via double-checked locking. _maybe_refresh() is also
    guarded by _SKILLS_LOCK to prevent parallel reloads on cache miss."""
    global _SKILLS
    if _SKILLS is None:
        with _SKILLS_LOCK:
            if _SKILLS is None:
                _SKILLS = _LoadedSkills()
    with _SKILLS_LOCK:
        _SKILLS._maybe_refresh()
    return _SKILLS


def _reset_skills_cache() -> None:
    """Test helper — invalidates the skills cache."""
    global _SKILLS
    _SKILLS = None


def retrieve_skills(skill_category: str, *,
                     k: int = 5,
                     query: str = "",
                     applicable_to: str | None = None,
                     boost_category: str | None = None) -> list[dict]:
    """Return top-K skill entries matching the given v4 skill_category.

    Args:
        skill_category: one of global_silhouette | floor_layout |
            connector_template | wall_fitting | room_role |
            room_decoration | exterior_feature.
        k: how many to return after filtering + ranking.
        query: optional free-text used to rank within the filtered subset
            (TF-IDF over description + tags.category + tags.style +
            parameters keys). Empty query → return first K by id order.
        applicable_to: optional category filter (e.g. "residential").
            Skills with non-empty applicable_to MUST contain this value;
            skills with absent/empty applicable_to are kept (universal).

    Returns: list of dicts, each {id, name, description_short,
        skill_category, parameters, applicable_to, style, alexander_patterns}.
        Empty list if no skills match the category.
    """
    sk = _skills()
    pool = [e for e in sk.entries if e.get("skill_category") == skill_category]
    if applicable_to:
        pool = [
            e for e in pool
            if not e.get("applicable_to") or applicable_to in e["applicable_to"]
        ]
    if not pool:
        return []
    # Ranking: bag-of-words overlap between query tokens and the skill's
    # description+tags, PLUS a strong category bonus. The bag-of-words term is
    # dominated by generic architecture words ("roof", "room", "wall"), so a
    # cottage would tie a temple for a "temple" prompt; `boost_category` lifts
    # every silhouette whose tags.category / applicable_to matches the building
    # type above the non-matching ones (text overlap breaks ties within).
    if query or boost_category:
        q_tokens = {t for t in re.findall(r"[a-z][a-z0-9_-]+", query.lower())
                     if len(t) > 2} if query else set()

        def _score(e: dict) -> float:
            base = 0.0
            if q_tokens:
                desc = " ".join([
                    e.get("description", ""),
                    e.get("name", ""),
                    (e.get("tags") or {}).get("category", ""),
                    " ".join((e.get("tags") or {}).get("style", []) or []),
                    " ".join((e.get("parameters") or {}).keys()),
                ]).lower()
                tokens = set(re.findall(r"[a-z][a-z0-9_-]+", desc))
                base = len(q_tokens & tokens) / max(1, len(q_tokens))
            bonus = 0.0
            if boost_category:
                appl = e.get("applicable_to") or []
                cat = (e.get("tags") or {}).get("category")
                if boost_category == cat or boost_category in appl:
                    bonus = 2.0          # dominates base (∈[0,1]) → category first
            return base + bonus
        pool.sort(key=_score, reverse=True)
    else:
        pool.sort(key=lambda e: e["id"])
    return [_skill_brief(e) for e in pool[:k]]


def _skill_brief(entry: dict) -> dict:
    """Compact view of a skill entry for agent context."""
    return {
        "id":               entry.get("id"),
        "name":             entry.get("name", ""),
        "description":      (entry.get("description") or "")[:400],
        "skill_category":   entry.get("skill_category"),
        "kind":             entry.get("kind"),
        "category":         (entry.get("tags") or {}).get("category"),
        "style":            (entry.get("tags") or {}).get("style", []),
        "applicable_to":    entry.get("applicable_to", []),
        "parameters":       entry.get("parameters", {}),
        "typical_dimensions": entry.get("typical_dimensions", {}),
        "alexander_patterns": entry.get("alexander_patterns_relevant", []),
        "examples":         entry.get("examples", []),
    }


if __name__ == "__main__":
    import sys
    p = " ".join(sys.argv[1:]) or "a small medieval cottage with a kitchen and a bedroom"
    hits = retrieve(p, k=5)
    print(f"Query: {p!r}")
    for h in hits:
        cs = h["composite_score"]
        cs_str = f"{cs:.3f}" if cs is not None else " null"
        print(f"  {h['score']:.3f}  (composite={cs_str})  "
              f"{h['size_bucket']:6s}  {h['style']!s:30s}  "
              f"{h['title'][:60]}")
