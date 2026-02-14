# search_engine_v1

## Ideia:

Com meus estudos sobre pagerank, indexação, funcionamento de motores de busca, decidi aplicar um pouco do que aprendi e vi em um projeto próprio.
Esse projeto vai evoluir, essa é apenas uma versão demonstrativa mas já estou trabalhando em versões mais completas e capaz.

## Crawler e Scraper `crawler_and_scraper.py`

**Crawler** já é algo bem conhecido, usado pra acessar sites e extrair links. **Scraper** faz a parte de extrair dados da página. 
Nesse projeto o sistema ele opera misto, primeiro ele acessa a página usando um sistema `asyncio` que permite criar `workers` que
acessarão as páginas e então fazer a parter de crawling, que é extrair os links, mas de scraping extraindo textos e metadados.

### informações extraídas
* Titulo.
* Data e hora.
* Idioma
* texto da página.
* URLs.

Também é salvo data e hora que foi extraído e e quantos links encontrados. Esses links realimentam o sistema pra buscar neles mais links e dados da página.

### asynsio

Usa `workers` definido a quantidade em `class CrawlerConfic:` -> `max_global_workers: int = 50` aqui está definido 50 mas pode colocar valor **int** que quiser.
cada worker atua independente e assíncrono entrando no site e buscando mais links pra realimentar o crawler e repetir processo e tbem fazer a raspagem. Como são independentes eles não esperam o "irmão" terminar para partir para os próximos sites, ele continua a lista das URLs encontradas e continua. 
* `save_chunk_size: int = 20` esse é sistema de salvamento periódico onde a cada 20 urls visitadas e extraídas ele salva e então limpa a memória para não ficar salvo em variável. 
* `max_total_urls: int = 1000 ` controla limite máximo de sites que vai ser feito crawling e scraping, isso é para ter um limite para não fazer indefinidamente pois ele poderia fazer sim toda a WEB.
  aqui vale uma observação pois como os workers são independentes pode acontecer de o limite passar um pouco. Mas não é um grande desvio, pode também encerrar o terminal.
* ` max_concurrent_per_host: int = 2` quantos workers pode acessar o mesmo site, cuidado pois vários deles podem ser interpretados como DDoS e até derrubar sites sem proteção.
* `delay_between_requests: float = 1.0` Cooldown por worker, após terminar um site e ir para a próxima URL. Ajuda também evitar ser interpretado como DDoS.
* `request_timeout: int = 15` quanto tempo o worker espera o site retornar um resultado antes de tentar novamente.
* `max_retries: int = 3` quantas tentativas antes de desistir se o site der erro.
* `retry_backoff: int = 2` tempo de expera que cresce exponencial se site der erro. Exemplo se for 2 = 2 segundos. Ele cresce exponencial se der erro exemplo erro na primeira é espera 2 segundos antes de tentar novamente. Segundo erro espera 4s, terceiro espera 6s antes de tentar novamente até atingir limite em `max_retries`. Isso serve para evitar ser interpretado como spam ou DDoS.
* ` respect_robots: bool = True` Mantenha sempre **True**. Respeita os Robots.txt. Não seje uma mula e mude para **False**.
* `seeds` urls iniciais, a partir das urls e dados encontrados nela, cria-se a árvore e seus ínumeros galhos.

## Indexer:

Usa `BM25`, `Pagerank`, `Index_factors`. Não explicarei **BM25** e **Pagerank**. O Google contém mais de 14 mil fatores de indexação segundo estimativas já que não é público. Yandex 1400+. Isso por que eles analisam conteúdo, estrutura, spam, etc. O meu eu simplifiquei em 8. que serão listados abaixo. Esses fatores servem pra pontuar o site além do pagerank e da correspondência do BM25.
Isso garante que sites se sobressaiam a outros e se ajuste mais com o que foi pesquisado. 

### `class IndexerController`: Fatores de indexação:

* `scraped_file: str = "scraped_data.json"` input e `output_index_file: str = "index.json"` output.
* `limit: int = 0` limite de sites indexados. Se 0 significa infinito isso faz sentido pq como vc quer salvar 0 chunk de X valor? Não rode o código. Por isso 0 seria infito que seria tudo que tem no `scraped_file`.
* `save_chunk_size: int = 10` salvamentos de chunks. Salva no output file a cada X sites indexados. Serve para salvamento em caso de erros e também não excer demais a memória RAM. Ele limpa buffer após salvar e continua.
* **ulr length** que analisa aspectos da URL e pontualiza.
* **Content legth** que é tamanho do coteúdo da página.
* **TLD** URLs que terminarem com esses domínios ganham mais pontos
* **AUTHORITHY LINKS** que é os sites que se forem apontados ele ganha mais pontos. 
* **LANGUAGE** sites com esse Idioma ganham mais pontos.

## Searcher

Aqui seria a caixa de pesquisa do Google, Yahoo, Yandex, DuckDuck go, Bing, Brave Search etc.
`query` é o que você quer pesquisar.

