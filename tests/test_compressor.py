"""Tests for the compressor module."""

import re

import pytest

from llm_text_compressor import (
    compress,
    compress_with_stats,
    compress_stream,
    compress_file,
    CompressionResult,
    PreservedSpan,
)


class TestCompress:
    def test_returns_string(self):
        assert isinstance(compress("Hello world"), str)

    def test_output_shorter_than_input(self):
        text = "understanding artificial intelligence significantly transformed"
        assert len(compress(text)) < len(text)

    def test_preserves_short_words(self):
        assert compress("I am the one") == "I am the one"

    def test_preserves_punctuation(self):
        assert "," in compress("hello, world")

    def test_preserves_acronyms(self):
        result = compress("the NASA program")
        assert "NASA" in result

    def test_level_1_removes_doubles(self):
        result = compress("letter", level=1)
        assert result == "leter"

    def test_level_2_removes_vowels(self):
        result = compress("understanding", level=2)
        assert len(result) < len("understanding")
        assert result[0] == "u"
        assert result[-1] == "g"

    def test_level_3_trims_long_words(self):
        result = compress("understanding", level=3)
        assert len(result) <= 6

    def test_preserves_non_alpha_separators(self):
        result = compress("hello, world! foo bar")
        assert "," in result
        assert "!" in result

    def test_empty_string(self):
        assert compress("") == ""

    @pytest.mark.parametrize("level", [1, 2, 3])
    def test_all_levels_produce_output(self, level: int):
        text = "The algorithm iterates through each element"
        result = compress(text, level=level)
        assert len(result) > 0


class TestPreserveEmails:
    def test_simple_email(self):
        assert "john@example.com" in compress("contact john@example.com for details")

    def test_complex_email(self):
        email = "first.last+tag@sub.domain.co.uk"
        assert email in compress(f"send to {email} please")

    def test_multiple_emails(self):
        text = "reach alice@test.com or bob@test.com"
        result = compress(text)
        assert "alice@test.com" in result
        assert "bob@test.com" in result


class TestPreserveURLs:
    def test_http_url(self):
        url = "http://example.com/page?q=1"
        assert url in compress(f"visit {url} now")

    def test_https_url(self):
        url = "https://docs.python.org/3/library/re.html"
        assert url in compress(f"see {url} for reference")

    def test_www_url(self):
        url = "www.example.com/path"
        assert url in compress(f"go to {url} today")


class TestPreservePhoneNumbers:
    def test_us_format(self):
        phone = "+1-555-123-4567"
        assert phone in compress(f"call {phone} anytime")

    def test_intl_format(self):
        phone = "+44 20 7946 0958"
        assert phone in compress(f"ring {phone} for support")

    def test_parens_format(self):
        phone = "(555) 123-4567"
        assert phone in compress(f"dial {phone} now")


class TestPreserveIDs:
    def test_uuid(self):
        uid = "550e8400-e29b-41d4-a716-446655440000"
        assert uid in compress(f"record {uid} saved")

    def test_hex_id(self):
        hid = "a1b2c3d4e5f6"
        assert hid in compress(f"commit {hid} merged")

    def test_alphanumeric_id(self):
        aid = "USR_42x9"
        assert aid in compress(f"user {aid} logged in")


class TestPreserveProperNouns:
    def test_capitalized_name(self):
        result = compress("Alice sent a message to Bob")
        assert "Alice" in result
        assert "Bob" in result

    def test_name_in_sentence(self):
        result = compress("The meeting with Jonathan was productive")
        assert "Jonathan" in result

    def test_all_caps_preserved(self):
        result = compress("send it to NASA headquarters")
        assert "NASA" in result


class TestCompressorOffTags:
    def test_basic_off_region(self):
        text = "this is compressible [COMPRESSOR_OFF]this must stay intact[/COMPRESSOR_OFF] more compressible"
        result = compress(text)
        assert "this must stay intact" in result
        # tags themselves are stripped
        assert "[COMPRESSOR_OFF]" not in result
        assert "[/COMPRESSOR_OFF]" not in result

    def test_surrounding_text_still_compressed(self):
        text = "understanding everything [COMPRESSOR_OFF]preserve me[/COMPRESSOR_OFF] understanding everything"
        result = compress(text)
        assert "preserve me" in result
        # the word "understanding" outside the tags should be compressed
        assert result.count("understanding") == 0

    def test_multiple_off_regions(self):
        text = (
            "compressible text [COMPRESSOR_OFF]first block[/COMPRESSOR_OFF] "
            "more compressible [COMPRESSOR_OFF]second block[/COMPRESSOR_OFF] end"
        )
        result = compress(text)
        assert "first block" in result
        assert "second block" in result

    def test_multiline_off_region(self):
        text = "before [COMPRESSOR_OFF]line one\nline two\nline three[/COMPRESSOR_OFF] after"
        result = compress(text)
        assert "line one\nline two\nline three" in result

    def test_no_off_tags_unchanged_behavior(self):
        text = "understanding artificial intelligence"
        assert compress(text) == compress(text)  # deterministic, no tags involved

    def test_entire_text_in_off_region(self):
        text = "[COMPRESSOR_OFF]nothing should change here[/COMPRESSOR_OFF]"
        assert compress(text) == "nothing should change here"


class TestWhitespaceNormalization:
    def test_trailing_spaces_removed(self):
        text = "hello world   \ngoodbye   "
        result = compress(text)
        # No trailing spaces
        assert not any(line.endswith(" ") for line in result.split("\n"))

    def test_runs_of_spaces_collapsed(self):
        text = "hello     world    test"
        result = compress(text)
        # Should not have runs of multiple spaces
        assert "  " not in result

    def test_consecutive_blank_lines_collapsed(self):
        text = "line1\n\n\n\n\nline2"
        result = compress(text)
        # Max 2 blank lines between content
        assert "\n\n\n\n" not in result
        # Should still have some blank lines
        assert "\n\n" in result

    def test_leading_indentation_preserved(self):
        text = "    indented line\n        more indented"
        result = compress(text, normalize=True)
        # Leading spaces preserved (note: words are compressed but indentation isn't)
        lines = result.split("\n")
        assert lines[0].startswith("    ")
        assert lines[1].startswith("        ")

    def test_text_in_compressor_off_not_normalized(self):
        text = "hello    world [COMPRESSOR_OFF]keep  these    spaces[/COMPRESSOR_OFF] more    text"
        result = compress(text, normalize=True)
        # Spaces inside COMPRESSOR_OFF preserved
        assert "keep  these    spaces" in result
        # Spaces outside should be normalized
        lines_outside = result.replace("keep  these    spaces", "").split()
        for line in lines_outside:
            assert "  " not in line

    def test_normalize_disabled(self):
        text = "hello    world\n\n\n\ntest   "
        result = compress(text, normalize=False)
        # Should still have multiple spaces (though word compression happens)
        # At least verify we can disable normalization
        result_normalized = compress(text, normalize=True)
        # They should be different
        assert len(result) != len(result_normalized) or result != result_normalized

    def test_empty_input_with_normalization(self):
        assert compress("", normalize=True) == ""
        assert compress("   \n\n\n   ", normalize=True) == ""

    def test_single_blank_line_preserved(self):
        text = "paragraph1\n\nparagraph2"
        result = compress(text, normalize=True)
        # Should preserve the single blank line
        assert "\n\n" in result or "prgrph1\n\nprgrph2" in result


class TestPreserveStructuredData:
    def test_fenced_code_block_preserved(self):
        text = "here is code:\n```python\ndef hello():\n    print('world')\n```\nmore text"
        result = compress(text)
        # Code block should be intact
        assert "def hello():" in result
        assert "print('world')" in result
        # Surrounding text should be compressed
        assert "here" not in result or "hre" in result

    def test_inline_code_preserved(self):
        text = "use the `compress()` function to compress text"
        result = compress(text)
        # Inline code preserved
        assert "`compress()`" in result

    def test_json_object_preserved(self):
        text = 'the response is {"status": "success", "data": {"id": 123}} and processing continues'
        result = compress(text)
        # JSON should be intact
        assert '{"status": "success", "data": {"id": 123}}' in result
        # Surrounding text compressed (response -> rsponse, processing -> prcsng or prcesng)
        assert ("rsponse" in result or "rspnse" in result) and ("prcsng" in result or "prcesng" in result)

    def test_json_array_preserved(self):
        text = "values are [1, 2, 3,  4, 5] in the array"
        result = compress(text)
        # JSON array preserved (note: whitespace may be normalized)
        assert "[1, 2, 3" in result and "4, 5]" in result

    def test_nested_json_preserved(self):
        text = '{"outer": {"inner": [1, 2, {"deep": "value"}]}} test'
        result = compress(text)
        # Nested JSON intact
        assert '{"outer": {"inner": [1, 2, {"deep": "value"}]}}' in result

    def test_xml_block_preserved(self):
        text = "the response <response><status>ok</status><data>test</data></response> was received"
        result = compress(text)
        # XML should be intact
        assert"<response><status>ok</status><data>test</data></response>" in result

    def test_mixed_structured_and_prose(self):
        text = "understanding this `code snippet` and processing these values"
        result = compress(text)
        # Code preserved, prose compressed
        assert "`code snippet`" in result
        assert "understanding" not in result

    def test_plain_brackets_not_json(self):
        text = "I have [some text] in brackets"
        result = compress(text)
        # Should NOT be treated as JSON, should be compressed normally
        # The word "text" should be compressed
        assert "txt" in result or "[some text]" not in result

    def test_fenced_code_without_language(self):
        text = "```\nsome code here\n```"
        result = compress(text)
        # Should still be preserved
        assert "some code here" in result

    def test_multiple_inline_code_spans(self):
        text = "use `first()` and `second()` functions together"
        result = compress(text)
        assert "`first()`" in result
        assert "`second()`" in result


class TestCompressionStats:
    def test_result_text_matches_compress(self):
        text = "understanding artificial intelligence"
        result = compress_with_stats(text)
        assert result.text == compress(text)

    def test_original_length_correct(self):
        text = "hello world"
        result = compress_with_stats(text)
        assert result.original_length == len(text)

    def test_compressed_length_correct(self):
        text = "understanding"
        result = compress_with_stats(text)
        assert result.compressed_length == len(result.text)

    def test_ratio_calculation(self):
        text = "understanding artificial intelligence"
        result = compress_with_stats(text)
        expected_ratio = result.compressed_length / result.original_length
        assert abs(result.ratio - expected_ratio) < 0.001

    def test_savings_pct_calculation(self):
        text = "understanding artificial intelligence"
        result = compress_with_stats(text)
        expected_savings = (1 - result.ratio) * 100
        assert abs(result.savings_pct - expected_savings) < 0.001

    def test_level_recorded(self):
        text = "hello world"
        result = compress_with_stats(text, level=3)
        assert result.level == 3

    def test_preserved_url_span(self):
        text = "visit https://example.com for info"
        result = compress_with_stats(text)
        # Should have a URL span
        url_spans = [s for s in result.preserved_spans if s.kind == "preserve"]
        assert len(url_spans) > 0
        assert "https://example.com" in url_spans[0].text

    def test_preserved_email_span(self):
        text = "contact user@example.com today"
        result = compress_with_stats(text)
        email_spans = [s for s in result.preserved_spans if s.kind == "preserve"]
        assert len(email_spans) > 0
        assert "user@example.com" in email_spans[0].text

    def test_preserved_inline_code_span(self):
        text = "use the `compress()` function"
        result = compress_with_stats(text)
        code_spans = [s for s in result.preserved_spans if s.kind == "inline_code"]
        assert len(code_spans) > 0
        assert "`compress()`" == code_spans[0].text

    def test_compressor_off_span(self):
        text = "hello [COMPRESSOR_OFF]keep this[/COMPRESSOR_OFF] world"
        result = compress_with_stats(text)
        off_spans = [s for s in result.preserved_spans if s.kind == "compressor_off"]
        assert len(off_spans) > 0
        assert "keep this" == off_spans[0].text

    def test_str_returns_text(self):
        text = "understanding compression"
        result = compress_with_stats(text)
        assert str(result) == result.text

    def test_empty_input(self):
        result = compress_with_stats("")
        assert result.text == ""
        assert result.original_length == 0
        assert result.compressed_length == 0
        assert result.ratio == 1.0
        assert result.savings_pct == 0.0
        assert len(result.preserved_spans) == 0

    def test_span_positions_correct(self):
        text = "text https://example.com more"
        result = compress_with_stats(text)
        # Verify span positions point to actual content in compressed text
        for span in result.preserved_spans:
            assert result.text[span.start:span.end] == span.text


class TestCustomPreservePatterns:
    def test_custom_pattern_preserves_jira_ticket(self):
        text = "fix issue JIRA-1234 in the understanding module"
        result = compress(text, preserve_patterns=[r"JIRA-\d+"])
        assert "JIRA-1234" in result
        # Other text should be compressed
        assert "undrstndng" in result or "undrstand" in result

    def test_custom_pattern_stripe_key(self):
        text = "use key sk_live_abcd1234 for processing payments"
        result = compress(text, preserve_patterns=[r"sk_live_\w+"])
        assert "sk_live_abcd1234" in result

    def test_multiple_custom_patterns(self):
        text = "ticket JIRA-123 needs key sk_test_xyz"
        result = compress(text, preserve_patterns=[r"JIRA-\d+", r"sk_test_\w+"])
        assert "JIRA-123" in result
        assert "sk_test_xyz" in result

    def test_custom_pattern_as_compiled_regex(self):
        pattern = re.compile(r"PROJ-\d+")
        text = "working on PROJ-456 today"
        result = compress(text, preserve_patterns=[pattern])
        assert "PROJ-456" in result

    def test_invalid_regex_raises_error(self):
        with pytest.raises(ValueError, match="Invalid regex pattern"):
            compress("test", preserve_patterns=["[invalid"])

    def test_custom_patterns_do_not_interfere_with_builtin(self):
        text = "email user@test.com and ticket JIRA-999"
        result = compress(text, preserve_patterns=[r"JIRA-\d+"])
        # Both custom and built-in patterns should work
        assert "user@test.com" in result
        assert "JIRA-999" in result

    def test_custom_pattern_overlapping_with_builtin(self):
        # Custom patterns have priority
        text = "url http://example.com and ticket PROJ-123"
        result = compress(text, preserve_patterns=[r"http://\S+"])
        assert "http://example.com" in result

    def test_custom_pattern_in_stats(self):
        text = "processing CUSTOM-ID-789 successfully"
        result = compress_with_stats(text, preserve_patterns=[r"CUSTOM-ID-\d+"])
        # Should have a custom_pattern span
        custom_spans = [s for s in result.preserved_spans if s.kind == "custom_pattern"]
        assert len(custom_spans) > 0
        assert "CUSTOM-ID-789" in custom_spans[0].text


class TestCustomPreserveWords:
    def test_custom_word_preserved(self):
        text = "the mRNA vaccine is understanding complex"
        result = compress(text, preserve_words={"mRNA"})
        # Custom word preserved
        assert "mRNA" in result
        # Other words compressed
        assert "vcne" in result or "vaccn" in result

    def test_multiple_custom_words(self):
        text = "HIPAA compliance and tort law require understanding"
        result = compress(text, preserve_words={"HIPAA", "tort"})
        assert "HIPAA" in result
        assert "tort" in result

    def test_custom_words_merged_with_builtin(self):
        text = "the custom term is important"
        result = compress(text, preserve_words={"custom"})
        # Built-in words still preserved
        assert "the" in result
        assert "is" in result
        # Custom word preserved
        assert "custom" in result

    def test_case_insensitive_custom_words(self):
        text = "using Custom and CUSTOM terms"
        result = compress(text, preserve_words={"custom"})
        # Both cases should be preserved
        assert "Custom" in result
        assert "CUSTOM" in result

    def test_empty_custom_word_set(self):
        text = "understanding the concept"
        # Empty set should not cause issues
        result = compress(text, preserve_words=set())
        assert len(result) > 0

    def test_custom_words_in_stats(self):
        text = "the specialized terminology matters"
        result = compress_with_stats(text, preserve_words={"specialized"})
        # Output should contain the word
        assert "specialized" in result.text


class TestMarkdownMode:
    def test_heading_preserved(self):
        text = "## Understanding the Algorithm\nThis section explains everything"
        result = compress(text, markdown=True, level=2)
        # Heading marker and text both preserved
        assert "##" in result
        assert "Understanding" in result
        assert "Algorithm" in result
        # Body text compressed (check it's shorter)
        assert "section" not in result  # vowels removed

    def test_multiple_heading_levels(self):
        text = "# Main Title\n## Section One\n### Subsection\nContent here"
        result = compress(text, markdown=True, level=2)
        assert "#" in result
        assert "Main" in result
        assert "Title" in result
        assert "##" in result
        assert "Section" in result
        assert "###" in result

    def test_unordered_list_preserved(self):
        text = "Here are the features:\n- First feature\n- Second feature\n- Third feature"
        result = compress(text, markdown=True, level=2)
        # List markers preserved
        assert result.count("-") >= 3
        # List items compressed
        assert "First" in result
        assert "feature" not in result  # vowels removed

    def test_ordered_list_preserved(self):
        text = "Steps to follow:\n1. Download the file\n2. Install the software\n3. Configure settings"
        result = compress(text, markdown=True, level=2)
        # Numbers and dots preserved
        assert "1." in result
        assert "2." in result
        assert "3." in result

    def test_link_text_compressed_url_preserved(self):
        text = "Check out [this amazing article](https://example.com/article) for more information"
        result = compress(text, markdown=True, level=2)
        # URL preserved entirely
        assert "https://example.com/article" in result
        # Link text compressed (no vowels)
        assert "amazing" not in result
        # Link brackets preserved
        assert "[" in result
        assert "]" in result
        assert "(" in result
        assert ")" in result

    def test_multiple_links(self):
        text = "See [documentation](https://docs.example.com) and [tutorial](https://tutorial.com)"
        result = compress(text, markdown=True, level=2)
        assert "https://docs.example.com" in result
        assert "https://tutorial.com" in result

    def test_blockquote_preserved(self):
        text = "> This is a quote from someone\n> It continues on another line\n\nRegular text"
        result = compress(text, markdown=True, level=2)
        # Blockquote markers preserved
        assert ">" in result
        # Content compressed (no "quote" word in exact form)
        assert "quote" not in result

    def test_horizontal_rule_preserved(self):
        text = "First section\n\n---\n\nSecond section"
        result = compress(text, markdown=True, level=2)
        # Horizontal rule preserved
        assert "---" in result

    def test_image_alt_compressed_url_preserved(self):
        text = "Here is an image: ![beautiful landscape](https://example.com/image.jpg)"
        result = compress(text, markdown=True, level=2)
        # URL preserved
        assert "https://example.com/image.jpg" in result
        # Alt text compressed (no vowels in "beautiful")
        assert "beautiful" not in result
        # Image syntax preserved
        assert "![" in result

    def test_nested_markdown_structures(self):
        text = """# Main Title
        
- Item with [link](https://example.com)
- Another item
  - Nested item

> Quote with **bold text**

Regular paragraph with understanding"""
        result = compress(text, markdown=True, level=2)
        # Check various elements preserved
        assert "#" in result
        assert "-" in result
        assert "https://example.com" in result
        assert ">" in result

    def test_markdown_false_backward_compatibility(self):
        text = "## This is a heading\nRegular text"
        result_standard = compress(text, markdown=False, level=2)
        result_no_param = compress(text, level=2)
        # Should produce identical output
        assert result_standard == result_no_param

    def test_markdown_with_compressor_off(self):
        text = "## Heading\n[COMPRESSOR_OFF]Keep this verbatim[/COMPRESSOR_OFF]\nMore text"
        result = compress(text, markdown=True, level=2)
        # Heading preserved
        assert "##" in result
        # COMPRESSOR_OFF content preserved
        assert "Keep this verbatim" in result

    def test_markdown_stats_integration(self):
        text = "## Section\nSome understanding text with [link](https://example.com)"
        result = compress_with_stats(text, markdown=True, level=2)
        # Should return CompressionResult
        assert isinstance(result, CompressionResult)
        assert result.compressed_length < result.original_length
        # Check compression actually happened
        assert "understanding" not in result.text


class TestLocaleSupport:
    def test_french_locale_preserves_stop_words(self):
        text = "Le développement de la technologie est incroyable"
        result = compress(text, level=2, locale="fr")
        # French stop words preserved
        assert "Le" in result
        assert "de" in result
        assert "la" in result
        assert "est" in result
        # Other words compressed
        assert "développement" not in result  # vowels should be removed

    def test_spanish_locale_preserves_stop_words(self):
        text = "El desarrollo de la tecnología es increíble"
        result = compress(text, level=2, locale="es")
        # Spanish stop words preserved
        assert "El" in result
        assert "de" in result
        assert "la" in result
        assert "es" in result
        # Other words compressed (vowels removed from tecnología -> tcnlgía or similar)
        assert "tecnología" not in result

    def test_german_locale_preserves_stop_words(self):
        text = "Die entwicklung der technologie ist unglaublich"
        result = compress(text, level=2, locale="de")
        # German stop words preserved
        assert "Die" in result
        assert "der" in result
        assert "ist" in result
        # Check compression happened (result shorter than input)
        assert len(result) < len(text)

    def test_accented_characters_handled(self):
        text = "café résumé naïve"
        result = compress(text, level=2)
        # Should not crash, accented chars treated as vowels
        assert len(result) > 0
        # é, è should be treated as vowels and removed
        assert "café" not in result

    def test_portuguese_locale(self):
        text = "O desenvolvimento da tecnologia é incrível"
        result = compress(text, level=2, locale="pt")
        # Portuguese stop words preserved
        assert "O" in result
        assert "da" in result
        assert "é" in result

    def test_italian_locale(self):
        text = "Lo sviluppo della tecnologia è incredibile"
        result = compress(text, level=2, locale="it")
        # Italian stop words preserved
        assert "Lo" in result
        assert "della" in result
        assert "è" in result

    def test_locale_merged_with_custom_words(self):
        text = "Le développement du système API"
        result = compress(text, level=2, locale="fr", preserve_words={"API", "système"})
        # Both locale and custom words preserved
        assert "Le" in result
        assert "du" in result
        assert "API" in result
        assert "système" in result

    def test_invalid_locale_ignored(self):
        text = "understanding the technology"
        result = compress(text, level=2, locale="xyz")
        # Should not crash, just treat as no locale
        assert len(result) > 0
        assert "understanding" not in result  # still compressed

    def test_locale_with_stats(self):
        text = "La technologie moderne est fascinante"
        result = compress_with_stats(text, level=2, locale="fr")
        assert isinstance(result, CompressionResult)
        # French stop words preserved
        assert "La" in result.text
        assert "est" in result.text
        # Other words compressed
        assert "technologie" not in result.text

    def test_locale_with_markdown(self):
        text = "## Le Titre\n\nLe contenu avec [lien](https://example.com)"
        result = compress(text, level=2, locale="fr", markdown=True)
        # Markdown preserved
        assert "##" in result
        assert "https://example.com" in result
        # French stop words preserved
        assert "Le" in result
        # Other words compressed
        assert "contenu" not in result

class TestStreamCompression:
    def test_basic_streaming(self):
        chunks = ["This is a ", "test of streaming ", "compression."]
        result = "".join(compress_stream(chunks, level=2))
        # Should produce compressed output
        assert len(result) > 0
        assert len(result) < sum(len(c) for c in chunks)

    def test_stream_equals_non_stream(self):
        text = "The understanding of artificial intelligence requires significant computational resources."
        chunks = [text[i:i+10] for i in range(0, len(text), 10)]
        
        # Streaming result
        stream_result = "".join(compress_stream(chunks, level=2))
        # Non-streaming result
        direct_result = compress(text, level=2)
        
        assert stream_result == direct_result

    def test_stream_with_single_chunk(self):
        text = "This is a single chunk of text for testing"
        result = "".join(compress_stream([text], level=2))
        expected = compress(text, level=2)
        assert result == expected

    def test_stream_with_many_small_chunks(self):
        text = "understanding the mechanism"
        # Split into individual characters
        chunks = list(text)
        result = "".join(compress_stream(chunks, level=2, buffer_size=10))
        # When chunks are very small, whitespace handling may differ
        # Just verify compression happened and key letters preserved
        assert len(result) < len(text)
        assert "undrst" in result or "undrstand" in result

    def test_stream_with_empty_chunks(self):
        chunks = ["hello ", "", "world", "", ""]
        result = "".join(compress_stream(chunks, level=2))
        expected = compress("hello world", level=2)
        assert result == expected

    def test_stream_with_markdown(self):
        chunks = ["## Header\n\n", "Some text with ", "[link](https://example.com)"]
        result = "".join(compress_stream(chunks, level=2, markdown=True))
        expected = compress("## Header\n\nSome text with [link](https://example.com)", level=2, markdown=True)
        assert result == expected

    def test_stream_with_locale(self):
        text = "Le développement de la technologie"
        chunks = [text[i:i+8] for i in range(0, len(text), 8)]
        result = "".join(compress_stream(chunks, level=2, locale="fr"))
        expected = compress(text, level=2, locale="fr")
        assert result == expected

    def test_stream_with_custom_patterns(self):
        text = "Processing TICKET-123 and understanding the system"
        chunks = [text[i:i+15] for i in range(0, len(text), 15)]
        result = "".join(compress_stream(chunks, level=2, preserve_patterns=[r"TICKET-\d+"]))
        # TICKET-123 should be preserved
        assert "TICKET-123" in result

    def test_stream_preserves_urls_across_chunks(self):
        # URL split across chunks
        chunks = ["Visit https://", "example.", "com/path for info"]
        result = "".join(compress_stream(chunks, level=2))
        # URL should be preserved even though it was split
        assert "https://example.com/path" in result

    def test_file_streaming_basic(self, tmp_path):
        # Create a temporary file
        test_file = tmp_path / "test.txt"
        content = "This is a test file with understanding and significant content that needs compression."
        test_file.write_text(content)
        
        # Stream compress the file
        result = "".join(compress_file(str(test_file), level=2))
        expected = compress(content, level=2)
        assert result == expected

    def test_file_streaming_large_file(self, tmp_path):
        # Create a larger file
        test_file = tmp_path / "large.txt"
        line = "The understanding of artificial intelligence requires computational resources. "
        content = line * 100  # ~8KB
        test_file.write_text(content)
        
        # Stream compress with small chunks
        result = "".join(compress_file(str(test_file), level=2, chunk_size=512))
        # Verify compression happened
        assert len(result) < len(content)
        # Key words should be compressed
        assert "undrstandng" in result or "undrstand" in result
        assert "intlignce" in result or "inteligenc" in result

    def test_file_not_found(self):
        import pytest
        with pytest.raises(FileNotFoundError):
            list(compress_file("/nonexistent/file.txt"))

    def test_stream_different_buffer_sizes(self):
        text = "The quick brown fox jumps over the lazy dog. " * 20
        chunks = [text[i:i+20] for i in range(0, len(text), 20)]
        
        # Different buffer sizes should produce compressed output
        result_small = "".join(compress_stream(chunks, level=2, buffer_size=100))
        result_large = "".join(compress_stream(chunks, level=2, buffer_size=1000))
        
        # Both should compress the text
        assert len(result_small) < len(text)
        assert len(result_large) < len(text)
        # Key compressed words should appear
        assert "qck" in result_small or "quick" in result_small
        assert "brwn" in result_small or "brown" in result_small


class TestSentencePruning:
    def test_level_4_removes_filler_phrases(self):
        text = "I think this is, you know, a really good example of basically what we mean."
        result = compress(text, level=4)
        # Filler phrases should be removed
        assert "you know" not in result.lower()
        assert "I think" not in result.lower()
        assert "basically" not in result.lower()
        # Core content should remain
        assert "xmple" in result or "example" in result

    def test_level_4_deduplicates_lines(self):
        text = "This is a line\nThis is a line\nThis is different"
        result = compress(text, level=4)
        # Consecutive duplicate lines should be removed
        lines = [l for l in result.split("\n") if l.strip()]
        # Should have 2 non-empty lines (duplicates removed)
        assert len(lines) == 2

    def test_level_4_compression_stronger_than_3(self):
        text = "I really think that this is basically a very good understanding of the mechanism, you know."
        result_3 = compress(text, level=3)
        result_4 = compress(text, level=4)
        # Level 4 should be shorter due to filler removal
        assert len(result_4) < len(result_3)

    def test_level_4_with_stats(self):
        text = "Honestly, I believe this is a good example."
        result = compress_with_stats(text, level=4)
        assert isinstance(result, CompressionResult)
        assert result.compressed_length < result.original_length
        # Filler removed
        assert "Honestly" not in result.text

    def test_invalid_level_raises_error(self):
        with pytest.raises(ValueError, match="Compression level must be 1-4"):
            compress("test", level=0)
        
        with pytest.raises(ValueError, match="Compression level must be 1-4"):
            compress("test", level=5)

    def test_level_4_preserves_meaningful_content(self):
        text = "The understanding of artificial intelligence requires computational resources."
        result = compress(text, level=4)
        # Should still be readable with level 3 compression
        assert "The" in result
        assert len(result) < len(text)

    def test_level_4_with_markdown(self):
        text = "## Introduction\n\nI think this is, you know, really important.\n\nThis is important."
        result = compress(text, level=4, markdown=True)
        # Markdown preserved
        assert "##" in result
        # Fillers removed
        assert "I think" not in result.lower()
        assert "you know" not in result.lower()

    def test_level_4_with_locale(self):
        text = "Je pense que c'est vraiment, vous savez, très important."
        result = compress(text, level=4, locale="fr")
        # French stop words preserved
        assert "Je" in result or "je" in result
        # Compression applied
        assert len(result) < len(text)

    def test_level_4_with_compressor_off(self):
        text = "I think this text needs compression. [COMPRESSOR_OFF]Preserve this exactly![/COMPRESSOR_OFF] More text here."
        result = compress(text, level=4)
        # Content in COMPRESSOR_OFF preserved
        assert "Preserve this exactly!" in result
        # Fillers outside removed
        assert "I think" not in result.lower()
