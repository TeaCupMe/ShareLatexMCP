import unittest

from pyoverleaf import Project

from server import (
    Heading,
    _parse_ack,
    append_ops,
    compile_log_lines,
    full_replace_ops,
    headings_in,
    included_files,
    replacement_ops,
    resolve_include,
    resolve_project,
    search_hits,
    section_text,
    slice_lines,
)


def project(project_id: str, name: str, updated: str = "2026-01-01T00:00:00.000Z") -> Project:
    return Project(
        id=project_id,
        name=name,
        last_updated=updated,
        access_level="owner",
        source="owner",
        archived=False,
        trashed=False,
    )


class ResolveProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.projects = [
            project("id-exam", "DM Exam"),
            project("id-copy", "DM Exam (Copy)"),
            project("id-notes", "ExampleNotes"),
        ]

    def test_exact_id_wins(self) -> None:
        self.assertEqual(resolve_project(self.projects, "id-exam").name, "DM Exam")

    def test_exact_name(self) -> None:
        self.assertEqual(resolve_project(self.projects, "ExampleNotes").id, "id-notes")

    def test_case_insensitive_name(self) -> None:
        self.assertEqual(resolve_project(self.projects, "examplenotes").id, "id-notes")

    def test_ambiguous_name_lists_matches(self) -> None:
        projects = [project("a", "Notes"), project("b", "notes")]
        with self.assertRaises(RuntimeError) as caught:
            resolve_project(projects, "NOTES")
        self.assertIn("a", str(caught.exception))
        self.assertIn("b", str(caught.exception))

    def test_missing_project(self) -> None:
        with self.assertRaises(RuntimeError):
            resolve_project(self.projects, "missing")


class TextToolTests(unittest.TestCase):
    SAMPLE = "\\chapter{One}\n\\section{Intro}\nbody\n\\subsection{Detail}\nmore\n\\section{Next}\nend\n"

    def test_line_range_is_inclusive(self) -> None:
        self.assertEqual(slice_lines("a\nb\nc", 2, 3), "b\nc")

    def test_end_line_is_clamped(self) -> None:
        self.assertEqual(slice_lines("a\nb", 1, 9), "a\nb")

    def test_section_stops_at_same_level(self) -> None:
        body = section_text(self.SAMPLE, "Intro")
        self.assertIn("\\section{Intro}", body)
        self.assertIn("\\subsection{Detail}", body)
        self.assertNotIn("\\section{Next}", body)

    def test_duplicate_heading_is_rejected(self) -> None:
        text = "\\section{Intro}\n\\section{Intro}\n"
        with self.assertRaises(RuntimeError) as caught:
            section_text(text, "Intro")
        self.assertIn("1", str(caught.exception))
        self.assertIn("2", str(caught.exception))

    def test_heading_lines_include_command(self) -> None:
        found = headings_in(self.SAMPLE)
        self.assertIsInstance(found[0], Heading)
        self.assertEqual(found[0].command, "chapter")

    def test_include_skips_comments_and_resolves_tex(self) -> None:
        from pyoverleaf import ProjectFile

        text = "% \\input{skip}\n\\input{chapters/one}\n\\include{missing}\n"
        indexed = {"chapters/one.tex": ProjectFile(id="1", name="one.tex", created=None, type="doc")}
        found = included_files(text, "main.tex", indexed)
        self.assertEqual(found, [("input", "chapters/one", "chapters/one.tex"), ("include", "missing", None)])
        self.assertEqual(resolve_include("main.tex", "chapters/one", indexed), "chapters/one.tex")

    def test_search_is_capped_and_case_insensitive(self) -> None:
        text = "\n".join(f"Alpha {i}" for i in range(5))
        hits = search_hits("main.tex", text, "alpha", 2)
        self.assertEqual(len(hits), 2)
        self.assertTrue(hits[0].startswith("main.tex:1:"))

    def test_replacement_requires_one_match_and_uses_utf16_index(self) -> None:
        text = "a\U0001f600bX"
        ops = replacement_ops(text, "X", "Y")
        self.assertEqual(ops, [{"p": 4, "d": "X"}, {"p": 4, "i": "Y"}])
        with self.assertRaises(RuntimeError):
            replacement_ops("aa", "a", "b")

    def test_full_replace_and_append_ops(self) -> None:
        self.assertEqual(full_replace_ops("ab", "cd"), [{"p": 0, "d": "ab"}, {"p": 0, "i": "cd"}])
        self.assertEqual(append_ops("ab", "!"), [{"p": 2, "i": "!"}])
        self.assertEqual(full_replace_ops("ab", "ab"), [])

    def test_empty_socket_ack_has_no_payload(self) -> None:
        self.assertIsNone(_parse_ack("6:::3", 3))
        self.assertEqual(_parse_ack('6:::2+[null,["a"],1]', 2)[1], ["a"])

    def test_compile_log_keeps_error_location(self) -> None:
        log = "normal\n! Undefined control sequence.\nl.3 \\foo\nLaTeX Warning: loose\n"
        self.assertEqual(
            compile_log_lines(log),
            ["! Undefined control sequence.", "l.3 \\foo", "LaTeX Warning: loose"],
        )


if __name__ == "__main__":
    unittest.main()
