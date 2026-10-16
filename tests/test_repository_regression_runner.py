import unittest

from scripts.run_repository_regression import test_result as parse_result


class RegressionReceiptTests(unittest.TestCase):
    def test_requires_test_count_and_explicit_success(self):
        self.assertEqual(parse_result('Ran 14 tests in 0.2s\n\nOK\n', 0)['status'], 'passed')
        self.assertEqual(parse_result('Ran 1 test in 0.2s\n\nOK (skipped=1)\n', 0)['status'], 'passed')
        self.assertEqual(parse_result('A partial quiet log\n', 0)['status'], 'failed')

    def test_timeout_and_nonzero_exit_are_not_green(self):
        text = 'Ran 14 tests in 0.2s\n\nOK\n'
        self.assertEqual(parse_result(text, 1)['status'], 'failed')
        self.assertEqual(parse_result(text, 0, True)['status'], 'timed_out')


if __name__ == '__main__':
    unittest.main()
