# ProfilesRnsCrawler

Utilities for crawling Profiles RNS directories and extracting email addresses from image-based email fields.

## Scripts

This folder has three main workflows.

### 1. Crawl Profiles RNS RDF files

- `ProfilesRnsCrawler.py`: crawls a Profiles RNS search result and collects profile names, profile links, and RDF links
- `GetProfiles.py`: command-line wrapper that saves the profile list to CSV and downloads RDF files

### 2. Extract email addresses from encrypted email fields

- `get_emails.py`: reads one CSV or many CSV files, fetches email images from the Profiles email handler, runs OCR, and writes extracted emails to CSV
- `get_emails.sh`: wrapper script with batch defaults and logging for the current UChicago workflow
- `ProfilesRnsWebCrawler.py`: older one-off OCR experiment

### 3. Load extracted emails into GraphDB

- `add_email_to_graphdb.py`: reads a CSV with extracted email addresses, builds batched SPARQL updates, and inserts `vivo:primaryEmail` triples into GraphDB
- `add_email_to_graphdb.sh`: wrapper script with GraphDB defaults, CSV input defaults, and logging for the current UChicago workflow

## Setup

Install Python packages:

```bash
python3 -m pip install -r requirements.txt
```

This installs the OCR dependencies plus `SPARQLWrapper` for the GraphDB loader.

Install Tesseract on macOS:

```bash
brew install tesseract
```

## Input Format

`get_emails.py` expects CSV rows with at least these columns:

- `person`
- `emailencrypted`

Example:

```csv
person,emailencrypted
https://profiles.uchicago.edu/profiles/profile/12345678,abc123...
```

`add_email_to_graphdb.py` expects CSV rows with at least these columns:

- `person`
- `extracted_email`

Example:

```csv
person,extracted_email
https://profiles.uchicago.edu/profiles/profile/12345678,user@uchicago.edu
```

## Run

### RDF crawl workflow

Use `GetProfiles.py` to crawl profile pages and download RDF files.

Example:

```bash
python3 GetProfiles.py \
  --url 'https://profiles.rush.edu/search/default.aspx?searchtype=people&classuri=http://xmlns.com/foaf/0.1/Person&searchfor=&perpage=100&offset=0&page=' \
  --outfile links/rush_people_links.csv \
  --rdf_folder rdf/rush
```

```bash
python3 GetProfiles.py \
  --url 'https://profiles.uchicago.edu/profiles/search/default.aspx?searchtype=people&classuri=http://xmlns.com/foaf/0.1/Person&searchfor=&perpage=100&offset=0&page=' \
  --outfile links/uchicago_people_links.csv \
  --rdf_folder rdf/uchicago
```


This workflow:

- crawls paginated profile search results
- saves profile metadata to CSV
- downloads RDF files into the target folder

### Email extraction workflow

Default batch mode:

```bash
bash get_emails.sh
```

Direct single-file mode:

```bash
python3 get_emails.py \
  --csv-file email/uchicago_emailencrypted_sample.csv \
  --output-csv-file email/uchicago_extracted_emails_sample.csv
```

Direct multi-file mode:

```bash
python3 get_emails.py \
  --csv-glob 'email/uchicago_emailencrypted_split/*.csv' \
  --output-dir email/uchicago_extracted_split
```

Show all options:

```bash
python3 get_emails.py --help
```

### GraphDB email import workflow

Default wrapper mode:

```bash
bash add_email_to_graphdb.sh
```

Direct mode:

```bash
python3 add_email_to_graphdb.py
```

Override the GraphDB target or CSV file for a run:

```bash
GRAPHDB_STATEMENTS_URL="http://localhost:7200/repositories/ITM_Julian/statements" \
GRAPHDB_NAMED_GRAPH="https://profiles.uchicago.edu/profiles/" \
CSV_FILE="email/uchicago_extracted_all.csv" \
CHUNK_SIZE=500 \
bash add_email_to_graphdb.sh
```

This workflow:

- reads `(person, extracted_email)` rows from the CSV file
- sends SPARQL `INSERT` updates to the configured GraphDB statements endpoint in batches
- logs the start time, end time, elapsed runtime, and batch progress

## Current Batch Defaults

`get_emails.sh` currently uses:

- `CSV_GLOB="email/uchicago_emailencrypted_split/*.csv"`
- `OUTPUT_DIR="email/uchicago_extracted_split"`
- `MIN_DELAY_SECONDS=2`
- `MAX_DELAY_SECONDS=4`
- `FILE_DELAY_SECONDS=30`
- `MAX_RETRIES=4`
- `BACKOFF_BASE_SECONDS=10`
- `BACKOFF_CAP_SECONDS=300`

Each run is logged to `logs/get_emails_YYYYMMDD_HHMMSS.log` unless `LOG_DIR` or `LOG_FILE` is overridden.

`add_email_to_graphdb.sh` currently uses:

- `GRAPHDB_STATEMENTS_URL="http://localhost:7200/repositories/ITM_Julian/statements"`
- `GRAPHDB_NAMED_GRAPH="https://profiles.uchicago.edu/profiles/"`
- `CSV_FILE="email/uchicago_extracted_all.csv"`
- `CHUNK_SIZE=500`

Each run is logged to `logs/add_email_to_graphdb_YYYYMMDD_HHMMSS.log` unless `LOG_DIR` or `LOG_FILE` is overridden.

## Resume Behavior

The script resumes from an existing output CSV:

- existing rows are matched by `person`
- completed rows are skipped
- progress is saved after each processed row

This lets you restart a stopped run without losing progress.

## Output

Output CSV files contain the original columns plus:

- `extracted_email`

In batch mode, outputs are written like this:

```text
email/uchicago_extracted_split/uchicago_emailencrypted_part_001_extracted.csv
```

The GraphDB loader does not write a new CSV. It reads an extracted-email CSV and writes triples directly to the configured GraphDB repository.

## Other Scripts

- `ProfilesRnsCrawler.py` and `GetProfiles.py` support the RDF crawl workflow
- `ProfilesRnsWebCrawler.py` is an older OCR experiment kept for reference

Use `GetProfiles.py` for RDF crawling, `get_emails.py` or `get_emails.sh` for email extraction, and `add_email_to_graphdb.py` or `add_email_to_graphdb.sh` for GraphDB import.