// start.js
// This electron app is based off of a tutorial by Simon Biggs for PyMedPhys: 
// https://docs.pymedphys.com/en/continue-binary/contrib/dive/create-streamlit-exe.html#

const childProcess = require("child_process");
const electron = require("electron");
const webpack = require("webpack");
const config = require("./webpack.app.config");

const compiler = webpack(config({ development: true }));
let electronStarted = false;

compiler.watch({}, (err, stats) => {
  if (err) {
    console.error('Webpack compilation error:', err);
    return;
  }

  if (stats) {
    console.log(stats.toString({ colors: true }));
  }

  if (!electronStarted) {
    electronStarted = true;
    const electronProcess = childProcess.spawn(electron, ['.'], { stdio: 'inherit' });

    electronProcess.on("close", () => {
      console.log('Electron process closed. Stopping watcher.');
      compiler.close(() => console.log('Webpack watcher stopped.'));
    });
  }
});
