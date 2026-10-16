"""A valid code/header, original bytes and explicit unit/frequency must all agree."""
import hashlib
import unittest
from services.fred_native_review import METADATA,fred_unit_matches,validate_fred_native_source


class FredNativeReviewTests(unittest.TestCase):
    def sample(self):
        data=b'observation_date,UNRATE\n2026-08-01,4.1\n2026-09-01,4.2\n'
        return data,{'series_code':'UNRATE','source_url':'https://fred.stlouisfed.org/graph/fredgraph.csv?id=UNRATE',
            'certificate_or_proxy_override':False,'account_login_used':False,'access_mode':'native_public_fred_csv_endpoint',
            'bytes':len(data),'raw_sha256':hashlib.sha256(data).hexdigest(),'frequency_excerpt':'Monthly','units_excerpt':'Percent, Seasonally Adjusted'}

    def test_valid_raw_source_returns_original_monthly_dates(self):
        data,receipt=self.sample();rows=validate_fred_native_source(receipt,data,METADATA['UNRATE'])
        self.assertEqual(rows[-1],{'period':'2026-09-01','value':4.2})

    def test_hash_unit_frequency_identity_and_transformation_are_required(self):
        data,receipt=self.sample()
        mutations=[('raw_sha256','0'*64),('bytes',1),('units_excerpt','Billions of Dollars'),
            ('frequency_excerpt','Quarterly'),('certificate_or_proxy_override',True),('account_login_used',True),
            ('source_url',receipt['source_url']+'&transformation=pc1'),('source_url',receipt['source_url'].replace('UNRATE','U6RATE')),
            ('source_url',receipt['source_url'].replace('https:','http:'))]
        for field,value in mutations:
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):
                validate_fred_native_source({**receipt,field:value},data,METADATA['UNRATE'])

    def test_only_known_rate_and_housing_aliases_are_accepted(self):
        self.assertTrue(fred_unit_matches('JTSQUR','%','Rate, Seasonally Adjusted'))
        self.assertFalse(fred_unit_matches('UNRATE','%','Rate'))
        self.assertTrue(fred_unit_matches('HSN1F','千套','Thousands, Seasonally Adjusted Annual Rate'))
        self.assertFalse(fred_unit_matches('HOUST','千套','Thousands of Persons'))

    def test_chained_and_explicit_index_bases_are_not_silently_rebased(self):
        self.assertTrue(fred_unit_matches('GDPC1','十亿美元','Billions of Chained 2017 Dollars'))
        self.assertFalse(fred_unit_matches('GDPC1','十亿美元','Billions of Chained 2022 Dollars'))
        self.assertFalse(fred_unit_matches('QUSR628BIS','指数','Index 2020=100'))

    def test_native_ui_frequency_can_corroborate_preflight_metadata(self):
        data,receipt=self.sample();del receipt['frequency_excerpt'];receipt['source_url']+='&fq=Monthly&fml=a&transformation=lin'
        self.assertEqual(len(validate_fred_native_source(receipt,data,METADATA['UNRATE'])),2)


if __name__=='__main__':unittest.main()
