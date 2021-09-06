"""__main__.py for finitude
"""

from finitude import finitude


if __name__ == '__main__':
    import sys, os
    sys.exit(finitude.main(sys.argv, os.environ))
