#!/usr/bin/env python
"""Django command-line entrypoint for the Riachuelo platform."""
import os
import sys


def main():
    """Run Django management commands with the project settings loaded."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
