import os
import runpy
import sys
import warnings

import psutil

RAM = psutil.virtual_memory().total / (1024**3)
RAM_CAP = 0.7
available = psutil.virtual_memory().available / (1024**3)
print(f"Total detected system RAM: {RAM:.2f} GB")
print(f"Total available system RAM at launch: {available:.2f} GB")
print(f"Capping in-memory capture to: {available*RAM_CAP:.2f} GB")

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
