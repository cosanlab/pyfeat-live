import os
import runpy
import sys
import warnings

print("Checking if pytorch models need to be downloaded...")
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from feat.FastDetector import FastDetector

    tmp = FastDetector()
print("All models found on disk and ready to use!")
del tmp

import pyfeatlive


def main() -> None:
    streamlit_script_path = os.path.join(os.path.dirname(pyfeatlive.__file__), "app.py")
    sys.argv = ["streamlit", "run", streamlit_script_path]
    runpy.run_module("streamlit", run_name="__main__")


if __name__ == "__main__":
    main()
