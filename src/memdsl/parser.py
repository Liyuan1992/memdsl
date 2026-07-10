"""Parser for `.mem` source files.

Grammar (v0.4):

    document    := (module_stmt | use_stmt | declaration)*
    module_stmt := 'module' DOTTED_NAME
    use_stmt    := 'use' DOTTED_NAME
    declaration := KIND NAME block
    block       := '{' entry* '}'
    entry       := FIELD ':' value | FIELD block
    value       := STRING | ATOM | list
    list        := '[' (value (',' value)*)? ']'

ATOM covers bare identifiers, dotted symbols, numbers, dates
(2026-06-15), and call-like scope forms such as project("Aurora"),
which are kept verbatim as strings.

Comments start with '#' and run to end of line.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple


class ParseError(Exception):
    def __init__(self, message: str, file: str = "<text>", line: int = 0):
        self.file = file
        self.line = line
        super().__init__(f"{file}:{line}: {message}")


@dataclass
class Token:
    kind: str  # 'atom' | 'string' | 'punct'
    value: str
    line: int


_PUNCT = set("{}[]:,")


def _tokenize(text: str, file: str) -> List[Token]:
    tokens: List[Token] = []
    i, line = 0, 1
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
            i += 1
        elif ch in " \t\r":
            i += 1
        elif ch == "#":
            while i < n and text[i] != "\n":
                i += 1
        elif ch == '"':
            start_line = line
            i += 1
            buf = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    esc = text[i + 1]
                    buf.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(esc, esc))
                    i += 2
                else:
                    if text[i] == "\n":
                        line += 1
                    buf.append(text[i])
                    i += 1
            if i >= n:
                raise ParseError("unterminated string", file, start_line)
            i += 1
            tokens.append(Token("string", "".join(buf), start_line))
        elif ch in _PUNCT:
            tokens.append(Token("punct", ch, line))
            i += 1
        else:
            start = i
            start_line = line
            while i < n and text[i] not in " \t\r\n#" and text[i] not in _PUNCT and text[i] != '"':
                if text[i] == "(":
                    # call-like atom: consume until matching ')'
                    depth = 0
                    while i < n:
                        if text[i] == "(":
                            depth += 1
                        elif text[i] == ")":
                            depth -= 1
                            if depth == 0:
                                i += 1
                                break
                        elif text[i] == "\n":
                            line += 1
                        i += 1
                    break
                i += 1
            atom = text[start:i]
            if atom:
                tokens.append(Token("atom", atom, start_line))
    return tokens


@dataclass
class RawDeclaration:
    kind: str
    name: str
    fields: dict  # str -> str | list | dict (nested block)
    file: str
    line: int
    module: Optional[str] = None


@dataclass
class Document:
    module: Optional[str]
    uses: List[str] = field(default_factory=list)
    declarations: List[RawDeclaration] = field(default_factory=list)
    file: str = "<text>"


class _Parser:
    def __init__(self, tokens: List[Token], file: str):
        self.tokens = tokens
        self.file = file
        self.pos = 0

    def _peek(self) -> Optional[Token]:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _next(self) -> Token:
        tok = self._peek()
        if tok is None:
            last_line = self.tokens[-1].line if self.tokens else 0
            raise ParseError("unexpected end of file", self.file, last_line)
        self.pos += 1
        return tok

    def _expect_punct(self, ch: str) -> Token:
        tok = self._next()
        if tok.kind != "punct" or tok.value != ch:
            raise ParseError(f"expected '{ch}', got '{tok.value}'", self.file, tok.line)
        return tok

    def parse_document(self) -> Document:
        doc = Document(module=None, file=self.file)
        while self._peek() is not None:
            tok = self._next()
            if tok.kind != "atom":
                raise ParseError(f"expected keyword or kind, got '{tok.value}'", self.file, tok.line)
            if tok.value == "module":
                name = self._next()
                if name.kind != "atom":
                    raise ParseError("expected module name", self.file, name.line)
                doc.module = name.value
            elif tok.value == "use":
                name = self._next()
                if name.kind != "atom":
                    raise ParseError("expected symbol after 'use'", self.file, name.line)
                doc.uses.append(name.value)
            else:
                kind = tok.value
                name_tok = self._next()
                if name_tok.kind != "atom":
                    raise ParseError(f"expected declaration name after '{kind}'", self.file, name_tok.line)
                fields = self._parse_block()
                doc.declarations.append(
                    RawDeclaration(kind=kind, name=name_tok.value, fields=fields,
                                   file=self.file, line=tok.line)
                )
        for d in doc.declarations:
            d.module = doc.module
        return doc

    def _parse_block(self) -> dict:
        self._expect_punct("{")
        fields: dict = {}
        while True:
            tok = self._peek()
            if tok is None:
                raise ParseError("unterminated block", self.file, self.tokens[-1].line)
            if tok.kind == "punct" and tok.value == "}":
                self._next()
                return fields
            key_tok = self._next()
            if key_tok.kind != "atom":
                raise ParseError(f"expected field name, got '{key_tok.value}'", self.file, key_tok.line)
            sep = self._peek()
            if sep is not None and sep.kind == "punct" and sep.value == ":":
                self._next()
                fields[key_tok.value] = self._parse_value()
            elif sep is not None and sep.kind == "punct" and sep.value == "{":
                fields[key_tok.value] = self._parse_block()
            else:
                got = sep.value if sep else "end of file"
                raise ParseError(f"expected ':' or '{{' after '{key_tok.value}', got '{got}'",
                                 self.file, key_tok.line)

    def _parse_value(self) -> Any:
        tok = self._peek()
        if tok is None:
            raise ParseError("expected value", self.file, self.tokens[-1].line)
        if tok.kind == "punct" and tok.value == "[":
            return self._parse_list()
        tok = self._next()
        if tok.kind in ("string", "atom"):
            return tok.value
        raise ParseError(f"unexpected value '{tok.value}'", self.file, tok.line)

    def _parse_list(self) -> List[Any]:
        self._expect_punct("[")
        items: List[Any] = []
        while True:
            tok = self._peek()
            if tok is None:
                raise ParseError("unterminated list", self.file, self.tokens[-1].line)
            if tok.kind == "punct" and tok.value == "]":
                self._next()
                return items
            items.append(self._parse_value())
            tok = self._peek()
            if tok is not None and tok.kind == "punct" and tok.value == ",":
                self._next()


def parse_text(text: str, file: str = "<text>") -> Document:
    """Parse `.mem` source text into a Document."""
    return _Parser(_tokenize(text, file), file).parse_document()


def parse_file(path: str) -> Document:
    """Parse a `.mem` file into a Document."""
    with open(path, "r", encoding="utf-8") as f:
        return parse_text(f.read(), file=path)
