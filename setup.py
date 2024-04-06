from setuptools import setup

with open("requirements.txt") as f:
    requirements = f.read().splitlines()

setup(
    name="pyfeatlive",
    version="1.0",
    install_requires=requirements,
    packages=["pyfeatlive"],
    package_data={"pyfeatlive": ["*.png"]},
    entry_points={
        "console_scripts": [
            "pyfeat-live=pyfeatlive.Detect_entry_point:main",
        ],
    },
)
