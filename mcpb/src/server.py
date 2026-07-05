"""MCPB entry point: delegates to the real memory-fabric-mcp server installed from PyPI."""

import sys

from memory_fabric.server import main

if __name__ == "__main__":
    sys.exit(main())
