"""SDK version + supported schema range."""

__version__ = "0.1.7"

# Schema range this SDK can produce and read. Inclusive on both ends.
# Bump on every schema-affecting release; see docs/versioning.md.
SUPPORTED_SCHEMA_RANGE: tuple[str, str] = ("0.1", "0.1")
