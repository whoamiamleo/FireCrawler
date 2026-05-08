import argparse, random, requests, signal, sys, threading, urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed

urllib3.disable_warnings()

_stop_event = threading.Event()

MIN_SLEEP = 15
MAX_SLEEP = 30
REQUEST_TIMEOUT = 60
MAX_POLL_RETRIES = 5

def build_headers(api_key=None):
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers

def cancel_crawl_job(base_url, job_id, api_key=None, verbose=False):
    try:
        requests.delete(
            f"{base_url}/v1/crawl/{job_id}",
            headers=build_headers(api_key),
            timeout=REQUEST_TIMEOUT,
        )
        if verbose:
            print(f"[INFO] Crawl job cancelled: {job_id}")
    except Exception as e:
        if verbose:
            print(f"[WARN] Failed to cancel job {job_id}: {e}")

def map_firecrawl(base_url, url, api_key=None, verbose=False):
    headers = build_headers(api_key)
    payload = {"url": url, "includeSubdomains": True, "limit": 100000}
    response = requests.post(
        f"{base_url}/v1/map", headers=headers, json=payload, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    links = response.json().get("links", [])
    if verbose:
        print(f"[INFO] Mapped {len(links)} URLs for {url}")
    return links

def extract_urls_from_results(results):
    urls = []
    for result in results:
        metadata = result.get("metadata", {})
        for key in ("sourceURL", "ogUrl", "canonicalUrl"):
            val = metadata.get(key)
            if val:
                urls.append(val)
        for link in result.get("links", []):
            urls.append(link)
    return urls

def flush_new_urls(urls, written_set, output_file, file_lock, verbose=False):
    to_write = sorted(u for u in set(urls) if u not in written_set)
    if not to_write:
        return
    with file_lock:
        for u in to_write:
            output_file.write(u + '\n')
            output_file.flush()
            if verbose:
                print(u)
    written_set.update(to_write)

def crawl_firecrawl(base_url, url, api_key=None, verbose=False,
                    written_set=None, output_file=None, file_lock=None):
    headers = build_headers(api_key)
    payload = {
        "url": url,
        "limit": 10000,
        "crawlEntireDomain": True,
        "allowSubdomains": True,
        "ignoreQueryParameters": True,
        "scrapeOptions": {
            "formats": ["links"]
        }
    }

    response = requests.post(
        f"{base_url}/v1/crawl", headers=headers, json=payload, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    data = response.json()

    job_id = data.get("id")
    if not job_id:
        print(f"[ERROR] No job ID returned for {url}: {data}")
        return

    if verbose:
        print(f"[INFO] Crawl job started: {job_id}")

    poll_crawl_job(base_url, job_id, api_key, verbose,
                   written_set=written_set, output_file=output_file, file_lock=file_lock)

def poll_crawl_job(base_url, job_id, api_key=None, verbose=False,
                   written_set=None, output_file=None, file_lock=None):
    status_url = f"{base_url}/v1/crawl/{job_id}"
    headers = build_headers(api_key)
    completed_normally = False
    effective_lock = file_lock or threading.Lock()
    consecutive_errors = 0

    try:
        while not _stop_event.is_set():
            try:
                response = requests.get(status_url, headers=headers, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                data = response.json()
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors >= MAX_POLL_RETRIES:
                    print(f"[ERROR] Polling job {job_id} failed {consecutive_errors} times consecutively, giving up: {e}")
                    return
                print(f"[WARN] Polling job {job_id} failed (attempt {consecutive_errors}/{MAX_POLL_RETRIES}): {e}. Retrying...")
                _stop_event.wait(random.randint(MIN_SLEEP, MAX_SLEEP))
                continue

            status = data.get("status")

            if verbose:
                completed = data.get("completed", 0)
                total = data.get("total", "?")
                print(f"[INFO] Crawl job {job_id}: {completed}/{total} pages")

            results = data.get("data", [])
            if results and output_file is not None and written_set is not None:
                flush_new_urls(
                    extract_urls_from_results(results),
                    written_set, output_file, effective_lock, verbose
                )

            if status == "completed":
                completed_normally = True
                next_url = data.get("next")
                while next_url and not _stop_event.is_set():
                    try:
                        resp = requests.get(next_url, headers=headers, timeout=REQUEST_TIMEOUT)
                        resp.raise_for_status()
                        page = resp.json()
                        if output_file is not None and written_set is not None:
                            flush_new_urls(
                                extract_urls_from_results(page.get("data", [])),
                                written_set, output_file, effective_lock, verbose
                            )
                        next_url = page.get("next")
                    except Exception as e:
                        print(f"[WARN] Failed to fetch paginated results for job {job_id}: {e}. Stopping pagination.")
                        break
                return
            elif status in ("failed", "cancelled"):
                completed_normally = True
                print(f"[ERROR] Crawl job {job_id} ended with status: {status}")
                return

            sleep_secs = random.randint(MIN_SLEEP, MAX_SLEEP)
            _stop_event.wait(sleep_secs)
    finally:
        if not completed_normally:
            cancel_crawl_job(base_url, job_id, api_key, verbose)

def collect_urls(base_url, target_url, output_file, api_key=None, verbose=False, file_lock=None):
    written_set = set()
    effective_lock = file_lock or threading.Lock()

    if verbose:
        print(f"[INFO] Mapping {target_url}")
    try:
        map_urls = map_firecrawl(base_url, target_url, api_key, verbose)
        flush_new_urls(map_urls, written_set, output_file, effective_lock, verbose)
    except Exception as e:
        if verbose:
            print(f"[WARN] Map failed for {target_url}: {e}")

    if verbose:
        print(f"[INFO] Crawling {target_url}")
    try:
        crawl_firecrawl(base_url, target_url, api_key, verbose,
                        written_set=written_set, output_file=output_file, file_lock=effective_lock)
    except Exception as e:
        print(f"[ERROR] Crawl failed for {target_url}: {e}")

    if verbose:
        print(f"[INFO] {len(written_set)} unique URLs scraped from {target_url}")

    return written_set

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-u",
        "--urls",
        required=True,
        help="File containing URLs to crawl (one per line)"
    )
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Output file"
    )
    parser.add_argument(
        "-s",
        "--server",
        required=True,
        help="Firecrawl service base URL (e.g. http://localhost:3002)"
    )
    parser.add_argument(
        "-k",
        "--api-key",
        required=False,
        default=None,
        help="Firecrawl API key (optional)"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        required=False,
        help="Enable verbose output"
    )
    parser.add_argument(
        "-t",
        "--threads",
        type=int,
        default=1,
        help="Number of parallel threads (default: 1)"
    )
    args = parser.parse_args()

    _stop_handler = lambda sig, frame: _stop_event.set()
    signal.signal(signal.SIGINT, _stop_handler)
    signal.signal(signal.SIGTERM, _stop_handler)

    base_url = args.server.rstrip("/")

    urls = []
    try:
        urls = [u.strip() for u in open(args.urls).readlines() if u.strip()]
    except Exception as e:
        print("[ERROR]", e)
        print(f"Usage: python {sys.argv[0]} -u /path/to/urls.txt -o output.txt -s http://localhost:3002")
        sys.exit(1)

    if len(urls) < 1:
        print("[ERROR] No URLs found in input file.")
        sys.exit(1)
    if args.threads < 1:
        print("[ERROR] --threads must be at least 1.")
        sys.exit(1)
    if args.threads > len(urls):
        hint = f"Use -t {len(urls)}." if len(urls) == 1 else f"Use -t <= {len(urls)}."
        print(f"[ERROR] --threads ({args.threads}) exceeds number of input URLs ({len(urls)}). {hint}")
        sys.exit(1)
    threads = args.threads

    try:
        output_file = open(args.output, "a")
    except Exception as e:
        print(f"[ERROR] Cannot open output file: {e}")
        sys.exit(1)

    file_lock = threading.Lock()

    def process_url(url):
        try:
            if args.verbose:
                print(f"[INFO] Verifying connectivity with {url}...")
            requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"},
                timeout=20,
                verify=False,
            )
        except Exception as e:
            if args.verbose:
                print(f"[ERROR] Unable to connect to {url}: {e}. Skipping...")
            return
        try:
            collect_urls(base_url, url, output_file, args.api_key, args.verbose, file_lock)
        except Exception as e:
            print(f"[ERROR] Unexpected error processing {url}: {e}")

    try:
        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = {executor.submit(process_url, u): u for u in urls}
            for future in as_completed(futures):
                exc = future.exception()
                if exc:
                    print(f"[ERROR] Thread for {futures[future]} raised: {exc}")
    finally:
        output_file.close()
