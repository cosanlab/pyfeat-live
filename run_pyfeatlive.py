import os

import streamlit.web.bootstrap as bootstrap
from streamlit.web import cli

if __name__ == "__main__":
    os.chdir(os.path.dirname(__file__))

    flag_options = {
        "server.port": 8501,
        "global.developmentMode": False,
    }

    bootstrap.load_config_options(flag_options=flag_options)
    flag_options["_is_running_with_streamlit"] = True
    bootstrap.run("pyfeatlive/Detect.py", "streamlit run", [], flag_options)

# if __name__ == "__main__":
#     cli._main_run("Detect.py", "streamlit run")
#     # cli._main_run_clExplicit("Detect.py", "streamlit run")
