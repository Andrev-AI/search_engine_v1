import json
import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from rank_bm25 import BM25Okapi


# =========================================================
# CONTROLLER (YOU CONTROL EVERYTHING HERE)
# =========================================================

@dataclass
class IndexerController:
    # Files
    scraped_file: str = "scraped_data.json"
    output_index_file: str = "index.json"

    # --- LIMITS AND MEMORY ---
    limit: int = 0               # 0 = infinite
    save_chunk_size: int = 10    # Save every X pages

    # --- PageRank ---
    pagerank_damping: float = 0.85
    pagerank_iterations: int = 25

    # --- Final Weight ---
    weight_pagerank: float = 0.45
    weight_factors: float = 0.55

    # --- URL LENGTH ---
    url_length_enabled: bool = True
    url_length_points: float = 10.0
    url_length_min: int = 25
    url_length_max: int = 120
    url_length_mode: str = "range"

    # --- CONTENT LENGTH ---
    content_length_enabled: bool = True
    content_length_points: float = 15.0
    content_length_min: int = 120
    content_length_max: int = 3000
    content_length_mode: str = "range"

    # --- TLD ---
    tld_enabled: bool = True
    tld_points: float = 10.0
    tld_list: List[str] = field(default_factory=lambda: [
        ".gov", ".edu", ".org", ".com.br", ".gov.br", ".edu.br"
    ])

    # --- AUTHORITY LINKS ---
    authority_outlinks_enabled: bool = True
    authority_outlinks_points: float = 10.0
    authority_domains: List[str] = field(default_factory=lambda: [
        "wikipedia.org",
        "pt.wikipedia.org",
        "g1.globo.com",
        "bbc.com",
        "reuters.com",
        "gov.br"
    ])
    authority_outlinks_min_hits: int = 1

    # --- LANGUAGE ---
    language_enabled: bool = True
    language_points: float = 10.0
    language_list: List[str] = field(default_factory=lambda: [
        "pt", "pt-br", "pt_BR", "en", "es"
    ])

    # --- BM25 ---
    bm25_enabled: bool = True
    bm25_top_terms: int = 8

    # --- SCORE ---
    clamp_final_score_0_100: bool = True
    
    # --- TEXT SAVE ---
    save_text_preview: bool = True
    text_preview_max_chars: int = 1500




# =========================================================
# UTILITIES
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


def safe_float(x, default=0.0):
    try:
        return float(x)
    except:
        return default


def tokenize(text: str) -> List[str]:
    if not text:
        return []
    text = text.lower()
    text = re.sub(r"[^a-z0-9áàâãéèêíìîóòôõúùûç\- ]+", " ", text, flags=re.IGNORECASE)
    tokens = [t.strip() for t in text.split() if len(t.strip()) >= 3]
    tokens = [t for t in tokens if t not in STOPWORDS]
    return tokens


def normalize_range(value: int, min_v: int, max_v: int) -> float:
    if max_v <= min_v:
        return 0.0
    if value <= min_v:
        return 0.0
    if value >= max_v:
        return 1.0
    return (value - min_v) / (max_v - min_v)


def endswith_any(domain: str, tlds: List[str]) -> bool:
    domain = domain.lower()
    for tld in tlds:
        if domain.endswith(tld.lower()):
            return True
    return False


def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except:
        return ""


def url_has_language(url: str, lang_list: List[str]) -> bool:
    url_l = url.lower()
    for lang in lang_list:
        lang_l = lang.lower()
        if f"/{lang_l}/" in url_l or f"lang={lang_l}" in url_l or f"hl={lang_l}" in url_l:
            return True
    return False


def page_language_match(lang: str, lang_list: List[str]) -> bool:
    if not lang:
        return False
    lang_l = lang.lower().strip()
    for allowed in lang_list:
        a = allowed.lower().strip()
        if lang_l == a:
            return True
        if lang_l.startswith(a):
            return True
    return False


# =========================================================
# INDEXER
# =========================================================

class Indexer:
    def __init__(self, controller: IndexerController):
        self.cfg = controller

        self.docs: List[dict] = []
        self.url_to_idx: Dict[str, int] = {}
        self.graph_out: Dict[int, List[int]] = {}

        self.bm25 = None
        self.bm25_tokens: List[List[str]] = []
    
    def save_chunk(self, buffer: List[dict]):
        if not buffer:
            return

        with open(self.cfg.output_index_file, "a", encoding="utf-8") as f:
            for item in buffer:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

        buffer.clear()


    def load_scraped(self):
        print(f"📥 Reading {self.cfg.scraped_file} ...")
        docs = []

        with open(self.cfg.scraped_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if "url" in obj and obj["url"]:
                        docs.append(obj)
                except:
                    continue

        self.docs = docs
        self.url_to_idx = {d["url"]: i for i, d in enumerate(self.docs)}
        print(f"✅ Loaded: {len(self.docs)} pages")

    def build_graph(self):
        print("🧠 Building link graph...")

        graph_out = {i: [] for i in range(len(self.docs))}

        for i, doc in enumerate(self.docs):
            links = doc.get("links_found", []) or []
            targets = []

            for link in links:
                if link in self.url_to_idx:
                    targets.append(self.url_to_idx[link])

            graph_out[i] = list(dict.fromkeys(targets))

        self.graph_out = graph_out
        print("✅ Graph ready")

    def compute_pagerank(self) -> List[float]:
        n = len(self.docs)
        if n == 0:
            return []

        print("📈 Calculating PageRank...")

        d = self.cfg.pagerank_damping
        pr = [1.0 / n] * n

        outdegree = [len(self.graph_out[i]) for i in range(n)]
        inbound = [[] for _ in range(n)]

        for i in range(n):
            for j in self.graph_out[i]:
                inbound[j].append(i)

        for _ in range(self.cfg.pagerank_iterations):
            new_pr = [(1 - d) / n] * n

            for node in range(n):
                s = 0.0
                for src in inbound[node]:
                    if outdegree[src] > 0:
                        s += pr[src] / outdegree[src]
                new_pr[node] += d * s

            pr = new_pr

        min_pr = min(pr)
        max_pr = max(pr)
        if max_pr > min_pr:
            pr = [(x - min_pr) / (max_pr - min_pr) for x in pr]
        else:
            pr = [0.0] * n

        print("✅ PageRank ready")
        return pr

    def build_bm25(self):
        if not self.cfg.bm25_enabled:
            return

        print("🧾 Creating BM25...")
        tokens = []
        for d in self.docs:
            text = (d.get("title", "") or "") + " " + (d.get("text_content", "") or "")
            tokens.append(tokenize(text))

        self.bm25_tokens = tokens
        self.bm25 = BM25Okapi(tokens)
        print("✅ BM25 ready")

    def infer_theme_keywords(self, doc_idx: int) -> List[str]:
        if not self.cfg.bm25_enabled or not self.bm25:
            return []

        tokens = self.bm25_tokens[doc_idx]
        if not tokens:
            return []

        freq: Dict[str, int] = {}
        for t in tokens:
            freq[t] = freq.get(t, 0) + 1

        top_by_freq = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:20]
        query = [w for w, _ in top_by_freq]

        scores = self.bm25.get_scores(query)
        score_self = scores[doc_idx]

        if score_self <= 0:
            return [w for w, _ in top_by_freq[: self.cfg.bm25_top_terms]]

        scored = []
        for w, c in top_by_freq:
            idf = safe_float(self.bm25.idf.get(w, 0.0))
            scored.append((w, c * (1.0 + idf)))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [w for w, _ in scored[: self.cfg.bm25_top_terms]]

    # =========================================================
    # INDEX FACTORS
    # =========================================================

    def score_url_length(self, url: str) -> Tuple[float, dict]:
        if not self.cfg.url_length_enabled:
            return 0.0, {"enabled": False}

        L = len(url)
        points = self.cfg.url_length_points

        if self.cfg.url_length_mode == "range":
            norm = normalize_range(L, self.cfg.url_length_min, self.cfg.url_length_max)
            return points * norm, {"enabled": True, "len": L, "norm": norm}

        if self.cfg.url_length_mode == "prefer_short":
            if L <= self.cfg.url_length_min:
                return points, {"enabled": True, "len": L, "mode": "prefer_short"}
            if L >= self.cfg.url_length_max:
                return 0.0, {"enabled": True, "len": L, "mode": "prefer_short"}
            norm = 1.0 - normalize_range(L, self.cfg.url_length_min, self.cfg.url_length_max)
            return points * norm, {"enabled": True, "len": L, "norm": norm}

        if self.cfg.url_length_mode == "prefer_long":
            if L <= self.cfg.url_length_min:
                return 0.0, {"enabled": True, "len": L, "mode": "prefer_long"}
            if L >= self.cfg.url_length_max:
                return points, {"enabled": True, "len": L, "mode": "prefer_long"}
            norm = normalize_range(L, self.cfg.url_length_min, self.cfg.url_length_max)
            return points * norm, {"enabled": True, "len": L, "norm": norm}

        return 0.0, {"enabled": True, "error": "unknown_mode"}

    def score_content_length(self, text: str) -> Tuple[float, dict]:
        if not self.cfg.content_length_enabled:
            return 0.0, {"enabled": False}

        L = len(text or "")
        points = self.cfg.content_length_points

        if self.cfg.content_length_mode == "range":
            norm = normalize_range(L, self.cfg.content_length_min, self.cfg.content_length_max)
            return points * norm, {"enabled": True, "len": L, "norm": norm}

        if self.cfg.content_length_mode == "prefer_short":
            if L <= self.cfg.content_length_min:
                return points, {"enabled": True, "len": L, "mode": "prefer_short"}
            if L >= self.cfg.content_length_max:
                return 0.0, {"enabled": True, "len": L, "mode": "prefer_short"}
            norm = 1.0 - normalize_range(L, self.cfg.content_length_min, self.cfg.content_length_max)
            return points * norm, {"enabled": True, "len": L, "norm": norm}

        if self.cfg.content_length_mode == "prefer_long":
            if L <= self.cfg.content_length_min:
                return 0.0, {"enabled": True, "len": L, "mode": "prefer_long"}
            if L >= self.cfg.content_length_max:
                return points, {"enabled": True, "len": L, "mode": "prefer_long"}
            norm = normalize_range(L, self.cfg.content_length_min, self.cfg.content_length_max)
            return points * norm, {"enabled": True, "len": L, "norm": norm}

        return 0.0, {"enabled": True, "error": "unknown_mode"}

    def score_tld(self, url: str) -> Tuple[float, dict]:
        if not self.cfg.tld_enabled:
            return 0.0, {"enabled": False}

        dom = domain_of(url)
        ok = endswith_any(dom, self.cfg.tld_list)
        return (self.cfg.tld_points if ok else 0.0), {"enabled": True, "domain": dom, "match": ok}

    def score_authority_outlinks(self, links: List[str]) -> Tuple[float, dict]:
        if not self.cfg.authority_outlinks_enabled:
            return 0.0, {"enabled": False}

        hits = 0
        hit_domains = []

        for link in links or []:
            dom = domain_of(link)
            for auth in self.cfg.authority_domains:
                if auth.lower() in dom:
                    hits += 1
                    hit_domains.append(dom)
                    break

        ok = hits >= self.cfg.authority_outlinks_min_hits
        return (self.cfg.authority_outlinks_points if ok else 0.0), {
            "enabled": True,
            "hits": hits,
            "min_hits": self.cfg.authority_outlinks_min_hits,
            "hit_domains": list(dict.fromkeys(hit_domains))[:10],
            "match": ok
        }

    def score_language(self, url: str, lang: str) -> Tuple[float, dict]:
        if not self.cfg.language_enabled:
            return 0.0, {"enabled": False}

        url_match = url_has_language(url, self.cfg.language_list)
        meta_match = page_language_match(lang, self.cfg.language_list)

        ok = url_match or meta_match
        return (self.cfg.language_points if ok else 0.0), {
            "enabled": True,
            "url_match": url_match,
            "meta_lang": lang,
            "meta_match": meta_match,
            "match": ok
        }

    def compute_factors_score(self, doc: dict) -> Tuple[float, dict]:
        url = doc.get("url", "")
        text = doc.get("text_content", "") or ""
        links = doc.get("links_found", []) or []
        lang = doc.get("language", "") or ""

        url_len_score, url_len_meta = self.score_url_length(url)
        content_len_score, content_len_meta = self.score_content_length(text)
        tld_score, tld_meta = self.score_tld(url)
        auth_score, auth_meta = self.score_authority_outlinks(links)
        lang_score, lang_meta = self.score_language(url, lang)

        total = (
            url_len_score +
            content_len_score +
            tld_score +
            auth_score +
            lang_score
        )

        meta = {
            "url_length": {"score": url_len_score, **url_len_meta},
            "content_length": {"score": content_len_score, **content_len_meta},
            "tld": {"score": tld_score, **tld_meta},
            "authority_outlinks": {"score": auth_score, **auth_meta},
            "language": {"score": lang_score, **lang_meta},
            "factors_total": total
        }

        return total, meta

    def clamp_0_100(self, x: float) -> float:
        if x < 0:
            return 0.0
        if x > 100:
            return 100.0
        return x

    def run(self):
        self.load_scraped()
        self.build_graph()
        pagerank = self.compute_pagerank()
        self.build_bm25()

        print("🧪 Calculating factors and indexing...")

        factors_scores = []
        factors_meta_list = []

        for doc in self.docs:
            s, meta = self.compute_factors_score(doc)
            factors_scores.append(s)
            factors_meta_list.append(meta)

        min_f = min(factors_scores) if factors_scores else 0.0
        max_f = max(factors_scores) if factors_scores else 1.0

        def norm_f(x):
            if max_f > min_f:
                return (x - min_f) / (max_f - min_f)
            return 0.0

        indexed_buffer: List[dict] = []
        indexed_count = 0
        limit = self.cfg.limit

        for i, doc in enumerate(self.docs):
            if limit > 0 and indexed_count >= limit:
                print(f"🛑 Limit of {limit} pages reached")
                break

            pr = pagerank[i] if pagerank else 0.0
            f_raw = factors_scores[i]
            f_norm = norm_f(f_raw)

            final_0_1 = (
                pr * self.cfg.weight_pagerank +
                f_norm * self.cfg.weight_factors
            )

            final_0_100 = final_0_1 * 100.0
            if self.cfg.clamp_final_score_0_100:
                final_0_100 = max(0.0, min(100.0, final_0_100))

            keywords = self.infer_theme_keywords(i)
            
            text_preview = ""
            if self.cfg.save_text_preview:
                raw_text = doc.get("text_content", "") or ""
                text_preview = raw_text[: self.cfg.text_preview_max_chars]


            indexed = {
                "url": doc.get("url"),
                "title": doc.get("title"),
                "publish_date": doc.get("publish_date"),
                "language": doc.get("language"),
                "links_count": doc.get("links_count", 0),
                "text_preview": text_preview,
                "pagerank": pr,
                "factors_raw": f_raw,
                "factors_norm": f_norm,
                "final_score": final_0_100,
                "theme_keywords": keywords,
                "factors_breakdown": factors_meta_list[i],
                "scraped_at": doc.get("scraped_at")
            }

            indexed_buffer.append(indexed)
            indexed_count += 1

            if len(indexed_buffer) >= self.cfg.save_chunk_size:
                print(f"💾 Saving chunk ({indexed_count} indexed)...")
                self.save_chunk(indexed_buffer)

        self.save_chunk(indexed_buffer)

        print(f"✅ Indexing completed: {indexed_count} pages")



if __name__ == "__main__":
    controller = IndexerController(
        scraped_file="scraped_data.json",
        output_index_file="index.json",

        save_chunk_size=100,
        limit=0,

        save_text_preview=True,
        text_preview_max_chars=1500,

        bm25_enabled=True
    )


    idx = Indexer(controller)
    idx.run()
