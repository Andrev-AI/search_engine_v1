import asyncio
import aiohttp
import aiofiles
import json
import logging
import sys
import os
import re
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Set, List, Dict, DefaultDict, Optional
from dataclasses import dataclass
from collections import defaultdict
import langdetect

# --- CENTRALIZED CONFIGURATION ---
@dataclass
class CrawlerConfig:
    # Global Limits
    max_total_urls: int = 1000           # Stop after successfully downloading X pages
    max_global_workers: int = 50         # Total asynchronous workers
    save_chunk_size: int = 20            # Save to disk every X items
    
    # Per Host/Site Limits (Anti-DDoS)
    max_concurrent_per_host: int = 2     # Max simultaneous connections to same site
    delay_between_requests: float = 1.0  # Seconds between requests (per worker)
    
    # Resilience
    request_timeout: int = 15            # Timeout in seconds
    max_retries: int = 3                 # Attempts before giving up
    retry_backoff: int = 2               # Wait multiplier between attempts
    
    # Robots.txt
    respect_robots: bool = True          # Respect robots.txt

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("crawler.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger()

class RobotsTxtCache:
    def __init__(self):
        self.cache: Dict[str, RobotFileParser] = {}
        self.lock = asyncio.Lock()
    
    async def can_fetch(self, url: str, user_agent: str = "*") -> bool:
        domain = urlparse(url).netloc
        
        async with self.lock:
            if domain not in self.cache:
                parser = RobotFileParser()
                robots_url = f"{urlparse(url).scheme}://{domain}/robots.txt"
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(robots_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                            if resp.status == 200:
                                text = await resp.text()
                                parser.parse(text.splitlines())
                            else:
                                parser.parse([])
                except:
                    parser.parse([])
                
                self.cache[domain] = parser
            
            return self.cache[domain].can_fetch(user_agent, url)

class RobustAsyncCrawler:
    def __init__(self, start_urls: List[str], config: CrawlerConfig):
        self.start_urls = start_urls
        self.cfg = config
        
        self.visited_file = "savedlinks.json"
        self.scraped_file = "scraped_data.json"
        
        self.queue = asyncio.Queue()
        self.visited_urls: Set[str] = set()
        self.data_buffer: List[Dict] = []
        self.urls_crawled_count = 0
        
        self.file_lock = asyncio.Lock()
        self.buffer_lock = asyncio.Lock()
        self.count_lock = asyncio.Lock()
        
        self.domain_semaphores: DefaultDict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(self.cfg.max_concurrent_per_host)
        )
        
        self.robots_cache = RobotsTxtCache()
        
        self.should_stop = False

    async def init_state(self):
        if os.path.exists(self.visited_file):
            try:
                async with aiofiles.open(self.visited_file, mode='r', encoding='utf-8') as f:
                    content = await f.read()
                    for line in content.strip().split('\n'):
                        if line.strip():
                            try:
                                data = json.loads(line)
                                self.visited_urls.add(data['url'])
                            except json.JSONDecodeError:
                                continue
                logger.info(f"Loaded {len(self.visited_urls)} already visited URLs")
            except Exception as e:
                logger.error(f"Error loading visited: {e}")
        
        for url in self.start_urls:
            if url not in self.visited_urls:
                await self.queue.put(url)
        
        logger.info(f"Configuration: Max {self.cfg.max_total_urls} URLs, {self.cfg.max_global_workers} workers, {self.cfg.max_concurrent_per_host} per host")

    async def save_visited(self, url: str):
        async with self.file_lock:
            try:
                async with aiofiles.open(self.visited_file, mode='a', encoding='utf-8') as f:
                    await f.write(json.dumps({"url": url}, ensure_ascii=False) + "\n")
            except Exception as e:
                logger.error(f"Error saving visited: {e}")

    async def save_data(self, force=False):
        async with self.buffer_lock:
            if not self.data_buffer:
                return
            
            if len(self.data_buffer) >= self.cfg.save_chunk_size or force:
                logger.info(f"💾 Saving {len(self.data_buffer)} items to disk...")
                try:
                    async with aiofiles.open(self.scraped_file, mode='a', encoding='utf-8') as f:
                        for item in self.data_buffer:
                            await f.write(json.dumps(item, ensure_ascii=False) + "\n")
                    self.data_buffer.clear()
                    logger.info("✅ Data saved and buffer cleared")
                except Exception as e:
                    logger.error(f"Error saving data: {e}")

    async def fetch_with_retry(self, session: aiohttp.ClientSession, url: str) -> Optional[str]:
        for attempt in range(1, self.cfg.max_retries + 1):
            try:
                timeout = aiohttp.ClientTimeout(total=self.cfg.request_timeout)
                headers = {'User-Agent': 'Mozilla/5.0 (compatible; CustomCrawler/1.0)'}
                
                async with session.get(url, timeout=timeout, headers=headers) as response:
                    if response.status == 200:
                        return await response.text()
                    elif response.status in [404, 403, 410]:
                        logger.warning(f"❌ Fatal error {response.status} at {url}")
                        return None
                    else:
                        logger.warning(f"⚠️  Status {response.status} at {url}. Attempt {attempt}/{self.cfg.max_retries}")
            
            except asyncio.TimeoutError:
                logger.error(f"⏱️  Timeout at {url}. Attempt {attempt}/{self.cfg.max_retries}")
            except aiohttp.ClientError as e:
                logger.error(f"🔌 Connection error ({type(e).__name__}) at {url}. Attempt {attempt}/{self.cfg.max_retries}")
            except Exception as e:
                logger.error(f"💥 Unexpected error at {url}: {e}")
            
            if attempt < self.cfg.max_retries:
                wait_time = attempt * self.cfg.retry_backoff
                await asyncio.sleep(wait_time)
        
        return None

    def extract_publish_date(self, soup: BeautifulSoup) -> Optional[str]:
        date_selectors = [
            ('meta', {'property': 'article:published_time'}),
            ('meta', {'name': 'pubdate'}),
            ('meta', {'name': 'publishdate'}),
            ('meta', {'property': 'og:published_time'}),
            ('time', {'datetime': True}),
        ]
        
        for tag, attrs in date_selectors:
            element = soup.find(tag, attrs)
            if element:
                date_value = element.get('content') or element.get('datetime')
                if date_value:
                    return date_value
        
        return None

    def extract_language(self, soup: BeautifulSoup, text: str) -> str:
        lang_tag = soup.find('html', attrs={'lang': True})
        if lang_tag:
            return lang_tag.get('lang', 'unknown')
        
        try:
            if len(text) > 50:
                return langdetect.detect(text)
        except:
            pass
        
        return 'unknown'

    async def parse(self, html: str, url: str) -> Dict:
        soup = BeautifulSoup(html, 'html.parser')
        
        title = soup.title.string.strip() if soup.title and soup.title.string else "No Title"
        
        paragraphs = soup.find_all('p')
        text_content = ' '.join([p.get_text(strip=True) for p in paragraphs[:10]])
        
        publish_date = self.extract_publish_date(soup)
        
        language = self.extract_language(soup, text_content)
        
        links = []
        base_domain = urlparse(url).netloc
        for a in soup.find_all('a', href=True):
            try:
                full_link = urljoin(url, a['href'])
                clean_link = full_link.split('#')[0].split('?')[0] if '?' in full_link else full_link.split('#')[0]
                
                if urlparse(clean_link).netloc == base_domain and clean_link not in links:
                    links.append(clean_link)
            except:
                continue
        
        return {
            "url": url,
            "title": title,
            "text_content": text_content[:500] if text_content else "",
            "publish_date": publish_date,
            "language": language,
            "links_found": links,
            "links_count": len(links),
            "scraped_at": datetime.now().isoformat()
        }

    async def worker(self, name: str, session: aiohttp.ClientSession):
        while not self.should_stop:
            try:
                url = await asyncio.wait_for(self.queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                if self.queue.empty() or self.should_stop:
                    logger.info(f"[{name}] Shutting down...")
                    break
                continue
            
            if self.should_stop:
                self.queue.task_done()
                logger.info(f"[{name}] Stopping (limit reached)")
                break
            
            if url in self.visited_urls:
                self.queue.task_done()
                continue
            
            self.visited_urls.add(url)
            await self.save_visited(url)
            
            if self.cfg.respect_robots:
                can_fetch = await self.robots_cache.can_fetch(url)
                if not can_fetch:
                    logger.warning(f"[{name}] 🤖 Blocked by robots.txt: {url}")
                    self.queue.task_done()
                    continue
            
            domain = urlparse(url).netloc
            domain_sem = self.domain_semaphores[domain]
            
            async with domain_sem:
                if self.cfg.delay_between_requests > 0:
                    await asyncio.sleep(self.cfg.delay_between_requests)
                
                logger.info(f"[{name}] 🌐 Downloading: {url}")
                html = await self.fetch_with_retry(session, url)
                
                if html:
                    try:
                        data = await self.parse(html, url)
                        
                        async with self.buffer_lock:
                            self.data_buffer.append(data)
                        await self.save_data()
                        
                        new_links_added = 0
                        for link in data['links_found']:
                            if link not in self.visited_urls:
                                await self.queue.put(link)
                                new_links_added += 1
                        
                        async with self.count_lock:
                            if self.urls_crawled_count >= self.cfg.max_total_urls:
                                logger.info(f"[{name}] 🛑 Limit reached, discarding result")
                                self.should_stop = True
                                while not self.queue.empty():
                                    try: 
                                        self.queue.get_nowait()
                                        self.queue.task_done()
                                    except: 
                                        break
                                break
                            
                            self.urls_crawled_count += 1
                            current = self.urls_crawled_count
                        
                        if current >= self.cfg.max_total_urls:
                            logger.info(f"[{name}] ✅ Success! Total: {current}/{self.cfg.max_total_urls} | LIMIT REACHED")
                            self.should_stop = True
                        else:
                            logger.info(f"[{name}] ✅ Success! Total: {current}/{self.cfg.max_total_urls} | +{new_links_added} links")
                    
                    except Exception as e:
                        logger.error(f"[{name}] 💥 Error processing {url}: {e}")
                
                else:
                    logger.error(f"[{name}] ❌ Permanent failure at {url}")
                
                self.queue.task_done()

    async def run(self):
        await self.init_state()
        
        connector = aiohttp.TCPConnector(
            limit=self.cfg.max_global_workers,
            ttl_dns_cache=300
        )
        
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = [
                asyncio.create_task(self.worker(f"W{i:02d}", session)) 
                for i in range(self.cfg.max_global_workers)
            ]
            
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except asyncio.CancelledError:
                pass
            
            await self.save_data(force=True)
            
            logger.info(f"🏁 Crawler finished! Total processed: {self.urls_crawled_count} URLs")

if __name__ == "__main__":
    # === YOUR CONTROLS ===
    config = CrawlerConfig(
        max_total_urls=150,              # Stop after 150 successful URLs
        max_global_workers=20,           # 20 total workers
        max_concurrent_per_host=1,        # Max 1 simultaneous worker per site
        save_chunk_size=10,               # Save every 10 items
        request_timeout=15,                # 15s timeout per request
        max_retries=4,                     # Try 4 times before giving up
        retry_backoff=4,                    # Wait 4s, 8s, 12s between attempts
        delay_between_requests=1.0,         # 1s between requests from same worker
        respect_robots=True                  # Respect robots.txt
    )
    
    seeds = [
        "https://www.cnnbrasil.com.br",
        "https://www.g1.globo.com"
    ]
    
    crawler = RobustAsyncCrawler(seeds, config)
    
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    async def main():
        try:
            await crawler.run()
        except KeyboardInterrupt:
            logger.info("⚠️  Interrupted by user. Saving progress...")
            crawler.should_stop = True
            await crawler.save_data(force=True)
        except Exception as e:
            logger.error(f"💥 Fatal error: {e}")
            await crawler.save_data(force=True)
        finally:
            logger.info("✅ Shutdown complete")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Force closing...")
        sys.exit(0)
