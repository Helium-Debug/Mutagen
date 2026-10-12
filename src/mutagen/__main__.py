"""Allow running mutagen as `python -m mutagen`."""

from mutagen.cli.main import app_entry

if __name__ == "__main__":
    app_entry()
