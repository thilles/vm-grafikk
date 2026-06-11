"""Leser tippesvarene fra Google Forms-regnearket.

Kilde (i prioritert rekkefølge):
1. SHEET_CSV_URL  – publisert CSV-lenke til Google Sheet (oppdateres live)
2. PREDICTIONS_XLSX – lokal Excel-fil (nedlastet kopi), standard /data/svar.xlsx
"""
import csv
import io
import logging
import os
import re

import httpx
import openpyxl

from .teams import canonical

log = logging.getLogger("vm.predictions")

RE_GROUP = re.compile(r"gruppe ([A-L])\?\s*\[(.+)\]", re.IGNORECASE)
RE_MATCH = re.compile(r"resultatet i (?:åpningskampen\s*)?(.+?)\?\s*\[(.+)\]", re.IGNORECASE)
RE_PLACE = re.compile(r"(\d)")


def _headers_rows_from_xlsx(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    return rows[0], rows[1:]


def _headers_rows_from_csv(url):
    resp = httpx.get(url, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    reader = csv.reader(io.StringIO(resp.text))
    rows = list(reader)
    return rows[0], rows[1:]


def _clean(h):
    return re.sub(r"\s+", " ", str(h or "")).strip()


def parse_rows(headers, rows):
    headers = [_clean(h) for h in headers]
    people = []
    for row in rows:
        if not any(row):
            continue
        p = {
            "name": None, "timestamp": None,
            "group_order": {},      # gruppe -> {canonical: plass}
            "matches": {},          # frozenset({lag1, lag2}) -> {canonical: mål}
            "jevnest": None, "norge_ut": None, "haiti": None,
            "toppscorer": None, "hattrick": None,
            "vinner": None, "taper_finale": None, "semifinalister": [],
            "sverige_r16": None, "afrika_qf": None, "qf_maal": None,
            "ryerson": None, "selvmaal_semi": None,
        }
        for header, value in zip(headers, row):
            if value is None or str(value).strip() == "":
                continue
            v = str(value).strip()

            if header == "Timestamp":
                p["timestamp"] = v
            elif header.startswith("Hele navnet"):
                p["name"] = v
            elif RE_GROUP.search(header):
                grp, team = RE_GROUP.search(header).groups()
                place = RE_PLACE.search(v)
                team_c = canonical(team)
                if team_c and place:
                    p["group_order"].setdefault(grp.upper(), {})[team_c] = int(place.group(1))
            elif RE_MATCH.search(header):
                _, team = RE_MATCH.search(header).groups()
                team_c = canonical(team)
                if team_c is not None:
                    p.setdefault("_match_cols", {})[team_c] = int(float(v))
            elif header.startswith("Hvilken gruppe blir jevnest"):
                p["jevnest"] = v  # "Gruppe D"
            elif header.startswith("I hvilken runde ryker Norge"):
                p["norge_ut"] = v
            elif header.startswith("Scorer Haiti"):
                p["haiti"] = v
            elif header.startswith("Hvem blir toppscorer"):
                p["toppscorer"] = v
            elif header.startswith("Hvem scorer første hattrick"):
                p["hattrick"] = v
            elif header.startswith("Hvilket lag vinner VM"):
                p["vinner"] = canonical(v) or v
            elif header.startswith("Hvilket lag taper VM-finalen"):
                p["taper_finale"] = canonical(v) or v
            elif header.startswith("Hvilke lag kommer til semifinale"):
                p["semifinalister"] = [canonical(t.strip()) or t.strip() for t in v.split(",")]
            elif header.startswith("Kommer Sverige til 8-delsfinale"):
                p["sverige_r16"] = v
            elif header.startswith("Kommer noen av de afrikanske"):
                p["afrika_qf"] = v
            elif header.startswith("Hvor mange mål scores totalt i kvartfinalene"):
                p["qf_maal"] = v
            elif header.startswith("Hvor mange gule kort får Ryerson"):
                p["ryerson"] = int(float(v))
            elif header.startswith("Blir det selvmål"):
                p["selvmaal_semi"] = v

        # Kolonnene for kampresultat kommer parvis per kamp; grupper dem på de
        # fire kjente kampene fra skjemaet.
        match_cols = p.pop("_match_cols", {})
        known_fixtures = [
            ("Mexico", "South Africa"),
            ("Morocco", "Brazil"),
            ("Switzerland", "Qatar"),
            ("Norway", "Iraq"),
        ]
        for home, away in known_fixtures:
            if home in match_cols and away in match_cols:
                p["matches"][frozenset((home, away))] = {home: match_cols[home], away: match_cols[away]}

        if p["name"]:
            people.append(p)
    return people


def load_predictions():
    url = os.environ.get("SHEET_CSV_URL", "").strip()
    if url:
        try:
            headers, rows = _headers_rows_from_csv(url)
            people = parse_rows(headers, rows)
            log.info("Lastet %d svar fra Google Sheet", len(people))
            return people, "google-sheet"
        except Exception as e:
            log.error("Feil ved henting av Google Sheet (%s) – prøver lokal fil", e)

    path = os.environ.get("PREDICTIONS_XLSX", "/data/svar.xlsx")
    headers, rows = _headers_rows_from_xlsx(path)
    people = parse_rows(headers, rows)
    log.info("Lastet %d svar fra %s", len(people), path)
    return people, path
