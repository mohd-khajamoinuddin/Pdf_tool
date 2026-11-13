"""DocSuite local processing engine.

A long-lived child process that the desktop shell talks to over stdin/stdout
using newline-delimited JSON. It opens no sockets and makes no network calls.
"""

__version__ = "0.1.0"
