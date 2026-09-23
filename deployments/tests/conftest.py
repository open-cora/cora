"""Put the descriptor modules on the path.

`deployments/` is not a package and does not want to be: the scripts here
are run by an operator with a path, not imported by an application. That
leaves the tests to say where they are.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
