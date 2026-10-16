"""Checkpoint summaries must reject partial or non-fill-only evidence."""
import copy
import unittest

from scripts.freeze_provincial_fiscal_checkpoint import parse_test_summary, verify_receipts


class ProvincialFiscalCheckpointTests(unittest.TestCase):
    def receipts(self):
        old={'id':1,'value':100,'source_url':'https://example.gov.cn/old','updated_at':'unchanged'}
        applied={'phase':'applied_readback_verified','exact_value_readback':True,'protected_rows_unchanged':True,
                 'import':{'inserted':1,'updated':0,'errors':[]},'committed_rows':1,'target_keys':2,
                 'target_rows_before':[old],'target_rows_after':[copy.deepcopy(old),{'id':2,'value':200}]}
        replay={**applied,'import':{'inserted':0,'updated':0,'errors':[]},'committed_rows':0}
        return applied,replay

    def test_verified_fill_only_and_replay(self):
        self.assertEqual(verify_receipts(*self.receipts()),(1,1))

    def test_rejects_partial_replay_updates_and_metadata_changes(self):
        for target,field,value in [('apply','phase','failed_rolled_back'),('replay','committed_rows',1),
                                   ('replay','protected_rows_unchanged',False),('apply','target_keys',3)]:
            applied,replay=self.receipts();(applied if target=='apply' else replay)[field]=value
            with self.assertRaises(ValueError):verify_receipts(applied,replay)
        applied,replay=self.receipts();applied['target_rows_after'][0]['source_url']='different'
        with self.assertRaises(ValueError):verify_receipts(applied,replay)
        applied,replay=self.receipts();applied['import']['updated']=1
        with self.assertRaises(ValueError):verify_receipts(applied,replay)

    def test_terminal_python_and_node_summaries(self):
        self.assertEqual(parse_test_summary('Ran 136 tests in 0.4s\n\nOK\n','python'),136)
        self.assertEqual(parse_test_summary('ℹ tests 9\nℹ pass 9\nℹ fail 0\n','node'),9)
        for content,kind in [('Ran 136 tests','python'),('Ran 5 tests\nFAILED','python'),
                             ('ℹ tests 9\nℹ fail 1','node'),('not ok 1\nℹ tests 9\nℹ fail 0','node')]:
            with self.assertRaises(ValueError):parse_test_summary(content,kind)


if __name__=='__main__':unittest.main()
