# from src/sentry/tasks/assemble.py


def enum(**named_values):
    """Creates an enum type."""
    return type("Enum", (), named_values)


ChunkFileState = enum(
    OK="ok",  # File in database
    NOT_FOUND="not_found",  # File not found in database
    CREATED="created",  # File was created in the request and send to the worker for assembling
    ASSEMBLING="assembling",  # File still being processed by worker
    ERROR="error",  # Error happened during assembling
)

