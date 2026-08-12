from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / 'static' / 'abdc_astar_research.html'


class AstarTitleLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = PAGE.read_text(encoding='utf-8')

    def test_title_links_prefer_doi_and_open_new_page_safely(self):
        self.assertIn(
            'if(a && a.doi) return `https://doi.org/${a.doi}`;',
            self.html)
        self.assertIn('target="_blank" rel="noopener noreferrer"', self.html)

    def test_latest_and_semantic_cards_use_title_link_helper(self):
        marker = '<div class="card-title">${articleTitleLink(a)}</div>'
        self.assertGreaterEqual(self.html.count(marker), 2)


if __name__ == '__main__':
    unittest.main()
