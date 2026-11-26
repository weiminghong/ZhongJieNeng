from pathlib import Path
import re
import unittest
from tests import test_learning as fixtures
from cecep_console import learning as ml, research_views


class BusinessPresentationTests(unittest.TestCase):
    def test_frontend_has_no_disclosure_tables_or_raw_debug_views(self):
        frontend=Path(__file__).resolve().parents[1]/"apps/web/src"
        for file in frontend.glob("*.tsx"):
            text=file.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"<(details|summary|pre|code)\b",text),file.name)
            self.assertIsNone(re.search(r">\s*\{\s*[\w?.]+\.(source_hash|weights_hash|dataset_id|model_version_id|feedback_id)\s*\}",text),file.name)
            self.assertIsNone(re.search(r">\s*\{\s*(llmMode|\w+\.llm_mode)\s*\}",text),file.name)
        self.assertNotIn("/api/v1/research/schema",(frontend/"DataFlow.tsx").read_text(encoding="utf-8"))

    def test_display_names_are_stable_and_do_not_change_stored_evidence(self):
        f=fixtures.LearningTests();f.setUp()
        try:
            _, ids=f.trained()
            before=[tuple(r) for r in f.store.db.execute("SELECT * FROM ml_object ORDER BY rowid")]
            one=ml.get_object(f.store,ids[0]);self.assertEqual(one["display_name"],"电价预测模型（第1版）")
            p=ml.prediction(f.store,ids[0],"2024-02-26")
            records=research_views.prediction_list(f.store)
            self.assertEqual(records[0]["model_name"],one["display_name"])
            self.assertEqual(records[0]["display_name"],"预测记录（第1次）")
            ml.add_object(f.store,"analysis",{"note":"generated display test"},f.sha,p["id"]);f.store.db.commit()
            self.assertEqual(ml.get_object(f.store,ids[0])["display_name"],one["display_name"])
            for row in before:
                self.assertEqual(tuple(f.store.db.execute("SELECT * FROM ml_object WHERE object_id=?",(row[0],)).fetchone()),row)
        finally:f.tearDown()


if __name__=="__main__":unittest.main()
