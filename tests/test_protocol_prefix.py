import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from initial_imperfection_material.export_protocol_prefix import export_prefix


class ProtocolPrefixTests(unittest.TestCase):
    def fixture(self,root):
        source=root/'parent'
        source.mkdir()
        manifest={'status':'running','run_id':'parent-id','parameters':{'targets':[.001,-.001]}}
        (source/'run_manifest.json').write_text(json.dumps(manifest))
        rows=[]
        for stage,p,step in [('initial',0,0),('gravity',.5,1),('gravity',1,2),
                             ('target_1_+0.001000',0,0),('target_1_+0.001000',1,8),
                             ('target_2_-0.001000',0,8),('target_2_-0.001000',.4,12)]:
            rows.append({'committed':True,'stage_id':stage,'stage_progress':p,
                         'source_step':step,'accepted_step':len(rows)})
        history=source/'member_states.jsonl'
        history.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        history.with_suffix('.metadata.json').write_text('{}')
        return history

    def test_complete_prefix_does_not_reclassify_incomplete_parent(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            history=self.fixture(root)
            before=hashlib.sha256(history.read_bytes()).hexdigest()
            report=export_prefix(history,root/'prefix',1)
            self.assertEqual(report['rows'],5)
            self.assertEqual(json.loads(history.with_name('run_manifest.json').read_text())['status'],'running')
            result=json.loads((root/'prefix/run_manifest.json').read_text())
            self.assertEqual(result['status'],'completed')
            self.assertEqual(result['parameters']['targets'],[.001])
            self.assertEqual(result['parameters']['prefix_scope']['source_requested_target_count'],2)
            self.assertFalse(result['eligible_for_fragility'])
            self.assertEqual(hashlib.sha256(history.read_bytes()).hexdigest(),before)

    def test_unfinished_requested_prefix_is_rejected_without_output(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            history=self.fixture(root)
            with self.assertRaisesRegex(ValueError,'not completely committed'):
                export_prefix(history,root/'prefix',2)
            self.assertFalse((root/'prefix').exists())

    def test_missing_gravity_and_noncommitted_rows_are_rejected(self):
        for change in ('gravity','trial'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as td:
                root=Path(td)
                history=self.fixture(root)
                rows=[json.loads(line) for line in history.read_text().splitlines()]
                if change=='gravity': rows=[r for r in rows if r['stage_id']!='gravity']
                else: rows[1]['committed']=False
                history.write_text(''.join(json.dumps(r)+'\n' for r in rows))
                with self.assertRaises(ValueError): export_prefix(history,root/'prefix',1)


if __name__=='__main__':unittest.main()
