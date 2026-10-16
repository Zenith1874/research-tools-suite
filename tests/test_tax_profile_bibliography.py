"""Profile citation imports must remain within corroborated publication scope."""

import unittest
from bs4 import BeautifulSoup
from scripts.import_tax_profile_bibliography import parse_profile_citation


class ProfileCitationTests(unittest.TestCase):
    def fixture(self, year='2025', venue='Australian Tax Forum: a journal of taxation policy, law and reform', heading='Journal articles'):
        return BeautifulSoup(f'''<div class="pub-content"><h2>{heading}</h2><p>
            <span class="rg-author">Brown R; Sadiq K; Donald S</span>,<span class="rg-year">{year}</span>,
            <span class="rg-title">'Superannuation taxation: Options for best practice reform'</span>,
            <i class="rg-source-title">{venue}</i>,<span class="rg-volume">40</span>,<span class="rg-page">pp. 267 - 310</span>
        </p></div>''', 'html.parser')

    def test_supplied_initials_and_year_precision_remain_unchanged(self):
        fields = parse_profile_citation(self.fixture(), 'Superannuation taxation: Options for best practice reform', 2025)
        self.assertEqual(['Brown R', 'Sadiq K', 'Donald S'], fields['authors'])
        self.assertIsNone(fields['publication_date'])
        self.assertEqual('year', fields['date_precision'])
        self.assertIn('source does not supply ISSN', fields['journal_identity_note'])

    def test_conflicting_year_or_wrong_venue_is_rejected(self):
        for soup in (self.fixture(year='2026'), self.fixture(venue='Australian Tax Review')):
            with self.assertRaises(ValueError):
                parse_profile_citation(soup, 'Superannuation taxation: Options for best practice reform', 2025)

    def test_book_section_cannot_be_imported_as_journal_article(self):
        with self.assertRaises(ValueError):
            parse_profile_citation(self.fixture(heading='Books'), 'Superannuation taxation: Options for best practice reform', 2025)


if __name__ == '__main__':
    unittest.main()
