def make_exe():
    dist = default_python_distribution(python_version="3.10")

    policy = dist.make_python_packaging_policy()
    policy.set_resource_handling_mode("files")

    # site-packages is required here so that streamlit doesn't boot in
    # development mode:
    # https://github.com/streamlit/streamlit/blob/953dfdbe/lib/streamlit/config.py#L255-L267
    policy.resources_location = "filesystem-relative:site-packages"

    python_config = dist.make_python_interpreter_config()
    python_config.module_search_paths = ["$ORIGIN/site-packages"]
    python_config.run_module = "pyfeatlive"

    python_config.filesystem_importer = True
    python_config.oxidized_importer = False
    python_config.sys_frozen = True

    exe = dist.to_python_executable(
        name="pyfeatlive",
        packaging_policy=policy,
        config=python_config,
    )
    exe.windows_runtime_dlls_mode = "always"
    exe.windows_subsystem = "console"

    exe.add_python_resources(exe.pip_install(["-r", "requirements.txt"]))
    exe.add_python_resources(exe.pip_install(["."]))

    return exe


def make_install(exe):
    files = FileManifest()
    files.add_python_resource(".", exe)
    files.install("dist", replace=True)

    return files


register_target("exe", make_exe)
register_target(
    "install", make_install, depends=["exe"], default=True, default_build_script=True
)

resolve_targets()
