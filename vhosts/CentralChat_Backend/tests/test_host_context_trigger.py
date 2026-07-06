import unittest

from app.host_context_trigger import normalize_text_for_trigger, should_inject_host_context_from_text


class TestHostContextTrigger(unittest.TestCase):
    def test_normalize_strips_accents(self) -> None:
        self.assertIn("memoria", normalize_text_for_trigger("Memória"))

    def test_cpu_usage_pt(self) -> None:
        self.assertTrue(should_inject_host_context_from_text("Qual o uso de CPU agora?"))

    def test_ram_question(self) -> None:
        self.assertTrue(should_inject_host_context_from_text("Quanto de RAM está livre no sistema?"))

    def test_process_count(self) -> None:
        self.assertTrue(should_inject_host_context_from_text("Quantos processos estão rodando?"))

    def test_chitchat_no_trigger(self) -> None:
        self.assertFalse(should_inject_host_context_from_text("Conta uma piada curta."))

    def test_cpu_word_only_no_trigger(self) -> None:
        self.assertFalse(should_inject_host_context_from_text("CPU"))

    def test_short_text_no_trigger(self) -> None:
        self.assertFalse(should_inject_host_context_from_text("oi cpu"))


if __name__ == "__main__":
    unittest.main()
