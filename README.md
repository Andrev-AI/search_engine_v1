# search_engine_v1

[English version](README.md) • [Português-Brasil version (click)](README.pt-BR.md)

## Idea

After studying PageRank, indexing, and how search engines work, I decided to apply what I learned into a personal project.

This project will keep evolving. This is only a demo version, but I’m already working on more complete and capable versions.

---

## Crawler & Scraper (`crawler_and_scraper.py`)

A **crawler** is responsible for visiting pages and extracting links. A **scraper** extracts the page content and metadata.

In this project, the system works in a hybrid way:

1. It visits pages asynchronously using `asyncio`.
2. Workers extract links (**crawling**) and also extract text + metadata (**scraping**).
3. The extracted links feed the system again, expanding the crawl graph.

### Extracted information

- Title
- Date and time
- Language
- Page text
- URLs

It also stores:
- The date and time when the page was extracted
- How many links were found

Those links are used as new inputs for the crawler.

---

## Asyncio Workers

The crawler uses multiple asynchronous workers, configured in:

`class CrawlerConfig:` → `max_global_workers: int = 50`

You can set any integer value.

Workers run independently. They don’t wait for each other. Each one keeps consuming discovered URLs, visiting pages, extracting links and content, and continuing the process.

Important config fields:

- `save_chunk_size: int = 20`  
  Periodic saving system. Every 20 visited pages, it saves to disk and clears memory to avoid keeping everything in RAM.

- `max_total_urls: int = 1000`  
  Maximum number of URLs to crawl and scrape. This prevents the crawler from running forever.

  ⚠️ Since workers are asynchronous, the system may slightly exceed this limit.

- `max_concurrent_per_host: int = 2`  
  How many workers can hit the same host at the same time.  
  Be careful: too many requests can be interpreted as DDoS and may cause sites to block you.

- `delay_between_requests: float = 1.0`  
  Cooldown per worker between requests. Helps reduce load and avoid being flagged.

- `request_timeout: int = 15`  
  How long a worker waits for a response before retrying.

- `max_retries: int = 3`  
  Maximum retries before giving up.

- `retry_backoff: int = 2`  
  Exponential backoff factor. Example:
  - 1st error: wait 2s
  - 2nd error: wait 4s
  - 3rd error: wait 6s  
  This helps prevent spam behavior.

- `respect_robots: bool = True`  
  Keep this **True**. It respects `robots.txt`.  
   Don't be a mule and set this to **False**.

- `seeds`  
  Initial URLs. From them, the system expands into a link graph.

---

## Fake User-Agent

The system uses `fake-user-agent` to simulate different devices/browsers.

However, this is not state-of-the-art.

The best approach for modern dynamic websites (React, Next.js, etc.) would be using **Playwright**.

That will be implemented in a future version.

---

## Indexer

The indexer uses:

- **BM25**
- **PageRank**
- **Index Factors**

I won’t explain BM25 and PageRank here.

Google is estimated to use over 14,000 ranking factors (not public).  
Yandex is estimated around 1,400+.

My project uses **8 simplified factors**.

These factors help rank pages beyond BM25 relevance and PageRank, improving result quality.

---

## `class IndexerController`: Ranking Factors

- `scraped_file: str = "scraped_data.json"` (input)
- `output_index_file: str = "index.json"` (output)

- `limit: int = 0`  
  Maximum number of indexed pages.  
  If `0`, it means “no limit” (index everything in the scraped file).

- `save_chunk_size: int = 10`  
  Saves the index every X pages. Prevents RAM overload and helps recover from errors.

- `text_preview_max_chars: int = 1500`  
  Stores a preview of the page text for search results.

Ranking factors include:

- **URL length** (URL structure scoring)
- **Content length** (page content size scoring)
- **TLD scoring** (certain domains get a boost)
- **Authority links** (boost if referenced by trusted sites)
- **Language** (boost pages in preferred languages)

---

## Searcher

This is the “search box” part (Google, Bing, DuckDuckGo, Brave, etc).

`query` is what you type to search.

The system returns:

- Title
- URL
- Language
- Text preview
- Scores

It runs BM25 against the index, then combines relevance + ranking scores.

### Search options

- `results_limit=10`  
  Number of results displayed.

- `order="desc"`  
  Score ordering:
  - `asc`: worst → best
  - `desc`: best → worst

- `preview_length=260`  
  Preview size shown in the search output.

The indexer stores up to 1500 chars, but the searcher prints only 260.

---

## TODO / Future

This project still needs a lot to reach mainstream level.

If Google is a benchmark 10/10, this system is around 4/10 right now.  
But I’m already working on new versions that may reach 7/10.

Planned improvements:

- Use a real database instead of `.json` files (JSON is easier for early development)
- Compress extracted data
- Use Playwright for dynamic websites
- Add more ranking factors
- Add a watcher system to detect site updates
- Use sitemap parsing for better crawling + update detection
- Use embeddings instead of only BM25
- Add topic classification
- Improve strict URL limits (async workers can slightly exceed limits)

---

## How to Run

Optimized for Windows. Adapt as needed for your OS.

Runs in terminal.

**Python 3.10+ required**  
Recommended: **Python 3.11** + latest `pip`

### 1) Run the crawler & scraper

Before running, check:
- workers count
- max URLs
- seed URLs

```
python crawl_and_scraper.py
```
---

### 2) Run the indexer (PageRank + ranking factors)

```
python indexer.py
```
---

### 3) Run the search engine
Now you can type queries and see real results.

```
python search.py
```
