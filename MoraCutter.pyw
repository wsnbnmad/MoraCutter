"""Transparent source launcher for Mora Cutter.

This file intentionally contains no compiled executable code. It can be opened
in any text editor before launch.
"""

import multiprocessing


if __name__ == "__main__":
    multiprocessing.freeze_support()
    from mora_cutter.app import main

    main()
