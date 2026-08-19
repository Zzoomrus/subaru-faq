"""`python -m pipeline` — то же, что `python -m pipeline.run`."""
import sys

from pipeline.run import main

if __name__ == "__main__":
    sys.exit(main())
