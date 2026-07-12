"""Deterministic, language-aware reconstruction of ordered passage tokens."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import polars as pl

type TokenRow = Mapping[str, object]
type TokenRows = pl.DataFrame | Sequence[TokenRow]

_HEBREW_MAQQEF = "\u05be"
_OPENING_PUNCTUATION = frozenset("([{\u00ab\u2018\u201c")
_CLOSING_PUNCTUATION = frozenset(",.;:!?)]}\u00bb\u2019\u201d\u05c3\u05c6\u037e\u0387\u00b7")
_GREEK_ELISION_MARKS = frozenset({"\u2019", "\u02bc", "\u1fbd"})


class ReconstructionError(ValueError):
    """Raised when ordered token rows cannot be reconstructed safely."""


@dataclass(frozen=True, slots=True)
class PassageReconstruction:
    """Passage text forms and ordered, null-preserving analytical sequences."""

    surface_text: str
    normalized_text: str
    unpointed_text: str | None
    folded_text: str | None
    token_ids_json: str
    lemma_sequence_json: str
    root_sequence_json: str
    part_of_speech_sequence_json: str
    semantic_domain_sequence_json: str
    entity_ids_json: str
    participant_ids_json: str


@dataclass(frozen=True, slots=True)
class _HebrewWord:
    """One source-word group rendered in the three Hebrew text forms."""

    surface: str
    normalized: str
    unpointed: str
    after: str | None


def _materialize_rows(tokens: TokenRows) -> tuple[TokenRow, ...]:
    if isinstance(tokens, pl.DataFrame):
        rows: tuple[TokenRow, ...] = tuple(tokens.iter_rows(named=True))
    else:
        rows = tuple(tokens)
    if not rows:
        raise ReconstructionError("cannot reconstruct an empty token sequence")
    return rows


def _required_string(row: TokenRow, field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str):
        raise ReconstructionError(f"token field {field!r} must be a string")
    return value


def _optional_string(row: TokenRow, field: str) -> str | None:
    value = row.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ReconstructionError(f"token field {field!r} must be a string or null")
    return value


def _required_bool(row: TokenRow, field: str) -> bool:
    value = row.get(field)
    if not isinstance(value, bool):
        raise ReconstructionError(f"token field {field!r} must be a boolean")
    return value


def _required_positive_int(row: TokenRow, field: str) -> int:
    value = row.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ReconstructionError(f"token field {field!r} must be a positive integer")
    return value


def _canonical_json(values: Sequence[str | None]) -> str:
    """Serialize an ordered nullable string sequence without ASCII rewriting."""
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _validate_unicode(value: str, field: str) -> None:
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ReconstructionError(f"{field} contains invalid Unicode") from exc


def _sequence_json(rows: Sequence[TokenRow], field: str) -> str:
    values = [_optional_string(row, field) for row in rows]
    for value in values:
        if value is not None:
            _validate_unicode(value, field)
    return _canonical_json(values)


def _common_sequences(rows: Sequence[TokenRow]) -> dict[str, str]:
    token_ids = [_required_string(row, "token_id") for row in rows]
    if len(token_ids) != len(set(token_ids)):
        raise ReconstructionError("a passage cannot contain duplicate token IDs")
    for token_id in token_ids:
        _validate_unicode(token_id, "token_id")
    return {
        "token_ids_json": _canonical_json(token_ids),
        "lemma_sequence_json": _sequence_json(rows, "lemma"),
        "root_sequence_json": _sequence_json(rows, "lexical_root"),
        "part_of_speech_sequence_json": _sequence_json(rows, "part_of_speech"),
        "semantic_domain_sequence_json": _sequence_json(rows, "semantic_domain"),
        "entity_ids_json": _sequence_json(rows, "entity_id"),
        "participant_ids_json": _sequence_json(rows, "participant_id"),
    }


def _hebrew_after(row: TokenRow) -> str | None:
    """Return the source separator, distinguishing an explicit empty value."""
    raw = _optional_string(row, "source_extras_json")
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReconstructionError("source_extras_json must contain valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ReconstructionError("source_extras_json must encode an object")
    attributes = parsed.get("attributes")
    if attributes is None:
        return None
    if not isinstance(attributes, dict):
        raise ReconstructionError("source_extras_json attributes must encode an object")
    after = attributes.get("after")
    if after is None:
        return None
    if not isinstance(after, str):
        raise ReconstructionError("source after value must be a string")
    _validate_unicode(after, "source after value")
    return after


def _hebrew_words(rows: Sequence[TokenRow]) -> tuple[_HebrewWord, ...]:
    groups: list[list[TokenRow]] = []
    seen_word_ids: set[str] = set()
    current_word_id: str | None = None
    for row in rows:
        language = _required_string(row, "language")
        if language not in {"hebrew", "aramaic"}:
            raise ReconstructionError(f"Hebrew reconstruction received {language!r} token")
        word_id = _required_string(row, "source_word_id")
        _required_positive_int(row, "position_in_word")
        if word_id != current_word_id:
            if word_id in seen_word_ids:
                raise ReconstructionError(
                    f"source word {word_id!r} is non-contiguous in passage membership"
                )
            seen_word_ids.add(word_id)
            groups.append([])
            current_word_id = word_id
        groups[-1].append(row)

    rendered: list[_HebrewWord] = []
    for group in groups:
        positions = [_required_positive_int(row, "position_in_word") for row in group]
        if positions != sorted(positions) or len(positions) != len(set(positions)):
            raise ReconstructionError(
                "morpheme positions must be strictly increasing within a word"
            )
        visible = [row for row in group if not _required_bool(row, "is_zero_width")]
        for row in group:
            zero_width = _required_bool(row, "is_zero_width")
            forms = (
                _required_string(row, "surface_form"),
                _required_string(row, "normalized_form"),
                _required_string(row, "unpointed_form"),
            )
            if zero_width and any(forms):
                raise ReconstructionError("zero-width Hebrew tokens must have empty text forms")
            if not zero_width and not all(forms):
                raise ReconstructionError("visible Hebrew tokens require all text forms")
        if not visible:
            continue
        rendered.append(
            _HebrewWord(
                surface="".join(_required_string(row, "surface_form") for row in visible),
                normalized="".join(_required_string(row, "normalized_form") for row in visible),
                unpointed="".join(_required_string(row, "unpointed_form") for row in visible),
                after=_hebrew_after(group[-1]),
            )
        )
    if not rendered:
        raise ReconstructionError("passage token sequence has no visible Hebrew or Aramaic text")
    return tuple(rendered)


def _hebrew_fallback_separator(previous: str, following: str) -> str:
    if not previous or not following:
        return ""
    if previous.endswith(_HEBREW_MAQQEF):
        return ""
    if following[0] in _CLOSING_PUNCTUATION:
        return ""
    if previous[-1] in _OPENING_PUNCTUATION:
        return ""
    return " "


def _join_hebrew(words: Sequence[_HebrewWord], field: str) -> str:
    pieces: list[str] = []
    for index, word in enumerate(words):
        value = getattr(word, field)
        pieces.append(value)
        if index + 1 < len(words):
            separator = word.after
            if separator is None:
                following = getattr(words[index + 1], field)
                separator = _hebrew_fallback_separator(value, following)
            pieces.append(separator)
    result = "".join(pieces)
    _validate_unicode(result, f"Hebrew {field} reconstruction")
    return result


def reconstruct_hebrew(tokens: TokenRows) -> PassageReconstruction:
    """Reconstruct an ordered Hebrew/Aramaic passage by source-word groups."""
    rows = _materialize_rows(tokens)
    words = _hebrew_words(rows)
    sequences = _common_sequences(rows)
    return PassageReconstruction(
        surface_text=_join_hebrew(words, "surface"),
        normalized_text=_join_hebrew(words, "normalized"),
        unpointed_text=_join_hebrew(words, "unpointed"),
        folded_text=None,
        **sequences,
    )


def _is_closing_punctuation(value: str) -> bool:
    return bool(value) and all(character in _CLOSING_PUNCTUATION for character in value)


def _is_opening_punctuation(value: str) -> bool:
    return bool(value) and all(character in _OPENING_PUNCTUATION for character in value)


def _join_greek(pieces: Sequence[tuple[str, bool]]) -> str:
    output: list[str] = []
    previous_value = ""
    previous_punctuation = False
    for value, punctuation_only in pieces:
        if not value:
            continue
        if output:
            attach_to_previous = punctuation_only and _is_closing_punctuation(value)
            attach_to_following = previous_punctuation and _is_opening_punctuation(previous_value)
            if not attach_to_previous and not attach_to_following:
                output.append(" ")
        output.append(value)
        previous_value = value
        previous_punctuation = punctuation_only
    result = "".join(output)
    _validate_unicode(result, "Greek reconstruction")
    return result


def reconstruct_greek(tokens: TokenRows) -> PassageReconstruction:
    """Reconstruct an ordered Greek passage with source punctuation and elision."""
    rows = _materialize_rows(tokens)
    surface_pieces: list[tuple[str, bool]] = []
    normalized_pieces: list[tuple[str, bool]] = []
    folded_pieces: list[tuple[str, bool]] = []
    for row in rows:
        if _required_string(row, "language") != "greek":
            raise ReconstructionError("Greek reconstruction received a non-Greek token")
        surface = _required_string(row, "surface_form")
        normalized = _required_string(row, "normalized_form")
        folded = _required_string(row, "folded_form")
        leading = _required_string(row, "leading_punctuation")
        trailing = _required_string(row, "trailing_punctuation")
        punctuation_only = _required_bool(row, "is_punctuation")
        if not surface or not normalized or not folded:
            raise ReconstructionError("Greek tokens require non-empty text forms")
        if not punctuation_only and leading + normalized + trailing != surface:
            raise ReconstructionError(
                "Greek punctuation fields do not reconstruct the preserved surface form"
            )
        is_elided = _required_bool(row, "is_elided")
        if is_elided and normalized[-1] not in _GREEK_ELISION_MARKS:
            raise ReconstructionError("Greek elision metadata disagrees with the normalized form")
        surface_pieces.append((surface, punctuation_only))
        normalized_pieces.append((normalized, punctuation_only))
        folded_pieces.append((folded, punctuation_only))

    sequences = _common_sequences(rows)
    return PassageReconstruction(
        surface_text=_join_greek(surface_pieces),
        normalized_text=_join_greek(normalized_pieces),
        unpointed_text=None,
        folded_text=_join_greek(folded_pieces),
        **sequences,
    )


def reconstruct_passage(tokens: TokenRows, *, corpus: str | None = None) -> PassageReconstruction:
    """Dispatch to a language-specific reconstruction policy for ordered rows."""
    rows = _materialize_rows(tokens)
    inferred = corpus or _required_string(rows[0], "corpus")
    if inferred == "hebrew":
        return reconstruct_hebrew(rows)
    if inferred == "greek":
        return reconstruct_greek(rows)
    raise ReconstructionError(f"unsupported reconstruction corpus: {inferred!r}")
