import copy
import unittest

from scripts.activate_bank_history_year import validated_year_targets
from scripts.audit_bank_workbook import ROW_LABELS


class BankHistoryActivationTests(unittest.TestCase):
    def sample(self):
        table = {'year':2021, 'values':{code:[1,2,3,4] for code in ROW_LABELS}}
        table['values']['CN_BANK_NSFR'] = [None] * 4
        cells = [{'indicator_code':code, 'period':f'2021-{q*3:02d}', 'reported_value':value}
                 for code in ROW_LABELS for q,value in enumerate(table['values'][code],1)]
        return table, cells

    def test_exact_52_cell_identity_and_values(self):
        table, cells = self.sample()
        expected = validated_year_targets(table, cells)
        self.assertEqual(len(expected),52)
        self.assertNotIn(('CN_BANK_NSFR','2021-03'),expected)
        table['values']['CN_BANK_NPL_RATIO'][0]=0
        next(c for c in cells if c['indicator_code']=='CN_BANK_NPL_RATIO' and c['period']=='2021-03')['reported_value']=0
        self.assertEqual(validated_year_targets(table,cells)['CN_BANK_NPL_RATIO','2021-03'],0)

    def test_missing_duplicate_wrong_year_and_source_mismatch_reject(self):
        table,cells=self.sample()
        for mutation in ('missing','duplicate','year','value'):
            damaged=copy.deepcopy(cells)
            if mutation=='missing':damaged.pop()
            elif mutation=='duplicate':damaged[-1]=copy.deepcopy(damaged[0])
            elif mutation=='year':damaged[0]['period']='2020-03'
            else:damaged[0]['reported_value']=10
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                validated_year_targets(table,damaged)

    def test_missing_boolean_nan_and_undisclosed_nsfr_are_not_observations(self):
        for value in (None,True,float('nan')):
            table,cells=self.sample();table['values']['CN_BANK_NPL_RATIO'][0]=value
            with self.subTest(value=value),self.assertRaises(ValueError):validated_year_targets(table,cells)
        table,cells=self.sample();table['values']['CN_BANK_NSFR'][0]=120
        with self.assertRaises(ValueError):validated_year_targets(table,cells)


if __name__ == '__main__':
    unittest.main()
