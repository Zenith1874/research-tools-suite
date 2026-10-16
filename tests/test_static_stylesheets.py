# -*- coding: utf-8 -*-
"""Stylesheet rules that fail silently.

CSS has no error channel. A declaration the parser rejects is dropped and the
page renders with whatever it had before -- no console message, no visual break
loud enough to notice. That is how `minmax(340px, minmax(0, 1fr))` survived: it
reads as a sensible combination of two things that are individually correct,
`minmax()` does not nest, so every multi-column rule on the observatory page
was dead, the grid stayed at one column, and `grid-column: span 2` then created
an implicit second column that squeezed four cards to 37px wide on a desktop
viewport. The page looked plausible the whole time.

These are lints for constructs that disappear rather than break.
"""

import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"

# `minmax(` appearing inside another `minmax(`'s argument list. The max
# argument must be a track breadth -- a length, percentage, flex, or one of the
# content keywords -- never another minmax().
NESTED_MINMAX = re.compile(r"minmax\([^()]*minmax\(", re.I)

# `repeat()` needs a count or auto-fit/auto-fill; a stray `repeat(minmax(...))`
# is the other shape of the same slip.
BARE_REPEAT = re.compile(r"repeat\(\s*minmax\(", re.I)

# Comments are where the explanation of a banned construct lives, so linting
# raw text makes documenting a bug indistinguishable from committing it.
COMMENT = re.compile(r"/\*.*?\*/", re.S)


def strip_comments(text):
    """Blank comment bodies in place, so reported line numbers stay honest."""
    return COMMENT.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def stylesheets():
    return sorted(STATIC.glob("*.css"))


def declarations(path):
    """(line number, text) per line, with comments blanked."""
    text = strip_comments(path.read_text(encoding="utf-8"))
    return list(enumerate(text.splitlines(), start=1))


class NestedMinmaxTests(unittest.TestCase):
    def test_no_stylesheet_nests_minmax(self):
        offenders = []
        for path in stylesheets():
            for number, line in declarations(path):
                if NESTED_MINMAX.search(line):
                    offenders.append(f"{path.name}:{number}: {line.strip()}")
        self.assertEqual([], offenders, "minmax() does not nest; the browser "
                         "drops the whole declaration and the grid silently "
                         "falls back to its previous value:\n  " +
                         "\n  ".join(offenders))

    def test_no_stylesheet_calls_repeat_without_a_count(self):
        offenders = []
        for path in stylesheets():
            for number, line in declarations(path):
                if BARE_REPEAT.search(line):
                    offenders.append(f"{path.name}:{number}: {line.strip()}")
        self.assertEqual([], offenders, "repeat() needs a count or auto-fit/auto-fill")

    def test_the_lint_would_actually_catch_the_bug_it_was_written_for(self):
        # A lint nobody has seen fail is a lint nobody knows works.
        self.assertRegex(
            "grid-template-columns: repeat(auto-fit, minmax(340px, minmax(0, 1fr)));",
            NESTED_MINMAX)
        self.assertNotRegex(
            "grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));", NESTED_MINMAX)
        self.assertNotRegex("grid-template-columns: minmax(0, 1fr);", NESTED_MINMAX)

    def test_a_comment_describing_the_construct_is_not_flagged_as_using_it(self):
        # The fix is documented in a comment quoting the bad CSS verbatim.
        blanked = strip_comments(
            "a {}\n/* minmax(340px, minmax(0, 1fr)) is invalid */\nb {}")
        self.assertNotRegex(blanked, NESTED_MINMAX)
        self.assertEqual(3, len(blanked.splitlines()), "line numbers must survive")


class SpanGuardTests(unittest.TestCase):
    """`grid-column: span N` needs the tracks it spans to exist.

    On a one-column grid `span 2` does not clamp -- it creates an implicit
    column and the row lays out at twice the intended width. So every span rule
    has to sit inside the same condition that creates the extra track.
    """

    def test_every_span_rule_is_inside_a_media_query(self):
        for path in stylesheets():
            text = strip_comments(path.read_text(encoding="utf-8"))
            for match in re.finditer(r"grid-column:\s*span\s+[2-9]", text):
                before = text[:match.start()]
                # Unclosed braces: depth 1 is a bare rule, depth 2+ means the
                # rule is nested inside an at-rule block.
                depth = before.count("{") - before.count("}")
                line = before.count("\n") + 1
                self.assertGreaterEqual(
                    depth, 2,
                    f"{path.name}:{line}: `span` at rule depth {depth} is not "
                    "guarded by the media query that creates the extra track")


if __name__ == "__main__":
    unittest.main()
