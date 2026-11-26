import gzip
import hashlib
import json
import multiprocessing
import time
from pathlib import Path
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from .store import atomic_file
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

USER_AGENT = "ProjectMealCatalog/0.1 (+public grocery catalog research)"
MAX_BYTES = 16 * 1024 * 1024


class FetchError(Exception):
    pass


class BudgetReached(FetchError):
    pass


class SafeRedirect(HTTPRedirectHandler):
    def __init__(self, hosts):
        self.hosts = hosts

    def redirect_request(self, request, fp, code, message, headers, newurl):
        parsed = urlsplit(newurl)
        if parsed.scheme != "https" or parsed.hostname not in self.hosts:
            raise FetchError("Redirect leaves the configured retailer domains")
        return super().redirect_request(request, fp, code, message, headers, newurl)


def download(url, hosts, connection):
    """Isolate DNS as well as socket reads so a dead resolver cannot hang the worker."""
    try:
        opener = build_opener(SafeRedirect(hosts))
        request = Request(url, headers={"User-Agent": USER_AGENT,
                                       "Accept": "application/json,text/html,application/xml"})
        with opener.open(request, timeout=20) as response:
            chunks, size = [], 0
            while True:
                chunk = response.read1(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BYTES:
                    raise FetchError("Response exceeds 16 MiB safety limit")
                chunks.append(chunk)
            connection.send(("ok", b"".join(chunks), response.url, response.headers.get("Content-Type", "")))
    except HTTPError as error:
        connection.send(("http_error", error.code, error.headers.get("Retry-After", "")))
    except Exception as error:
        connection.send(("error", type(error).__name__))
    finally:
        connection.close()


def bounded_request(url, hosts, timeout=45):
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=download, args=(url, hosts, sender), daemon=True)
    process.start()
    sender.close()
    try:
        if not receiver.poll(timeout):
            raise TimeoutError("DNS or network request exceeded 45 seconds")
        try:
            return receiver.recv()
        except EOFError as error:
            raise OSError("Network subprocess ended without a response") from error
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
        process.join(timeout=2)
        if process.is_alive():
            process.kill()
            process.join()


class Client:
    def __init__(self, source, root: Path, max_pages):
        self.source = source
        self.hosts = set(source["hosts"])
        self.root = root
        self.max_pages = max_pages
        self.pages = 0
        self.last_request = 0
        self.robots = {}
        self.last_evidence = None

    def allowed_url(self, url):
        parts = urlsplit(url)
        return parts.scheme == "https" and parts.hostname in self.hosts and not parts.username

    def _defer_rate_limit(self, retry):
        delay = 900
        if retry and retry.isdigit():
            delay = max(60, int(retry))
        elif retry:
            try:
                deadline = parsedate_to_datetime(retry)
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=timezone.utc)
                delay = max(60, deadline.timestamp() - time.time())
            except (TypeError, ValueError, OverflowError):
                pass
        destination = self.root / "cooldowns" / (self.source["id"] + ".json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with atomic_file(destination) as output:
            json.dump({"retry_at": time.time() + delay}, output)

    def _raw(self, url):
        cooldown = self.root / "cooldowns" / (self.source["id"] + ".json")
        if cooldown.exists():
            retry_at = json.loads(cooldown.read_text())["retry_at"]
            if time.time() < retry_at:
                deadline = datetime.fromtimestamp(retry_at, timezone.utc).isoformat(timespec="seconds")
                raise FetchError(f"HTTP 429; saved rate-limit pause until {deadline}")
        for attempt in range(3):
            delay = max(float(self.source.get("delay_seconds", 1.5)),
                        float(self.source.get("crawl_delay", 0)))
            time.sleep(max(0, delay - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            try:
                result = bounded_request(url, self.hosts)
                if result[0] == "ok":
                    return result[1], result[2], result[3]
                if result[0] == "http_error":
                    code, retry = result[1], result[2]
                    if code == 429 and (attempt == 2 or retry and (not retry.isdigit() or int(retry) > 45)):
                        self._defer_rate_limit(retry)
                        raise FetchError("HTTP 429; source backoff saved for the next run")
                    if code in (429, 500, 502, 503, 504) and attempt < 2:
                        if retry and (not retry.isdigit() or int(retry) > 45):
                            raise FetchError(f"HTTP {code}; retry postponed to next run")
                        time.sleep(max(int(retry or 0), 2 ** (attempt + 1)))
                        continue
                    raise FetchError(f"HTTP {code} from {url}")
                raise OSError(result[1])
            except (TimeoutError, OSError) as error:
                if attempt < 2:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise FetchError(f"Request failed for {url}: {type(error).__name__}") from error
        raise FetchError("Retry limit reached")

    def check_robots(self, url):
        origin = f"https://{urlsplit(url).netloc}"
        if origin not in self.robots:
            try:
                body, _, content_type = self._raw(origin + "/robots.txt")
            except FetchError as error:
                if "HTTP 404 " in str(error):
                    body, content_type = b"", "text/plain"
                else:
                    raise
            if "html" in content_type or b"<html" in body.lower():
                raise FetchError("robots.txt is HTML; collection paused until source access is reviewed")
            parser = RobotFileParser()
            parser.parse(body.decode("utf-8", "replace").splitlines())
            self.robots[origin] = parser
            self.source["crawl_delay"] = max(self.source.get("crawl_delay", 0),
                                             parser.crawl_delay(USER_AGENT) or parser.crawl_delay("*") or 0)
        if not self.robots[origin].can_fetch(USER_AGENT, url):
            raise FetchError(f"robots.txt disallows {url}")

    def get(self, url):
        if not self.allowed_url(url):
            raise FetchError("URL leaves the configured retailer domains")
        self.check_robots(url)
        if self.pages >= self.max_pages:
            raise BudgetReached("Per-source page limit reached; resume on the next run")
        self.pages += 1
        body, final_url, content_type = self._raw(url)
        if final_url != url:
            self.check_robots(final_url)
        digest = hashlib.sha256(body).hexdigest()
        relative = Path("raw") / self.source["id"] / f"{digest}.gz"
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            destination.write_bytes(gzip.compress(body))
        self.last_evidence = {"sha256": digest, "raw_file": str(relative),
                              "requested_url": url, "final_url": final_url, "content_type": content_type}
        return body.decode("utf-8", "replace")

    def get_json(self, url):
        try:
            return json.loads(self.get(url))
        except json.JSONDecodeError as error:
            raise FetchError("Expected JSON but received a different page format") from error
