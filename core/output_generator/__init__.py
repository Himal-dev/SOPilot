"""Output generator: fill the output schema from state + evidence.

Maps accumulated step outputs and the evidence ledger onto the user-defined (or
compiler-suggested) output schema, so every field traces back to evidence.
"""

from core.output_generator.generator import generate_output

__all__ = ["generate_output"]
