from bs4 import BeautifulSoup
from .base_parser import BaseParser


class ArchanaKitchenParser(BaseParser):

    def can_parse(self, url: str) -> bool:
        return 'archanaskitchen.com' in url

    def parse(self, url: str, html: str) -> dict | None:
        try:
            soup = BeautifulSoup(html, 'lxml')

            name_el = soup.find('h1', class_='recipe-title') or soup.find('h1')
            if not name_el:
                return None
            name = self.clean(name_el.get_text())

            desc_el = soup.find('div', class_='recipe-description') or soup.find('meta', {'name': 'description'})
            if desc_el:
                description = self.clean(desc_el.get('content', '') or desc_el.get_text())
            else:
                description = ''

            ing_items = soup.select('.ingredients-list li, .ingredient-list li, .wprm-recipe-ingredient')
            ingredients = []
            for el in ing_items:
                text = self.clean(el.get_text())
                if text:
                    ingredients.append({"qty": "", "item": text})

            step_items = soup.select('.recipe-instructions li, .wprm-recipe-instruction-text, .instructions li')
            instructions = [self.clean(el.get_text()) for el in step_items if el.get_text().strip()]

            if not name or not ingredients or not instructions:
                return None

            author_el = soup.find('span', class_='author') or soup.find('a', rel='author')
            author = self.clean(author_el.get_text()) if author_el else 'Archana\'s Kitchen'

            prep_el = soup.find(class_='wprm-recipe-prep_time-container')
            cook_el = soup.find(class_='wprm-recipe-cook_time-container')

            return {
                'name': name,
                'slug': self.slugify(name),
                'description': description[:500],
                'ingredients': ingredients[:30],
                'instructions': instructions[:20],
                'source_url': url,
                'author_credit': author,
                'prep_time_mins': self.parse_time(prep_el.get_text()) if prep_el else None,
                'cook_time_mins': self.parse_time(cook_el.get_text()) if cook_el else None,
                'servings': None,
            }
        except Exception:
            return None
