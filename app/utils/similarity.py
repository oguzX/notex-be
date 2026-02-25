"""Text similarity utilities."""

from typing import Any


def token_overlap_score(text1: str, text2: str) -> float:
    """
    Calculate token overlap similarity score (0-1).
    
    Simple implementation using word tokens.
    """
    if not text1 or not text2:
        return 0.0
    
    # Tokenize and normalize
    tokens1 = set(text1.lower().split())
    tokens2 = set(text2.lower().split())
    
    if not tokens1 or not tokens2:
        return 0.0
    
    # Jaccard similarity
    intersection = tokens1 & tokens2
    union = tokens1 | tokens2
    
    return len(intersection) / len(union) if union else 0.0


def fuzzy_similarity(text1: str, text2: str) -> float:
    """
    Calculate fuzzy string similarity (0-100).
    
    Uses rapidfuzz if available, otherwise falls back to token overlap.
    """
    try:
        from rapidfuzz import fuzz
        return fuzz.ratio(text1.lower(), text2.lower()) / 100.0
    except ImportError:
        # Fallback to token overlap
        return token_overlap_score(text1, text2)


def best_match(query: str, candidates: list[str], threshold: float = 0.5) -> tuple[str | None, float]:
    """
    Find best matching candidate for a query.
    
    Returns (best_match, score) or (None, 0.0) if no match above threshold.
    """
    if not query or not candidates:
        return None, 0.0
    
    best_candidate = None
    best_score = 0.0
    
    for candidate in candidates:
        score = fuzzy_similarity(query, candidate)
        if score > best_score:
            best_score = score
            best_candidate = candidate
    
    if best_score >= threshold:
        return best_candidate, best_score
    
    return None, 0.0
