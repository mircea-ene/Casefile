import os

# Before `app` is imported: unit tests never send traces, whatever .env says.
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
