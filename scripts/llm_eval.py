#!/usr/bin/env python3
"""Backward-compatible entry point for evaluate_data.py."""

import sys

from evaluate_data import main


def translate_legacy_args(argv):
    translated = []
    index = 0
    while index < len(argv):
        item = argv[index]
        if item == "--api-style" and index + 1 < len(argv):
            style = argv[index + 1]
            if style != "auto":
                translated.extend(["--provider", style])
            index += 2
            continue
        if item == "--seed-ratio" and index + 1 < len(argv):
            index += 2
            continue
        translated.append(item)
        index += 1
    return translated


if __name__ == "__main__":
    sys.argv[1:] = translate_legacy_args(sys.argv[1:])
    sys.exit(main())
