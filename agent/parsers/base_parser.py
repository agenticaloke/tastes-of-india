from __future__ import annotations
import re
from abc import ABC, abstractmethod


class BaseParser(ABC):
    """Abstract base class for all recipe site parsers."""

    @abstractmethod
    def can_parse(self, url: str) -> bool:
        """Return True if this parser handles the given URL."""

    @abstractmethod
    def parse(self, url: str, html: str) -> dict | None:
        """
        Parse HTML and return a recipe dict, or None if parsing fails.

        Returned dict must have at minimum:
          name, description, ingredients (list of str), instructions (list of str),
          source_url, author_credit
        Optional: prep_time_mins, cook_time_mins, servings
        """

    @staticmethod
    def slugify(text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r'[^a-z0-9\s-]', '', text)
        text = re.sub(r'[\s-]+', '-', text)
        return text.strip('-')

    @staticmethod
    def clean(text: str) -> str:
        return ' '.join(text.split()).strip()

    @staticmethod
    def parse_time(text: str) -> int | None:
        """Parse '30 mins', '1 hour 15 minutes' etc. to total minutes."""
        text = text.lower()
        hours = re.search(r'(\d+)\s*h', text)
        mins = re.search(r'(\d+)\s*m', text)
        total = 0
        if hours:
            total += int(hours.group(1)) * 60
        if mins:
            total += int(mins.group(1))
        return total if total else None
