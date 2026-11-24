import importlib.util
import sys
import unittest
spec = importlib.util.spec_from_file_location('app.main', '/tmp/main_fixed.py')
module = importlib.util.module_from_spec(spec)
sys.modules['app.main'] = module
spec.loader.exec_module(module)
sys.path.insert(0, '/tmp')
result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromName('test_join_lifecycle'))
sys.exit(not result.wasSuccessful())
