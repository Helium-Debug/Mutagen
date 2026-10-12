"""Allow running mutagen CLI as `python -m mutagen.cli`."""

from mutagen.cli.main import app_entry

if __name__ == "__main__":
    app_entry()
