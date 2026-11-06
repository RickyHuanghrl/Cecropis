"""User-run, resumable HTTPS download of official MaleCNS EM skeletons.

Standard library only. No installation, credentials or Git required.
Run this script explicitly; importing it never accesses the network.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait
import json
from pathlib import Path
import queue
import re
import shutil
import ssl
import threading
import time
import sys
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

BUCKET = "flyem-male-cns"
PREFIX = "v1.0/segmentation/skeletons-malecns/skeletons-precomputed/"
LIST_URL = f"https://storage.googleapis.com/storage/v1/b/{BUCKET}/o"
SSL_CONTEXT = ssl.create_default_context()


def open_url(url, headers=None):
    request = Request(url, headers={"User-Agent": "MaleCNS-local-download/1", **(headers or {})})
    return urlopen(request, timeout=40, context=SSL_CONTEXT)


def listing(control, offline=False, quiet=False):
    """Cache each complete metadata page; later invocations reuse these pages."""
    token = None
    items = []
    page_number = 0
    while True:
        page_path = control / f"listing-{page_number:04d}.json"
        if page_path.exists():
            page = json.loads(page_path.read_text(encoding="utf-8"))
        else:
            if offline:
                raise FileNotFoundError('Complete cached listing is unavailable; explicitly refresh metadata before starting')
            query = dict(prefix=PREFIX, maxResults=1000,
                         fields="items(name,size,generation),nextPageToken")
            if token:
                query["pageToken"] = token
            for attempt in range(5):
                try:
                    with open_url(LIST_URL + "?" + urlencode(query)) as response:
                        payload = response.read()
                    page = json.loads(payload)
                    break
                except (OSError, ValueError):
                    if attempt == 4:
                        raise
                    time.sleep(min(2 ** attempt, 8))
            temporary = page_path.with_suffix(".tmp")
            temporary.write_bytes(payload)
            temporary.replace(page_path)
        for item in page.get("items", []):
            name = item["name"]
            if not name.startswith(PREFIX):
                raise ValueError(f"Unexpected object prefix: {name}")
            relative = name[len(PREFIX):]
            if not re.fullmatch(r"(?:[0-9]+|info)", relative):
                raise ValueError(f"Unexpected object name: {relative}; no files downloaded")
            items.append(dict(name=relative, size=int(item["size"]),
                              generation=item["generation"]))
        page_number += 1
        if page_number % 20 == 0 and not quiet:
            print(f"Directory: {len(items):,} objects listed", flush=True)
        token = page.get("nextPageToken")
        if not token:
            break
    if not any(item["name"] == "info" for item in items):
        raise ValueError("Official listing has no info metadata; download stopped")
    if len({item["name"] for item in items}) != len(items):
        raise ValueError("Duplicate objects in listing; download stopped")
    return sorted(items, key=lambda item: (item["name"] != "info", item["name"]))


def object_url(item):
    if item.get('url'):
        return item['url']
    name = quote(PREFIX + item["name"], safe="")
    query = urlencode(dict(alt="media", generation=item["generation"]))
    return f"https://storage.googleapis.com/download/storage/v1/b/{BUCKET}/o/{name}?{query}"


def partial_path(target, name):
    """Continue an existing legacy .part; never merge two partial payloads."""
    current=target/(name+'.partial');legacy=target/(name+'.part')
    if current.exists() and legacy.exists():
        raise ValueError(f'Two partial files exist for {name}; choose one before continuing')
    return legacy if legacy.exists() else current


def download_one(item, target, stop, progress=None):
    path = target / item["name"]
    partial = partial_path(target, item['name'])
    expected = item["size"]
    if path.exists() and path.stat().st_size == expected:
        return "skipped"
    for attempt in range(5):
        if stop.is_set():
            return "interrupted"
        offset = partial.stat().st_size if partial.exists() else 0
        if offset > expected:
            raise ValueError(f"Partial file exceeds listed size: {partial}")
        if offset == expected and partial.exists():
            partial.replace(path)
            return "downloaded"
        headers = {"Accept-Encoding": "identity"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        try:
            with open_url(object_url(item), headers) as response:
                if offset:
                    content_range = response.headers.get("Content-Range", "")
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
                    if (response.status != 206 or not match or
                            int(match[1]) != offset or int(match[3]) != expected):
                        raise ValueError("Server did not honor the requested resume range")
                elif response.status != 200:
                    raise ValueError(f"Unexpected HTTP status: {response.status}")
                with partial.open("ab" if offset else "wb") as stream:
                    while not stop.is_set():
                        block = response.read(256 * 1024)
                        if not block:
                            break
                        stream.write(block)
                        if progress:
                            progress(len(block))
            if stop.is_set():
                return "interrupted"
            actual = partial.stat().st_size
            if actual > expected:
                raise ValueError(f"Received {actual} bytes; expected {expected}")
            if actual != expected:
                raise OSError(f"Incomplete transfer: {actual}/{expected} bytes")
            partial.replace(path)
            return "downloaded"
        except HTTPError as error:
            if error.code not in (408, 429, 500, 502, 503, 504) or attempt == 4:
                raise
        except OSError:
            if attempt == 4:
                raise
        if stop.wait(min(2 ** attempt, 8)):
            return "interrupted"
    return "interrupted"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True,
                        help="User-selected destination; relative to the current directory")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument('--mode', choices=('plan','status','start'), default='plan')
    parser.add_argument('--refresh-listing', action='store_true', help='Explicitly fetch missing official listing pages')
    args = parser.parse_args()
    # Shared entry point owns plan/status and the same mature per-file downloader.
    try:
        from .download_data import run_download,cli_emit
    except ImportError:
        from download_data import run_download,cli_emit
    return run_download('skeletons', args.target, args.mode, args.workers, args.refresh_listing,emit=cli_emit)


if __name__ == "__main__":
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped; existing listing pages and partial files retained.")
        raise SystemExit(130)
