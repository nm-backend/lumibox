"""
Нечёткий поиск (fuzzy search) для MovieHub.

Использует расстояние Левенштейна для исправления опечаток.
Не требует внешних зависимостей — работает на чистом Python.
"""

from difflib import SequenceMatcher
from typing import Optional


def fuzzy_match(query: str, candidates: list[str], threshold: float = 0.6) -> Optional[str]:
    """
    Находит наиболее похожий кандидат на запрос.

    Args:
        query: поисковый запрос пользователя
        candidates: список кандидатов для сравнения
        threshold: минимальный порог相似ности (0.0-1.0)

    Returns:
        Лучший кандидат или None если相似ность ниже порога
    """
    if not query or not candidates:
        return None

    query_lower = query.lower().strip()
    best_match = None
    best_score = 0

    for candidate in candidates:
        candidate_lower = candidate.lower().strip()

        # Точное совпадение
        if query_lower == candidate_lower:
            return candidate

        # Проверяем вхождение
        if query_lower in candidate_lower or candidate_lower in query_lower:
            score = len(query_lower) / max(len(query_lower), len(candidate_lower))
            if score > best_score:
                best_score = score
                best_match = candidate
            continue

        # SequenceMatcher для相似ности
        score = SequenceMatcher(None, query_lower, candidate_lower).ratio()
        if score > best_score:
            best_score = score
            best_match = candidate

    return best_match if best_score >= threshold else None


def suggest_corrections(query: str, existing_titles: list[str], max_suggestions: int = 3) -> list[str]:
    """
    Предлагает исправления для запроса.

    Args:
        query: поисковый запрос
        existing_titles: список существующих названий
        max_suggestions: максимальное количество предложений

    Returns:
        Список предложений для исправления
    """
    if not query or not existing_titles:
        return []

    suggestions = []
    query_lower = query.lower().strip()

    for title in existing_titles:
        title_lower = title.lower().strip()
        score = SequenceMatcher(None, query_lower, title_lower).ratio()
        if score >= 0.4 and score < 1.0:
            suggestions.append((score, title))

    suggestions.sort(key=lambda x: x[0], reverse=True)
    return [s[1] for s in suggestions[:max_suggestions]]
