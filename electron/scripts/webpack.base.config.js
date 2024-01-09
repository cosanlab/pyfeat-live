// This electron app is based off of a tutorial by Simon Biggs for PyMedPhys: 
// https://docs.pymedphys.com/en/continue-binary/contrib/dive/create-streamlit-exe.html#

const path = require("path");
const nodeExternals = require("webpack-node-externals");
require('dotenv').config();

const determineEnvironment = () => {
    // Use the environment variable
    const env = process.env.nodeEnvironment;
    return env === 'production' ? 'production' : env === 'test' ? 'test' : 'development';
};

const determineMode = () => {
    const env = process.env.nodeEnvironment;
    return env === 'production' ? 'production' : 'development';
};

module.exports = () => ({
    target: "electron-renderer",
    mode: determineMode(),
    node: {
        __dirname: false,
        __filename: false
    },
    externals: [nodeExternals()],
    resolve: {
        alias: {
            env: path.resolve(__dirname, `../config/env_${determineEnvironment()}.json`)
        },
        extensions: ['.js'],
    },
    experiments: {
        topLevelAwait: true
    },
    devtool: "source-map",
    module: {
        rules: []
    },
});