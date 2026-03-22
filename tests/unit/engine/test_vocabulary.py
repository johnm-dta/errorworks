"""Tests for errorworks.engine.vocabulary."""

from __future__ import annotations

import pytest

from errorworks.engine.vocabulary import ENGLISH_VOCABULARY, LOREM_VOCABULARY, get_vocabulary


class TestGetVocabulary:
    """Tests for get_vocabulary lookup function."""

    def test_english_returns_english_vocabulary(self) -> None:
        assert get_vocabulary("english") is ENGLISH_VOCABULARY

    def test_lorem_returns_lorem_vocabulary(self) -> None:
        assert get_vocabulary("lorem") is LOREM_VOCABULARY

    def test_unknown_name_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown vocabulary"):
            get_vocabulary("klingon")
