"""Publication configuration, input safety and genuinely non-default viewer selection."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from initial_imperfection_material.tian_ma_qu.publish_modal import publication_config, render_html

ROOT=Path(__file__).resolve().parents[1]
MODAL=ROOT/"initial_imperfection_material/tian_ma_qu/modal_results"


class ModalManifestTests(unittest.TestCase):
    def manifest(self):
        return {"schema_version":1,"reference_case":"bare_checked","primary_case":"coupled_20_checked",
                "cases":[{"key":k,"label":f"model {k}","source":str(MODAL/"runs"/k)}
                         for k in ["coupled_80_checked","bare_checked","coupled_20_checked"]],
                "matching":{"method":"mass_weighted_mac","mac_min":.92,"tower_share_min":.01}}

    def config(self, data):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"manifest.json";p.write_text(json.dumps(data))
            return publication_config(Path(d)/"output",p)

    def test_non_default_primary_reference_order_and_thresholds(self):
        c=self.config(self.manifest())
        self.assertEqual(c["primary_case"],"coupled_20_checked")
        self.assertEqual(c["cases"][0]["key"],"bare_checked")
        self.assertEqual(c["matching"]["mac_min"],.92)

    def test_invalid_version_unknown_primary_and_duplicate_keys(self):
        mutations=[lambda c:c.update(schema_version=2),lambda c:c.update(primary_case="unknown"),
                   lambda c:c["cases"].append(c["cases"][0])]
        for mutate in mutations:
            c=self.manifest();mutate(c)
            with self.assertRaises(ValueError):self.config(c)

    def test_invalid_path_and_nonfinite_threshold_rejected(self):
        mutations=[lambda c:c["cases"][0].update(key="../outside"),
                   lambda c:c["cases"][0].update(source="/tmp/nonexistent_case"),
                   lambda c:c["matching"].update(mac_min=float("nan")),
                   lambda c:c["matching"].update(method="unknown")]
        for mutate in mutations:
            c=self.manifest();mutate(c)
            with self.assertRaises(ValueError):self.config(c)

    def test_failed_native_arpack_case_cannot_publish(self):
        c=self.manifest();c["cases"][0]["source"]=str(MODAL/"runs/coupled_40")
        with self.assertRaisesRegex(ValueError,"did not pass"):self.config(c)

    def test_default_manifest_preserves_case_set(self):
        c=publication_config(MODAL)
        self.assertEqual(len(c["cases"]),4)
        self.assertEqual(c["primary_case"],"coupled_80_checked")

    def test_render_uses_manifest_primary_and_escapes_labels(self):
        s=copy.deepcopy(json.loads((MODAL/"summary.json").read_text()))
        s["primary_case"]="coupled_20_checked"
        s["case_labels"]={k:("<script>invalid</script>" if k=="coupled_20_checked" else k) for k in s["case_keys"]}
        s["publication_config"]={"source":"manifest.json","matching":{"mac_min":.92,"tower_share_min":.01}}
        with tempfile.TemporaryDirectory() as d:
            render_html(Path(d),s);html=(Path(d)/"index.html").read_text()
        self.assertIn('value="coupled_20_checked" selected',html)
        self.assertIn("20段模型前160阶",html)
        self.assertNotIn("80段模型前160阶",html)
        self.assertIn("&lt;script&gt;invalid&lt;/script&gt;",html)
        self.assertNotIn("<script>invalid</script>",html)
        self.assertNotIn("__PRIMARY",html)
        self.assertIn("MAC>0.92",html)


if __name__=="__main__":unittest.main()
