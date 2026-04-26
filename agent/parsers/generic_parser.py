"""
Generic fallback parser using schema.org/Recipe JSON-LD,
which most modern recipe sites embed for SEO.
"""
import json
import re
from bs4 import BeautifulSoup
from .base_parser import BaseParser


class GenericParser(BaseParser):

    def can_parse(self, url: str) -> bool:
        return True  # fallback — always try

    def parse(self, url: str, html: str) -> dict | None:
        try:
            soup = BeautifulSoup(html, 'lxml')
            data = self._extract_json_ld(soup)
            if not data:
                return None

            name = self.clean(data.get('name', ''))
            if not name:
                return None

            description = self.clean(data.get('description', ''))[:500]

            raw_ings = data.get('recipeIngredient', [])
            ingredients = [{"qty": "", "item": self.clean(i)} for i in raw_ings if i]

            raw_steps = data.get('recipeInstructions', [])
            instructions = []
            for step in raw_steps:
                if isinstance(step, dict):
                    text = step.get('text', '')
                elif isinstance(step, str):
                    text = step
                else:
                    continue
                text = self.clean(re.sub(r'<[^>]+>', ' ', text))
                if text:
                    instructions.append(text)

            if not ingredients or not instructions:
                return None

            author = ''
            raw_author = data.get('author', {})
            if isinstance(raw_author, dict):
                author = raw_author.get('name', '')
            elif isinstance(raw_author, list) and raw_author:
                author = raw_author[0].get('name', '') if isinstance(raw_author[0], dict) else str(raw_author[0])
            elif isinstance(raw_author, str):
                author = raw_author

            prep = self.parse_time(data.get('prepTime', ''))
            cook = self.parse_time(data.get('cookTime', ''))

            servings_raw = data.get('recipeYield', '')
            if isinstance(servings_raw, list):
                servings_raw = servings_raw[0] if servings_raw else ''
            servings_match = re.search(r'\d+', str(servings_raw))
            servings = int(servings_match.group()) if servings_match else None

            return {
                'name': name,
                'slug': self.slugify(name),
                'description': description,
                'ingredients': ingredients[:30],
                'instructions': instructions[:20],
                'source_url': url,
                'author_credit': self.clean(author) or 'Unknown',
                'prep_time_mins': prep,
                'cook_time_mins': cook,
                'servings': servings,
            }
        except Exception:
            return None

    def _extract_json_ld(self, soup):
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                raw = json.loads(script.string or '{}')
                # Handle @graph arrays
                if isinstance(raw, dict) and '@graph' in raw:
                    for item in raw['@graph']:
                        if isinstance(item, dict) and 'Recipe' in item.get('@type', ''):
                            return item
                if isinstance(raw, list):
                    for item in raw:
                        if isinstance(item, dict) and 'Recipe' in item.get('@type', ''):
                            return item
                if isinstance(raw, dict) and 'Recipe' in raw.get('@type', ''):
                    return raw
            except Exception:
                continue
        return None
