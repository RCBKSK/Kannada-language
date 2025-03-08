
import fire

from lokbot.app import main

if __name__ == "__main__":
    fire.Fire(main)
else:
    # Allow running with fire CLI or directly
    fire.Fire(main)
