# search_engine_v1

[Português-Brasil](README.pt-BR.md) • [English (click)](README.md) 

## Ideia

Com meus estudos sobre PageRank, indexação e funcionamento de motores de busca, decidi aplicar um pouco do que aprendi em um projeto próprio.

Esse projeto vai evoluir. Essa é apenas uma versão demonstrativa, mas já estou trabalhando em versões mais completas e capazes.


## Crawler e Scraper (`crawler_and_scraper.py`)

**Crawler** é algo bem conhecido, usado para acessar sites e extrair links.  
**Scraper** faz a parte de extrair dados da página.

Nesse projeto o sistema opera de forma mista:

1. Ele acessa páginas usando `asyncio`.
2. Workers extraem links (**crawling**) e também extraem textos + metadados (**scraping**).
3. Os links extraídos realimentam o sistema, expandindo o grafo de páginas.

### Informações extraídas

- Título
- Data e hora
- Idioma
- Texto da página
- URLs

Também é salvo:
- Data e hora em que a página foi extraída
- Quantos links foram encontrados

Esses links alimentam o sistema para buscar mais páginas e repetir o processo.


### Asyncio (Workers)

O crawler usa múltiplos workers assíncronos, configurados em:

`class CrawlerConfig:` → `max_global_workers: int = 50`

Você pode definir qualquer valor inteiro.

Cada worker atua de forma independente e assíncrona. Eles não esperam o “irmão” terminar.  
Cada worker continua consumindo a lista de URLs encontradas, visitando páginas, extraindo links e conteúdo, e repetindo o processo.

Configurações importantes:

- `save_chunk_size: int = 20`  
  Sistema de salvamento periódico. A cada 20 URLs visitadas e extraídas, ele salva e limpa a memória para não ficar tudo em variável.

- `max_total_urls: int = 1000`  
  Controla o limite máximo de sites que vão ser crawlados e raspados.  
  Isso evita rodar indefinidamente (porque sim, ele poderia rastrear a web inteira).

  ⚠️ Como os workers são independentes, o limite pode passar um pouco.

- `max_concurrent_per_host: int = 2`  
  Quantos workers podem acessar o mesmo host ao mesmo tempo.  
  Cuidado: muitos acessos podem ser interpretados como DDoS e até derrubar sites sem proteção.

- `delay_between_requests: float = 1.0`  
  Cooldown por worker, após terminar um site e ir para a próxima URL.  
  Ajuda a reduzir carga e também evita ser interpretado como DDoS.

- `request_timeout: int = 15`  
  Quanto tempo o worker espera o site responder antes de tentar novamente.

- `max_retries: int = 3`  
  Quantas tentativas antes de desistir se o site der erro.

- `retry_backoff: int = 2`  
  Tempo de espera que cresce exponencialmente caso o site dê erro.  
  Exemplo com valor 2:
  - 1º erro: espera 2s
  - 2º erro: espera 4s
  - 3º erro: espera 6s  
  Isso serve para evitar spam e reduzir o risco de bloqueio.

- `respect_robots: bool = True`  
  Mantenha sempre **True**. Respeita o `robots.txt`.  
  Não seja uma mula e mude isso para **False**.

- `seeds`  
  URLs iniciais. A partir delas, o sistema cria a árvore e seus inúmeros galhos.


### Fake User-Agent

O sistema usa `fake-user-agent` para simular browsers/dispositivos.

Porém ainda não é estado da arte.

O ideal seria usar **Playwright** para sites dinâmicos que usam JavaScript (React, Next.js, etc.).  
Isso vai ser implementado em uma nova versão.


## Indexer

O indexer usa:

- **BM25**
- **PageRank**
- **Index Factors**

Não explicarei BM25 e PageRank aqui.

O Google tem estimativas de mais de 14 mil fatores de ranking (não é público).  
O Yandex tem estimativas de 1400+.

O meu projeto simplifica isso em **8 fatores**.

Esses fatores servem para pontuar o site além do PageRank e da correspondência do BM25.  
Isso ajuda sites a se sobressaírem a outros e se ajustarem melhor com o que foi pesquisado.


### `class IndexerController`: Fatores de indexação

- `scraped_file: str = "scraped_data.json"` (entrada)
- `output_index_file: str = "index.json"` (saída)

- `limit: int = 0`  
  Limite de sites indexados.  
  Se `0`, significa “sem limite” (indexa tudo do `scraped_file`).

- `save_chunk_size: int = 10`  
  Salvamento em chunks.  
  Salva no arquivo de saída a cada X sites indexados.  
  Serve para salvar em caso de erros e também para não exceder RAM.  
  O buffer é limpo após salvar, e o processo continua.

- `text_preview_max_chars: int = 1500`  
  Preview: quantos caracteres serão salvos para depois, na busca, mostrar um trecho da página.

### Fatores usados:

- **URL length** (analisa aspectos da URL e pontua)
- **Content length** (tamanho do conteúdo da página)
- **TLD** (URLs que terminam com certos domínios ganham mais pontos)
- **Authority links** (sites que, se apontarem para ele, aumentam pontuação)
- **Language** (sites em certos idiomas ganham mais pontos)


## Searcher

Aqui é a parte da caixa de pesquisa (Google, Yahoo, Yandex, DuckDuckGo, Bing, Brave Search etc).

`query` é o que você digita para pesquisar.

Ele retorna:

- Título
- URL
- Idioma
- Preview do texto
- Scores

Ele usa BM25 na query e cruza com o índice.  
Depois combina os scores e entrega os resultados.

### Opções do search

- `results_limit=10`  
  Quantos resultados mostrar.

- `order="desc"`  
  Ordem dos scores:
  - `asc`: pior → melhor
  - `desc`: melhor → pior

- `preview_length=260`  
  Tamanho do preview mostrado na busca.

O indexer salva até 1500 caracteres, mas o search mostra só 260.


## TO DO e Futuro

Esse projeto ainda deve evoluir muito para chegar nível mainstream.

Se usarmos o Google como benchmark (Google = 10), esse sistema seria uns 4.  
Porém já estou trabalhando em novas versões que podem chegar a nota 7.

Melhorias planejadas:

- Usar banco de dados ao invés de `.json` (JSON é mais fácil para desenvolvimento inicial)
- Usar compressão nos dados extraídos
- Usar Playwright ao invés de apenas fake-user-agent para sites dinâmicos
- Mais fatores de indexação
- Observador para analisar updates de sites
- Usar sitemap para detectar atualizações e obter informações mais completas
- Usar embeddings ao invés de apenas BM25
- Classificador de assunto do conteúdo
- Respeitar melhor o limite de sites salvos (workers assíncronos podem ultrapassar um pouco)


## Como usar

Sistema otimizado para Windows. Faça adaptações para seu OS.

Rodará no terminal.

**Python 3.10+ required**  
Recomendado: **Python 3.11** e `pip` atualizado.

### 1) Rode o crawler + scraper

Antes de rodar, verifique:
- quantidade de workers
- limite de sites
- URLs iniciais (seeds)

```
python crawl_and_scraper.py
```
---
### 2) Rode o indexer (PageRank + fatores)

```
python indexer.py
```

---

###  3) Rode o search

Aqui você poderá fazer as pesquisas e ver o sistema funcionando.

```
python search.py
```
