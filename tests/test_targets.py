"""Execute generated SQLite and verify portable output envelopes and limits."""

import itertools
import json
import sqlite3
import unittest
import sunbear as sb
from sunbear import f, emit, targets


class TargetTests(unittest.TestCase):
    def tree(self, rows):
        return sb.DataTree.from_records(rows)

    def test_sqlite_script_roundtrip_upsert_delete(self):
        schema = {"id": "integer", "title": "text", "tags": "json", "active": "boolean"}
        job = (
            sb.Program()
            .emit(emit.row('po"sts', key="id", mode="upsert", schema=schema))
            .compile(targets.sql("sqlite"))
        )
        con = sqlite3.connect(":memory:")
        for artifact in job.artifacts():
            con.executescript(artifact.text)
        rows = [
            {
                "id": 1,
                "title": "quote'; DROP TABLE posts; --\nü\\",
                "tags": ["a", None],
                "active": True,
            },
            {"id": 1, "title": "updated", "tags": [], "active": False},
            {"id": 2, "title": None, "tags": {}, "active": True},
        ]
        for batch in job.stream(iter(rows), batch_rows=1):
            con.executescript(batch.text)
        self.assertEqual(
            con.execute(
                'select id,title,tags,active from "po""sts" order by id'
            ).fetchall(),
            [(1, "updated", "[]", 0), (2, None, "{}", 1)],
        )
        delete = (
            self.tree([{"id": 2}])
            .emit(emit.row('po"sts', key="id", mode="delete"))
            .compile(targets.sql("sqlite"))
        )
        for batch in delete.stream():
            con.executescript(batch.text)
        self.assertEqual(con.execute('select count(*) from "po""sts"').fetchone()[0], 1)

    def test_sqlite_parameters_roundtrip(self):
        con = sqlite3.connect(":memory:")
        con.execute("create table posts (id integer primary key, text text)")
        rows = [{"id": 1, "text": "x'\n雪"}, {"id": 2, "text": "y"}]
        job = (
            self.tree(rows)
            .emit(emit.row("posts"))
            .compile(targets.sql("sqlite", output="parameters"))
        )
        for batch in job.stream():
            self.assertNotIn("雪", batch.text)
            for sql, params in batch.statements:
                con.execute(sql, params)
        self.assertEqual(
            con.execute("select * from posts").fetchall(), [(1, "x'\n雪"), (2, "y")]
        )

    def test_postgres_literals_and_parameter_styles(self):
        tree = self.tree([{"x": "a'\\b"}])
        script = next(tree.emit(emit.row("t")).compile(targets.sql()).stream()).text
        self.assertEqual(script, "INSERT INTO \"t\" (\"x\") VALUES (E'a''\\\\b');\n")
        for style, placeholder in [("numeric", "$1"), ("format", "%s")]:
            batch = next(
                tree.emit(emit.row("t"))
                .compile(targets.sql(output="parameters", parameter_style=style))
                .stream()
            )
            self.assertIn(placeholder, batch.text)
            self.assertEqual(batch.statements[0][1], ("a'\\b",))

    def test_format_parameters_escape_identifier_percent(self):
        batch = next(
            self.tree([{"%s": "data"}])
            .emit(emit.row("table%s"))
            .compile(targets.sql(output="parameters", parameter_style="format"))
            .stream()
        )
        self.assertEqual(batch.text, 'INSERT INTO "table%%s" ("%%s") VALUES (%s);\n')

    def test_static_preflight_never_reads_source(self):
        seen = []

        def rows():
            seen.append(True)
            yield {"id": 1}

        tree = sb.DataTree.from_iter(rows())
        with self.assertRaises(TypeError):
            tree.emit(emit.document("x")).compile(targets.sql())
        with self.assertRaises(ValueError):
            targets.sql("mysql")
        with self.assertRaises(ValueError):
            emit.row("x", mode="upsert")
        with self.assertRaises(ValueError):
            tree.emit(emit.row("x", schema={"id": "raw SQL"})).compile(targets.sql())
        self.assertEqual(seen, [])

    def test_sql_schema_freezes_per_stream(self):
        job = sb.Program().emit(emit.row("t")).compile(targets.sql("sqlite"))
        with self.assertRaisesRegex(emit.EmissionError, "frozen schema"):
            list(job.stream([{"x": 1}, {"y": 2}]))
        # New sessions have an independent first-row schema.
        self.assertIn('"y"', next(job.stream([{"y": 2}])).text)
        with self.assertRaises(emit.EmissionError):
            list(job.stream([{"x": {"nested": 1}}]))

    def test_declared_types_missing_and_null(self):
        job = (
            sb.Program()
            .emit(emit.row("t", schema={"id": "integer", "x": "text"}))
            .compile(targets.sql("sqlite"))
        )
        for row in (
            {"id": 1},
            {"id": "oops", "x": None},
            {"id": 1, "x": "a", "extra": 2},
        ):
            with self.subTest(row=row), self.assertRaises(emit.EmissionError):
                list(job.stream([row]))
        self.assertIn("NULL", next(job.stream([{"id": 1, "x": None}])).text)

    def test_elasticsearch_wire_format(self):
        row = {"id": "p1", "text": "a\nb"}
        for mode, action in [
            ("insert", "create"),
            ("replace", "index"),
            ("update", "update"),
            ("delete", "delete"),
        ]:
            job = (
                self.tree([row])
                .emit(emit.document("posts", key=f.id, mode=mode))
                .compile(targets.elasticsearch())
            )
            batch = next(job.stream())
            self.assertTrue(batch.text.endswith("\n"))
            lines = [json.loads(line) for line in batch.text.splitlines()]
            self.assertEqual(lines[0], {action: {"_index": "posts", "_id": "p1"}})
            if mode == "delete":
                self.assertEqual(len(lines), 1)
            else:
                self.assertEqual(lines[1], {"doc": row} if mode == "update" else row)

    def test_mongodb_commands_preserve_order_and_data(self):
        tree = self.tree([{"id": "p1", "text": "hello"}])
        for mode in ("insert", "replace", "update", "delete"):
            batch = next(
                tree.emit(emit.document("posts", key=f.id, mode=mode))
                .compile(targets.mongodb())
                .stream()
            )
            command = batch.payload
            self.assertTrue(command["ordered"])
            if mode == "insert":
                self.assertEqual(command["documents"][0]["_id"], "p1")
            elif mode == "delete":
                self.assertEqual(command["deletes"], [{"q": {"_id": "p1"}, "limit": 1}])
            else:
                update = command["updates"][0]
                self.assertEqual(update["q"], {"_id": "p1"})
                self.assertEqual(update["upsert"], mode == "replace")
                self.assertEqual(
                    update["u"],
                    {"$set": {"id": "p1", "text": "hello"}}
                    if mode == "update"
                    else {"id": "p1", "text": "hello"},
                )
        declarations = [
            emit.document("posts", key=f.id, mode=mode)
            for mode in ("insert", "delete", "replace")
        ]
        batches = list(tree.emit(*declarations).compile(targets.mongodb()).stream())
        self.assertEqual(
            [next(iter(b.payload)) for b in batches], ["insert", "delete", "update"]
        )

    def test_document_identity_guards(self):
        for target in (targets.elasticsearch(), targets.mongodb()):
            with self.assertRaises(emit.EmissionError):
                list(
                    self.tree([{}])
                    .emit(emit.document("posts", key=f.id, mode="delete"))
                    .compile(target)
                    .stream()
                )
        with self.assertRaises(emit.EmissionError):
            list(
                self.tree([{"id": "1", "_id": "2"}])
                .emit(emit.document("posts", key=f.id))
                .compile(targets.mongodb())
                .stream()
            )

    def test_kusto_setup_separate_from_payload(self):
        target = targets.kusto(schema={"id": "long", "data": "dynamic"})
        job = (
            self.tree([{"id": 1, "data": {"tags": ["x"]}}])
            .emit(emit.document("posts"))
            .compile(target)
        )
        setup = job.artifacts()[0].text
        self.assertIn(".create table posts (id:long, data:dynamic)", setup)
        self.assertIn("ingestion json mapping", setup)
        self.assertNotIn(".ingest inline", setup)
        self.assertEqual(
            json.loads(next(job.stream()).text), {"id": 1, "data": {"tags": ["x"]}}
        )
        with self.assertRaises(TypeError):
            self.tree([]).emit(emit.document("posts", key=f.id, mode="delete")).compile(
                target
            )

    def test_utf8_batch_limits_and_backpressure(self):
        seen = []

        def rows():
            for i in itertools.count():
                seen.append(i)
                yield {"id": i, "text": "雪" * 10}

        job = sb.Program().emit(emit.document("posts")).compile(targets.jsonl())
        stream = job.stream(rows(), batch_rows=3, batch_bytes=180)
        batch = next(stream)
        self.assertLessEqual(batch.operation_count, 3)
        self.assertLessEqual(batch.byte_size, 180)
        self.assertLessEqual(len(seen), 4)
        stream.close()
        finite = list(
            job.stream(
                [{"id": i, "text": "雪" * 10} for i in range(20)],
                batch_rows=3,
                batch_bytes=180,
            )
        )
        self.assertEqual(sum(b.operation_count for b in finite), 20)
        self.assertTrue(
            all(b.byte_size <= 180 and b.operation_count <= 3 for b in finite)
        )

    def test_single_large_operation_fails_contextually(self):
        job = (
            self.tree([{"text": "large"}])
            .emit(emit.document("posts"))
            .compile(targets.jsonl())
        )
        with self.assertRaises(emit.EmissionError) as error:
            list(job.stream(batch_bytes=1))
        self.assertEqual(error.exception.row, 0)
        self.assertEqual(error.exception.destination, "posts")

    def test_source_tokens_preserved_without_ack_claim(self):
        tree = sb.DataTree.from_records([{"id": 1}, {"id": 1}])
        batches = list(
            tree.emit(emit.row("posts"))
            .compile(targets.jsonl())
            .stream(source_token=lambda meta: meta["i"])
        )
        self.assertEqual(batches[0].source_tokens, (0, 1))
        self.assertEqual(batches[0].operation_count, 2)

    def test_custom_target_protocol(self):
        class Custom:
            def validate(self, declarations):
                pass

            def artifacts(self, declarations):
                return []

            def session(self):
                return self

            def encode(self, operations):
                return emit.Batch(
                    "custom", "text/plain", len(operations), text="x" * len(operations)
                )

        job = self.tree([{}, {}]).emit(emit.document("posts")).compile(Custom())
        self.assertEqual(next(job.stream()).text, "xx")


if __name__ == "__main__":
    unittest.main()
