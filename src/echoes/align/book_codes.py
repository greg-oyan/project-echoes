"""OSHB-to-MACULA book-code mapping (first governed scheme mapping instance).

Both corpora represent the Westminster Leningrad Codex 4.20, so books map
one-to-one; only the identifiers differ (OSHB uses OSIS book IDs such as
``2Kgs``, MACULA uses three-character codes such as ``2KI``).  This mapping is
a scheme translation, never an identity rewrite: it feeds the supplementary
alignment layer and the versification-crosswalk document, and it must never
participate in token-ID generation.
"""

from __future__ import annotations

OSHB_TO_MACULA_BOOK: dict[str, str] = {
    "Gen": "GEN",
    "Exod": "EXO",
    "Lev": "LEV",
    "Num": "NUM",
    "Deut": "DEU",
    "Josh": "JOS",
    "Judg": "JDG",
    "Ruth": "RUT",
    "1Sam": "1SA",
    "2Sam": "2SA",
    "1Kgs": "1KI",
    "2Kgs": "2KI",
    "1Chr": "1CH",
    "2Chr": "2CH",
    "Ezra": "EZR",
    "Neh": "NEH",
    "Esth": "EST",
    "Job": "JOB",
    "Ps": "PSA",
    "Prov": "PRO",
    "Eccl": "ECC",
    "Song": "SNG",
    "Isa": "ISA",
    "Jer": "JER",
    "Lam": "LAM",
    "Ezek": "EZK",
    "Dan": "DAN",
    "Hos": "HOS",
    "Joel": "JOL",
    "Amos": "AMO",
    "Obad": "OBA",
    "Jonah": "JON",
    "Mic": "MIC",
    "Nah": "NAM",
    "Hab": "HAB",
    "Zeph": "ZEP",
    "Hag": "HAG",
    "Zech": "ZEC",
    "Mal": "MAL",
}

MACULA_TO_OSHB_BOOK: dict[str, str] = {macula: oshb for oshb, macula in OSHB_TO_MACULA_BOOK.items()}


def macula_book_for_oshb(oshb_book: str) -> str:
    """Resolve an OSHB OSIS book identifier to its MACULA code or fail clearly."""
    try:
        return OSHB_TO_MACULA_BOOK[oshb_book]
    except KeyError as exc:
        raise ValueError(f"unknown OSHB book identifier: {oshb_book}") from exc
