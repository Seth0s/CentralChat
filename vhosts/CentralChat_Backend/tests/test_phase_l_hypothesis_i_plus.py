"""
I+ — property-based (Hypothesis) sobre parse e validação de tools (sem rede).

Requer: pip install -r requirements-dev.txt (hypothesis).
"""
from __future__ import annotations

import json
import unittest

from app.tool_loop import parse_agent_tool_response
from app.tool_registry import list_registered_tool_names, validate_tool_arguments

try:
    from hypothesis import HealthCheck, given, settings
    from hypothesis import strategies as st

    _HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover - CI instala requirements-dev
    _HAS_HYPOTHESIS = False

if _HAS_HYPOTHESIS:
    _H_SETTINGS = settings(
        max_examples=60,
        deadline=None,
        suppress_health_check=(HealthCheck.filter_too_much,),
    )

    @unittest.skipUnless(_HAS_HYPOTHESIS, "Instala hypothesis: pip install -r requirements-dev.txt")
    class TestHypothesisParseEnvelope(unittest.TestCase):
        """Qualquer texto UTF-8 em `final` dentro de envelope JSON válido deve parsear sem excepção."""

        @_H_SETTINGS
        @given(st.text(min_size=0, max_size=400))
        def test_final_text_roundtrip_never_raises(self, final_text: str) -> None:
            raw = json.dumps({"final": final_text, "tool_calls": []}, ensure_ascii=False)
            try:
                f, calls, ok = parse_agent_tool_response(raw)
            except Exception as exc:  # pragma: no cover
                self.fail(f"parse raised: {exc!r}")
            self.assertTrue(ok)
            self.assertEqual(calls, [])
            exp = final_text.strip() or None
            self.assertEqual(f, exp)

    @unittest.skipUnless(_HAS_HYPOTHESIS, "Instala hypothesis: pip install -r requirements-dev.txt")
    class TestHypothesisValidateToolArguments(unittest.TestCase):
        """validate_tool_arguments nunca levanta; devolve None ou str curta."""

        @_H_SETTINGS
        @given(
            st.sampled_from(list_registered_tool_names()),
            st.dictionaries(
                keys=st.text(
                    min_size=0, max_size=40, alphabet="abcdefghijklmnopqrstuvwxyz0123459_"
                ),
                values=st.one_of(
                    st.none(), st.booleans(), st.integers(-10_000, 10_000), st.text(max_size=30)
                ),
                max_size=8,
            ),
        )
        def test_registered_names_random_dicts_never_raise(self, name: str, args: dict) -> None:
            try:
                err = validate_tool_arguments(name, args)
            except Exception as exc:  # pragma: no cover
                self.fail(f"validate_tool_arguments raised: {exc!r}")
            self.assertTrue(err is None or isinstance(err, str), repr(err))


class TestValidateToolArgumentsUnknownName(unittest.TestCase):
    """Sem Hypothesis — regressão rápida para nome desconhecido."""

    def test_unknown_name_returns_string(self) -> None:
        err = validate_tool_arguments("definitely_not_a_central_tool_xyz", {"x": 1})
        self.assertIsInstance(err, str)
        self.assertTrue(err)


if __name__ == "__main__":
    unittest.main()
