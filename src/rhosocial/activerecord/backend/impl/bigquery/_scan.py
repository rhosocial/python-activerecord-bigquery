# src/rhosocial/activerecord/backend/impl/bigquery/_scan.py
"""Character scanning for the two texts this backend reads rather than renders.

Two pieces of this backend recognise text a caller wrote: the introspection
type parser reads back a declared column type, and the partition mixin
validates a declared ``PARTITION BY`` / ``CLUSTER BY`` spelling.  Both used
regular expressions, and ``src`` may not import ``re`` at all, so the same
shapes are recognised here by walking characters.

The character classes below are the ones the expressions used, which are
wider than an ASCII reading suggests:

* the identifier sets were spelled ``[A-Za-z0-9_]``, so they are ASCII here;
* ``\\d`` is a Unicode *decimal* digit, which is what :meth:`str.isdecimal`
  tests;
* ``\\s`` is Unicode whitespace, which is what :meth:`str.isspace` tests.

Whitespace is skipped before every token, mirroring the ``\\s*`` the
expressions placed between their tokens.  The one token whose interior
whitespace matters -- a signed number, where the sign must touch its digits --
handles it inside :meth:`Scanner.take_signed_digits`.
"""

__all__ = ["Scanner"]


def _is_word_character(character: str) -> bool:
    """Whether *character* is one of the ASCII ``[A-Za-z_]``."""
    return bool(character) and (
        character == "_" or "A" <= character <= "Z" or "a" <= character <= "z"
    )


def _is_identifier_character(character: str) -> bool:
    """Whether *character* is one of the ASCII ``[A-Za-z0-9_]``."""
    return _is_word_character(character) or ("0" <= character <= "9")


def _is_decimal_digit(character: str) -> bool:
    """Whether *character* is what ``re`` matches as ``\\d``."""
    return bool(character) and character.isdecimal()


class Scanner:
    """A reading position over a string, with the primitives both parsers need.

    Instances are cheap and single-use: a recogniser that can fail two ways
    constructs a fresh :class:`Scanner` for each shape rather than rewinding a
    shared one.
    """

    __slots__ = ("_text", "_index")

    def __init__(self, text: str) -> None:
        self._text = text
        self._index = 0

    def peek(self, offset: int = 0) -> str:
        """The character *offset* places ahead, or ``""`` past either end."""
        position = self._index + offset
        if position < 0 or position >= len(self._text):
            return ""
        return self._text[position]

    def skip_space(self) -> None:
        """Advance past whitespace, if any."""
        while self._index < len(self._text) and self._text[self._index].isspace():
            self._index += 1

    def at_end(self) -> bool:
        """Whether only whitespace remains."""
        self.skip_space()
        return self._index >= len(self._text)

    def take_char(self, character: str) -> bool:
        """Consume *character* if it is next, or leave the position alone."""
        self.skip_space()
        if self.peek() != character:
            return False
        self._index += 1
        return True

    def take_word(self) -> "str | None":
        """Consume a run of letters and underscores, or nothing."""
        self.skip_space()
        start = self._index
        while _is_word_character(self.peek()):
            self._index += 1
        if self._index == start:
            return None
        return self._text[start:self._index]

    def take_identifier(self) -> "str | None":
        """Consume a bare or backtick-quoted identifier, or nothing.

        The text is returned as it was written, backticks included: the caller
        that renders a cluster column appends it unchanged, so the quoting is
        part of the spelling, not decoration to be stripped.
        """
        self.skip_space()
        if self.peek() == "`":
            closing = self._text.find("`", self._index + 1)
            if closing < 0:
                return None
            body = self._text[self._index + 1:closing]
            if not _is_word_character(body[0] if body else ""):
                return None
            for character in body[1:]:
                if not _is_identifier_character(character):
                    return None
            text = self._text[self._index:closing + 1]
            self._index = closing + 1
            return text
        if not _is_word_character(self.peek()):
            return None
        start = self._index
        self._index += 1
        while _is_identifier_character(self.peek()):
            self._index += 1
        return self._text[start:self._index]

    def take_digits(self, first_digits: str = "") -> "str | None":
        """Consume a run of decimal digits, or nothing.

        Args:
            first_digits: when given, the first digit must be one of these
                characters.  The step of ``GENERATE_ARRAY`` is ``[1-9]\\d*``,
                which is this vocabulary's way of saying "positive, no
                leading zero".
        """
        self.skip_space()
        start = self._index
        if first_digits:
            following = self.peek()
            if not following or following not in first_digits:
                return None
            self._index += 1
        while _is_decimal_digit(self.peek()):
            self._index += 1
        if self._index == start:
            return None
        return self._text[start:self._index]

    def take_signed_digits(self) -> "str | None":
        """Consume ``-?\\d+``, or nothing.

        Whitespace is skipped before the sign, not between it and the digits:
        `` - 10`` is not a number, exactly as in the expression this replaces.
        """
        self.skip_space()
        start = self._index
        if self.peek() == "-":
            self._index += 1
        digits_start = self._index
        while _is_decimal_digit(self.peek()):
            self._index += 1
        if self._index == digits_start:
            self._index = start
            return None
        return self._text[start:self._index]

    def take_group(self, opener: str, closer: str) -> "str | None":
        """Consume ``opener ... closer`` and return the interior, or nothing.

        Nesting is counted rather than assumed, so a ``<`` inside an
        ``ARRAY<...>`` belongs to the group instead of ending it early.  An
        unterminated group is refused, and nothing is consumed in that case.
        The interior is returned as written; it is the caller that decides
        whether an empty or whitespace-only interior is a spelling.
        """
        self.skip_space()
        if self.peek() != opener:
            return None
        depth = 0
        position = self._index
        while position < len(self._text):
            character = self._text[position]
            if character == opener:
                depth += 1
            elif character == closer:
                depth -= 1
                if depth == 0:
                    interior = self._text[self._index + 1:position]
                    self._index = position + 1
                    return interior
            position += 1
        return None
