"""Offline example: transform once, compile for SQL, documents, RDF and Datalog.

Run: PYTHONPATH=src python examples/social_outputs.py
No files, network calls, or database connections are required.
"""

import sunbear as sb
from sunbear import f, emit, targets, graph as g, logic as l

RECORDS = [
    {"id": "p1", "author": "u1", "text": " Hello ", "reply": None, "mentions": ["p2"]},
    {"id": "p2", "author": "u2", "text": " A reply ", "reply": "p1", "mentions": []},
]


def main():
    posts = sb.Program().assign(text=f.text.str.strip())
    relational = (
        posts.select("id", "author", "text")
        .emit(
            emit.row(
                "posts",
                key="id",
                mode="upsert",
                schema={"id": "text", "author": "text", "text": "text"},
            )
        )
        .compile(targets.sql("sqlite"))
    )
    documents = posts.emit(emit.document("posts", key=f.id, mode="replace")).compile(
        targets.elasticsearch()
    )

    post = g.ref("post", f.id)
    social = (
        g.Mapping("https://example.org/social/")
        .node(post, kind="Post", text=f.text)
        .edge(post, "authored_by", g.ref("user", f.author))
        .edge(post, "replies_to", g.ref("post", f.reply), when=f.reply.is_not_null())
        .edges(post, "mentions", g.ref("post", f.mentions))
    )
    triples = social.emit(posts).compile(targets.rdf())

    replies = l.relation("replies", source="symbol", target="symbol")
    logic = (
        l.Program()
        .facts(replies(f.id, f.reply), when=f.reply.is_not_null())
        .output(replies)
    )
    facts = logic.emit(posts).compile(targets.datalog())

    for label, job in [
        ("SQL", relational),
        ("Elasticsearch", documents),
        ("RDF", triples),
        ("Datalog", facts),
    ]:
        print(label)
        for artifact in job.artifacts():
            print(artifact.destination, artifact.text, sep="\n")
        for batch in job.stream(RECORDS, batch_rows=3):
            print(batch.destination, batch.text or batch.payload, sep="\n")


if __name__ == "__main__":
    main()
