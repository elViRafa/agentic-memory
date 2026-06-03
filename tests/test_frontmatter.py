from __future__ import annotations

import unittest
from memory_fabric.frontmatter import (
    parse_frontmatter,
    dump_frontmatter,
    FrontmatterError,
    _can_be_bare,
    _parse_value,
)


class FrontmatterTests(unittest.TestCase):
    def test_parse_valid_frontmatter(self) -> None:
        text = (
            "---\n"
            "priority: high\n"
            "summary: \"A test summary\"\n"
            "tags: [test, docs, frontmatter]\n"
            "active: true\n"
            "---\n"
            "# Heading\n"
            "Some content here.\n"
        )
        metadata, body = parse_frontmatter(text)
        self.assertEqual(metadata["priority"], "high")
        self.assertEqual(metadata["summary"], "A test summary")
        self.assertEqual(metadata["tags"], ["test", "docs", "frontmatter"])
        self.assertEqual(metadata["active"], True)
        self.assertEqual(body, "# Heading\nSome content here.\n")

    def test_parse_missing_opening_delimiter(self) -> None:
        text = "priority: high\n---\n# Heading"
        with self.assertRaises(FrontmatterError) as ctx:
            parse_frontmatter(text)
        self.assertIn("Missing YAML frontmatter delimiter", str(ctx.exception))

    def test_parse_missing_closing_delimiter(self) -> None:
        text = "---\npriority: high\n# Heading"
        with self.assertRaises(FrontmatterError) as ctx:
            parse_frontmatter(text)
        self.assertIn("Missing closing YAML frontmatter delimiter", str(ctx.exception))

    def test_parse_invalid_line_format(self) -> None:
        text = (
            "---\n"
            "invalid_line_no_colon\n"
            "---\n"
            "content"
        )
        with self.assertRaises(FrontmatterError) as ctx:
            parse_frontmatter(text)
        self.assertIn("Invalid frontmatter line", str(ctx.exception))

    def test_parse_empty_key(self) -> None:
        text = (
            "---\n"
            ": value\n"
            "---\n"
            "content"
        )
        with self.assertRaises(FrontmatterError) as ctx:
            parse_frontmatter(text)
        self.assertIn("Empty frontmatter key", str(ctx.exception))

    def test_dump_frontmatter(self) -> None:
        metadata = {
            "priority": "low",
            "summary": "Another test",
            "tags": ["a", "b"],
            "active": False,
        }
        body = "Some body content."
        dumped = dump_frontmatter(metadata, body)
        
        # Verify it can be parsed back correctly
        parsed_metadata, parsed_body = parse_frontmatter(dumped)
        self.assertEqual(parsed_metadata["priority"], "low")
        self.assertEqual(parsed_metadata["summary"], "Another test")
        self.assertEqual(parsed_metadata["tags"], ["a", "b"])
        self.assertEqual(parsed_metadata["active"], False)
        self.assertEqual(parsed_body.strip(), body)

    def test_can_be_bare_logic(self) -> None:
        self.assertTrue(_can_be_bare("simple_value"))
        self.assertTrue(_can_be_bare("path/to/file.md"))
        self.assertFalse(_can_be_bare("value with spaces"))
        self.assertFalse(_can_be_bare("special*char"))

    def test_parse_value_types(self) -> None:
        self.assertEqual(_parse_value(""), "")
        self.assertEqual(_parse_value("true"), True)
        self.assertEqual(_parse_value("FALSE"), False)
        self.assertEqual(_parse_value("123"), "123")
        self.assertEqual(_parse_value("'quoted'"), "quoted")
        self.assertEqual(_parse_value('"double_quoted"'), "double_quoted")
        self.assertEqual(_parse_value("[]"), [])
        self.assertEqual(_parse_value("['a', 'b']"), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
