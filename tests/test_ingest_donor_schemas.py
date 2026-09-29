import json
import tempfile
import unittest
from pathlib import Path

from ingest import FileSystemStore, Ingestor, TextSource


ROOT = Path(__file__).resolve().parents[1] / "packages" / "vera_ingest" / "src" / "ingest" / "resources"


class SchemaSurfaceTests(unittest.TestCase):
    def test_schema_contracts_and_emitted_shapes_agree_on_required_keys(self):
        record_schema = json.loads((ROOT / "schemas/ingest-record-v1.schema.json").read_text())
        receipt_schema = json.loads((ROOT / "schemas/ingest-stage-receipt-v1.schema.json").read_text())
        with tempfile.TemporaryDirectory() as tmp:
            store = FileSystemStore(Path(tmp) / ".ingest")
            result = Ingestor(store).ingest(TextSource("schema", locator="urn:schema"))
            record = store.get_record(result.ingest_id)
            receipt = store.get_receipt(result.receipt_ids[0])
        self.assertEqual(record_schema["$id"], record["schema"])
        self.assertEqual(receipt_schema["$id"], receipt["schema"])
        self.assertTrue(set(record_schema["required"]).issubset(record))
        self.assertTrue(set(receipt_schema["required"]).issubset(receipt))


if __name__ == "__main__":
    unittest.main()
