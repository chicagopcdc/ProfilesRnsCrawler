#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${LOG_DIR:-$SCRIPT_DIR/logs}"
RUN_TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_FILE:-$LOG_DIR/get_emails_${RUN_TIMESTAMP}.log}"

mkdir -p "$LOG_DIR"

export MIN_DELAY_SECONDS="${MIN_DELAY_SECONDS:-2}"
export MAX_DELAY_SECONDS="${MAX_DELAY_SECONDS:-4}"
export FILE_DELAY_SECONDS="${FILE_DELAY_SECONDS:-30}"
export MAX_RETRIES="${MAX_RETRIES:-4}"
export BACKOFF_BASE_SECONDS="${BACKOFF_BASE_SECONDS:-10}"
export BACKOFF_CAP_SECONDS="${BACKOFF_CAP_SECONDS:-300}"

# UChicago

# split files for polite queue processing
# export CSV_GLOB="${CSV_GLOB:-email/uchicago_emailencrypted_split/*.csv}"
# export OUTPUT_DIR="${OUTPUT_DIR:-email/uchicago_extracted_split}"

# for single file processing (e.g. retrying failed extractions)
# export CSV_GLOB=""
# export CSV_FILE="email/uchicago_emailencrypted_retry_wrong_extraction.csv"
# export OUTPUT_CSV_FILE="email/uchicago_extracted_retry_wrong_extraction_fresh.csv"

# optional single-file mode examples
# export CSV_FILE="${CSV_FILE:-email/uchicago_emailencrypted.csv}"
# export OUTPUT_CSV_FILE="${OUTPUT_CSV_FILE:-email/uchicago_extracted_emails.csv}"

# export BASE_PROFILE_PREFIX="${BASE_PROFILE_PREFIX:-https://profiles.uchicago.edu/profiles/profile/}"
# export EMAIL_HANDLER_URL="${EMAIL_HANDLER_URL:-https://profiles.uchicago.edu/profiles/profile/modules/CustomViewPersonGeneralInfo/EmailHandler.ashx}"


# Rush

export BASE_PROFILE_PREFIX="${BASE_PROFILE_PREFIX:-https://profiles.rush.edu/profile/}"
export EMAIL_HANDLER_URL="${EMAIL_HANDLER_URL:-https://profiles.rush.edu/profile/modules/CustomViewPersonGeneralInfo/EmailHandler.ashx}"

# # sample files for testing
# export CSV_FILE="${CSV_FILE:-email/rush_emailencrypted_sample.csv}"
# export OUTPUT_CSV_FILE="${OUTPUT_CSV_FILE:-email/rush_extracted_emails_sample.csv}"

# # actual list of encrypted emails to process
# export CSV_FILE="${CSV_FILE:-email/rush_emailencrypted.csv}"
# export OUTPUT_CSV_FILE="${OUTPUT_CSV_FILE:-email/rush_extracted_emails.csv}"
export CSV_FILE="${CSV_FILE:-email/rush_emailencrypted_failed.csv}"
export OUTPUT_CSV_FILE="${OUTPUT_CSV_FILE:-email/rush_extracted_failed_emails.csv}"



echo "Running get_emails.py with:"
echo "  CSV_GLOB=${CSV_GLOB:-}"
echo "  CSV_FILE=${CSV_FILE:-}"
echo "  OUTPUT_DIR=${OUTPUT_DIR:-}"
echo "  OUTPUT_CSV_FILE=${OUTPUT_CSV_FILE:-}"
echo "  MIN_DELAY_SECONDS=$MIN_DELAY_SECONDS"
echo "  MAX_DELAY_SECONDS=$MAX_DELAY_SECONDS"
echo "  FILE_DELAY_SECONDS=$FILE_DELAY_SECONDS"
echo "  MAX_RETRIES=$MAX_RETRIES"
echo "  BACKOFF_BASE_SECONDS=$BACKOFF_BASE_SECONDS"
echo "  BACKOFF_CAP_SECONDS=$BACKOFF_CAP_SECONDS"
echo "  LOG_FILE=$LOG_FILE"

cd "$SCRIPT_DIR"
python3 get_emails.py 2>&1 | tee "$LOG_FILE"
