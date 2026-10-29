import csv
import os
from pathlib import Path
import time
from datetime import datetime

from SPARQLWrapper import SPARQLWrapper, POST

GRAPHDB_STATEMENTS_URL = os.environ.get(
  "GRAPHDB_STATEMENTS_URL",
  "http://localhost:7200/repositories/ITM_Julian/statements",
)

sparql = SPARQLWrapper(GRAPHDB_STATEMENTS_URL)
sparql.setMethod(POST)

GRAPH = os.environ.get(
  "GRAPHDB_NAMED_GRAPH",
  "https://profiles.uchicago.edu/profiles/",
)
VIVO = "http://vivoweb.org/ontology/core#"
CSV_FILE = os.environ.get("CSV_FILE", "email/uchicago_extracted_all.csv")
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "500"))


def escape_sparql_string(value: str) -> str:
  return (
    value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
  )


def load_people_from_csv(csv_file: str) -> list[tuple[str, str]]:
  csv_path = Path(csv_file)
  if not csv_path.is_absolute():
    csv_path = Path(__file__).resolve().parent / csv_path

  people: list[tuple[str, str]] = []
  with csv_path.open(newline="", encoding="utf-8") as handle:
    reader = csv.DictReader(handle)
    for row in reader:
      person_uri = (row.get("person") or "").strip()
      email = (row.get("extracted_email") or "").strip()
      if not person_uri or not email:
        continue
      people.append((person_uri, email))

  return people

def build_values_block(batch: list[tuple[str, str]]) -> str:
    rows = "\n    ".join(
    f'(<{uri}> "{escape_sparql_string(email)}")'
        for uri, email in batch
    )
    return rows

def insert_emails_batch(batch: list[tuple[str, str]]):
    values_block = build_values_block(batch)
    query = f"""
PREFIX vivo: <{VIVO}>

INSERT {{
  GRAPH <{GRAPH}> {{
    ?person vivo:primaryEmail ?email .
  }}
}}
WHERE {{
  VALUES (?person ?email) {{
    {values_block}
  }}
}}
"""
    sparql.setQuery(query)
    sparql.query()

def main() -> None:
  start_time = time.perf_counter()
  start_timestamp = datetime.now().isoformat(timespec="seconds")
  print(f"Started at {start_timestamp}")

  people = load_people_from_csv(CSV_FILE)
  if not people:
    raise ValueError(f"No people with extracted_email found in {CSV_FILE}")

  for i in range(0, len(people), CHUNK_SIZE):
    chunk = people[i : i + CHUNK_SIZE]
    insert_emails_batch(chunk)
    print(f"Inserted {i + len(chunk)} / {len(people)}")

  end_timestamp = datetime.now().isoformat(timespec="seconds")
  elapsed_seconds = time.perf_counter() - start_time
  print(f"Finished at {end_timestamp}")
  print(f"Elapsed seconds: {elapsed_seconds:.2f}")


if __name__ == "__main__":
  main()