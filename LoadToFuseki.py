#!/usr/bin/env python3
"""Load RDF files into Apache Jena Fuseki via the SPARQL Graph Store Protocol.

Fuseki GSP write endpoint:
  POST {base_url}/{dataset}/data          — add triples to the default graph
  POST {base_url}/{dataset}/data?graph=.. — add triples to a named graph

Docs:
  https://jena.apache.org/documentation/fuseki2/fuseki-server-protocol.html
  https://www.w3.org/TR/sparql11-http-rdf-update/

Authentication uses HTTP Basic Auth (--username / --password or env vars).
The Fuseki admin password is set via the ADMIN_PASSWORD env var on the server.
"""

from __future__ import annotations

import argparse
import getpass
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

RDF_CONTENT_TYPE = "application/rdf+xml"
SCRIPT_DIR = Path(__file__).resolve().parent


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
    """Return the Fuseki GSP write endpoint URL for the given dataset."""
    url = f"{base_url.rstrip('/')}/{dataset.strip('/')}/data"
    if graph:
        url += f"?graph={graph}"
    return url


def resolve_credentials(
    username: str | None, password: str | None
) -> tuple[str | None, str | None]:
    """Return (username, password) for Basic auth, or (None, None) if unused."""
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


def redact_curl_args(args: list[str]) -> list[str]:
    """Mask password in --user user:pass for dry-run output."""
    redacted: list[str] = []
    hide_next = False
    for arg in args:
        if hide_next:
            if ":" in arg:
                user, _, _ = arg.partition(":")
                redacted.append(f"{user}:***")
            else:
                redacted.append("***")
            hide_next = False
            continue
        if arg in ("-u", "--user"):
            redacted.append(arg)
            hide_next = True
            continue
        redacted.append(arg)
    return redacted


def run_curl(args: list[str], dry_run: bool) -> tuple[int, str]:
    if dry_run:
        print("  " + " ".join(shlex.quote(a) for a in redact_curl_args(args)))
        return 204, ""
    result = subprocess.run(args, capture_output=True, text=True)
    body = (result.stdout or "") + (result.stderr or "")
    http_code = 0
    if result.stdout:
        lines = result.stdout.strip().splitlines()
        if lines and lines[-1].isdigit():
            http_code = int(lines[-1])
            body = "\n".join(lines[:-1]).strip()
    if http_code == 0:
        http_code = 500 if result.returncode != 0 else 200
    return http_code, body


def load_file(
    path: Path,
    url: str,
    dry_run: bool,
    username: str | None = None,
    password: str | None = None,
) -> int:
    curl = [
        "curl",
        "-sS",
        "-o",
        "-",
        "-w",
        "\n%{http_code}",
        "-X",
        "POST",
        "-H",
        f"Content-Type: {RDF_CONTENT_TYPE}",
        "--data-binary",
        f"@{path}",
    ]
    if username is not None and password is not None:
        curl.extend(["--user", f"{username}:{password}"])
    curl.append(url)
    code, body = run_curl(curl, dry_run)
    if not str(code).startswith("2"):
        print(f"  FAILED HTTP {code}: {body}", file=sys.stderr)
    return code


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
        "-b",
        "--base-url",
        default=os.environ.get("FUSEKI_BASE_URL", "http://localhost:3030"),
        help="Fuseki base URL (default: $FUSEKI_BASE_URL or http://localhost:3030)",
    )
    parser.add_argument(
        "-d",
        "--dataset",
        default=os.environ.get("FUSEKI_DATASET"),
        help="Dataset name (default: $FUSEKI_DATASET)",
    )
    parser.add_argument(
        "-g",
        "--graph",
        default=os.environ.get("FUSEKI_GRAPH"),
        help="Named graph URI to load into (default: default graph)",
    )
    parser.add_argument(
        "-u",
        "--username",
        default=os.environ.get("FUSEKI_USERNAME"),
        help="Fuseki username (default: $FUSEKI_USERNAME)",
    )
    parser.add_argument(
        "-p",
        "--password",
        default=os.environ.get("FUSEKI_PASSWORD"),
        help="Fuseki password (default: $FUSEKI_PASSWORD; prompted if username set)",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Print curl commands without executing",
    )
    args = parser.parse_args()

    if not args.dataset:
        parser.error("dataset name is required (-d / --dataset or FUSEKI_DATASET)")
    if shutil.which("curl") is None:
        raise SystemExit("curl is required on PATH")

    username, password = resolve_credentials(args.username, args.password)

    files = collect_files(args.paths)
    if not files:
        raise SystemExit("No RDF files found.")

    url = data_url(args.base_url, args.dataset, args.graph)

    print(f"Fuseki:  {args.base_url.rstrip('/')}")
    print(f"Dataset: {args.dataset}")
    print(f"Graph:   {args.graph or '(default graph)'}")
    print(f"Auth:    {username if username else '(none)'}")
    print(f"Files:   {len(files)}")
    print()

    ok = 0
    fail = 0
    for i, path in enumerate(files, start=1):
        print(f"[{i}/{len(files)}] POST {path.name}")
        code = load_file(path, url, args.dry_run, username, password)
        if str(code).startswith("2"):
            ok += 1
        else:
            fail += 1

    print()
    print(f"Done. succeeded={ok} failed={fail} total={len(files)}")
    if fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
