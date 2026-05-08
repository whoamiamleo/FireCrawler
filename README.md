# FireCrawler

![Python](https://img.shields.io/badge/Python-3.8%2B-blue?style=flat-square&logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Firecrawl](https://img.shields.io/badge/Powered%20by-Firecrawl-orange?style=flat-square&logo=fire&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey?style=flat-square)
![Authorized Pentesting Only](https://img.shields.io/badge/⚠%EF%B8%8F%20Authorized%20Pentesting%20Only-critical?style=flat-square)

Mass URL collection tool that crawls one or more target websites and dumps every discovered URL to a file. Works with self-hosted [Firecrawl](https://github.com/mendableai/firecrawl) instances and Firecrawl Cloud.

---

## Table of Contents

- [Features](#features)
- [How It Works](#how-it-works)
- [Installation](#installation)
- [Usage](#usage)
  - [Examples](#examples)
- [Support](#support)
- [Formatting](#formatting)
  - [Input](#input)
  - [Output](#output)
- [Contributing](#contributing)
- [Attribution](#attribution)
- [Legal & Ethics](#legal--ethics)
- [License](#license)

---

## Features

- **Domain mapping**: Runs a sitemap-based map via `/v1/map` (up to 100,000 URLs via sitemap and robots.txt discovery) before crawling.
- **Full-domain crawl**: Submits a crawl job via `/v1/crawl` that covers the entire domain and all subdomains (up to 10,000 pages per job).
- **Multi-target with parallelism**: Accepts a file of target URLs and crawls all of them, with configurable parallel threads via `-t`.
- **Rich URL extraction**: Extracts URLs from page metadata (`sourceURL`, `ogUrl`, `canonicalUrl`) and extracted link lists.
- **Resumable runs**: Appends to the output file in real time. Interrupted runs can be resumed safely by re-running the same command.
- **Graceful interrupt**: Cancels in-flight Firecrawl jobs via `DELETE /v1/crawl/{id}` on Ctrl+C before exiting.
- **Connectivity verification**: Checks each target is reachable before submitting a crawl job. Unreachable targets are skipped.
- **Firecrawl-agnostic**: Works with any self-hosted Firecrawl instance or Firecrawl Cloud.

## How It Works

FireCrawler is a thin orchestration wrapper around Firecrawl's REST API.

```
targets.txt
    │
    ▼
[connectivity check]       ← GET request with browser UA, skips dead hosts
    │
    ▼
POST /v1/map               ← sitemap + robots.txt discovery, includeSubdomains,
    │                        limit: 100000 — synchronous, returns immediately
    ▼
POST /v1/crawl             ← submits job: crawlEntireDomain, allowSubdomains,
    │                        ignoreQueryParameters, formats: ["links"], limit: 10000
    ▼
GET /v1/crawl/{id}         ← polls every 15-30 seconds (randomised jitter)
    │
    ▼
[status == "completed"]
    │
    ▼
collect map links + sourceURL / ogUrl / canonicalUrl + page links
    │
    ▼
deduplicate → append to output file
```

The random sleep between polls (15-30 s) keeps the API worker queue uncontested when running multiple threads. On interrupt, a `DELETE /v1/crawl/{id}` is sent for any in-progress job before the process exits.

---

## Installation

**Requires Python 3.8+ and a running Firecrawl instance.**

```bash
git clone https://github.com/whoamiamleo/FireCrawler.git
cd FireCrawler
pip install -r requirements.txt
```

Or install the single dependency directly:

```bash
pip install requests
```

**Running Firecrawl locally** — the fastest way is Docker Compose:

```bash
git clone https://github.com/mendableai/firecrawl.git
cd firecrawl
docker compose up -d
```

This starts the API server, worker, Playwright browser, Redis, RabbitMQ, and PostgreSQL. The API is available at `http://localhost:3002` once containers are healthy (usually under 30 seconds).

Verify it is up:

```bash
curl http://localhost:3002/
# {"message":"Firecrawl API","documentation_url":"https://docs.firecrawl.dev"}
```

---

## Usage

```
usage: firecrawler.py [-h] -u URLS -o OUTPUT -s SERVER [-k API_KEY] [-v] [-t THREADS]

options:
  -h, --help               show this help message and exit
  -u, --urls URLS          File containing target domains to crawl (one per line)
  -o, --output OUTPUT      Output file (URLs are appended, not overwritten)
  -s, --server SERVER      Firecrawl service base URL (e.g. http://localhost:3002)
  -k, --api-key API_KEY    Firecrawl API key (optional for self-hosted)
  -v, --verbose            Print job status and discovered URLs to stdout
  -t, --threads THREADS    Number of parallel crawl threads (default: 1)
```

### Examples

```bash
# Self-hosted Firecrawl, single target
echo "https://example.com" > targets.txt
python firecrawler.py -u targets.txt -o urls.txt -s http://localhost:3002 -v

# Multiple targets, 3 parallel threads
python firecrawler.py -u targets.txt -o urls.txt -s http://localhost:3002 -v -t 3

# Firecrawl Cloud with API key
python firecrawler.py -u targets.txt -o urls.txt -s https://api.firecrawl.dev -k fc-YOUR_API_KEY -v

# Silent mode: write to file only, no stdout
python firecrawler.py -u targets.txt -o urls.txt -s http://localhost:3002

# Deduplicate the output file after a run
sort -u urls.txt -o urls.txt
```

---

## Support

| Requirement | Details |
|---|---|
| Python | 3.8+ |
| Firecrawl | Self-hosted or Firecrawl Cloud (supplied via `-s`) |
| macOS | ✅ |
| Linux | ✅ |
| Windows | ✅ |

Results are deduplicated per target during a run. For global deduplication across multiple runs, pipe through `sort -u`.

The `limit: 10000` cap per crawl job is a Firecrawl parameter. Large sites may hit this ceiling. The tool does not perform DNS resolution or screenshot capture — it collects URLs only.

## Formatting

### Input

A plain text file with one target URL per line, including the `http://` or `https://` prefix. Blank lines are ignored.

```
https://example.com
https://subdomain.example.com
https://another-target.org
```

### Output

All discovered URLs are appended to the output file, one per line. Results for each target are written as soon as that crawl job completes. The file is safe to read incrementally during a run.

```
https://example.com/
https://example.com/about
https://example.com/contact
https://example.com/products/widget
```

If a run is interrupted and resumed, re-crawled targets will produce duplicate lines. Deduplicate with:

```bash
sort -u urls.txt -o urls.txt
```

---

## Contributing

Contributions, issues, and feature requests are welcome. Feel free to check the [issues](https://github.com/whoamiamleo/FireCrawler/issues) page or submit a pull request.

## Attribution

If you use FireCrawler in a project or research, a mention or link back to this repository is appreciated.

- Author: Leopold von Niebelschuetz-Godlewski
- Repository: [https://github.com/whoamiamleo/FireCrawler](https://github.com/whoamiamleo/FireCrawler)
- License: MIT

---

## Legal & Ethics

FireCrawler is intended solely for authorized security testing and research activities. Any unauthorized use is strictly prohibited. The author assumes no responsibility for misuse or damage resulting from improper or unlawful use.

---

## License

MIT License

Copyright (c) 2026 Leopold von Niebelschuetz-Godlewski

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
