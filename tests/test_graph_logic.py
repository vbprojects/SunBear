"""Graph identity, RDF grammar, and typed Datalog compilation contracts."""

import unittest
import sunbear as sb
from sunbear import f, graph as g, logic as l, targets, emit


class GraphLogicTests(unittest.TestCase):
    def test_social_graph_relationships(self):
        post = g.ref("post", f.id)
        author = g.ref("user", f.author)
        mapping = (
            g.Mapping("https://example.org/social/")
            .node(post, kind="Post", text=f.text)
            .edge(post, "authored_by", author)
            .edge(post, "reply_to", g.ref("post", f.reply), when=f.reply.is_not_null())
            .edges(post, "mentions", g.ref("post", f.mentions))
        )
        job = mapping.compile(targets.rdf())
        rows = [
            {
                "id": "p/1",
                "author": "u1",
                "text": 'Hello "world"\n雪',
                "mentions": ["p2", "p3"],
            }
        ]
        output = "".join(b.text for b in job.stream(rows, batch_rows=2))
        self.assertEqual(len(output.splitlines()), 5)
        self.assertIn("<https://example.org/social/post/s/p%2F1>", output)
        self.assertIn('"Hello \\"world\\"\\n雪"', output)
        self.assertIn("/post/s/p2>", output)
        self.assertNotIn("reply_to", output)

    def test_native_id_types_are_distinct(self):
        mapping = g.Mapping("urn:social:").node(g.ref("post", f.id), kind="Post")
        out = "".join(
            b.text
            for b in mapping.compile(targets.rdf()).stream([{"id": 1}, {"id": "1"}])
        )
        self.assertIn("post/i/1", out)
        self.assertIn("post/s/1", out)

    def test_typed_literal_language_and_missing_null(self):
        subject = g.iri("urn:subject")
        mapping = g.Mapping("urn:").node(
            subject, number=f.number, missing=f.missing, null=None, flag=True
        )
        text = next(mapping.compile(targets.rdf()).stream([{"number": 2}])).text
        self.assertIn('"2"^^<http://www.w3.org/2001/XMLSchema#integer>', text)
        self.assertIn('"true"^^<http://www.w3.org/2001/XMLSchema#boolean>', text)
        self.assertEqual(len(text.splitlines()), 2)
        localized = g.Mapping("urn:").triple(
            subject, "label", g.literal("bonjour", language="fr")
        )
        self.assertIn(
            '"bonjour"@fr', next(localized.compile(targets.rdf()).stream([{}])).text
        )
        with self.assertRaises(ValueError):
            g.literal("x", language="en; DROP")
        with self.assertRaises(emit.EmissionError):
            list(
                g.Mapping("urn:", nulls="raise")
                .node(subject, x=None)
                .compile(targets.rdf())
                .stream([{}])
            )

    def test_named_graph_and_retractions_capabilities(self):
        mapping = g.Mapping("urn:").triple(
            g.iri("urn:s"), "p", "v", graph=g.iri("urn:g")
        )
        with self.assertRaises(ValueError):
            mapping.compile(targets.rdf())
        nq = next(mapping.compile(targets.rdf("nquads")).stream([{}])).text
        self.assertEqual(nq, '<urn:s> <urn:p> "v" <urn:g> .\n')
        retract = g.Mapping("urn:").triple(
            g.iri("urn:s"), "p", "v", graph=g.iri("urn:g"), action="retract"
        )
        with self.assertRaises(ValueError):
            retract.compile(targets.rdf("nquads"))
        self.assertEqual(
            next(retract.compile(targets.rdf("sparql")).stream([{}])).text,
            'DELETE DATA { GRAPH <urn:g> { <urn:s> <urn:p> "v" . } };\n',
        )

    def test_reference_and_rdf_injection_guards(self):
        for bad in ("relative", "urn:a> . <urn:evil>", "urn:x\n"):
            with self.subTest(iri=bad), self.assertRaises(ValueError):
                g.iri(bad)
        mapping = g.Mapping("urn:").node(g.ref("post", f.id), kind="Post")
        with self.assertRaises(emit.EmissionError):
            list(mapping.compile(targets.rdf()).stream([{}]))

    def test_mapping_composes_with_transform(self):
        mapping = g.Mapping("urn:").node(g.ref("post", f.id), label=f.label)
        tree = sb.DataTree.from_records([{"id": 1, "text": "hi"}]).assign(
            label=f.text.str.upper()
        )
        self.assertIn(
            '"HI"', next(mapping.emit(tree).compile(targets.rdf()).stream()).text
        )

    def test_souffle_files_and_rule_program(self):
        edge = l.relation("edge", source="symbol", target="symbol")
        reach = l.relation("reach", source="symbol", target="symbol")
        x, y, z = l.var("X"), l.var("Y"), l.var("Z")
        mapping = (
            l.Program()
            .facts(edge(f.id, f.reply))
            .rule(reach(x, y), edge(x, y))
            .rule(reach(x, z), reach(x, y), edge(y, z))
            .output(reach)
        )
        job = mapping.compile(targets.datalog())
        setup = job.artifacts()[0].text
        self.assertIn(".decl edge(source:symbol, target:symbol)", setup)
        self.assertIn(".input edge", setup)
        self.assertIn("reach(X, Z) :- reach(X, Y), edge(Y, Z).", setup)
        self.assertIn(".output reach", setup)
        batch = next(job.stream([{"id": "p1", "reply": "p2"}]))
        self.assertEqual(batch.destination, "edge.facts")
        self.assertEqual(batch.text, "p1\tp2\n")

    def test_souffle_inline_escape(self):
        relation = l.relation("label", text="symbol")
        job = (
            l.Program()
            .facts(relation(f.text))
            .compile(targets.datalog(output="inline"))
        )
        self.assertNotIn(".input", job.artifacts()[0].text)
        self.assertEqual(
            next(job.stream([{"text": 'a"b\\c'}])).text, 'label("a\\"b\\\\c").\n'
        )

    def test_datalog_preflight_safety_arity_types(self):
        edge = l.relation("edge", source="symbol", target="symbol")
        x, y = l.var("X"), l.var("Y")
        with self.assertRaises(ValueError):
            edge(x)
        with self.assertRaises(ValueError):
            l.rule(edge(x, y), edge(x, x))
        numeric = l.relation("numeric", value="number")
        with self.assertRaises(TypeError):
            l.rule(numeric(x), edge(x, y))
        with self.assertRaises(ValueError):
            l.relation("bad); injection", x="symbol")
        with self.assertRaises(TypeError):
            l.Program().facts(edge(x, y)).compile(targets.datalog())
        with self.assertRaises(ValueError):
            targets.datalog("generic")

    def test_datalog_runtime_values_and_conflicting_declarations(self):
        r = l.relation("r", value="number")
        job = l.Program().facts(r(f.x)).compile(targets.datalog())
        for value in (None, "1", True, 2**40):
            with self.subTest(value=value), self.assertRaises(emit.EmissionError):
                list(job.stream([{"x": value}]))
        conflicting = l.relation("r", value="symbol")
        with self.assertRaises(ValueError):
            l.Program().facts(r(1)).facts(conflicting("x")).compile(targets.datalog())
        symbols = l.Program().facts(conflicting(f.x)).compile(targets.datalog())
        with self.assertRaises(emit.EmissionError):
            list(symbols.stream([{"x": "a\tb"}]))


if __name__ == "__main__":
    unittest.main()
