# Py-feat live

This is a quick demo of using py-feat to analyze webcam frames in real time and display the results using streamlit. Currently a work-in-progress!

![](./demo.gif)

## Setup

1. Create a new `conda` or `venv`
2. `pip install -r requirements.txt`
3. `streamlit run app.py`
4. Go to ` http://localhost:8501` in your browser

If you run into installation issues with py-feat see [this issue](https://github.com/cosanlab/py-feat/issues/186)

## Profiling

We also include a profiling script you can run with `python perf_testing.py`. This will generate a profiling file and save it as `basic.prof`

Then you can run `snakeviz basic.prof` to visualize what py-feat calls are taking taking the longest processing time on your system:

![](./snakeviz.png)