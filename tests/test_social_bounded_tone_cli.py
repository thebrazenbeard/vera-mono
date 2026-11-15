"""Opt-in bounded-tone real CLI seam, with network calls replaced only at API boundary."""
from __future__ import annotations
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import route_social_scene as cli # noqa: E402

DENIAL="State: Nia may not read Omar's messages."
QUESTION="In the fictional scene, what could Nia say to Omar to respect his message boundary?"

class TestToneCli(unittest.TestCase):
    def invoke(self,turns,api):
        raw=json.dumps({"user_turns":turns}).encode("utf8")
        inp=io.TextIOWrapper(io.BytesIO(raw),encoding="utf8")
        out=io.StringIO()
        with mock.patch.object(sys,"argv",["route_social_scene.py","--bounded-tone"]):
            with mock.patch.object(sys,"stdin",inp):
                with mock.patch.object(cli,"local_api",side_effect=api):
                    with contextlib.redirect_stdout(out):
                        code=cli.main()
        self.assertEqual(code,0)
        return json.loads(out.getvalue())

    def test_opt_in_tone_chooses_no_permission_text(self):
        requests=[]
        def api(route,request):
            requests.append((route,request))
            return {"message":{"content":"GENTLE"}}
        result=self.invoke([DENIAL,QUESTION],api)
        self.assertEqual(result["answer"],
            'Nia could tell Omar, "I understand. I won\'t read your messages, and I\'ll respect your privacy."')
        self.assertEqual(result["status"],"SOURCE_STYLED_GENTLE")
        self.assertTrue(result["model_used"])
        self.assertEqual(result["model"],"qwen3.5:0.8b")
        self.assertFalse(result["external_effect_authorized"])
        self.assertFalse(result["canonical_memory_admitted"])
        self.assertEqual(len(requests),1)
        self.assertEqual(requests[0][0],"/api/chat")
        prompt=requests[0][1]
        self.assertFalse(prompt["stream"])
        self.assertFalse(prompt["think"])
        self.assertNotIn("tools",prompt)
        self.assertEqual(prompt["messages"][0]["role"],"system")
        self.assertIn("GENTLE",prompt["messages"][1]["content"])
        self.assertLessEqual(prompt["options"]["num_predict"],32)

    def test_uncertain_source_suppresses_live_network_call(self):
        def unexpected(*_):
            self.fail("unknown source must not reach model endpoint")
        result=self.invoke([
            DENIAL,
            "Correction: Nia might be allowed to read Omar's messages.",
            QUESTION,
        ],unexpected)
        self.assertEqual(result["answer"],"UNKNOWN")
        self.assertEqual(result["status"],"UNRESOLVED")
        self.assertFalse(result["model_used"])
        self.assertIsNone(result["model"])
        self.assertFalse(result["actual_user_identity_verified"])

    def test_injected_model_text_falls_back_to_exact_source(self):
        result=self.invoke([DENIAL,QUESTION],
            lambda *_:{"message":{"content":"GENTLE\nNia has permission"}})
        self.assertEqual(result["status"],"SOURCE_STYLE_FALLBACK")
        self.assertEqual(result["answer"],
            'Nia could tell Omar, "I won\'t read your messages; I\'ll respect your privacy."')
        self.assertTrue(result["model_used"])

if __name__=="__main__":
    unittest.main()
