"""OSHB Ketiv/Qere supplement adapter (ADR 0009).

Parses the OSHB WLC OSIS markup — inline ``<w type="x-ketiv">`` words plus
``<note type="variant"><rdg type="x-qere">`` readings — and keys each ketiv
into the vacant MACULA word-number slot the primary edition preserves.  The
primary tables are never modified: ketiv readings become separate canonical
schema v2 token records with OSHB provenance, and the qere reading is
referenced by its existing MACULA token ID.

Slot model (verified corpus-wide before implementation): every OSHB ``w``
element consumes one word slot in document order, including ketiv words and
the qere words inside variant notes; ``seg`` elements and non-variant notes
consume nothing.  MACULA's ``source_word_id`` numbering follows the same
convention and keeps only the qere slots, so each ketiv slot is exactly a
MACULA gap.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import polars as pl
from pydantic import BaseModel, ConfigDict

from echoes.align.book_codes import OSHB_TO_MACULA_BOOK
from echoes.align.supplementary import build_kq_structural_alignments
from echoes.corpus.books import book_by_code
from echoes.corpus.models import (
    CANONICAL_TOKEN_COLUMNS,
    CANONICAL_TOKEN_POLARS_SCHEMA,
    CanonicalToken,
    IngestionIssue,
    Language,
    ValidationSeverity,
)
from echoes.corpus.token_ids import generate_source_edition_token_id
from echoes.manifests.sources import SourceManifest
from echoes.normalize.hebrew import normalize_hebrew_token
from echoes.settings import HebrewNormalization

OSIS = "{http://www.bibletechnologies.net/2003/OSIS/namespace}"
OSIS_ID_PATTERN = re.compile(r"^([1-9A-Za-z]+)\.([0-9]+)\.([0-9]+)$")
ALIGNMENT_METHOD = "vacant_slot_adjacency"

LocusKind = Literal["paired", "ketiv_only", "qere_only"]
SurfaceTier = Literal["exact", "consonantal", "mismatch", "not_applicable"]


class KQIngestionError(RuntimeError):
    """Raised when OSHB structure cannot be mapped without loss or fabrication."""


class KQSupplementSummary(BaseModel):
    """Concise deterministic summary of one supplement build."""

    model_config = ConfigDict(extra="forbid")

    loci: int
    paired_loci: int
    ketiv_only_loci: int
    qere_only_loci: int
    ketiv_tokens: int
    conflicts: int
    exact_surface_matches: int
    consonantal_surface_matches: int
    surface_mismatches: int
    loci_by_book: dict[str, int]
    issues_by_severity: dict[str, int]


@dataclass(slots=True)
class OshbWord:
    slot: int
    text: str
    oshb_id: str
    lemma: str | None
    morph: str | None
    is_ketiv: bool


@dataclass(slots=True)
class RawLocus:
    source_book_identifier: str  # OSHB/OSIS identifier, for source identity
    canonical_book: str  # Project Echoes/MACULA code, for joins and analysis
    chapter: int
    verse: int
    kind: LocusKind
    ketiv_words: list[OshbWord] = field(default_factory=list)
    qere_words: list[OshbWord] = field(default_factory=list)
    source_file: str = ""
    note_text: str | None = None


@dataclass(frozen=True, slots=True)
class KQSupplementResult:
    ketiv_tokens: pl.DataFrame
    locus_registry: pl.DataFrame
    structural_alignments: pl.DataFrame
    conflicts: pl.DataFrame
    issues: list[IngestionIssue]
    summary: KQSupplementSummary


REGISTRY_SCHEMA = {
    "locus_id": pl.String,
    "variant_group_id": pl.String,
    "kind": pl.String,
    "source_book_identifier": pl.String,
    "canonical_book": pl.String,
    "book": pl.String,
    "chapter": pl.Int16,
    "verse": pl.Int16,
    "ketiv_word_slots_json": pl.String,
    "qere_word_slots_json": pl.String,
    "ketiv_token_ids_json": pl.String,
    "macula_qere_token_ids_json": pl.String,
    "oshb_ketiv_ids_json": pl.String,
    "oshb_qere_ids_json": pl.String,
    "ketiv_surface": pl.String,
    "oshb_qere_surface": pl.String,
    "macula_qere_surface": pl.String,
    "surface_match_tier": pl.String,
    "alignment_method": pl.String,
    "alignment_confidence": pl.Float64,
    "conflict": pl.Boolean,
    "source_file": pl.String,
    "source_id": pl.String,
    "source_version": pl.String,
}
CONFLICT_SCHEMA = {
    "locus_id": pl.String,
    "field_name": pl.String,
    "primary_source_id": pl.String,
    "primary_value": pl.String,
    "supplement_source_id": pl.String,
    "supplement_value": pl.String,
    "alignment_method": pl.String,
    "alignment_confidence": pl.Float64,
    "note": pl.String,
}


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def strip_oshb_separators(text: str) -> str:
    """Remove OSHB's '/' morpheme-boundary markup from a word's text node."""
    return (text or "").replace("/", "").strip()


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _consonantal(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if not (0x0591 <= ord(c) <= 0x05C7))


def is_aramaic_reference(book: str, chapter: int, verse: int) -> bool:
    """Documented Aramaic passages of Ezra, Daniel, and Jeremiah 10:11."""
    return (
        (book == "EZR" and (chapter in {5, 6} or (chapter == 4 and verse >= 8)))
        or (book == "EZR" and chapter == 7 and 12 <= verse <= 26)
        or (book == "DAN" and (3 <= chapter <= 7))
        or (book == "DAN" and chapter == 2 and verse >= 4)
        or (book == "JER" and chapter == 10 and verse == 11)
    )


def _word_from_element(element: ET.Element, slot: int) -> OshbWord:
    oshb_id = (element.get("id") or "").strip()
    if not oshb_id:
        raise KQIngestionError(f"OSHB w element at slot {slot} lacks its immutable id")
    return OshbWord(
        slot=slot,
        text=element.text or "",
        oshb_id=oshb_id,
        lemma=(element.get("lemma") or "").strip() or None,
        morph=(element.get("morph") or "").strip() or None,
        is_ketiv=element.get("type") == "x-ketiv",
    )


def _parse_verse(
    verse: ET.Element,
    *,
    source_book_identifier: str,
    canonical_book: str,
    chapter: int,
    verse_number: int,
    source_file: str,
) -> tuple[list[RawLocus], int]:
    """Slot-walk one verse and return its loci plus the total slot count."""
    slot = 0
    loci: list[RawLocus] = []
    pending_ketiv: list[OshbWord] = []
    for child in verse:
        tag = child.tag
        if tag == OSIS + "w":
            slot += 1
            word = _word_from_element(child, slot)
            if word.is_ketiv:
                pending_ketiv.append(word)
            elif pending_ketiv:
                # A plain word interrupts a ketiv run without a variant note:
                # close the pending ketiv as an unpaired locus (recorded, not
                # forced onto a later note).
                loci.append(
                    RawLocus(
                        source_book_identifier=source_book_identifier,
                        canonical_book=canonical_book,
                        chapter=chapter,
                        verse=verse_number,
                        kind="ketiv_only",
                        ketiv_words=pending_ketiv[:],
                        source_file=source_file,
                        note_text="ketiv run interrupted by a plain word without a variant note",
                    )
                )
                pending_ketiv = []
        elif tag == OSIS + "note" and child.get("type") == "variant":
            rdg = child.find(OSIS + "rdg")
            qere_words: list[OshbWord] = []
            if rdg is not None:
                for qere_element in rdg:
                    if qere_element.tag == OSIS + "w":
                        slot += 1
                        qere_words.append(_word_from_element(qere_element, slot))
            kind: LocusKind
            if pending_ketiv and qere_words:
                kind = "paired"
            elif pending_ketiv:
                kind = "ketiv_only"
            elif qere_words:
                kind = "qere_only"
            else:
                raise KQIngestionError(
                    "variant note without ketiv or qere at "
                    f"{source_book_identifier} {chapter}:{verse_number}"
                )
            catchword = child.find(OSIS + "catchWord")
            loci.append(
                RawLocus(
                    source_book_identifier=source_book_identifier,
                    canonical_book=canonical_book,
                    chapter=chapter,
                    verse=verse_number,
                    kind=kind,
                    ketiv_words=pending_ketiv[:],
                    qere_words=qere_words,
                    source_file=source_file,
                    note_text=(catchword.text or "").strip() if catchword is not None else None,
                )
            )
            pending_ketiv = []
        # seg elements and non-variant notes consume no slots and never
        # interrupt ketiv adjacency (verified: exegesis and Masora notes).
    if pending_ketiv:
        loci.append(
            RawLocus(
                source_book_identifier=source_book_identifier,
                canonical_book=canonical_book,
                chapter=chapter,
                verse=verse_number,
                kind="ketiv_only",
                ketiv_words=pending_ketiv[:],
                source_file=source_file,
                note_text="ketiv at verse end without a variant note",
            )
        )
    return loci, slot


def parse_oshb_loci(oshb_root: Path) -> tuple[list[RawLocus], dict[tuple[str, int, int], int]]:
    """Parse every OSHB WLC book file into raw loci and per-verse slot totals."""
    wlc_dir = oshb_root / "wlc"
    if not wlc_dir.is_dir():
        raise KQIngestionError(f"OSHB wlc directory does not exist: {wlc_dir}")
    loci: list[RawLocus] = []
    verse_slots: dict[tuple[str, int, int], int] = {}
    for path in sorted(wlc_dir.glob("*.xml")):
        if path.name == "VerseMap.xml":
            continue
        oshb_book = path.stem
        if oshb_book not in OSHB_TO_MACULA_BOOK:
            raise KQIngestionError(f"unknown OSHB book file: {path.name}")
        canonical_book = OSHB_TO_MACULA_BOOK[oshb_book]
        source_file = f"wlc/{path.name}"
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError) as exc:
            raise KQIngestionError(f"could not parse {source_file}: {exc}") from exc
        for verse in root.iter(OSIS + "verse"):
            osis_id = verse.get("osisID") or ""
            match = OSIS_ID_PATTERN.fullmatch(osis_id)
            if match is None:
                raise KQIngestionError(f"malformed osisID '{osis_id}' in {source_file}")
            if match.group(1) != oshb_book:
                raise KQIngestionError(f"book mismatch in {source_file}: {osis_id}")
            chapter, verse_number = int(match.group(2)), int(match.group(3))
            verse_loci, total_slots = _parse_verse(
                verse,
                source_book_identifier=oshb_book,
                canonical_book=canonical_book,
                chapter=chapter,
                verse_number=verse_number,
                source_file=source_file,
            )
            verse_slots[(canonical_book, chapter, verse_number)] = total_slots
            loci.extend(verse_loci)
    return loci, verse_slots


def _variant_group_id(locus: RawLocus, anchor_slot: int) -> str:
    identity = "\0".join(sorted(word.oshb_id for word in (*locus.ketiv_words, *locus.qere_words)))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return (
        f"KQ_{locus.canonical_book}_{locus.chapter:03d}_{locus.verse:03d}_"
        f"{anchor_slot:04d}~{digest}"
    )


def _confidence(locus: RawLocus, *, tier: SurfaceTier, gap_ok: bool, frame_ok: bool) -> float:
    if not frame_ok or not gap_ok or tier == "mismatch":
        return 0.3
    if tier == "consonantal":
        return 0.7
    if locus.kind in {"ketiv_only", "qere_only"}:
        return 0.9
    if len(locus.ketiv_words) > 1 or len(locus.qere_words) > 1:
        return 0.9
    return 1.0


def build_kq_supplement(
    oshb_root: Path,
    primary_tokens: pl.DataFrame,
    *,
    source: SourceManifest,
    normalization: HebrewNormalization,
) -> KQSupplementResult:
    """Build ketiv tokens, the locus registry, and conflict rows.

    ``primary_tokens`` is the untouched MACULA Hebrew token frame; it is only
    read (gap verification, qere resolution, surface comparison), never
    modified.
    """
    loci, verse_slots = parse_oshb_loci(oshb_root)
    issues: list[IngestionIssue] = []

    primary = primary_tokens.select(
        "book",
        "chapter",
        "verse",
        "source_word_id",
        "token_id",
        "surface_form",
        "position_in_word",
    ).sort("book", "chapter", "verse", "position_in_word")
    verse_words: dict[tuple[str, int, int], dict[int, list[tuple[str, str]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for book, chapter, verse, word_id, token_id, surface, _pos in primary.iter_rows():
        number = int(str(word_id).rsplit("!", maxsplit=1)[-1])
        verse_words[(str(book), int(chapter), int(verse))][number].append(
            (str(token_id), str(surface))
        )

    ketiv_models: list[CanonicalToken] = []
    registry_rows: list[dict[str, object]] = []
    conflict_rows: list[dict[str, object]] = []
    counters = {"exact": 0, "consonantal": 0, "mismatch": 0}
    loci_by_book: dict[str, int] = defaultdict(int)
    supplement_position = 0

    for locus in sorted(
        loci,
        key=lambda item: (
            book_by_code(item.canonical_book).order,
            item.chapter,
            item.verse,
            (item.ketiv_words or item.qere_words)[0].slot,
        ),
    ):
        verse_key = (locus.canonical_book, locus.chapter, locus.verse)
        macula_verse = verse_words.get(verse_key, {})
        present = set(macula_verse)
        total_slots = verse_slots[verse_key]
        # The verse frame is checked per locus: this locus's ketiv slots must be
        # vacant, its qere slots present, and the verse's highest present word
        # number must equal the OSHB slot total.
        gap_ok = all(word.slot not in present for word in locus.ketiv_words)
        qere_present = all(word.slot in present for word in locus.qere_words)
        frame_ok = max(present, default=0) == total_slots and qere_present

        anchor_slot = (locus.ketiv_words or locus.qere_words)[0].slot
        group_id = _variant_group_id(locus, anchor_slot) if locus.ketiv_words else None
        locus_id = (
            f"KQL_{locus.canonical_book}_{locus.chapter:03d}_{locus.verse:03d}_{anchor_slot:04d}"
        )

        oshb_qere_surface = _nfc(
            strip_oshb_separators("".join(word.text for word in locus.qere_words))
        )
        macula_qere_tokens = [
            entry for word in locus.qere_words for entry in macula_verse.get(word.slot, [])
        ]
        macula_qere_surface = _nfc("".join(surface for _id, surface in macula_qere_tokens))
        tier: SurfaceTier
        if not locus.qere_words:
            tier = "not_applicable"
        elif oshb_qere_surface == macula_qere_surface:
            tier = "exact"
        elif _consonantal(oshb_qere_surface) == _consonantal(macula_qere_surface):
            tier = "consonantal"
        else:
            tier = "mismatch"
        if tier in counters:
            counters[tier] += 1
        confidence = _confidence(locus, tier=tier, gap_ok=gap_ok, frame_ok=frame_ok)
        conflict = tier in {"consonantal", "mismatch"} or not gap_ok or not frame_ok
        if conflict:
            conflict_rows.append(
                {
                    "locus_id": locus_id,
                    "field_name": "qere_surface" if tier != "not_applicable" else "verse_frame",
                    "primary_source_id": "macula-hebrew",
                    "primary_value": macula_qere_surface,
                    "supplement_source_id": source.source_id,
                    "supplement_value": oshb_qere_surface,
                    "alignment_method": ALIGNMENT_METHOD,
                    "alignment_confidence": confidence,
                    "note": (
                        f"tier={tier}, gap_ok={gap_ok}, frame_ok={frame_ok}; "
                        "both values preserved, never reconciled"
                    ),
                }
            )
            issues.append(
                IngestionIssue(
                    severity=ValidationSeverity.WARNING,
                    code="kq-alignment-conflict",
                    message=f"{locus_id}: surface tier {tier}, gap_ok={gap_ok}",
                    book=locus.canonical_book,
                    chapter=locus.chapter,
                    verse=locus.verse,
                )
            )

        ketiv_token_ids: list[str] = []
        language = (
            Language.ARAMAIC
            if is_aramaic_reference(locus.canonical_book, locus.chapter, locus.verse)
            else Language.HEBREW
        )
        for word in locus.ketiv_words:
            supplement_position += 1
            surface = strip_oshb_separators(word.text)
            if not surface:
                raise KQIngestionError(f"empty ketiv surface at {locus_id}")
            forms = normalize_hebrew_token(surface, normalization)
            token_id = generate_source_edition_token_id(
                book_identifier=locus.source_book_identifier,
                chapter=locus.chapter,
                verse=locus.verse,
                source_token_position=word.slot,
                source_record_id=word.oshb_id,
                disambiguate_with_source_record=True,
            )
            ketiv_token_ids.append(token_id)
            raw = {
                "oshb_text": word.text,
                "oshb_lemma": word.lemma,
                "oshb_morph": word.morph,
                "catchword": locus.note_text,
                "locus_kind": locus.kind,
                "alignment_method": ALIGNMENT_METHOD,
                "alignment_confidence": confidence,
                "source_book_identifier": locus.source_book_identifier,
                "canonical_book": locus.canonical_book,
            }
            morphology = {
                key: value
                for key, value in (
                    ("oshb_morph", word.morph),
                    ("oshb_lemma", word.lemma),
                )
                if value
            }
            ketiv_models.append(
                CanonicalToken(
                    token_id=token_id,
                    source_id=source.source_id,
                    source_version=source.version_or_commit or "UNPINNED",
                    source_file=locus.source_file,
                    source_record_id=word.oshb_id,
                    source_word_id=(
                        f"{locus.source_book_identifier} {locus.chapter}:{locus.verse}!{word.slot}"
                    ),
                    source_edition_reference=(
                        f"{locus.source_book_identifier} {locus.chapter}:{locus.verse}"
                    ),
                    source_row_reference=f"{locus.source_file}#{word.oshb_id}",
                    book=locus.canonical_book,
                    book_order=book_by_code(locus.canonical_book).order,
                    chapter=locus.chapter,
                    verse=locus.verse,
                    position_in_verse=word.slot,
                    position_in_corpus=supplement_position,
                    position_in_word=1,
                    surface_form=forms.surface_form,
                    normalized_form=forms.normalized_form,
                    unpointed_form=forms.unpointed_form,
                    lemma=None,
                    morphology_json=_canonical_json(morphology) if morphology else None,
                    language=language,
                    is_variant=True,
                    variant_type="ketiv",
                    variant_group_id=group_id,
                    is_default_reading=False,
                    ketiv_form=forms.surface_form,
                    source_extras_json=_canonical_json(raw),
                )
            )
        if language is Language.ARAMAIC and locus.ketiv_words:
            issues.append(
                IngestionIssue(
                    severity=ValidationSeverity.WARNING,
                    code="language-inferred",
                    message="ketiv language inferred from documented Aramaic passage",
                    book=locus.canonical_book,
                    chapter=locus.chapter,
                    verse=locus.verse,
                )
            )

        loci_by_book[locus.canonical_book] += 1
        registry_rows.append(
            {
                "locus_id": locus_id,
                "variant_group_id": group_id,
                "kind": locus.kind,
                "source_book_identifier": locus.source_book_identifier,
                "canonical_book": locus.canonical_book,
                "book": locus.canonical_book,
                "chapter": locus.chapter,
                "verse": locus.verse,
                "ketiv_word_slots_json": _canonical_json([word.slot for word in locus.ketiv_words]),
                "qere_word_slots_json": _canonical_json([word.slot for word in locus.qere_words]),
                "ketiv_token_ids_json": _canonical_json(ketiv_token_ids),
                "macula_qere_token_ids_json": _canonical_json(
                    [token_id for token_id, _surface in macula_qere_tokens]
                ),
                "oshb_ketiv_ids_json": _canonical_json(
                    [word.oshb_id for word in locus.ketiv_words]
                ),
                "oshb_qere_ids_json": _canonical_json([word.oshb_id for word in locus.qere_words]),
                "ketiv_surface": _nfc(
                    strip_oshb_separators("".join(word.text for word in locus.ketiv_words))
                )
                or None,
                "oshb_qere_surface": oshb_qere_surface or None,
                "macula_qere_surface": macula_qere_surface or None,
                "surface_match_tier": tier,
                "alignment_method": ALIGNMENT_METHOD,
                "alignment_confidence": confidence,
                "conflict": conflict,
                "source_file": locus.source_file,
                "source_id": source.source_id,
                "source_version": source.version_or_commit or "UNPINNED",
            }
        )

    duplicate_ids = len(ketiv_models) != len({token.token_id for token in ketiv_models})
    if duplicate_ids:
        raise KQIngestionError("ketiv token-ID collisions inside the supplement")
    primary_ids = set(primary_tokens["token_id"].to_list())
    collisions = sorted(token.token_id for token in ketiv_models if token.token_id in primary_ids)
    if collisions:
        raise KQIngestionError(f"ketiv token IDs collide with primary tokens: {collisions[:5]}")

    ketiv_rows = [token.model_dump(mode="json") for token in ketiv_models]
    ketiv_frame = pl.DataFrame(
        ketiv_rows, schema=CANONICAL_TOKEN_POLARS_SCHEMA, orient="row"
    ).select(CANONICAL_TOKEN_COLUMNS)
    registry_frame = pl.DataFrame(registry_rows, schema=REGISTRY_SCHEMA, orient="row")
    conflict_frame = pl.DataFrame(conflict_rows, schema=CONFLICT_SCHEMA, orient="row")
    structural_alignment_frame = build_kq_structural_alignments(
        primary_tokens,
        ketiv_frame,
        registry_frame,
    )

    from collections import Counter as _Counter

    summary = KQSupplementSummary(
        loci=registry_frame.height,
        paired_loci=registry_frame.filter(pl.col("kind") == "paired").height,
        ketiv_only_loci=registry_frame.filter(pl.col("kind") == "ketiv_only").height,
        qere_only_loci=registry_frame.filter(pl.col("kind") == "qere_only").height,
        ketiv_tokens=ketiv_frame.height,
        conflicts=conflict_frame.height,
        exact_surface_matches=counters["exact"],
        consonantal_surface_matches=counters["consonantal"],
        surface_mismatches=counters["mismatch"],
        loci_by_book=dict(sorted(loci_by_book.items())),
        issues_by_severity=dict(sorted(_Counter(issue.severity.value for issue in issues).items())),
    )
    return KQSupplementResult(
        ketiv_tokens=ketiv_frame,
        locus_registry=registry_frame,
        structural_alignments=structural_alignment_frame,
        conflicts=conflict_frame,
        issues=issues,
        summary=summary,
    )
