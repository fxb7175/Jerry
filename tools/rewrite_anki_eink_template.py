#!/usr/bin/env python3
"""Rewrite the Japanese vocabulary Anki package with an e-ink friendly template.

This script intentionally lives in the repo as text so pull requests do not need to
carry binary `.apkg` diffs. Run it locally from the repository root:

    python3 tools/rewrite_anki_eink_template.py 日语词汇.apkg

It updates the package in place and creates `日语词汇.apkg.bak` first.
"""
from __future__ import annotations

import ctypes
import pathlib
import shutil
import sqlite3
import sys
import tempfile
import zipfile

LAPIS_NOTE_TYPE_ID = 1667218449922
STAMP = 1782199999

CSS = """/* E-ink black-and-white Japanese vocabulary template */
.card { margin: 0 auto; padding: 20px 16px; max-width: 760px; font-family: "Noto Sans JP", "Hiragino Sans", "Yu Gothic", "Meiryo", Arial, sans-serif; font-size: 22px; line-height: 1.65; text-align: left; color: #000; background: #fff; word-break: break-word; }
#lapis { width: 100%; }
header, .top-container { font-size: 14px; text-align: right; margin-bottom: 8px; }
.card-block, .front, .back, .section { border: 2px solid #000; padding: 14px 16px; margin: 0 0 14px; background: #fff; }
.label { display: block; margin-bottom: 8px; padding-bottom: 3px; border-bottom: 1px solid #000; font-size: 14px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.vocab, .front-vocab, .term { font-size: 36px; font-weight: 700; line-height: 1.35; text-align: center; }
.reading { margin-top: 8px; font-size: 24px; text-align: center; }
.sentence, .front-sentence { font-size: 24px; line-height: 1.7; }
.definition, #glossaries, .glossary, .yomitan-glossary { font-size: 21px; line-height: 1.7; }
.definition-item, #glossaries li, .yomitan-glossary li, blockquote { margin: 10px 0; padding: 9px 12px; border-left: 4px solid #000; background: #f5f5f5; }
ul, ol { margin: .35em 0 .35em 1.35em; padding: 0; } li { margin: .3em 0; } p { margin: .45em 0; }
hr#answer, .answer-rule { border: 0; border-top: 3px double #000; margin: 18px 0; }
a { color: inherit; text-decoration: underline; } img { max-width: 100%; height: auto; filter: grayscale(100%) contrast(115%); }
.tags, .tag, .freq, .freq-dropdown, .pitch, #pitch-tags { color: #000; background: #fff; border-color: #000; }
.cloze { color: inherit; font-weight: 700; text-decoration: underline; }
.typeGood, .typeBad, .typeMissed { color: inherit; font-weight: 700; }
button { color: #000; background: #fff; border: 2px solid #000; padding: 8px 12px; font-weight: 700; }
.card.nightMode, .nightMode .card { color: #fff; background: #000; }
"""

LAPIS_FRONT = """<div id="lapis"><main>{{^IsSentenceCard}}<div class="card-block"><span class="label">Vocabulary</span><div lang="ja" class="vocab">{{Expression}}</div>{{#ExpressionFurigana}}<div lang="ja" class="reading">{{furigana:ExpressionFurigana}}</div>{{/ExpressionFurigana}}{{#ExpressionAudio}}<div>{{ExpressionAudio}}</div>{{/ExpressionAudio}}</div>{{/IsSentenceCard}}{{#IsSentenceCard}}<div class="card-block"><span class="label">Sentence</span><div lang="ja" class="front-sentence">{{kanji:Sentence}}</div>{{#SentenceAudio}}<div>{{SentenceAudio}}</div>{{/SentenceAudio}}</div>{{/IsSentenceCard}}{{#Hint}}<div class="section"><span class="label">Hint</span>{{Hint}}</div>{{/Hint}}</main></div>"""

LAPIS_BACK = """<div id="lapis" lang="ja"><main><div class="card-block"><span class="label">Vocabulary</span><div class="vocab">{{Expression}}</div>{{#ExpressionFurigana}}<div class="reading">{{furigana:ExpressionFurigana}}</div>{{/ExpressionFurigana}}{{#ExpressionAudio}}<div>{{ExpressionAudio}}</div>{{/ExpressionAudio}}{{#Frequency}}<div class="freq">{{Frequency}}</div>{{/Frequency}}</div>{{#Sentence}}<div class="section"><span class="label">Example sentence</span><div class="sentence">{{furigana:SentenceFurigana}}</div>{{#SentenceAudio}}<div>{{SentenceAudio}}</div>{{/SentenceAudio}}</div>{{/Sentence}}{{#MainDefinition}}<div class="section"><span class="label">Main definition</span><div class="definition">{{MainDefinition}}</div></div>{{/MainDefinition}}{{#Glossary}}<div class="section"><span class="label">Detailed explanations</span><div id="glossaries" class="definition">{{Glossary}}</div></div>{{/Glossary}}{{#SelectionText}}<div class="section"><span class="label">Selected text</span>{{SelectionText}}</div>{{/SelectionText}}{{#Picture}}<div class="section"><span class="label">Picture</span>{{Picture}}</div>{{/Picture}}{{#DefinitionPicture}}<div class="section"><span class="label">Definition picture</span>{{DefinitionPicture}}</div>{{/DefinitionPicture}}{{#MiscInfo}}<div class="section"><span class="label">Notes</span>{{MiscInfo}}</div>{{/MiscInfo}}</main></div>"""


def varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7


def replace_length_fields(blob: bytes, replacements: dict[int, str]) -> bytes:
    offset = 0
    out = bytearray()
    while offset < len(blob):
        start = offset
        key, offset = read_varint(blob, offset)
        field_number = key >> 3
        wire_type = key & 7
        out += blob[start:offset]
        if wire_type == 2:
            length, offset = read_varint(blob, offset)
            value = blob[offset : offset + length]
            offset += length
            if field_number in replacements:
                value = replacements[field_number].encode("utf-8")
            out += varint(len(value)) + value
        elif wire_type == 0:
            value, offset = read_varint(blob, offset)
            out += varint(value)
        elif wire_type == 5:
            out += blob[offset : offset + 4]
            offset += 4
        elif wire_type == 1:
            out += blob[offset : offset + 8]
            offset += 8
        else:
            raise ValueError(f"unsupported protobuf wire type: {wire_type}")
    return bytes(out)


def load_zstd() -> ctypes.CDLL:
    return ctypes.CDLL("libzstd.so.1")


def zstd_decompress(lib: ctypes.CDLL, compressed: bytes) -> bytes:
    lib.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
    lib.ZSTD_decompress.restype = ctypes.c_size_t
    lib.ZSTD_isError.argtypes = [ctypes.c_size_t]
    lib.ZSTD_isError.restype = ctypes.c_uint
    source = ctypes.create_string_buffer(compressed)
    for megabytes in (32, 64, 128):
        dest = ctypes.create_string_buffer(megabytes * 1024 * 1024)
        result = lib.ZSTD_decompress(dest, len(dest), source, len(compressed))
        if not lib.ZSTD_isError(result):
            return dest.raw[:result]
    raise RuntimeError("failed to decompress collection.anki21b")


def zstd_compress(lib: ctypes.CDLL, raw: bytes) -> bytes:
    lib.ZSTD_compress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
    lib.ZSTD_compress.restype = ctypes.c_size_t
    lib.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
    lib.ZSTD_compressBound.restype = ctypes.c_size_t
    lib.ZSTD_isError.argtypes = [ctypes.c_size_t]
    lib.ZSTD_isError.restype = ctypes.c_uint
    source = ctypes.create_string_buffer(raw)
    bound = lib.ZSTD_compressBound(len(raw))
    dest = ctypes.create_string_buffer(bound)
    result = lib.ZSTD_compress(dest, bound, source, len(raw), 3)
    if lib.ZSTD_isError(result):
        raise RuntimeError("failed to compress collection.anki21b")
    return dest.raw[:result]


def rewrite_database(db_path: pathlib.Path) -> None:
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    for note_type_id, config in cur.execute("select id, config from notetypes").fetchall():
        cur.execute(
            "update notetypes set config=?, mtime_secs=? where id=?",
            (replace_length_fields(config, {3: CSS}), STAMP, note_type_id),
        )
    for note_type_id, ordinal, config in cur.execute("select ntid, ord, config from templates").fetchall():
        if note_type_id == LAPIS_NOTE_TYPE_ID:
            front, back = LAPIS_FRONT, LAPIS_BACK
        else:
            front_field, back_field = ("{{Back}}", "{{Front}}") if ordinal == 1 else ("{{Front}}", "{{Back}}")
            front = f'<div class="front"><span class="label">Question</span><div class="term">{front_field}</div></div>'
            back = f'<div class="front"><span class="label">Question</span><div class="term">{front_field}</div></div><hr id="answer"><div class="back"><span class="label">Answer / Explanation</span><div class="definition">{back_field}</div></div>'
        cur.execute(
            "update templates set config=?, mtime_secs=? where ntid=? and ord=?",
            (replace_length_fields(config, {1: front, 2: back}), STAMP, note_type_id, ordinal),
        )
    cur.execute("update col set mod=?, scm=?", (STAMP, STAMP))
    con.commit()
    con.close()


def rewrite_package(apkg_path: pathlib.Path) -> None:
    lib = load_zstd()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = pathlib.Path(temp_dir)
        with zipfile.ZipFile(apkg_path) as archive:
            archive.extractall(temp)
        db_path = temp / "collection.anki21b.sqlite"
        db_path.write_bytes(zstd_decompress(lib, (temp / "collection.anki21b").read_bytes()))
        rewrite_database(db_path)
        (temp / "collection.anki21b").write_bytes(zstd_compress(lib, db_path.read_bytes()))
        backup = apkg_path.with_suffix(apkg_path.suffix + ".bak")
        shutil.copyfile(apkg_path, backup)
        with zipfile.ZipFile(apkg_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for entry in ("meta", "collection.anki21b", "collection.anki2", "media"):
                archive.write(temp / entry, entry)
    print(f"updated {apkg_path}; backup written to {backup}")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: rewrite_anki_eink_template.py <deck.apkg>", file=sys.stderr)
        return 2
    rewrite_package(pathlib.Path(sys.argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
