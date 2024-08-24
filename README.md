# Py-feat live

This is a standalone demo of using [py-feat](https://py-feat.org/) to analyze webcam frames in real time and display the results.

![](./demo.gif)

## Installation

1. Install: `pip install git+https://github.com/cosanlab/pyfeat-live.git`   
2. Run this command in the terminal to launch the GUI: `pyfeat-live`  

## Usage
1. Choose your camera by clicking on `SELECT DEVICE`.
2. Choose whether you would like to record the session by clicking `Record Session`. This will internally save the detections and frames as a video in memory. After you stop the session, there will be a button to download the Fex CSV file and also the corresponding video recording as an mp4.
3. Choose which detector models you would like to use with the `Swap detectors` buttons. This can be changed after the session is started.
4. Select which detectors you would like to run with the checkboxes. More detectors adds processing time and will slow the framerate. This can be changed on the fly.
5. Start the session by clicking the red `START` button.

## App Structure

In `setup.py` we define an `entry_point` that allows us to a define a console command "`pyfeat-live`" that the user can run in their terminal after they pip install the package. This mechanism gives us functionality similar to other CLI programs e.g. `fsleyes`. In other words, there is no need for the user to open a python interpreter or jupyter notebook and import anything. Once installed, the package is effectively a CLI app. 

The `pyfeat-live` command essentially runs `python entry_point.py` which executes the `main()` function within `entry_point.py`. This function wraps `streamlit run app.py` and allows us to immediately open a browser tab and start the streamlit app when the user types `pyfeat-live` at their terminal. 

## Pages and routing

`app.py` is setup as a [multi-page streamlit app](https://docs.streamlit.io/develop/concepts/multipage-apps). This allows us some "templating" like functionality, whereby we can share UI across pages by putting it within this file (e.g. footer). We also define a page-router within this file that streamlit will setup for us, providing a more consistent user-experience. 

Currently we have the following routes/pages:
- "live page" -> `detect.py` that also currently acts as the homepage
- "analyze page" -> `analyze.py` for a user to upload files to analyze and work with `py-feat` interactively
- "view page" -> `view.py` for the user to interactively explore detections a la `fslview`/`fsleyes`

## Client-side "state"

Python variables and values can be shared across pages and used to reactively update the UI. To do so we create custom keys in Streamlit's Session State dictionary in the following naming convention: `state.PAGE__KEY`. These can be as specific or general as needed, e.g. `state.analyze__ui_state` or `state.view__show_save_button`. These values can be used to keep data or objects in memory and are only wiped on page refreshes or `pyfeat-live` restarts.

## Data download

Until upstream `py-feat` <-> `huggingface` data storage and download integration is complete, each fresh environment install of `pyfeat-live` requires a fresh install of model weights. This will take a few minutes on first launch depending on internet speed.
You can avoid this by install `pyfeat-live` into an existing python environment that has a working install of `py-feat`. 

### Development Setup

To run the barebones streamlit app for development, clone this repository then:

1. Create a new `conda` or `venv`
2. `pip install -r requirements.txt`
3. `pip install -e .`
3. `pyfeat-live`
4. Go to ` http://localhost:8501` in your browser

If you run into installation issues with py-feat see [this issue](https://github.com/cosanlab/py-feat/issues/186)

## Profiling

We also include a profiling script you can run with `python perf_testing.py`. This will generate a profiling file and save it as `basic.prof`

Then you can run `snakeviz basic.prof` to visualize what py-feat calls are taking taking the longest processing time on your system:

![](./snakeviz.png)
