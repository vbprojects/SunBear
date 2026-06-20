from Record import Record

class binaryexpr:
    def __init__(self, right, left, operator):
        self.right = right
        self.left = left
        self.operator = operator

class operand:
    def __init__(self, operator, **args):
        self.operator = operator
        self.args = args

class arg:
    def __init__(self, indexand):
        self.indexer = Record._resolve_indexer(indexand)

class expr:
    def __init__(self, root):
        self.root = root
