// main.js
// This electron app is based off of a tutorial by Simon Biggs for PyMedPhys: 
// https://docs.pymedphys.com/en/continue-binary/contrib/dive/create-streamlit-exe.html#

const path = require('path');
const { spawn } = require("child_process");
const env = require("env");

let serverCommand, serverArgs, serverOptions;

if (env.name === "development") {
    // In development, using 'poetry' to run the script
    serverCommand = "poetry";
    serverArgs = ["run", "python/pyfeatlive", "gui", "--electron"];
    serverOptions = undefined; // Default current working directory
} else {
    // In production, directly running the script
    serverCommand = "/Users/lukechang/Github/pyfeat-live/build/electron/app/python/pyfeatlive";
    serverArgs = ["gui", "--electron"];
    serverOptions = { cwd: "/Users/lukechang/Github/pyfeat-live/build/electron/app/python" };
}

const appStreamlitServer = spawn(serverCommand, serverArgs, serverOptions);

// Add necessary event listeners for the spawned process
appStreamlitServer.stdout.on("data", (data) => {
    console.log(`stdout: ${data}`);
});
appStreamlitServer.stderr.on("data", (data) => {
    console.error(`stderr: ${data}`);
});
appStreamlitServer.on('error', (error) => {
    console.error(`Error: ${error.message}`);
});
appStreamlitServer.on('close', (code) => {
    console.log(`Child process exited with code ${code}`);
});









