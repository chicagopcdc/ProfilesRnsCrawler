#!/usr/bin/env python3
"""Load RDF files into Apache Jena Fuseki via the SPARQL Graph Store Protocol.

Fuseki GSP write endpoint:
  POST {base_url}/{dataset}/data          — add triples to the default graph
  POST {base_url}/{dataset}/data?graph=.. — add triples to a named graph

Docs:
  https://jena.apache.org/documentation/fuseki2/fuseki-server-protocol.html
  https://www.w3.org/TR/sparql11-http-rdf-update/

A single requests.Session is reused for all POSTs so that the TCP (and TLS)
connection is kept alive across files, eliminating per-file handshake overhead.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import time
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter

RDF_CONTENT_TYPE = "application/rdf+xml"
SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULT_RETRIES = 3
RETRY_BACKOFF = [2, 5, 10]   # seconds to wait before attempt 2, 3, 4


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        os.environ.setdefault(key, value)


def collect_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            if path.suffix.lower() == ".rdf":
                files.append(path)
            else:
                print(f"Warning: skipping non-.rdf file: {path}", file=sys.stderr)
        elif path.is_dir():
            files.extend(sorted(path.rglob("*.rdf")))
        else:
            print(f"Warning: path not found, skipping: {path}", file=sys.stderr)
    return files


def data_url(base_url: str, dataset: str, graph: str | None = None) -> str:
    url = f"{base_url.rstrip('/')}/{dataset.strip('/')}/data"
    if graph:
        url += f"?graph={graph}"
    return url


def resolve_credentials(
    username: str | None, password: str | None
) -> tuple[str | None, str | None]:
    if not username:
        if password:
            raise SystemExit(
                "FUSEKI_PASSWORD / --password set without a username "
                "(use --username or FUSEKI_USERNAME)"
            )
        return None, None
    if password is None:
        password = getpass.getpass(f"Password for Fuseki user {username!r}: ")
    return username, password


def make_session(username: str | None, password: str | None) -> requests.Session:
    session = requests.Session()
    if username:
        session.auth = (username, password)
    # One connection pool per host; allow up to 4 connections (future parallelism)
    adapter = HTTPAdapter(pool_connections=1, pool_maxsize=4)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def load_file(
    session: requests.Session,
    path: Path,
    url: str,
    dry_run: bool,
    retries: int = DEFAULT_RETRIES,
) -> int:
    if dry_run:
        auth_hint = f" (auth: {session.auth[0]})" if session.auth else ""
        print(f"  POST {url}{auth_hint}  < {path}")
        return 204

    for attempt in range(1, retries + 2):
        try:
            with open(path, "rb") as f:
                resp = session.post(
                    url,
                    data=f,
                    headers={"Content-Type": RDF_CONTENT_TYPE},
                    timeout=60,
                )
            code = resp.status_code
        except requests.RequestException as exc:
            code = 0
            body = str(exc)
        else:
            body = resp.text

        if str(code).startswith("2"):
            if attempt > 1:
                print(f"  OK after {attempt} attempts")
            return code

        is_last = attempt == retries + 1
        is_retryable = str(code).startswith("5") or code == 0
        if is_last or not is_retryable:
            print(f"  FAILED HTTP {code}: {body[:200]}", file=sys.stderr)
            return code

        wait = RETRY_BACKOFF[min(attempt - 1, len(RETRY_BACKOFF) - 1)]
        print(
            f"  HTTP {code} — retrying in {wait}s (attempt {attempt}/{retries + 1})",
            file=sys.stderr,
        )
        time.sleep(wait)

    return code  # unreachable


def _fmt_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s:02d}s" if m else f"{s}s"


def main() -> None:
    load_env_file(SCRIPT_DIR / "fuseki.env")

    parser = argparse.ArgumentParser(
        description="Load RDF into Apache Jena Fuseki via the Graph Store Protocol."
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="RDF file(s) or directory(ies) to load",
    )
    parser.add_argument(
        "-b", "--base-url",
        default=os.environ.get("FUSEKI_BASE_URL", "http://localhost:3030"),
        help="Fuseki base URL (default: $FUSEKI_BASE_URL or http://localhost:3030)",
    )
    parser.add_argument(
        "-d", "--dataset",
        default=os.environ.get("FUSEKI_DATASET"),
        help="Dataset name (default: $FUSEKI_DATASET)",
    )
    parser.add_argument(
        "-g", "--graph",
        default=os.environ.get("FUSEKI_GRAPH"),
        help="Named graph URI to load into (default: default graph)",
    )
    parser.add_argument(
        "-u", "--username",
        default=os.environ.get("FUSEKI_USERNAME"),
        help="Fuseki username (default: $FUSEKI_USERNAME)",
    )
    parser.add_argument(
        "-p", "--password",
        default=os.environ.get("FUSEKI_PASSWORD"),
        help="Fuseki password (default: $FUSEKI_PASSWORD; prompted if username set)",
    )
    parser.add_argument(
        "-r", "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help=f"Max retries on HTTP 5xx (default: {DEFAULT_RETRIES})",
    )
    parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Print what would be posted without sending",
    )
    args = parser.parse_args()

    if not args.dataset:
        parser.error("dataset name is required (-d / --dataset or FUSEKI_DATASET)")

    username, password = resolve_credentials(args.username, args.password)
    files = collect_files(args.paths)
    if not files:
        raise SystemExit("No RDF files found.")

    url = data_url(args.base_url, args.dataset, args.graph)
    total = len(files)

    print(f"Fuseki:  {args.base_url.rstrip('/')}")
    print(f"Dataset: {args.dataset}")
    print(f"Graph:   {args.graph or '(default graph)'}")
    print(f"Auth:    {username if username else '(none)'}")
    print(f"Files:   {total}")
    print(f"Retries: {args.retries} on HTTP 5xx")
    print()

    ok = 0
    fail = 0
    start = time.monotonic()

    with make_session(username, password) as session:
        for i, path in enumerate(files, start=1):
            pct = i * 100 // total
            elapsed = time.monotonic() - start
            eta = ""
            if i > 1:
                rate = (i - 1) / elapsed
                remaining = (total - i) / rate
                eta = f"  eta {_fmt_duration(remaining)}"
            print(f"[{i}/{total}] ({pct}%){eta}  {path.name}")
            code = load_file(session, path, url, args.dry_run, args.retries)
            if str(code).startswith("2"):
                ok += 1
            else:
                fail += 1

    elapsed = time.monotonic() - start
    print()
    print(f"Done in {_fmt_duration(elapsed)}. succeeded={ok} failed={fail} total={total}")
    if fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
