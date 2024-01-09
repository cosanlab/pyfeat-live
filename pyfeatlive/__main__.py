from pathlib import Path

import streamlit.web.bootstrap as bootstrap

HERE = Path(__file__).parent


def app():
    bootstrap.run(
        str(HERE.joinpath("Detect.py")),
        command_line=None,
        args=list(),
        flag_options=dict(),
    )


if __name__ == "__main__":
    app()
