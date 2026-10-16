"""Publisher years come from the actual issue, never the blog/upload timestamp."""

import unittest

from scripts.reconcile_thomson_contents_headers import assess_header


class PrintedYearTests(unittest.TestCase):
    def test_printed_issue_year_and_footer_agree(self):
        status, evidence = assess_header(['AUSTRALIAN TAX REVIEW', 'Volume 48, Number 3', '2019'],
            '(2019) 48 AT Rev 159', 'Australian Tax Review', 48, '3')
        self.assertEqual('HEADER_AND_CITATION_RECONCILED', status)
        self.assertEqual(2019, evidence['header_year'])

    def test_copied_conflicting_citation_is_reviewed(self):
        status, _ = assess_header(['AUSTRALIAN TAX REVIEW', 'Volume 48, Number 3', '2020'],
            '(2019) 48 AT Rev 159', 'Australian Tax Review', 48, '3')
        self.assertEqual('REVIEW_HEADER_CITATION_CONFLICT', status)

    def test_wrong_linked_part_is_reviewed(self):
        status, _ = assess_header(['Volume 48, Number 2', '2019'], '(2019) 48 AT Rev 159',
                                 'Australian Tax Review', 48, '3')
        self.assertEqual('REVIEW_POST_PDF_ISSUE_CONFLICT', status)

    def test_uppercase_footer_still_proves_the_actual_printed_year(self):
        status, evidence = assess_header(['INSOLVENCY LAW JOURNAL', 'Volume 22, Number 4', 'December 2014'],
            '(2014) 22 INSOLVLJ 165', 'Insolvency Law Journal', 22, '4')
        self.assertEqual('HEADER_AND_CITATION_RECONCILED', status)
        self.assertEqual(2014, evidence['header_year'])
