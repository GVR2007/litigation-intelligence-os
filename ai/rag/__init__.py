"""
ai.rag — Hybrid RAG pipeline for Income Tax litigation evidence retrieval.

Entry point:
    from ai.rag.pipeline import RAGPipeline
    strategy = RAGPipeline().build(query)

Section graph:
    from ai.rag.section_graph import expand, get_context_note

Legacy flat-module compatibility (ai/rag.py is shadowed by this package):
    from ai.rag import build_citation_context, inject_into_prompt
"""

import importlib.util
import os as _os

# Load the shadowed ai/rag.py as a standalone module so legacy imports work.
_rag_py = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "rag.py")
_spec = importlib.util.spec_from_file_location("ai._rag_legacy", _rag_py)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

get_citations_for_sections = _mod.get_citations_for_sections
build_citation_context      = _mod.build_citation_context
inject_into_prompt          = _mod.inject_into_prompt
call_with_routing           = _mod.call_with_routing
get_citation_stats          = _mod.get_citation_stats
