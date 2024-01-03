# Py-feat live

This is a standalone demo of using [py-feat](https://py-feat.org/) to analyze webcam frames in real time and display the results.

![](./demo.gif)

The app is built using [streamlit](https://streamlit.io/) and camera access is facilitated by [streamlit-webrtc](https://github.com/whitphx/streamlit-webrtc).

The standalone app packaging is based on a [tutorial](https://docs.pymedphys.com/en/continue-binary/contrib/dive/create-streamlit-exe.html#) by Simon Biggs for [PyMedPhys](https://docs.pymedphys.com/) and creates a self-contained python package using [pyoxidizer](https://pyoxidizer.readthedocs.io/en/stable/), which embeds the streamlit app into rust and has very fast application bootup times compared to other packages such as pyinstaller. Even though it is theoretically possible, we are currently unable to successfully build mac and windows binaries using pyoxidizer on an M1 machine. For now, we add additional overhead by wrapping our pyoxidizer build in an electron app, which allows us to more easily compile standalone binaries for Mac (Intel & Arm) & Windows. Packaging streamlit apps into standalone local binaries is surprisingly difficult. See this [discussion](https://discuss.streamlit.io/t/using-pyinstaller-or-similar-to-create-an-executable/902/18) on the streamlit discourse for more details.

Code signing is a bit of a pain at the moment. Code signing for Apple currently uses a certificate from our Cosanlab Apple Developer Account (Luke  Chang (S368GH6KF7)). We may need to add the scripting entitlement to the `entitlements.mac.plist` as streamlit seems to require terminal access to launch the server, unless we can figure out how to streamline this in the pyoxidizer build. We are finding it currently takes a long time to build the electron app and are investigating ways to speed this up. We do not have an account for signing windows apps yet.

## Setup

To run the barebones streamlit app for development, clone this repository then:

1. Create a new `conda` or `venv`
2. `pip install -r requirements.txt`
3. `streamlit run app.py`
4. Go to ` http://localhost:8501` in your browser

If you run into installation issues with py-feat see [this issue](https://github.com/cosanlab/py-feat/issues/186)

## Profiling

We also include a profiling script you can run with `python perf_testing.py`. This will generate a profiling file and save it as `basic.prof`

Then you can run `snakeviz basic.prof` to visualize what py-feat calls are taking taking the longest processing time on your system:

![](./snakeviz.png)

## Building Standalone Apps

To build the standalone apps for different platforms.

1. Build dependencies using [poetry](https://python-poetry.org/)
2. Build the self-contained python app using `pyoxidizer run`. This will create a new pyoxidizer build in the `build\aarch64-apple-darwin\debug\install` directory (if you're building on an arm64).
3. Copy the `install` directory to the electron folder `build\electron\app\python`.
4. Build the electron package for distribution using `npm run dist`. This will require having node/npm installed on your machine.

In theory we could automate this with a github action if someone wants to help.