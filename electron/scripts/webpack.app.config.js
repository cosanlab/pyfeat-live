// This electron app is based off of a tutorial by Simon Biggs for PyMedPhys: 
// https://docs.pymedphys.com/en/continue-binary/contrib/dive/create-streamlit-exe.html#

const path = require("path");
const { merge } = require("webpack-merge");
const base = require("./webpack.base.config");

module.exports = (env) => merge(base(env), {
    entry: {
        main: "./src/main.js",
        preload: "./src/preload.js"
    },
    output: {
        filename: "[name].js",
        path: path.resolve(__dirname, "../app")
    }
});
