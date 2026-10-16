"""Year-column coordinates and country/survey scopes of reviewed official PDF tables."""
import unittest
from unittest.mock import patch

from services.china_macro_extended_service import (
    COMPILED_ANNUAL_YEARS, parse_compiled_annual_words, parse_urbanization_retrospective,
)
from services.china_macro_dashboard_service import annual_comparability_groups
from scripts.activate_livelihood_history import validate_livelihood_source, COMPILED_BOOK_URL


class CompiledAnnualTests(unittest.TestCase):
    def population(self):
        words = [(200+i*25, 90, 210+i*25, 100, str(year)) for i, year in enumerate(COMPILED_ANNUAL_YEARS)]
        for offset, label in enumerate(('60岁及以上','65岁及以上')):
            y=130+offset*20; words.append((10,y,110,y+10,label))
            for index in range(len(COMPILED_ANNUAL_YEARS)):
                words.append((200+index*25,y,210+index*25,y+10,str(1000+100*offset+index)))
        return words, '表2.2.4 人口——中国 年末人口数(万人)'

    def test_selected_year_not_adjacent_or_last_column(self):
        words,text=self.population()
        self.assertEqual(parse_compiled_annual_words(words,text,'population_china',2020),
                         {'CN_POP_60_PLUS':1008.0,'CN_POP_65_PLUS':1108.0})

    def test_unlisted_year_is_not_interpolated(self):
        words,text=self.population()
        with self.assertRaises(ValueError):parse_compiled_annual_words(words,text,'population_china',2001)

    def test_missing_header_does_not_shift_columns(self):
        words,text=self.population();words=[word for word in words if word[4]!='2020']
        with self.assertRaises(ValueError):parse_compiled_annual_words(words,text,'population_china',2020)

    def test_foreign_country_or_wrong_unit_is_not_accepted(self):
        words,text=self.population()
        for changed in (text.replace('中国','南非'),text.replace('万人','人')):
            with self.assertRaises(ValueError):parse_compiled_annual_words(words,changed,'population_china',2020)

    def test_explicit_missing_cell_remains_absent_not_zero(self):
        words,text=self.population();words=[(*word[:4],'…') if word[4]=='1008' else word for word in words]
        result=parse_compiled_annual_words(words,text,'population_china',2020)
        self.assertNotIn('CN_POP_60_PLUS',result);self.assertEqual(result['CN_POP_65_PLUS'],1108)

    def test_duplicate_cell_token_is_not_concatenated_or_guessed(self):
        words,text=self.population();words.append((400,130,410,140,'26407'))
        with self.assertRaises(ValueError):parse_compiled_annual_words(words,text,'population_china',2020)

    def test_15_59_row_cannot_become_16_59_population(self):
        review={'source_url':COMPILED_BOOK_URL,'kind':'official_compilation_pdf','table_profile':'population_china',
                'year':2020,'values':{'CN_WORKING_AGE_POP':87975}}
        with patch('scripts.activate_livelihood_history.parse_compiled_annual_pdf',return_value={'CN_POP_60_PLUS':26407}):
            with self.assertRaises(ValueError):validate_livelihood_source(b'%PDF-fixture',review)

    def test_compilation_upload_or_pdf_creation_is_not_publication_day(self):
        review={'source_url':COMPILED_BOOK_URL,'kind':'official_compilation_pdf','table_profile':'population_china',
                'year':2020,'values':{'CN_POP_60_PLUS':26407}}
        with patch('scripts.activate_livelihood_history.parse_compiled_annual_pdf',return_value={'CN_POP_60_PLUS':26407}):
            timing=validate_livelihood_source(b'%PDF-fixture',review)
        self.assertIsNone(timing['release_date']);self.assertEqual(timing['release_date_not_provided'],1)

    def test_retrospective_keeps_each_explicit_year_and_rejects_conflicts(self):
        sentence='全国常住人口城镇化率从2020年的63.89%提高至2025年的67.89%。'
        self.assertEqual(parse_urbanization_retrospective(sentence),{'2020':63.89,'2025':67.89})
        self.assertEqual(parse_urbanization_retrospective(sentence+sentence.replace('63.89','63.50')), {})
        self.assertEqual(parse_urbanization_retrospective(sentence.replace('全国','某市')), {})

    def test_only_affected_population_series_break_and_subset_note_is_preserved(self):
        groups=[{'code':'demography','charts':[{'code':'aging_population','note':'65岁是60岁的子集，不能相加。'}]}]
        series={'CN_POP_60_PLUS':[{'period':'2020','source_url':COMPILED_BOOK_URL+'#page=32'}]}
        chart=annual_comparability_groups(groups,series)[0]['charts'][0]
        self.assertEqual(chart['series_breaks'],{'CN_POP_60_PLUS':['2020']})
        self.assertIn('不能相加',chart['note']);self.assertNotIn('series_breaks',groups[0]['charts'][0])


if __name__=='__main__':unittest.main()
