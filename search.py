import json
import re
import math
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional

from rank_bm25 import BM25Okapi


# =========================================================
# CONTROLLER
# =========================================================

@dataclass
class SearchController:
    index_file: str = "index.json"

    # How many results to show
    results_limit: int = 10

    # "desc" = best first, "asc" = worst first
    order: str = "desc"

    # Preview in characters
    preview_length: int = 240

    # Final score weights
    weight_bm25: float = 0.60
    weight_index_score: float = 0.35
    weight_pagerank: float = 0.05

    # Language: priority (if empty, ignore)
    # Ex: ["pt", "pt-br", "en"]
    lang_priority: List[str] = field(default_factory=lambda: ["pt", "pt-br", "en"])

    # Penalty for language outside priority
    lang_penalty_multiplier: float = 0.85

    # If True, tries to use index keywords as BM25 reinforcement
    use_theme_keywords_in_bm25: bool = True

    # If True, includes URL in BM25 (good for finding pages by name)
    use_url_in_bm25: bool = True


# =========================================================
# TOKENIZER / UTILS
# =========================================================

STOPWORDS_PT = set("""
a o os as um uma uns umas de da do das dos em no na nos nas por para com sem
que e é foi eram era ser ter tem tinha têm também mas ou se ao aos à às
como mais menos muito muita muitos muitas já ainda só seu sua seus suas
isso isto aquele aquela aqueles aquelas
""".split())

STOPWORDS_EN = set("""
the a an and or but if then else of in on at by for with without from to into
is are was were be been being have has had do does did
""".split())

STOPWORDS = STOPWORDS_PT | STOPWORDS_EN


def tokenize(text: str) -> List[str]:
    if not text:
        return []
    text = text.lower()
    text = re.sub(r"[^a-z0-9áàâãéèêíìîóòôõúùûç\- ]+", " ", text, flags=re.IGNORECASE)
    tokens = [t.strip() for t in text.split() if len(t.strip()) >= 3]
    tokens = [t for t in tokens if t not in STOPWORDS]
    return tokens


def normalize_0_1(values: List[float]) -> List[float]:
    if not values:
        return []
    mn = min(values)
    mx = max(values)
    if mx <= mn:
        return [0.0 for _ in values]
    return [(v - mn) / (mx - mn) for v in values]


def lang_rank(lang: str, priority: List[str]) -> Optional[int]:
    if not lang or not priority:
        return None
    lang_l = lang.lower().strip()
    for i, p in enumerate(priority):
        p_l = p.lower().strip()
        if lang_l == p_l:
            return i
        if lang_l.startswith(p_l):
            return i
    return None


def clamp(x: float, a: float, b: float) -> float:
    return max(a, min(b, x))


# =========================================================
# PREVIEW 
# =========================================================

def best_preview(text: str, query_tokens: List[str], preview_len: int) -> str:
    if not text:
        return ""

    text_clean = re.sub(r"\s+", " ", text).strip()
    if len(text_clean) <= preview_len:
        return text_clean

    if not query_tokens:
        return text_clean[:preview_len].strip() + "..."

    window = preview_len
    step = max(40, preview_len // 4)

    best_score = -1
    best_slice = text_clean[:preview_len]

    for start in range(0, max(1, len(text_clean) - window), step):
        chunk = text_clean[start:start + window]
        chunk_l = chunk.lower()

        score = 0
        for t in query_tokens:
            if t in chunk_l:
                score += 1

        if score > best_score:
            best_score = score
            best_slice = chunk

        if best_score >= min(len(query_tokens), 6):
            break

    prefix = "..." if best_slice != text_clean[:preview_len] else ""
    suffix = "..." if (len(best_slice) + text_clean.find(best_slice)) < len(text_clean) else ""

    return (prefix + best_slice.strip() + suffix).strip()


# =========================================================
# SEARCHER
# =========================================================

class Searcher:
    def __init__(self, controller: SearchController):
        self.cfg = controller

        self.docs: List[dict] = []
        self.tokens: List[List[str]] = []
        self.bm25 = None

    def load_index(self):
        print(f"📥 Reading {self.cfg.index_file} ...")
        docs = []

        with open(self.cfg.index_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("url"):
                        docs.append(obj)
                except:
                    continue

        self.docs = docs
        print(f"✅ Loaded: {len(self.docs)} pages")

    def build_bm25(self):
        print("🧾 Creating BM25...")

        all_tokens = []

        for d in self.docs:
            title = d.get("title", "") or ""
            url = d.get("url", "") or ""

            keywords = d.get("theme_keywords", []) or []
            keywords_str = " ".join(keywords)

            # IMPORTANT to Remember:
            # Here there is NO full text, so BM25 is limited.
            # But it works very well for initial ranking.
  
          parts = [title]

            if self.cfg.use_theme_keywords_in_bm25:
                parts.append(keywords_str)

            if self.cfg.use_url_in_bm25:
                parts.append(url)

            combined = " ".join(parts)
            all_tokens.append(tokenize(combined))

        self.tokens = all_tokens
        self.bm25 = BM25Okapi(all_tokens)

        print("✅ BM25 ready")

    def score_language(self, doc: dict) -> float:
        if not self.cfg.lang_priority:
            return 1.0

        lang = doc.get("language", "") or ""
        r = lang_rank(lang, self.cfg.lang_priority)

        if r is None:
            return self.cfg.lang_penalty_multiplier

      boost = 1.0 + (0.08 * (1.0 / (1 + r)))
        return boost

    def search(self, query: str) -> List[dict]:
        if not query.strip():
            return []

        q_tokens = tokenize(query)
        if not q_tokens:
            return []

        bm25_scores = self.bm25.get_scores(q_tokens)
        bm25_norm = normalize_0_1(list(bm25_scores))

        results = []
        for i, doc in enumerate(self.docs):
            index_score_0_100 = float(doc.get("final_score", 0.0) or 0.0)
            pagerank_0_1 = float(doc.get("pagerank", 0.0) or 0.0)

            index_norm = clamp(index_score_0_100 / 100.0, 0.0, 1.0)
            pr_norm = clamp(pagerank_0_1, 0.0, 1.0)

            bm = bm25_norm[i]

            lang_mult = self.score_language(doc)

            combined = (
                bm * self.cfg.weight_bm25 +
                index_norm * self.cfg.weight_index_score +
                pr_norm * self.cfg.weight_pagerank
            )

            combined *= lang_mult

            results.append({
                "doc": doc,
                "bm25": bm,
                "index_norm": index_norm,
                "pagerank": pr_norm,
                "lang_mult": lang_mult,
                "combined": combined
            })

        # sort
        reverse = (self.cfg.order.lower() == "desc")
        results.sort(key=lambda x: x["combined"], reverse=reverse)

        # limit
        return results[: self.cfg.results_limit]

    def print_results(self, query: str, results: List[dict]):
        q_tokens = tokenize(query)

        print("\n" + "=" * 70)
        print(f"🔎 Query: {query}")
        print("=" * 70)

        if not results:
            print("❌ No results.")
            return

        for rank, item in enumerate(results, start=1):
            d = item["doc"]

            title = d.get("title", "Untitled")
            url = d.get("url", "")
            lang = d.get("language", "unknown")
            keywords = d.get("theme_keywords", []) or []

            # preview:
            # index.json currently doesn't have text_content (if you want, I adapt the indexer)
            # so try to get from some existing field.
            preview_source = d.get("text_preview", "") or ""
            preview = best_preview(preview_source, q_tokens, self.cfg.preview_length)

            # scores
            final_score = float(d.get("final_score", 0.0) or 0.0)

            print(f"\n[{rank}] {title}")
            print(f"URL: {url}")
            print(f"Lang: {lang}")

            if keywords:
                print(f"Keywords: {', '.join(keywords[:10])}")

            if preview:
                print(f"Preview: {preview}")
            else:
                print("Preview: (no text saved in index)")

            print(
                "Scores -> "
                f"BM25={item['bm25']:.4f} | "
                f"IndexScore={final_score:.2f}/100 | "
                f"PageRank={item['pagerank']:.4f} | "
                f"LangMult={item['lang_mult']:.3f} | "
                f"Combined={item['combined']:.4f}"
            )

    def run_cli(self):
        self.load_index()
        self.build_bm25()

        print("\n=== Search Engine (BM25 + IndexScore + PageRank) ===")
        print("Press ENTER to exit.\n")

        while True:
            try:
                q = input("Query> ").strip()
                if not q:
                    break
                results = self.search(q)
                self.print_results(q, results)
            except KeyboardInterrupt:
                print("\n🛑 Shutting down.")
                break
            except Exception as e:
                print(f"💥 Error: {e}")


if __name__ == "__main__":
    controller = SearchController(
        index_file="index.json",
        results_limit=10,
        order="desc", #asc worst, desc best
        preview_length=260,

        # weights (you adjust)
        weight_bm25=0.65,
        weight_index_score=0.30,
        weight_pagerank=0.05,

        # language priority
        lang_priority=["pt", "pt-br", "en"]
    )

    s = Searcher(controller)
    s.run_cli()
