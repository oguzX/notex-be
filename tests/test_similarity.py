"""Tests for similarity utilities."""

import pytest

from app.utils.similarity import best_match, fuzzy_similarity, token_overlap_score


def test_token_overlap_exact_match():
    """Test exact match returns 1.0."""
    score = token_overlap_score("hello world", "hello world")
    assert score == 1.0


def test_token_overlap_no_match():
    """Test no overlap returns 0.0."""
    score = token_overlap_score("hello world", "foo bar")
    assert score == 0.0


def test_token_overlap_partial():
    """Test partial overlap."""
    score = token_overlap_score("hello world", "hello there")
    assert 0.0 < score < 1.0


def test_token_overlap_case_insensitive():
    """Test case insensitivity."""
    score1 = token_overlap_score("Hello World", "hello world")
    score2 = token_overlap_score("hello world", "hello world")
    assert score1 == score2


def test_fuzzy_similarity():
    """Test fuzzy similarity."""
    # Exact match
    assert fuzzy_similarity("test", "test") == 1.0
    
    # Similar
    assert fuzzy_similarity("test", "tests") > 0.8
    
    # Different
    assert fuzzy_similarity("test", "xyz") < 0.5


def test_best_match_found():
    """Test finding best match above threshold."""
    candidates = ["apple", "banana", "orange"]
    match, score = best_match("aple", candidates, threshold=0.5)
    
    assert match == "apple"
    assert score > 0.5


def test_best_match_not_found():
    """Test no match when below threshold."""
    candidates = ["apple", "banana", "orange"]
    match, score = best_match("xyz", candidates, threshold=0.7)
    
    assert match is None
    assert score < 0.7


def test_best_match_empty_candidates():
    """Test with empty candidate list."""
    match, score = best_match("test", [], threshold=0.5)
    
    assert match is None
    assert score == 0.0


def test_best_match_empty_query():
    """Test with empty query."""
    match, score = best_match("", ["test"], threshold=0.5)
    
    assert match is None
    assert score == 0.0
