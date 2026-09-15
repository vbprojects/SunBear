"""Optional independent grammar checks; no dependency required by the library.

PYTHONPATH=src uv run --no-project --with rdflib python -m unittest discover -s tests
"""

import importlib.util
import unittest
from sunbear import f, graph as g, targets


@unittest.skipUnless(
    importlib.util.find_spec("rdflib"), "optional RDFLib parser is not installed"
)
class RDFGrammarTests(unittest.TestCase):
    def test_independent_rdf_and_sparql_parsers(self):
        import rdflib
        from rdflib.plugins.sparql.parser import parseUpdate

        mapping = g.Mapping("https://example.org/").node(
            g.ref("post", f.id), kind="Post", text=f.text, number=1, flag=True
        )
        rows = [{"id": "a /雪", "text": 'hello\n"quote"\\line\t☃'}]
        text = "".join(b.text for b in mapping.compile(targets.rdf()).stream(rows))
        parsed = rdflib.Graph().parse(data=text, format="nt")
        self.assertEqual(len(parsed), 4)
        self.assertIn(rdflib.Literal(rows[0]["text"]), list(parsed.objects()))
        mapping = mapping.triple(
            g.ref("post", f.id), "link", g.ref("post", "other"), graph=g.iri("urn:g")
        )
        text = "".join(
            b.text for b in mapping.compile(targets.rdf("nquads")).stream(rows)
        )
        self.assertEqual(len(rdflib.Dataset().parse(data=text, format="nquads")), 5)
        update = "".join(
            b.text for b in mapping.compile(targets.rdf("sparql")).stream(rows)
        )
        parseUpdate(update)

    def test_attributed_relationship_reification(self):
        import rdflib

        mapping = g.Mapping("urn:").relationship(
            g.ref("relationship", "r1"),
            g.iri("urn:s"),
            "p",
            g.iri("urn:o"),
            confidence=0.8,
        )
        output = "".join(b.text for b in mapping.compile(targets.rdf()).stream([{}]))
        parsed = rdflib.Graph().parse(data=output, format="nt")
        self.assertEqual(len(parsed), 5)
        self.assertNotIn(
            (rdflib.URIRef("urn:s"), rdflib.URIRef("urn:p"), rdflib.URIRef("urn:o")),
            parsed,
        )
