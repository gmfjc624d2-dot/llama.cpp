import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("ccc", os.path.join(HERE, "..", "scripts", "check_casefold_collisions.py"))
ccc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ccc)


class CasefoldTest(unittest.TestCase):
    def test_leaf_names(self):
        self.assertEqual(list(ccc.collisions(["d/L__x.log", "d/l__x.log"]).values()), [["d/L__x.log", "d/l__x.log"]])

    def test_directory_component(self):
        c = ccc.collisions(["Evidence/a.log", "evidence/b.log"])
        self.assertEqual(list(c.values()), [["Evidence", "evidence"]])

    def test_file_vs_directory(self):
        self.assertEqual(len(ccc.collisions(["x/README", "X"])), 1)

    def test_unicode_normalization(self):
        self.assertEqual(len(ccc.collisions(["café.log", "café.log"])), 1)

    def test_no_collision(self):
        self.assertEqual(ccc.collisions(["dependencies__x.log", "loadcommands__x.log", "a/b", "a/c"]), {})


if __name__ == "__main__":
    unittest.main()
