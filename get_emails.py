from __future__ import annotations

import argparse
import csv
import io
import os
import random
import re
import time
import uuid
from pathlib import Path

import requests

try:
    import pytesseract
except ImportError:  # pragma: no cover - runtime dependency guard
    pytesseract = None

try:
    from PIL import Image, UnidentifiedImageError
except ImportError:  # pragma: no cover - runtime dependency guard
    Image = None

    class UnidentifiedImageError(Exception):
        pass

DEFAULT_BASE_PROFILE_PREFIX = "https://profiles.uchicago.edu/profiles/profile/"
DEFAULT_EMAIL_HANDLER_URL = (
    "https://profiles.uchicago.edu/profiles/profile/modules/"
    "CustomViewPersonGeneralInfo/EmailHandler.ashx"
)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return float(value)


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch email images sequentially with jitter, retries, and resume support."
    )
    parser.add_argument(
        "--csv-file",
        default=os.getenv("CSV_FILE", "email/uchicago_emailencrypted_sample.csv"),
        help="Single input CSV file or a directory containing CSV files.",
    )
    parser.add_argument(
        "--csv-glob",
        default=os.getenv("CSV_GLOB", ""),
        help="Glob for multiple input CSV files, for example email/split/*.csv.",
    )
    parser.add_argument(
        "--output-csv-file",
        default=os.getenv("OUTPUT_CSV_FILE", "email/uchicago_extracted_emails_sample.csv"),
        help="Output CSV path for single-file mode.",
    )
    parser.add_argument(
        "--output-dir",
        default=os.getenv("OUTPUT_DIR", ""),
        help="Output directory for multi-file mode. Defaults next to each input file.",
    )
    parser.add_argument(
        "--base-profile-prefix",
        default=os.getenv("BASE_PROFILE_PREFIX", DEFAULT_BASE_PROFILE_PREFIX),
        help="Profile URL prefix used to derive the profile key.",
    )
    parser.add_argument(
        "--email-handler-url",
        default=os.getenv("EMAIL_HANDLER_URL", DEFAULT_EMAIL_HANDLER_URL),
        help="Email image handler endpoint.",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=env_float("REQUEST_TIMEOUT", 20.0),
        help="Per-request timeout in seconds.",
    )
    parser.add_argument(
        "--min-delay",
        type=float,
        default=env_float("MIN_DELAY_SECONDS", 2.0),
        help="Minimum delay between requests in seconds.",
    )
    parser.add_argument(
        "--max-delay",
        type=float,
        default=env_float("MAX_DELAY_SECONDS", 4.0),
        help="Maximum delay between requests in seconds.",
    )
    parser.add_argument(
        "--file-delay",
        type=float,
        default=env_float("FILE_DELAY_SECONDS", 30.0),
        help="Delay between input files in seconds.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=env_int("MAX_RETRIES", 4),
        help="Maximum retries for retryable failures.",
    )
    parser.add_argument(
        "--backoff-base",
        type=float,
        default=env_float("BACKOFF_BASE_SECONDS", 10.0),
        help="Initial backoff delay in seconds.",
    )
    parser.add_argument(
        "--backoff-cap",
        type=float,
        default=env_float("BACKOFF_CAP_SECONDS", 300.0),
        help="Maximum backoff delay in seconds.",
    )
    return parser


def discover_input_files(csv_file: str, csv_glob: str) -> list[Path]:
    if csv_glob:
        return sorted(Path().glob(csv_glob))

    csv_path = Path(csv_file)
    if csv_path.is_dir():
        return sorted(csv_path.glob("*.csv"))
    return [csv_path]


def resolve_output_path(input_path: Path, args: argparse.Namespace, multi_file: bool) -> Path:
    if not multi_file:
        return Path(args.output_csv_file)

    if args.output_dir:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir / f"{input_path.stem}_extracted.csv"

    return input_path.with_name(f"{input_path.stem}_extracted.csv")


def load_email_tokens(csv_file: Path, base_profile_prefix: str) -> list[tuple[str, dict[str, str], str]]:
    rows: list[tuple[str, dict[str, str], str]] = []
    with csv_file.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            person = (row.get("person") or "").strip()
            token = (row.get("emailencrypted") or "").strip()
            if not person or not token:
                continue
            if person.startswith(base_profile_prefix):
                key = person[len(base_profile_prefix) :]
            else:
                key = person
            rows.append((key, row, token))
    return rows


def load_existing_results(output_csv: Path) -> dict[str, dict[str, str]]:
    if not output_csv.exists():
        return {}

    existing: dict[str, dict[str, str]] = {}
    with output_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            person = (row.get("person") or "").strip()
            if person:
                existing[person] = row
    return existing


def is_image_response(resp: requests.Response) -> bool:
    content_type = (resp.headers.get("Content-Type") or "").lower()
    return content_type.startswith("image/")


def cleanup_email_text(raw_text: str) -> str:
    normalized = raw_text.replace("\n", " ").replace("\r", " ").strip()
    normalized = re.sub(r"\s+", "", normalized)
    match = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", normalized)
    if match:
        return match.group(0).rstrip("_.-")
    return normalized.rstrip("_.,;:-")


def save_results(output_csv: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        return

    fieldnames = list(rows[0].keys())
    if "extracted_email" not in fieldnames:
        fieldnames.append("extracted_email")

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def request_with_backoff(
    session: requests.Session,
    email_handler_url: str,
    token: str,
    timeout: float,
    max_retries: int,
    backoff_base: float,
    backoff_cap: float,
) -> requests.Response:
    last_exception: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            response = session.get(
                email_handler_url,
                params={"msg": token, "rnd": str(uuid.uuid4())},
                timeout=timeout,
                allow_redirects=True,
            )
            if response.status_code in RETRYABLE_STATUS_CODES:
                if attempt == max_retries:
                    response.raise_for_status()
                retry_after = response.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    sleep_seconds = min(float(retry_after), backoff_cap)
                else:
                    sleep_seconds = min(backoff_base * (2**attempt), backoff_cap)
                print(
                    f"Retryable status {response.status_code}; sleeping {sleep_seconds:.1f}s before retry"
                )
                time.sleep(sleep_seconds)
                continue

            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_exception = exc
            if attempt == max_retries:
                break
            sleep_seconds = min(backoff_base * (2**attempt), backoff_cap)
            print(f"Request failed ({exc}); sleeping {sleep_seconds:.1f}s before retry")
            time.sleep(sleep_seconds)

    if last_exception is None:
        raise RuntimeError("Request retries exhausted without a captured exception")
    raise last_exception


def extract_email_from_response(response: requests.Response) -> str:
    if pytesseract is None or Image is None:
        raise RuntimeError(
            "Missing OCR dependencies. Install pytesseract and Pillow before fetching emails."
        )

    if not is_image_response(response):
        raise ValueError(
            "non-image response "
            f"(Content-Type={response.headers.get('Content-Type')})"
        )

    image = Image.open(io.BytesIO(response.content))
    try:
        return cleanup_email_text(pytesseract.image_to_string(image))
    finally:
        image.close()


def process_csv_file(
    session: requests.Session,
    input_csv: Path,
    output_csv: Path,
    args: argparse.Namespace,
) -> tuple[int, int, int]:
    rows = load_email_tokens(input_csv, args.base_profile_prefix)
    existing = load_existing_results(output_csv)
    processed_rows: list[dict[str, str]] = []
    skipped_count = 0
    fetched_count = 0
    error_count = 0

    for key, original_row, token in rows:
        person = (original_row.get("person") or "").strip()
        if person in existing:
            processed_rows.append(existing[person])
            skipped_count += 1
            continue

        print(f"Processing {input_csv.name}: {key}")
        result_row = {**original_row, "extracted_email": ""}

        try:
            response = request_with_backoff(
                session,
                args.email_handler_url,
                token,
                args.request_timeout,
                args.max_retries,
                args.backoff_base,
                args.backoff_cap,
            )
            result_row["extracted_email"] = extract_email_from_response(response)
            print(f"Extracted email for {key}: {result_row['extracted_email']}")
            fetched_count += 1
        except ValueError as exc:
            print(f"Skipped {key}: {exc}")
            error_count += 1
        except UnidentifiedImageError:
            print(f"Invalid image for {key}: response is not a readable image")
            error_count += 1
        except requests.RequestException as exc:
            print(f"Request error for {key}: {exc}")
            error_count += 1
        except Exception as exc:  # noqa: BLE001
            print(f"Unexpected error for {key}: {exc}")
            error_count += 1

        processed_rows.append(result_row)
        save_results(output_csv, processed_rows)
        time.sleep(random.uniform(args.min_delay, args.max_delay))

    return fetched_count, skipped_count, error_count


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.min_delay < 0 or args.max_delay < args.min_delay:
        parser.error("Delay settings must satisfy 0 <= min-delay <= max-delay")
    if args.max_retries < 0:
        parser.error("--max-retries must be non-negative")

    input_files = discover_input_files(args.csv_file, args.csv_glob)
    if not input_files:
        parser.error("No input CSV files found")

    multi_file = len(input_files) > 1
    total_fetched = 0
    total_skipped = 0
    total_errors = 0

    with requests.Session() as session:
        session.headers.update(
            {
                "User-Agent": "Mozilla/5.0",
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            }
        )

        for index, input_csv in enumerate(input_files):
            output_csv = resolve_output_path(input_csv, args, multi_file)
            fetched_count, skipped_count, error_count = process_csv_file(
                session,
                input_csv,
                output_csv,
                args,
            )
            total_fetched += fetched_count
            total_skipped += skipped_count
            total_errors += error_count

            print(f"Saved CSV output to: {output_csv}")
            print(
                f"Summary for {input_csv.name}: fetched={fetched_count}, "
                f"resumed={skipped_count}, errors={error_count}"
            )

            if index < len(input_files) - 1 and args.file_delay > 0:
                print(f"Sleeping {args.file_delay:.1f}s before next file")
                time.sleep(args.file_delay)

    print(
        f"Finished {len(input_files)} file(s): fetched={total_fetched}, "
        f"resumed={total_skipped}, errors={total_errors}"
    )


if __name__ == "__main__":
    main()