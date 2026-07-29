from app.db.vector import to_pgvector


def test_to_pgvector_uses_stable_compact_float_format():
    assert to_pgvector([1, 1 / 3, -0.0]) == "[1,0.3333333333,-0]"
